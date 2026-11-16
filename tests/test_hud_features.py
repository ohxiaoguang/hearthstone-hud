"""Regression coverage for full-card requests and evidence-bound deck metadata."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from engine.full_cards import FullCards
from engine.images import validate_png
from engine.deckstring import DeckDefinition, encode
from engine.tracker import DeckLog
from engine.arena_memory import DraftState
from engine.arena_memory_view import ArenaPreview
from image_support import tile_png

class FeatureTests(unittest.TestCase):
    def test_deck_metadata_obeys_game_boundaries_and_queue_blocks(self):
        log=DeckLog();t=datetime(2026,11,16,12)
        code=encode(DeckDefinition([813],{1001:2}))
        log.feed(t,'Finding Game With Deck:')
        log.feed(t,'### My mage');log.feed(t,'# Deck ID: 123456');log.feed(t,code)
        record=log.record_for_game(t+timedelta(seconds=1))
        self.assertEqual((record['name'],record['deck_id'],record['code']),('My mage','123456',code))
        self.assertEqual(record['cards'],{1001:2});self.assertEqual(record['time'],t)
        self.assertEqual(log.record_for_game(t-timedelta(seconds=1)),{})
        self.assertEqual(log.record_for_game(t+timedelta(seconds=2),t),{})
        log.feed(t+timedelta(seconds=3),'Finding Game With Deck:')
        log.feed(t+timedelta(seconds=3),code)
        self.assertNotIn('name',log.record_for_game(t+timedelta(seconds=4),t))

    def test_arena_only_explicit_inactivity_clears_valid_deck(self):
        preview=ArenaPreview(None)
        state=DraftState('DRAFTING','CARD',False,(),'42','HERO_08',('CARD_A',))
        diag=dict(pid=123,process_instance='one',code='card_selection')
        preview.feed(state,diag)
        preview.feed(None,dict(diag,code='read_error',error='temporary'))
        self.assertEqual(preview.deck,('CARD_A',));self.assertTrue(preview.stale)
        preview.feed(None,dict(diag,inactive=True,stale_read=True))
        self.assertEqual(preview.deck,('CARD_A',))
        preview.feed(None,dict(diag,inactive=True))
        self.assertEqual(preview.deck,());self.assertEqual(preview.deck_id,'')

    def test_full_png_validation_rejects_tiles_and_corruption(self):
        data=tile_png(512,768)
        self.assertTrue(validate_png(data,full=True))
        with self.assertRaises(ValueError):validate_png(tile_png(),full=True)
        with self.assertRaises(ValueError):validate_png(data[:-5],full=True)
        with self.assertRaises(ValueError):validate_png(data)

    def test_worker_fallback_coalesces_and_cached_cards_skip_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);calls=[];done=threading.Event()
            def fetch(url,limit,verify):
                calls.append(url)
                if '/zhCN/' in url:raise HTTPError(url,404,'missing',None,None)
                return tile_png(512,768)
            worker=FullCards(root,fetch);self.addCleanup(worker.close)
            path=root/'cache/full-cards/zhCN/CARD_A.png'
            (root/'hover.json').write_text(json.dumps(dict(id='CARD_A',locale='zhCN',updated=time.time())))
            for _ in range(5):worker.request('zhCN')
            deadline=time.monotonic()+3
            while not path.exists() and time.monotonic()<deadline:done.wait(.01)
            self.assertTrue(path.exists());self.assertEqual(len(calls),2)
            worker.close()
            again=FullCards(root,fetch);again._load(('zhCN','CARD_A',True));again.close()
            self.assertEqual(len(calls),2)

    def test_disk_eviction_keeps_recent_card_and_caps_total_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=FullCards(folder);directory=worker.root/'enUS';directory.mkdir(parents=True)
            old=directory/'OLD.png';recent=directory/'NEW.png'
            old.write_bytes(b'x'*20);recent.write_bytes(b'y'*20)
            with patch('engine.full_cards.DISK_LIMIT',25):worker._trim(recent)
            self.assertFalse(old.exists());self.assertTrue(recent.exists())
            worker.close()

    def test_departure_cancels_fallback_and_discards_late_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);started=threading.Event();release=threading.Event();calls=[]
            def fetch(url,limit,verify):
                calls.append(url);started.set();release.wait(3)
                return tile_png(512,768)
            worker=FullCards(root,fetch)
            try:
                (root/'hover.json').write_text(json.dumps(dict(id='CARD_A',locale='enUS',updated=time.time())))
                worker.request('enUS');self.assertTrue(started.wait(2))
                worker.request('enUS',enabled=False);release.set();worker.close()
                self.assertFalse((root/'cache/full-cards/enUS/CARD_A.png').exists())
                self.assertEqual(len(calls),1)
            finally:release.set();worker.close()

    def test_bad_hover_ipc_is_reported_without_stopping_backend(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=FullCards(folder)
            for value in ([],dict(id='CARD_A',locale='enUS',updated=float('nan'))):
                (Path(folder)/'hover.json').write_text(json.dumps(value))
                worker.request('enUS')
                self.assertEqual(worker.diagnostic()['stage'],'request_error')
            (Path(folder)/'hover.json').write_text(json.dumps(dict(id='CARD_A',locale='zhCN',updated=time.time())))
            worker.request('enUS');self.assertEqual(worker.diagnostic()['stage'],'locale_mismatch')
            worker.close()

    def test_download_failure_is_reported_and_retries_while_still_hovered(self):
        with tempfile.TemporaryDirectory() as folder, patch('engine.full_cards.RETRY_SECONDS',.05):
            calls=[];ready=threading.Event()
            def fetch(url,limit,verify):
                calls.append(url)
                if len(calls)==1:raise OSError('offline')
                return tile_png(512,768)
            root=Path(folder);worker=FullCards(root,fetch)
            try:
                (root/'hover.json').write_text(json.dumps(dict(id='CARD_A',locale='enUS',updated=time.time())))
                worker.request('enUS')
                deadline=time.monotonic()+2
                while worker.diagnostic()['stage']!='download_failed' and time.monotonic()<deadline:ready.wait(.002)
                self.assertEqual(worker.diagnostic()['error'],'offline')
                while worker.diagnostic()['stage']!='ready' and time.monotonic()<deadline:ready.wait(.01)
                self.assertEqual(worker.diagnostic()['stage'],'ready')
                self.assertEqual(len(calls),2)
                ready.wait(.1);self.assertEqual(len(calls),2)
            finally:worker.close()
