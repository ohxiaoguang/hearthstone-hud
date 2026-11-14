"""Targeted v0.2.2 regressions; no device logs or game memory used."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from engine.logconfig import ensure_power, ensure_decks, inspect_config
from engine.cards import Cards, fetch, validate_dataset
from engine.tracker import Tracker, DeckLog
from engine.deckstring import encode, DeckDefinition
from engine.discovery import discover


def dataset():
    return [dict(id='SAMPLE_'+str(i),dbfId=i+1,name='离线样本'+str(i),cost=1) for i in range(100)]


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_controlled_decks_write_preserves_power_and_backup(self):
        prefix=self.root/'pfx';home=prefix/'drive_c/users/custom/AppData/Local/Blizzard/Hearthstone';home.mkdir(parents=True)
        process=dict(found=True,prefix=str(prefix),user_dir=str(home))
        ensure_power(process)
        path=home/'log.config';original=path.read_bytes()+b'\n[Other]\nKeep=yes\n; original comment\n'
        path.write_bytes(original)
        self.assertFalse(inspect_config(home,'Decks')['enabled'])
        self.assertEqual(path.read_bytes(),original)
        result=ensure_decks(process)
        self.assertTrue(result['success']);self.assertTrue(result['restart_required'])
        self.assertEqual(Path(result['backup']).read_bytes(),original)
        self.assertTrue(path.read_bytes().startswith(original))
        self.assertTrue(inspect_config(home)['enabled']);self.assertTrue(inspect_config(home,'Decks')['enabled'])
        self.assertIn('Verbose=False',path.read_text());self.assertFalse(ensure_decks(process)['changed'])

    def test_offline_import_validates_before_replacing_cache(self):
        cards=Cards(self.root/'cache');path=self.root/'zhCN.json';path.write_text(json.dumps(dataset()))
        cards.apply(cards.import_file(path));self.assertEqual(len(cards.by_id),100)
        before=(cards.directory/'cards.json').read_bytes()
        for value in ({'locale':'enUS','cards':dataset()},dataset()[:99],[{'broken':True}]*100):
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):cards.import_file(path)
            self.assertEqual((cards.directory/'cards.json').read_bytes(),before)
            self.assertEqual(len(cards.by_id),100)
        self.assertEqual(Cards(cards.directory).info('SAMPLE_0')['name'],'离线样本0')

    def test_ssl_eof_retries_without_losing_offline_cache(self):
        cards=Cards(self.root/'cache');path=self.root/'zhCN.json';path.write_text(json.dumps(dataset()))
        cards.apply(cards.import_file(path));before=(cards.directory/'cards.json').read_bytes()
        with patch('engine.cards.fetch',side_effect=ssl.SSLError('UNEXPECTED_EOF_WHILE_READING')) as download, patch('engine.cards.time.sleep'):
            self.assertIsNone(cards.refresh());self.assertEqual(download.call_count,2)
        self.assertEqual((cards.directory/'cards.json').read_bytes(),before)
        self.assertEqual(len(cards.by_id),100);self.assertIn('EOF',cards.error)

    def test_https_certificate_verification_is_enabled(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'[]'
        with patch('engine.cards.urllib.request.urlopen',return_value=response) as request:
            fetch('https://api.hearthstonejson.com/example',100)
            context=request.call_args.kwargs['context']
            self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)

    def test_stale_refresh_cannot_overwrite_manual_import(self):
        cards=Cards(self.root/'cache');generation=cards.generation
        path=self.root/'zhCN.json';path.write_text(json.dumps(dataset()))
        cards.apply(cards.import_file(path))
        self.assertIsNone(cards._commit(dataset(),'old download',generation))
        self.assertIn('离线',cards.source)

    def test_power_only_known_ids_and_late_deck_binding(self):
        decks=DeckLog();tracker=Tracker(decks);cards=Cards(self.root/'cache')
        day=datetime(2026,11,14).date()
        for line in (Path(__file__).parent/'fixtures/power-format.txt').read_text().splitlines():tracker.feed_line(line,day)
        view=tracker.view(cards);row=next(r for r in view['own'] if r['id']=='CS2_029')
        self.assertEqual(row['name'],'CS2_029');self.assertIsNone(row['initial']);self.assertIsNone(row['remaining'])
        self.assertEqual(row['known_in_deck'],1);self.assertEqual(row['drawn'],1);self.assertEqual(row['used'],1)
        stamp=datetime(2026,11,14,12,0,0)
        decks.feed(stamp,'Finding Game With Deck:');decks.feed(stamp,'### Redacted deck')
        decks.feed(stamp,encode(DeckDefinition([813],{315:2})))
        tracker.view(cards);self.assertEqual(tracker.initial_dbf,{315:2})
        # Future deck changes cannot bind to the already started game.
        other=Tracker(DeckLog())
        for line in (Path(__file__).parent/'fixtures/power-format.txt').read_text().splitlines():other.feed_line(line,day)
        other.decks.feed(datetime(2026,11,14,13),'Finding Game With Deck:')
        other.decks.feed(datetime(2026,11,14,13),encode(DeckDefinition([813],{315:2})))
        other.view(cards);self.assertEqual(other.initial_dbf,{})

    def test_decks_from_other_session_are_not_associated(self):
        logs=self.root/'Logs';(logs/'current').mkdir(parents=True);(logs/'old').mkdir()
        (logs/'current/Power.log').write_text('current')
        (logs/'old/Decks.log').write_text('unrelated')
        self.assertIsNone(discover(self.root)['decks'])
