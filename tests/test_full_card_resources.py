import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from engine.full_cards import FullCards
from image_support import tile_png

class FullCardResourceTests(unittest.TestCase):
    def wait(self,predicate):
        deadline=time.monotonic()+3
        pause=threading.Event()
        while not predicate() and time.monotonic()<deadline:pause.wait(.005)
        self.assertTrue(predicate())

    def hover(self,root,cid,locale='enUS'):
        (root/'hover.json').write_text(json.dumps(dict(id=cid,locale=locale,updated=time.time())))

    def test_bulk_promotes_hover_and_downloads_each_card_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);started=threading.Event();release=threading.Event();calls=[]
            def fetch(url,limit,verify):
                cid=url.rsplit('/',1)[1][:-4];calls.append(cid)
                if cid=='CARD_A':started.set();release.wait(3)
                return tile_png(256,384)
            worker=FullCards(root,fetch)
            try:
                worker.begin_download(['CARD_A','CARD_B','CARD_C','CARD_C'],'enUS')
                self.assertTrue(started.wait(2))
                self.hover(root,'CARD_C');worker.request('enUS')
                release.set();self.wait(lambda:worker.batch_view()['status']=='complete')
                self.assertEqual(calls,['CARD_A','CARD_C','CARD_B'])
                self.assertEqual(worker.batch_view()['success'],3)
                self.assertEqual(worker.batch_view()['done'],3)
                usage=worker.usage('enUS',3)
                self.assertEqual((usage['manual'],usage['cached']),(3,3))
                self.assertTrue((root/'cache/full-cards/256x/enUS/manual/CARD_C.png').is_file())
            finally:release.set();worker.close()

    def test_retry_missing_and_skip_have_final_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);calls={}
            cached=root/'cache/full-cards/256x/zhCN/CARD_C.png'
            cached.parent.mkdir(parents=True);cached.write_bytes(tile_png(256,384))
            def fetch(url,limit,verify):
                cid=url.rsplit('/',1)[1][:-4];calls[cid]=calls.get(cid,0)+1
                if cid=='CARD_A' and calls[cid]==1:raise OSError('temporary')
                if cid=='CARD_B':raise HTTPError(url,404,'missing',None,None)
                return tile_png(256,384)
            worker=FullCards(root,fetch)
            try:
                worker.begin_download(['CARD_A','CARD_B','CARD_C'],'zhCN')
                self.wait(lambda:worker.batch_view()['status']=='complete')
                batch=worker.batch_view()
                self.assertEqual([batch[k] for k in ('success','missing','skipped','failed','retried','done')],[1,1,1,0,1,3])
                self.assertEqual(calls,dict(CARD_A=2,CARD_B=2))
                self.assertFalse(cached.exists())
                self.assertTrue((cached.parent/'manual'/cached.name).is_file())
            finally:worker.close()

    def test_cancel_keeps_promoted_inflight_hover_and_drops_bulk_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);started=threading.Event();release=threading.Event();calls=[]
            def fetch(url,limit,verify):
                calls.append(url);started.set();release.wait(3);return tile_png(256,384)
            worker=FullCards(root,fetch)
            try:
                worker.begin_download(['CARD_A','CARD_B'],'enUS');self.assertTrue(started.wait(2))
                self.hover(root,'CARD_A');worker.request('enUS');worker.cancel_download();release.set()
                path=root/'cache/full-cards/256x/enUS/CARD_A.png'
                self.wait(path.exists)
                self.assertEqual(worker.batch_view()['status'],'cancelled');self.assertEqual(len(calls),1)
                self.assertFalse((path.parent/'manual/CARD_B.png').exists())
            finally:release.set();worker.close()

    def test_manual_cache_survives_auto_limit_and_clear_is_separate_from_tiles(self):
        with tempfile.TemporaryDirectory() as folder,patch('engine.full_cards.DISK_LIMIT',1):
            root=Path(folder);worker=FullCards(root,lambda *args,**kwargs:tile_png(256,384))
            tile=root/'cache/images/CARD_A.png';tile.parent.mkdir(parents=True);tile.write_bytes(b'tile')
            try:
                worker.begin_download(['CARD_A','CARD_B'],'enUS')
                self.wait(lambda:worker.batch_view()['status']=='complete')
                self.assertEqual(worker.usage('enUS',2)['manual'],2)
                worker._trim(Path('unused'))
                self.assertEqual(worker.usage('enUS',2)['cached'],2)
                worker.close();worker.clear()
                self.assertEqual(worker.usage('enUS',2)['bytes'],0)
                self.assertEqual(tile.read_bytes(),b'tile')
            finally:worker.close()

    def test_language_switch_cancels_old_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);started=threading.Event();release=threading.Event()
            def fetch(*args,**kwargs):started.set();release.wait(3);return tile_png(256,384)
            worker=FullCards(root,fetch)
            try:
                worker.begin_download(['CARD_A','CARD_B'],'zhCN');self.assertTrue(started.wait(2))
                worker.request('enUS');release.set();worker.close()
                self.assertEqual(worker.batch_view()['status'],'cancelled')
                self.assertEqual(worker.usage('zhCN',2)['cached'],0)
            finally:release.set();worker.close()

    def test_terminal_failure_counts_once_and_resume_skips_retained_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);calls={}
            def fetch(url,limit,verify):
                cid=url.rsplit('/',1)[1][:-4];calls[cid]=calls.get(cid,0)+1
                if cid=='CARD_B':raise OSError('offline')
                return tile_png(256,384)
            worker=FullCards(root,fetch)
            try:
                worker.begin_download(['CARD_A','CARD_B'],'enUS')
                self.wait(lambda:worker.batch_view()['status']=='complete')
                self.assertEqual(calls,dict(CARD_A=1,CARD_B=2))
                self.assertEqual(worker.batch_view()['failed'],1);self.assertEqual(worker.batch_view()['done'],2)
                worker.begin_download(['CARD_A'],'enUS')
                self.wait(lambda:worker.batch_view()['status']=='complete')
                self.assertEqual(worker.batch_view()['skipped'],1)
                self.assertEqual(calls['CARD_A'],1)
            finally:worker.close()
