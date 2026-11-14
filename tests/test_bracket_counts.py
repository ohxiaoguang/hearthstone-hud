"""Controller-omitted synthetic fixture in real GameState entity-ref syntax.
This is a reproduction of the observed diagnostic gap, not a device replay.
"""
from pathlib import Path
from datetime import date
import tempfile
import unittest
from engine.cards import Cards
from engine.tracker import Tracker

class BracketCountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(Path(self.tmp.name));self.cards.install([dict(id='TEST_A',dbfId=1,name='测试甲')])
        self.lines=Path('tests/fixtures/power-bracket-format.txt').read_text().splitlines()
        self.p=Tracker();self.n=0
        for line in self.lines:self.p.feed_line(line,date(2026,11,14))
        self.p.initial_dbf={1:2}
    def feed(self,text):
        self.n+=1;self.p.feed_line(f'D 12:00:03.{self.n:07d} GameState.DebugPrintPower() - '+text,date(2026,11,14))
    def row(self):return self.p.view(self.cards)['own'][0]
    def test_controller_from_bracket_and_deferred_original_owner(self):
        ent=self.p.game.entities[4]
        self.assertEqual((ent.controller,ent.owner,ent.in_starting_deck),(2,2,True))
        self.assertEqual(self.p.bracket_hydrations,2)
        self.assertEqual((self.row()['initial'],self.row()['remaining']),(2,1))
        self.assertEqual(self.p.view(self.cards)['own_remaining'],1)
        self.assertEqual(self.p.game.entities[6].controller,0) # Do not guess the other entity's owner.
    def test_play_does_not_subtract_again_and_all_copies_exhaust(self):
        self.feed('TAG_CHANGE Entity=[entityName=测试甲 id=4 zone=HAND zonePos=1 cardId=TEST_A player=2] tag=ZONE value=PLAY')
        self.assertEqual(self.row()['remaining'],1)
        self.assertTrue(self.p.view(self.cards)['own_played'][0]['in_starting_deck'])
        self.feed('TAG_CHANGE Entity=[entityName=测试甲 id=5 zone=DECK zonePos=0 cardId=TEST_A player=2] tag=ZONE value=HAND')
        self.assertEqual(self.row()['remaining'],0)
        self.assertEqual(self.row()['count_confidence'],'exact')
    def test_incomplete_snapshot_preserves_unknown_and_no_false_zero(self):
        p=Tracker()
        for line in self.lines:
            if 'tag=ZONE_POSITION value=0' not in line:p.feed_line(line,date(2026,11,14))
        p.initial_dbf={1:2}
        self.assertIsNone(p.view(self.cards)['own'][0]['remaining'])
        self.assertIsNone(p.view(self.cards)['own_remaining'])
    def test_explicit_controller_wins_over_stale_reference(self):
        self.feed('TAG_CHANGE Entity=[entityName=测试甲 id=4 zone=HAND zonePos=1 cardId=TEST_A player=1] tag=ATK value=3')
        self.assertEqual(self.p.game.entities[4].controller,2)
    def test_unknown_departure_stays_uncertain(self):
        self.feed('TAG_CHANGE Entity=[entityName=UNKNOWN ENTITY id=5 zone=DECK zonePos=0 cardId= player=2] tag=ZONE value=HAND')
        self.assertIsNone(self.row()['remaining'])
    def test_optional_entity_prefix_and_id_attribute_order(self):
        self.feed('FULL_ENTITY - Updating Entity=[entityName=测试甲 zone=DECK id=5 zonePos=0 cardId=TEST_A player=2] CardID=TEST_A')
        self.assertEqual(self.p.game.entities[5].controller,2)
        self.assertTrue(self.p.game.entities[5].in_starting_deck)
        self.assertEqual(self.row()['remaining'],1)

class SameTimestampTests(unittest.TestCase):
    def setUp(self):
        self.p=Tracker()
        self.lines=Path('tests/fixtures/power-same-timestamp.txt').read_text().splitlines()
        for line in self.lines:self.p.feed_line(line,date(2026,11,14))
    def test_identical_tags_in_distinct_entity_records_are_not_duplicates(self):
        for eid,pid in [(4,1),(5,1),(6,2),(7,2)]:
            ent=self.p.game.entities[eid]
            self.assertEqual(ent.controller,pid);self.assertEqual(ent.zone,'DECK');self.assertTrue(ent.in_starting_deck)
        self.assertEqual(self.p.accepted,len(self.lines))
    def test_duplicate_whole_records_are_ignored_with_context_preserved(self):
        before={e.id:dict(e.tags) for e in self.p.game.entities.values()};accepted=self.p.accepted
        for line in self.lines:self.p.feed_line(line,date(2026,11,14))
        self.assertEqual({e.id:e.tags for e in self.p.game.entities.values()},before)
        self.assertEqual(self.p.accepted,accepted)
    def test_interleaved_non_power_line_does_not_drop_entity_tag(self):
        for line in ['FULL_ENTITY - Creating ID=8 CardID=TEST_A','tag=ZONE value=HAND']:
            self.p.feed_line('D 12:01:01.0000000 GameState.DebugPrintPower() - '+line)
        self.p.feed_line('D 12:01:01.0000000 PowerTaskList.DebugPrintPower() - ignored')
        self.p.feed_line('D 12:01:01.0000000 GameState.DebugPrintPower() - tag=CONTROLLER value=1')
        self.assertEqual(self.p.game.entities[8].controller,1)
        self.assertFalse(self.p.game.entities[8].in_starting_deck)

    def test_counts_after_same_timestamp_batch_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            cards=Cards(folder);cards.install([dict(id='TEST_A',dbfId=1,name='测试甲')]);self.p.initial_dbf={1:2}
            self.assertEqual(self.p.view(cards)['own'][0]['remaining'],2)
            self.p.feed_line('D 12:00:02.0000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=4 tag=ZONE value=HAND')
            self.assertEqual(self.p.view(cards)['own'][0]['remaining'],1)
            self.p.feed_line('D 12:00:03.0000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=4 tag=ZONE value=PLAY')
            self.assertEqual(self.p.view(cards)['own'][0]['remaining'],1)
