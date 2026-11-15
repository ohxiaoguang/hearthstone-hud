"""Focused provenance/event regression in real Power.log wire syntax.
All generated fixtures are synthetic and contain no user/game account data.
"""
from pathlib import Path
from datetime import datetime
import test_tracking as fixtures
from engine.tracker import Tracker

# Reuse the parser fixture builder without inheriting/rerunning its test methods.
import unittest
class DeckModelTests(unittest.TestCase):
    setUp=fixtures.TrackingTests.setUp
    feed=fixtures.TrackingTests.feed
    entity=fixtures.TrackingTests.entity
    row=fixtures.TrackingTests.row
    def view(self):return self.p.view(self.cards)
    def move(self,eid,zone):self.feed(f'TAG_CHANGE Entity={eid} tag=ZONE value={zone}')

    def test_two_copies_draw_then_play_does_not_deduct_twice(self):
        self.assertEqual(self.row('TEST_A')['remaining'],2)
        self.move(4,'HAND');self.assertEqual(self.row('TEST_A')['remaining'],1)
        self.feed('TAG_CHANGE Entity=GameEntity tag=TURN value=5')
        self.move(4,'PLAY');self.assertEqual(self.row('TEST_A')['remaining'],1)
        e=self.view()['own_played'][0]
        self.assertEqual((e['card_id'],e['name'],e['turn'],e['order']),('TEST_A','测试甲',3,1))
        self.assertTrue(e['in_starting_deck']);self.assertFalse(e['generated'])
        self.move(5,'HAND');self.assertEqual(self.row('TEST_A')['remaining'],0)
        self.assertEqual(len(self.view()['own']),1)  # exhausted row retained

    def test_hand_play_and_battlefield_creation_never_make_a_deck(self):
        self.entity(8,'TEST_B','HAND',1);self.entity(9,'TEST_B','PLAY',1)
        self.assertEqual(self.view()['own_added'],[])
        self.move(8,'SECRET')
        self.assertEqual([r['id'] for r in self.view()['own']],['TEST_A'])
        self.assertEqual(self.view()['own_added'],[])
        e=self.view()['own_played'][0]
        self.assertEqual(e['origin'],'non_initial');self.assertFalse(e['generated'])
        self.assertEqual(len(self.view()['own_played']),1)

    def test_same_id_generated_shuffle_draw_is_separate_from_original(self):
        self.feed('BLOCK_START BlockType=POWER Entity=4 EffectCardId= EffectIndex=0 Target=0')
        self.entity(8,'TEST_A','HAND',1);self.feed('BLOCK_END')
        self.move(8,'DECK');self.assertEqual(self.row('TEST_A')['remaining'],2)
        added=self.view()['own_added'][0]
        self.assertEqual((added['id'],added['remaining']),('TEST_A',1))
        self.assertTrue(added['generated']);self.assertTrue(added['shuffled_in'])
        self.assertEqual(added['source_card_id'],'TEST_A')
        self.move(8,'HAND');self.assertEqual(self.view()['own_added'],[])
        self.move(8,'PLAY');self.assertEqual(self.row('TEST_A')['remaining'],2)
        self.assertTrue(self.view()['own_played'][0]['generated'])
        self.assertFalse(self.view()['own_played'][0]['in_starting_deck'])

    def test_transform_bounce_replay_shuffle_snapshots_and_duplicates(self):
        self.move(4,'HAND');line=self.feed('TAG_CHANGE Entity=4 tag=ZONE value=PLAY')
        self.p.feed_line(line)
        self.move(4,'HAND');self.feed('CHANGE_ENTITY - Updating Entity=4 CardID=TEST_B')
        self.move(4,'PLAY');self.move(4,'PLAY')
        plays=self.view()['own_played']
        self.assertEqual([e['card_id'] for e in plays],['TEST_A','TEST_B'])
        self.assertEqual([e['order'] for e in plays],[1,2]);self.assertTrue(plays[1]['returned'])
        self.move(4,'DECK');self.assertEqual(self.row('TEST_A')['remaining'],1)
        added=self.view()['own_added'][0];self.assertEqual(added['origin'],'transformed')
        self.assertEqual(added['remaining'],1)
        self.move(4,'HAND');self.assertEqual(self.view()['own_added'],[])
        self.assertEqual(self.row('TEST_A')['remaining'],1)

    def test_foreign_card_and_unproven_discovery_are_not_all_generated(self):
        self.entity(8,'TEST_B','HAND',2)
        self.feed('TAG_CHANGE Entity=8 tag=CONTROLLER value=1');self.move(8,'PLAY')
        e=self.view()['own_played'][0]
        self.assertTrue(e['foreign']);self.assertEqual(e['origin'],'opponent')
        self.assertFalse(e['generated'])
        self.entity(9,'TEST_B','HAND',1);self.move(9,'PLAY')
        self.assertEqual(self.view()['own_played'][1]['origin_label'],'Not in the initial deck')

    def test_copy_creator_tag_and_distinct_sources_not_merged(self):
        for eid,source in [(8,4),(9,5)]:
            self.entity(eid,'TEST_B','HAND',1)
            self.feed(f'TAG_CHANGE Entity={eid} tag=COPIED_FROM_ENTITY_ID value={source}')
            self.move(eid,'DECK')
        self.assertEqual(len(self.view()['own_added']),2)
        self.assertTrue(all(r['generated'] for r in self.view()['own_added']))
        self.assertEqual(self.row('TEST_A')['remaining'],2)

    def test_opponent_seen_and_repeated_play_events_are_independent(self):
        self.move(6,'HAND');self.feed('SHOW_ENTITY - Updating Entity=6 CardID=TEST_B')
        self.assertEqual(len(self.view()['opponent_seen']),1)
        self.assertEqual(self.view()['opponent_played'],[])
        self.move(6,'PLAY');self.move(6,'HAND');self.move(6,'PLAY')
        self.assertEqual(len(self.view()['opponent_seen']),1)
        self.assertEqual(len(self.view()['opponent_played']),2)
        self.assertEqual([e['order'] for e in self.view()['opponent_played']],[1,2])
        self.assertEqual(self.view()['own_played'],[])

    def test_reconnect_does_not_replay_plays_and_new_match_resets(self):
        self.move(4,'HAND');self.move(4,'PLAY');self.feed('CREATE_GAME')
        self.entity(4,'TEST_A','HAND',1);self.move(4,'PLAY')
        self.assertEqual(len(self.p.used),1)
        # Recreate the game entity as a reconnect snapshot would.
        self.feed('GameEntity EntityID=1');self.feed('TAG_CHANGE Entity=GameEntity tag=STATE value=COMPLETE')
        self.feed('CREATE_GAME');self.assertEqual(self.p.used,[]);self.assertEqual(self.p.public,set())

    def test_unknown_play_can_reveal_once_without_future_transform_rewrite(self):
        self.move(6,'HAND');self.move(6,'SECRET')
        self.assertEqual(self.view()['opponent_played'][0]['card_id'],'')
        self.feed('SHOW_ENTITY - Updating Entity=6 CardID=TEST_A')
        self.feed('CHANGE_ENTITY - Updating Entity=6 CardID=TEST_B')
        self.assertEqual(self.view()['opponent_played'][0]['card_id'],'TEST_A')

    def test_log_format_fixture_replay_is_idempotent(self):
        p=Tracker();lines=Path('tests/fixtures/power-format.txt').read_text().splitlines()
        for line in lines:p.feed_line(line,datetime(2026,11,14).date())
        first=p.view(self.cards)
        for line in lines:p.feed_line(line,datetime(2026,11,14).date())
        self.assertEqual(p.view(self.cards),first)
        self.assertEqual(len(first['own_played']),1)
        self.assertEqual(first['own_played'][0]['card_id'],'CS2_029')

    def test_hidden_play_transformation_does_not_invent_earlier_identity(self):
        self.move(6,'HAND');self.move(6,'PLAY')
        self.feed('CHANGE_ENTITY - Updating Entity=6 CardID=TEST_B')
        self.feed('TAG_CHANGE Entity=6 tag=ATK value=3')
        self.assertEqual(self.view()['opponent_played'][0]['card_id'],'')
