"""Resource management: per-language databases, full art downloads, clearing."""
import asyncio
import contextlib
from collections import deque
import json
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import i18n
from engine.cards import Cards, MIN_CARDS
from image_support import tile_png


def rows(count=MIN_CARDS,prefix='CARD_'):
    return [dict(id=f'{prefix}{i}',dbfId=i+1,name=f'{prefix}{i}',cost=i % 8,type='MINION') for i in range(count)]


class ResourceHelpers:
    """Shared fixtures; no test methods, so inheriting adds nothing to the run."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'cache'
        i18n.set_ui_language('en')

    def tearDown(self):
        i18n.set_ui_language('en')

    def cache(self,locale,count=MIN_CARDS):
        self.folder.mkdir(parents=True,exist_ok=True)
        path=self.folder/f'cards-{locale}.json'
        path.write_text(json.dumps(dict(updated=time.time(),source='test',locale=locale,cards=rows(count))))
        return path

    def worker(self,cards,download=None,fetch=None,until=None,seconds=.5):
        """Run the real worker loop for a while, optionally stopping on a condition."""
        async def main():
            stop=asyncio.Event()
            patcher=patch.object(cards,'download_image',side_effect=download) if download else \
                    patch('engine.cards.fetch',side_effect=fetch) if fetch else contextlib.nullcontext()
            with patcher:
                task=asyncio.create_task(cards.worker(stop))
                deadline=time.time()+seconds
                while time.time()<deadline:
                    if until and until():break
                    await asyncio.sleep(.01)
                stop.set();await task
        asyncio.run(main())


class ResourceTests(ResourceHelpers,unittest.TestCase):
    pass

    def test_databases_report_presence_size_and_active_locale(self):
        path=self.cache('enUS')
        cards=Cards(self.folder)
        info=cards.language_files()
        self.assertEqual(list(info),['enUS','zhCN'])
        self.assertTrue(info['enUS']['exists']);self.assertTrue(info['enUS']['active'])
        self.assertEqual(info['enUS']['bytes'],path.stat().st_size)
        self.assertFalse(info['zhCN']['exists']);self.assertEqual(info['zhCN']['bytes'],0)
        self.assertEqual(info['zhCN']['code'],'zhCN')

    def test_clearing_an_inactive_database_keeps_the_active_one_and_art(self):
        self.cache('enUS');self.cache('zhCN')
        cards=Cards(self.folder);(cards.images/'CARD_0.png').write_bytes(tile_png())
        self.assertFalse(cards.clear_language('zhCN'))          # not the active locale
        self.assertTrue((self.folder/'cards-enUS.json').exists())
        self.assertFalse((self.folder/'cards-zhCN.json').exists())
        self.assertEqual(len(cards.by_id),MIN_CARDS)
        self.assertTrue((cards.images/'CARD_0.png').exists())

    def test_clearing_the_active_database_stops_automatic_redownload(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        self.assertTrue(cards.clear_language('enUS'))
        self.assertEqual(cards.by_id,{})
        self.assertEqual(cards.download_phase,'idle')
        self.assertFalse(cards.auto_download)
        self.assertFalse((self.folder/'cards-enUS.json').exists())
        calls=[]
        self.worker(cards,fetch=lambda *a,**k:calls.append(a[0]) or b'[]',seconds=.4)
        self.assertEqual(calls,[])                              # nothing re-downloaded
        cards.auto_download=True;cards.attempted=0              # an explicit retry does fetch
        self.worker(cards,fetch=lambda *a,**k:calls.append(a[0]) or json.dumps(rows()).encode(),
                    until=lambda:bool(cards.by_id))
        self.assertEqual(len(calls),1);self.assertIn('/enUS/',calls[0])
        self.assertEqual(len(cards.by_id),MIN_CARDS)

    def test_full_art_download_dedupes_skips_cache_and_resumes(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        card_ids=cards.all_card_ids()
        self.assertEqual(len(card_ids),MIN_CARDS);self.assertEqual(len(set(card_ids)),MIN_CARDS)
        (cards.images/(card_ids[0]+'.png')).write_bytes(tile_png())
        calls=[]
        def download(cid):
            calls.append(cid);(cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(card_ids+[card_ids[0]])
        self.assertEqual(cards.image_batch['total'],MIN_CARDS)   # duplicates collapsed
        self.assertEqual(cards.image_batch['skipped'],1)         # already cached
        self.worker(cards,download=download,seconds=6,until=lambda:cards.image_batch['status']=='complete')
        self.assertEqual(cards.image_batch['status'],'complete')
        self.assertEqual(cards.image_batch['success'],MIN_CARDS-1)
        self.assertEqual(len(calls),MIN_CARDS-1);self.assertNotIn(card_ids[0],calls)
        self.assertEqual(len(set(calls)),len(calls))             # never downloaded twice
        self.assertEqual(cards.image_usage()['cached'],MIN_CARDS)
        # A second run finds everything on disk and does no work at all.
        calls.clear()
        cards.begin_image_download(card_ids)
        self.assertEqual(cards.image_batch['skipped'],MIN_CARDS)
        self.assertEqual(cards.image_batch['status'],'complete')
        self.assertEqual(calls,[])

    def test_resume_after_an_interruption_only_fetches_what_is_missing(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        ids=cards.all_card_ids()[:20]
        for cid in ids[:8]:(cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(ids)
        self.assertEqual(cards.image_batch['skipped'],8)         # cache reused, not fetched
        self.assertEqual(cards.image_batch['total'],20)
        # Simulate an interruption: the bookkeeping is lost, the files are not.
        cards.batch_stream.clear();cards.batch_remaining.clear();cards.image_batch['status']='idle'
        cards.begin_image_download(ids)
        self.assertEqual(cards.image_batch['skipped'],8)
        self.assertEqual(cards.image_batch['total'],20)
        self.assertEqual(cards.image_batch['status'],'running')

    def test_a_failing_tile_is_retried_once_then_reported(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid)
            if cid=='FAIL':raise ssl.SSLError('EOF')
            (cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(['CARD_0','FAIL'])
        self.worker(cards,download=download,seconds=4,until=lambda:cards.image_batch['status']=='complete')
        self.assertEqual(calls.count('FAIL'),2)                  # one retry pass
        self.assertEqual(cards.image_batch['retried'],1)
        self.assertEqual(cards.image_batch['failed'],1)          # final result, not attempts
        self.assertEqual(cards.image_batch['success'],1)
        self.assertEqual(cards.batch_view()['done'],2)

    def test_a_retry_that_succeeds_counts_as_success_only(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid)
            if calls.count(cid)==1:raise ssl.SSLError('transient')   # first attempt fails
            (cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(['CARD_0','CARD_1'])
        self.worker(cards,download=download,seconds=4,until=lambda:cards.image_batch['status']=='complete')
        batch=cards.batch_view()
        self.assertEqual(calls.count('CARD_0'),2)                    # attempted twice
        self.assertEqual((batch['success'],batch['failed']),(2,0))   # final result only
        self.assertEqual(batch['retried'],2)
        self.assertEqual((batch['done'],batch['total']),(2,2))
        # Attempt counters are separate from the final result.
        self.assertEqual(cards.image_totals['failed'],2);self.assertEqual(cards.image_totals['success'],2)

    def test_missing_art_is_not_retried_and_is_reported_separately(self):
        from urllib.error import HTTPError
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def fetch(url,limit,verify=True):
            cid=url.rsplit('/',1)[-1].split('.')[0]
            calls.append(cid)
            if cid=='CARD_2':raise HTTPError(url,404,'Not Found',None,None)
            return tile_png()
        cards.begin_image_download(['CARD_0','CARD_1','CARD_2'])
        self.worker(cards,fetch=fetch,seconds=4,until=lambda:cards.image_batch['status']=='complete')
        batch=cards.batch_view()
        self.assertEqual(calls.count('CARD_2'),1)     # a 404 is never retried
        self.assertEqual((batch['success'],batch['failed'],batch['missing']),(2,0,1))
        self.assertEqual(batch['retried'],0)
        self.assertEqual((batch['done'],batch['total']),(3,3))
        self.assertIn('CARD_2',cards.image_missing)
        self.assertEqual(list(cards.image_errors),[])  # no art is not a download error
        # A later run reports the known 404 without requesting it again.
        calls.clear()
        cards.begin_image_download(['CARD_0','CARD_1','CARD_2'])
        self.assertEqual(cards.image_batch['status'],'complete')
        self.assertEqual((cards.image_batch['missing'],cards.image_batch['skipped']),(1,2))
        self.worker(cards,download=lambda cid:None,seconds=.5)
        self.assertEqual(calls,[])

    def test_progress_never_exceeds_one_hundred_percent(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        ids=cards.all_card_ids()[:6]
        def download(cid):
            if cid.endswith('3'):raise ssl.SSLError('persistent')    # both attempts fail
            (cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(ids)
        seen=[]
        async def main():
            stop=asyncio.Event()
            with patch.object(cards,'download_image',side_effect=download):
                task=asyncio.create_task(cards.worker(stop))
                deadline=time.time()+5
                while time.time()<deadline:
                    seen.append(cards.batch_view()['done'])
                    if cards.image_batch['status']=='complete':break
                    await asyncio.sleep(.01)
                stop.set();await task
        asyncio.run(main())
        batch=cards.batch_view()
        self.assertTrue(seen);self.assertTrue(all(0<=value<=batch['total'] for value in seen))
        self.assertEqual((batch['done'],batch['total']),(6,6))
        self.assertEqual((batch['success'],batch['failed']),(5,1))

    def test_a_legacy_manual_directory_is_removed_by_clearing(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        manual=cards.images/'manual';manual.mkdir(parents=True,exist_ok=True)
        (manual/'CARD_0.png').write_bytes(tile_png())
        (cards.images/'CARD_1.png').write_bytes(tile_png())
        (self.folder/'unrelated.json').write_text('keep')
        self.assertEqual(cards.image_usage()['cached'],1)     # manual files are not counted
        self.assertEqual(cards.clear_images(),1)
        self.assertEqual(list(cards.images.glob('*.png')),[])
        self.assertFalse(manual.exists())                     # the legacy directory goes too
        self.assertTrue((self.folder/'unrelated.json').exists())
        self.assertTrue((self.folder/'cards-enUS.json').exists())
        self.assertEqual(len(cards.by_id),MIN_CARDS)
        self.assertEqual(cards.image_usage()['cached'],0)

    def test_image_usage_reports_sizes_and_totals(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        (cards.images/'A.png').write_bytes(tile_png())
        (cards.images/'B.png').write_bytes(tile_png()*2)
        usage=cards.image_usage()
        self.assertEqual(usage['cached'],2)
        self.assertEqual(usage['bytes'],sum(p.stat().st_size for p in cards.images.glob('*.png')))
        self.assertEqual(usage['total'],MIN_CARDS)
        self.assertFalse(usage['downloading'])

    def test_unsupported_locale_cannot_be_cleared(self):
        cards=Cards(self.folder)
        with self.assertRaises(ValueError):cards.clear_language('xxXX')
        with self.assertRaises(ValueError):cards.clear_language('en')


class BatchControlTests(ResourceHelpers,unittest.TestCase):
    """Cancel keeps the art; the on-demand queue always jumps the batch queue."""

    def test_cancelling_keeps_downloaded_art_and_stops_the_batch(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[];release=threading.Event();started=threading.Event()
        def download(cid):
            calls.append(cid)
            if len(calls)>=4:                       # let a few tiles land, then hold
                started.set();release.wait(5)
            (cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(cards.all_card_ids())
        stop=asyncio.Event()
        def run():
            async def main():
                with patch.object(cards,'download_image',side_effect=download):
                    await cards.worker(stop)
            asyncio.run(main())
        thread=threading.Thread(target=run);thread.start()
        try:
            self.assertTrue(started.wait(5))
            cards.cancel_image_download()
        finally:
            release.set();stop.set();thread.join(5)
        batch=cards.batch_view()
        self.assertEqual(batch['status'],'cancelled')
        self.assertEqual(cards.batch_remaining,set());self.assertEqual(cards.batch_stream,deque())
        self.assertEqual(cards.batch_queue.qsize(),0)
        self.assertGreaterEqual(cards.image_usage()['cached'],4)     # downloaded tiles kept
        # A later batch resumes cleanly: cached tiles are skipped, the rest finishes.
        cards.begin_image_download(cards.all_card_ids())
        self.worker(cards,download=lambda cid:(cards.images/(cid+'.png')).write_bytes(tile_png()),
                    seconds=40,until=lambda:cards.image_batch['status']=='complete')
        self.assertEqual(cards.image_batch['status'],'complete')
        self.assertEqual(cards.image_usage()['cached'],MIN_CARDS)

    def test_ondemand_requests_jump_ahead_of_the_running_batch(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid);(cards.images/(cid+'.png')).write_bytes(tile_png())
        stop=asyncio.Event()
        async def main():
            with patch.object(cards,'download_image',side_effect=download):
                cards.begin_image_download(['CARD_0','CARD_1','CARD_2','CARD_3','CARD_4'])
                cards.request_images(['CARD_29'])               # visible in the game right now
                task=asyncio.create_task(cards.worker(stop))
                deadline=time.time()+5
                while time.time()<deadline and len(calls)<2:
                    await asyncio.sleep(.01)
                stop.set();await task
        asyncio.run(main())
        self.assertEqual(calls[0],'CARD_29')                    # the on-demand card went first
        self.assertIn(calls[1],[f'CARD_{i}' for i in range(5)])


class PromotionTests(ResourceHelpers,unittest.TestCase):
    """A card the game asks for jumps its own batch queue, exactly once."""

    def test_a_batch_queued_card_is_promoted_when_the_game_requests_it(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid);(cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(cards.all_card_ids())     # 100 tiles, queue is full
        self.assertGreater(cards.batch_queue.qsize(),10)     # the target sits deep inside it
        cards.request_images(['CARD_50'])                    # the game shows it right now
        self.assertIn('CARD_50',cards.pending)               # still one reservation, now high priority
        self.assertNotIn('CARD_50',cards.batch_queued)
        stop=asyncio.Event()
        async def main():
            with patch.object(cards,'download_image',side_effect=download):
                task=asyncio.create_task(cards.worker(stop))
                deadline=time.time()+10
                while time.time()<deadline and len(calls)<3:
                    await asyncio.sleep(.01)
                stop.set();await task
        asyncio.run(main())
        self.assertEqual(calls[0],'CARD_50')                 # jumped ahead of the bulk run
        self.assertEqual(calls.count('CARD_50'),1)           # never fetched twice
        self.assertNotIn('CARD_50',cards.batch_remaining)
        # Counted exactly once, as a success, even though the bulk run went on.
        self.assertGreaterEqual(cards.image_batch['success'],1)
        self.assertLess(cards.image_batch['success'],MIN_CARDS)
        self.assertEqual(cards.batch_view()['done'],cards.image_batch['success'])

    def test_a_promoted_card_is_downloaded_once_across_the_whole_batch(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid);(cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(cards.all_card_ids())
        cards.request_images(['CARD_7','CARD_50'])
        self.worker(cards,download=download,seconds=40,
                    until=lambda:cards.image_batch['status']=='complete')
        batch=cards.batch_view()
        self.assertEqual(batch['status'],'complete')
        self.assertEqual(batch['success'],MIN_CARDS)         # every tile landed
        self.assertEqual(batch['done'],MIN_CARDS)
        self.assertEqual(len(calls),MIN_CARDS)               # each card exactly once
        self.assertEqual(len(set(calls)),MIN_CARDS)
        self.assertEqual(cards.image_usage()['cached'],MIN_CARDS)

    def test_a_promoted_failure_still_counts_once(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid)
            if cid=='CARD_9':raise ssl.SSLError('persistent')   # fails on promotion and on retry
            (cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(cards.all_card_ids())
        cards.request_images(['CARD_9'])
        self.worker(cards,download=download,seconds=40,
                    until=lambda:cards.image_batch['status']=='complete')
        batch=cards.batch_view()
        self.assertEqual(batch['status'],'complete')
        self.assertEqual(calls.count('CARD_9'),2)            # promoted attempt + one batch retry
        self.assertEqual(batch['failed'],1)                  # final result, counted once
        self.assertEqual(batch['success'],MIN_CARDS-1)
        self.assertEqual(batch['done'],MIN_CARDS)


class PromotionEdgeTests(ResourceHelpers,unittest.TestCase):
    """Promotion never loses a task when the on-demand queue is full."""

    def test_a_full_on_demand_queue_keeps_the_batch_slot_intact(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid);(cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(cards.all_card_ids())
        before_pending=set(cards.pending);before_queued=set(cards.batch_queued)
        # Saturate the on-demand queue without touching batch bookkeeping.
        overflow=['FULL_'+str(i) for i in range(200)]
        cards.request_images(overflow)
        self.assertTrue(cards.queue.full())
        cards.request_images(['CARD_50'])                    # the game asks for a batch card
        # Promotion was refused: nothing moved, nothing lost, no exception.
        self.assertTrue(cards.queue.full())
        self.assertEqual(calls,[])
        self.assertIn('CARD_50',cards.batch_queued)          # still in the low-priority queue
        self.assertIn('CARD_50',cards.pending)               # its reservation is intact
        self.assertIn('CARD_50',cards.batch_remaining)       # still a batch task
        # Drain the high queue, then run everything to completion: exactly one
        # download per card, batch stats intact.
        self.worker(cards,download=download,seconds=60,
                    until=lambda:cards.image_batch['status']=='complete')
        batch=cards.batch_view()
        self.assertEqual(batch['status'],'complete')
        self.assertEqual(batch['success'],MIN_CARDS)
        queued_full=len([c for c in calls if c.startswith('FULL_')])
        self.assertLessEqual(queued_full,128)                # the queue capacity held
        self.assertEqual(len(calls),MIN_CARDS+queued_full)   # every task ran exactly once
        self.assertEqual(len(set(calls)),len(calls))

    def test_cancel_after_promotion_keeps_the_promoted_request(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        calls=[]
        def download(cid):
            calls.append(cid);(cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(cards.all_card_ids())
        cards.request_images(['CARD_50'])                    # promoted to the on-demand queue
        self.assertNotIn('CARD_50',cards.batch_queued)
        self.assertTrue(cards.batch_remaining & {'CARD_50'})
        cards.cancel_image_download()                        # batch bookkeeping is dropped
        self.assertEqual(cards.batch_remaining,set())
        self.assertEqual(cards.batch_queued,set())
        # The promoted card was requested by the game, so it still downloads;
        # the rest of the batch does not.
        self.worker(cards,download=download,seconds=6,until=lambda:cards.queue.empty())
        self.assertEqual(calls,['CARD_50'])                  # game request kept, batch dropped
        self.assertEqual(cards.image_usage()['cached'],1)
