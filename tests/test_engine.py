import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from engine.io import Tail, atomic_json
from engine.power import PowerParser

class IOTests(unittest.TestCase):
    def test_append_partial_duplicate_and_truncate(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'Power.log'; t=Tail()
            p.write_bytes(b'one\npar')
            self.assertEqual(t.read(p),['one'])
            self.assertEqual(t.read(p),[])
            with p.open('ab') as f:f.write(b'tial\n')
            self.assertEqual(t.read(p),['partial'])
            p.write_bytes(b'new\n')
            self.assertEqual(t.read(p),['new'])
            self.assertEqual(t.generation,2)
    def test_replace_larger_and_rewrite(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'Power.log';t=Tail();p.write_text('a\n');t.read(p)
            q=Path(folder)/'next';q.write_text('replacement\n');q.replace(p)
            self.assertEqual(t.read(p),['replacement'])
            p.write_text('same inode but longer\n')
            self.assertEqual(t.read(p),['same inode but longer'])
    def test_atomic_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'state.json';atomic_json(p,{'title':'炉石'})
            self.assertIn('炉石',p.read_text())
            self.assertEqual(p.stat().st_mode & 0o777,0o600)

class ParserTests(unittest.TestCase):
    def test_game_zone_duplicate_and_reset(self):
        p=PowerParser()
        def feed(s):p.feed(datetime(2026,1,1),'GameState.DebugPrintPower() - '+s)
        feed('CREATE_GAME');feed('GameEntity EntityID=1')
        feed('FULL_ENTITY - Creating ID=5 CardID=CS2_029')
        feed('tag=ZONE value=HAND');feed('tag=CONTROLLER value=1')
        feed('TAG_CHANGE Entity=5 tag=ZONE value=PLAY')
        feed('TAG_CHANGE Entity=5 tag=ZONE value=PLAY')
        self.assertEqual(len(p.game.plays),1)
        p.feed(datetime.now(),'PowerTaskList.DebugPrintPower() - TAG_CHANGE Entity=5 tag=ZONE value=PLAY')
        self.assertEqual(len(p.game.plays),1)
        feed('TAG_CHANGE Entity=GameEntity tag=STATE value=COMPLETE')
        self.assertTrue(p.game.complete)
        feed('CREATE_GAME');self.assertEqual(p.game.plays,[])
        self.assertFalse(p.game.complete)
