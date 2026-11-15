"""Resource management: per-language databases, full art downloads, clearing."""
import asyncio
import contextlib
import json
import ssl
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import i18n
from engine.cards import Cards, MIN_CARDS
from image_support import tile_png


def rows(count=MIN_CARDS,prefix='CARD_'):
    return [dict(id=f'{prefix}{i}',dbfId=i+1,name=f'{prefix}{i}',cost=i % 8,type='MINION') for i in range(count)]


class ResourceTests(unittest.TestCase):
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
        self.assertEqual(cards.image_batch['failed'],2)          # both attempts counted
        self.assertEqual(cards.image_batch['success'],1)

    def test_clearing_images_keeps_databases_and_cancels_a_running_batch(self):
        self.cache('enUS')
        cards=Cards(self.folder)
        for cid in cards.all_card_ids()[:5]:(cards.images/(cid+'.png')).write_bytes(tile_png())
        cards.begin_image_download(cards.all_card_ids())         # 5 cached, the rest queued
        self.assertTrue(cards.batch_remaining)
        removed=cards.clear_images()
        self.assertEqual(removed,5)
        self.assertEqual(list(cards.images.glob('*.png')),[])
        self.assertEqual(cards.image_batch['status'],'idle')
        self.assertEqual(cards.batch_remaining,set())
        self.assertEqual(cards.pending,set())
        self.assertTrue((self.folder/'cards-enUS.json').exists())
        self.assertEqual(len(cards.by_id),MIN_CARDS)
        self.assertEqual(cards.info('CARD_1')['image'],'')

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
