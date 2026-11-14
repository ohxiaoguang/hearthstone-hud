import tempfile
from pathlib import Path
from datetime import datetime
import unittest
from engine.cards import Cards
from engine.tracker import Tracker

class CountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(Path(self.tmp.name)/'cache');self.cards.install([dict(id='A',dbfId=1,name='甲'),dict(id='B',dbfId=2,name='乙')])
        self.p=Tracker();self.n=0
        self.feed('CREATE_GAME');self.feed('GameEntity EntityID=1')
        for eid,pid in [(2,1),(3,2)]:
            self.feed(f'Player EntityID={eid} PlayerID={pid} GameAccountId=[hi=0 lo=0]')
            self.feed(f'tag=CONTROLLER value={pid}')
        for eid,cid in [(4,'A'),(5,'A'),(6,'B'),(7,'')]:self.entity(eid,cid,'DECK')
        self.feed('PlayerID=1, PlayerName=LOCAL',True);self.feed('PlayerID=2, PlayerName=UNKNOWN HUMAN PLAYER',True)
        self.feed('TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_READY');self.p.initial_dbf={1:2,2:2}
    def feed(self,text,game=False):
        self.n+=1;self.p.feed_line(f'D 12:00:00.{self.n:07d} GameState.DebugPrint'+('Game' if game else 'Power')+'() - '+text,datetime(2026,11,14).date())
    def entity(self,eid,cid,zone):
        self.feed(f'FULL_ENTITY - Creating ID={eid} CardID={cid}');self.feed(f'tag=ZONE value={zone}');self.feed('tag=CONTROLLER value=1')
    def row(self,cid):return next(r for r in self.p.view(self.cards)['own'] if r['id']==cid)
    def test_unknown_b_does_not_invalidate_fully_accounted_a(self):
        self.feed('TAG_CHANGE Entity=7 tag=ZONE value=HAND')
        self.assertEqual(self.row('A')['remaining'],2)
        self.assertIsNone(self.row('B')['remaining']);self.assertEqual(self.row('B')['remaining_lower_bound'],1)
        self.feed('TAG_CHANGE Entity=6 tag=ZONE value=HAND')
        self.assertIsNone(self.row('B')['remaining_lower_bound']);self.assertEqual(self.row('B')['count_confidence'],'unknown')
        self.assertEqual(self.row('A')['remaining'],2)
    def test_duplicate_draw_play_not_double_subtracted(self):
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND');self.feed('TAG_CHANGE Entity=4 tag=ZONE value=PLAY')
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=PLAY')
        row=self.row('A');self.assertEqual((row['initial'],row['remaining'],row['drawn'],row['used']),(2,1,1,1))
        self.feed('TAG_CHANGE Entity=5 tag=ZONE value=HAND');self.assertEqual(self.row('A')['remaining'],0)
    def test_incomplete_deck_definition_and_missing_mapping_are_local(self):
        self.p.initial_dbf={1:2};self.assertEqual(self.row('A')['remaining'],2);self.assertIsNone(self.row('B')['remaining'])
        self.p.initial_dbf={1:2,999:2};self.assertEqual(self.row('A')['remaining'],2);self.assertIsNone(self.row('dbf:999')['remaining'])
    def test_unknown_generated_deck_card_has_real_ambiguity(self):
        self.entity(8,'','DECK')
        self.assertIsNone(self.row('A')['remaining']);self.assertEqual(self.row('A')['remaining_lower_bound'],2)
    def test_generated_transform_shuffle(self):
        self.entity(8,'A','HAND');self.feed('TAG_CHANGE Entity=8 tag=ZONE value=PLAY');self.assertEqual(self.row('A')['remaining'],2)
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND');self.feed('CHANGE_ENTITY - Updating Entity=4 CardID=B')
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=DECK');self.assertEqual(self.row('A')['remaining'],1)
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND');self.feed('TAG_CHANGE Entity=4 tag=ZONE value=PLAY')
        self.assertEqual(self.row('A')['remaining'],1)
