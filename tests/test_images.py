import asyncio
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from engine.cards import Cards
from engine.images import TileStore,validate_png
from image_support import tile_png

class ImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=TileStore(self.root/'images')
    def archive(self,entries):
        path=self.root/'tiles.zip'
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in entries:z.writestr(name,data)
        return path
    def test_valid_and_damaged_png(self):
        self.assertTrue(validate_png(tile_png()))
        for data in [b'',tile_png()[:-1],tile_png(96,96),tile_png()[:40]+b'broken'+tile_png()[46:]]:
            with self.assertRaises(ValueError):validate_png(data)
    def test_manual_priority_idempotent_and_auto_cleanup(self):
        result=self.store.import_zip(self.archive([('CARD_A.png',tile_png()),('CARD_B.png',tile_png())]))
        self.assertEqual(result['imported'],2);self.assertEqual(self.store.import_zip(self.root/'tiles.zip')['skipped'],2)
        cards=Cards(self.root/'cache');cards.tiles=self.store;cards.images=self.store.root
        (cards.images/'CARD_A.png').write_bytes(tile_png(color=8));self.assertEqual(cards.info('CARD_A')['image'],str(self.store.manual/'CARD_A.png'))
        for i in range(260):(cards.images/f'AUTO_{i}.png').write_bytes(tile_png())
        cards.prune_images();self.assertTrue((self.store.manual/'CARD_A.png').exists());self.assertLessEqual(len(list(cards.images.glob('*.png'))),256)
    def test_paths_bad_id_corruption_and_limits(self):
        result=self.store.import_zip(self.archive([('../outside.png',tile_png()),('123.png',tile_png()),('CARD_A.png',b'broken'),('ok/CARD_B.png',tile_png())]))
        self.assertEqual(result['imported'],0);self.assertEqual(result['format_errors'],1);self.assertEqual(result['invalid_ids'],1);self.assertEqual(result['other_failures'],2)
        self.assertFalse((self.root/'outside.png').exists())
        many=self.archive([(f'CARD_{i}.png',b'') for i in range(513)])
        self.assertEqual(self.store.import_zip(many)['imported'],0)
        big=self.archive([('CARD_A.png',b'0'*(1024*1024+1))]);self.assertEqual(self.store.import_zip(big)['other_failures'],1)
    def test_download_interrupted_does_not_replace_valid_cache(self):
        cards=Cards(self.root/'cache');target=cards.images/'CARD_A.png';target.write_bytes(tile_png())
        for error in [TimeoutError('timeout'),ssl.SSLError('EOF')]:
            with patch('engine.cards.fetch',side_effect=error):
                with self.assertRaises(OSError):cards.download_image('CARD_A')
            self.assertEqual(target.read_bytes(),tile_png())
        self.assertFalse(list(cards.images.glob('.tile-*')))

class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_dedup_failure_manual_retry_and_responsiveness(self):
        with tempfile.TemporaryDirectory() as folder:
            cards=Cards(folder);cards.updated=10**12  # Keep metadata unrelated to this test.
            calls=[]
            def download(cid):
                import time
                calls.append(cid);time.sleep(.03)
                if cid=='FAIL':raise ssl.SSLError('EOF')
                (cards.images/(cid+'.png')).write_bytes(tile_png())
            with patch.object(cards,'download_image',side_effect=download):
                cards.begin_image_download(['CARD_A','CARD_A','FAIL']);worker=asyncio.create_task(cards.worker())
                await asyncio.sleep(.01);self.assertFalse(worker.done())
                for _ in range(100):
                    if cards.image_batch['status']=='complete':break
                    await asyncio.sleep(.01)
                self.assertEqual(cards.image_batch['total'],2);self.assertEqual(cards.image_batch['success'],1);self.assertEqual(cards.image_batch['failed'],1)
                cards.request_images(['FAIL']);self.assertNotIn('FAIL',cards.pending)
                cards.begin_image_download(['CARD_A','FAIL']);self.assertEqual(cards.image_batch['skipped'],1)
                for _ in range(100):
                    if cards.image_batch['status']=='complete':break
                    await asyncio.sleep(.01)
                self.assertEqual(calls.count('FAIL'),2);self.assertEqual(calls.count('CARD_A'),1)
                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):await worker

class ImportSafetyTests(unittest.TestCase):
    def test_zip_bomb_metadata_rejected_before_decompression(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bomb.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr('CARD_A.png',tile_png())
            entry=zipfile.ZipInfo('CARD_A.png');entry.file_size=65*1024*1024;entry.compress_size=10
            with patch('engine.images.zipfile.ZipFile.infolist',return_value=[entry]),patch('engine.images.zipfile.ZipFile.open') as read:
                result=TileStore(Path(folder)/'images').import_zip(path)
            self.assertEqual(result['other_failures'],1);read.assert_not_called()
    def test_atomic_write_failure_keeps_previous_image(self):
        with tempfile.TemporaryDirectory() as folder:
            cards=Cards(folder);target=cards.images/'CARD_A.png';target.write_bytes(tile_png())
            with patch('engine.cards.fetch',return_value=tile_png(color=9)),patch('engine.images.os.replace',side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):cards.download_image('CARD_A')
            self.assertEqual(target.read_bytes(),tile_png());self.assertFalse(list(cards.images.glob('.tile-*')))
