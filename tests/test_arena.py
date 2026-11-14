"""Synthetic Arena/Decks wire-format tests; no real device claims."""
from datetime import datetime,timedelta
from pathlib import Path
from collections import Counter
import json
import os
import tempfile
import unittest
from engine.arena import Arena
from engine.arena_ratings import ArenaRatings
from engine.cards import Cards
from engine.deckstring import DeckDefinition,encode
from engine.discovery import discover
from engine.logconfig import ensure_arena
from engine.tracker import Tracker

START=datetime(2026,11,15,12)
RATINGS=dict(schema=1,source='synthetic test fixture',captured_at='test only',classes={
    'MAGE':{'TEST_A':dict(score=80,tier='测试甲级'),'TEST_B':dict(score=80,tier='测试甲级')},
    'NEUTRAL':{'TEST_A':dict(score=50,tier='测试乙级'),'TEST_C':dict(score=60,tier='测试乙级')}})

class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(Path(self.tmp.name)/'cache')
        self.cards.install([dict(id='TEST_'+letter,dbfId=i,name='测试'+letter,cost=i,type='MINION',cardClass='NEUTRAL') for i,letter in enumerate('ABCD',1)]+[
            dict(id='HERO_08',dbfId=637,name='法师',type='HERO',cardClass='MAGE'),dict(id='CS2_034',dbfId=99,name='火冲',type='HERO_POWER')])
        self.now=START+timedelta(seconds=100);self.a=Arena(self.cards,ArenaRatings(data=RATINGS),clock=lambda:self.now);self.a.set_session('anonymous-session');self.n=0
    def feed(self,text,ts=None):
        self.n+=1;self.a.feed(ts or START+timedelta(seconds=self.n),text)
    def begin(self):
        self.feed('DraftManager.OnBegin - Got new draft deck with ID: 42')
        self.feed('Client chooses: 法师 (HERO_08)')
    def pick(self,cid='TEST_A',ts=None):self.feed('Client chooses: 匿名卡牌 ('+cid+')',ts)
    def block(self,header='Finished Editing Deck:',deck_id='42',counts=None,ts=None):
        ts=ts or START+timedelta(seconds=200)
        for line in [header,'### ',f'# Deck ID: {deck_id}',encode(DeckDefinition([637],counts or {1:2,2:28}))]:self.a.feed_decks(ts,line)
    def test_01_new_arena_and_class(self):
        self.begin();v=self.a.view();self.assertTrue(v['drafting']);self.assertEqual(v['deck_id'],'42');self.assertEqual(v['class_name'],'法师');self.assertEqual(v['count'],0)
    def test_02_hero_and_hero_power_are_not_card_picks(self):
        self.begin();self.pick('CS2_034');self.pick('HERO_08bp');self.assertEqual(self.a.view()['count'],0)
    def test_03_same_card_in_different_rounds_and_exact_duplicate(self):
        self.begin();self.pick();stamp=START+timedelta(seconds=20)
        self.pick(ts=stamp);self.pick(ts=stamp)
        self.assertEqual([r['round'] for r in self.a.view()['picks']],[1,2]);self.assertEqual(self.a.view()['count'],2)
    def test_04_thirty_cards_in_order(self):
        self.begin()
        for i in range(30):self.pick('TEST_A' if i%2 else 'TEST_B')
        v=self.a.view();self.assertEqual(v['count'],30);self.assertEqual([r['id'] for r in v['picks']][:3],['TEST_B','TEST_A','TEST_B'])
    def test_05_redraft_separate_then_final_replaces_old_deck(self):
        self.begin();self.pick('TEST_A')
        self.feed('SetDraftMode - REDRAFTING');self.feed('DraftManager.OnRedraftBegin - Got new redraft deck with ID: 43');self.pick('TEST_C')
        self.assertEqual(self.a.deck_id,'42');self.assertEqual(self.a.view()['count'],1);self.assertEqual(len(self.a.view()['redraft_picks']),1)
        self.feed('SetDraftMode - ACTIVE_DRAFT_DECK');self.block(counts={2:29,3:1})
        v=self.a.view();self.assertTrue(v['exact']);self.assertEqual(v['count'],30)
        self.assertEqual(Counter(r['id'] for r in v['picks']),{'TEST_B':29,'TEST_C':1})
    def test_06_unrelated_constructed_edit_never_overwrites_arena(self):
        self.begin();self.pick();self.block(deck_id='777')
        self.assertFalse(self.a.view()['exact']);self.assertEqual(self.a.view()['count'],1)
        self.block(header='Finding Game With Deck:',deck_id='42');self.assertFalse(self.a.exact_dbf)
    def test_07_candidates_do_not_count_and_tied_recommendations(self):
        self.begin();self.a.set_offer('42',self.a.phase,1,['TEST_A','TEST_B','TEST_D'])
        v=self.a.view();self.assertEqual(v['count'],0);self.assertEqual([r['best'] for r in v['candidates']],[True,True,False]);self.assertEqual(v['candidates'][2]['rating_label'],'暂无评分')
        self.a.clear_offer();self.assertEqual(self.a.view()['candidates'],[])
    def test_08_manual_and_delayed_log_same_round_reconcile(self):
        self.begin();self.a.manual_pick('42',self.a.phase,1,'TEST_A');self.a.manual_pick('42',self.a.phase,1,'TEST_A')
        self.pick('TEST_A',START+timedelta(seconds=50))
        records=self.a.records();self.assertEqual(len(records),1);self.assertTrue(records[0]['reconciled']);self.assertFalse(records[0]['conflict'])
    def test_09_log_conflict_wins_without_double_count(self):
        self.begin();self.a.manual_pick('42',self.a.phase,1,'TEST_A');self.pick('TEST_B',START+timedelta(seconds=50))
        self.assertEqual(self.a.records()[0]['card_id'],'TEST_B');self.assertEqual(self.a.view()['count'],1);self.assertEqual(self.a.view()['conflicts'],1)
    def test_10_next_log_after_missing_manual_round_is_new_round_even_same_id(self):
        self.begin();self.a.manual_pick('42',self.a.phase,1,'TEST_A');self.pick('TEST_A',START+timedelta(seconds=110))
        self.assertEqual([r['round'] for r in self.a.records()],[1,2]);self.assertEqual(self.a.view()['count'],2)
    def test_11_manual_persist_and_replay(self):
        self.begin();self.a.manual_pick('42',self.a.phase,1,'TEST_A')
        a=Arena(self.cards,ArenaRatings(data=RATINGS),manual=self.a.export_manual());a.set_session('anonymous-session')
        a.feed(START,'Got new draft deck with ID: 42');a.feed(START+timedelta(seconds=50),'Client chooses: 卡 (TEST_A)')
        self.assertEqual(len(a.records()),1);self.assertTrue(a.records()[0]['reconciled'])
    def test_12_class_specific_neutral_fallback_and_missing(self):
        ratings=ArenaRatings(data=RATINGS)
        self.assertEqual(ratings.get('MAGE','TEST_A')['score'],80);self.assertEqual(ratings.get('WARRIOR','TEST_A')['score'],50)
        self.assertEqual(ratings.get('MAGE','TEST_C')['score'],60);self.assertIsNone(ratings.get('MAGE','TEST_D'))
        self.assertEqual(ratings.get('MAGE','CORE_TEST_A')['score'],80)
    def test_13_final_definition_only_for_matching_arena_and_time(self):
        self.begin();self.block(header='Starting Arena Game With Deck:')
        self.assertEqual(self.a.definition_for_game(START+timedelta(seconds=201)),{1:2,2:28})
        self.assertEqual(self.a.definition_for_game(START+timedelta(seconds=50)),{})
        self.feed('Got new draft deck with ID: 99',START+timedelta(seconds=250))
        self.assertEqual(self.a.definition_for_game(START+timedelta(seconds=300)),{})
    def test_14_listing_cannot_overwrite_final_duplicate_counts(self):
        self.begin();self.block()
        self.feed('DraftManager.OnChoicesAndContents - Draft Deck ID: 42, Hero Card = HERO_08');self.feed('Draft deck contains card TEST_A')
        self.assertEqual(self.a.view()['count'],30);self.assertEqual(self.a.exact_dbf,{1:2,2:28})
    def test_15_unknown_type_is_deferred_not_counted_as_hero_power(self):
        self.begin();self.pick('UNKNOWN_BP');self.assertEqual(self.a.view()['count'],0);self.assertEqual(self.a.view()['unresolved_choices'],1)
        self.cards.by_id['UNKNOWN_BP']=dict(type='HERO_POWER');self.assertEqual(self.a.view()['count'],0)
    def test_16_stale_round_or_arena_cannot_be_manually_written(self):
        self.begin()
        for args in [('99',self.a.phase,1,'TEST_A'),('42','redraft:1',1,'TEST_A'),('42',self.a.phase,2,'TEST_A'),('42',self.a.phase,1,'CS2_034')]:
            with self.assertRaises(ValueError):self.a.manual_pick(*args)
        self.pick('TEST_A')
        with self.assertRaises(ValueError):self.a.manual_pick('42',self.a.phase,1,'TEST_B')
    def test_17_search_chinese_or_id_and_no_hero_powers(self):
        self.assertEqual(self.a.search('测试A')[0]['id'],'TEST_A');self.assertEqual(self.a.search('TEST_A')[0]['id'],'TEST_A')
        self.assertEqual(self.a.search('火冲'),[])
    def test_18_invalid_final_definition_preserves_existing(self):
        self.begin();self.block();self.block(counts={1:2})
        self.assertEqual(self.a.exact_dbf,{1:2,2:28});self.assertEqual(self.a.errors,1)
    def test_19_safe_arena_config_backup_and_no_other_sections_changed(self):
        root=Path(self.tmp.name);prefix=root/'prefix';user=prefix/'drive_c/users/actual/AppData/Local/Blizzard/Hearthstone';user.mkdir(parents=True)
        original='[Power]\nLogLevel=9\n[Other]\nKeep=1\n';path=user/'log.config';path.write_text(original)
        result=ensure_arena(dict(found=True,prefix=str(prefix),user_dir=str(user)))
        self.assertTrue(result['success']);self.assertTrue(result['restart_required']);self.assertEqual(Path(result['backup']).read_text(),original)
        self.assertTrue(path.read_text().startswith(original));self.assertIn('[Arena]',path.read_text());self.assertFalse(ensure_arena(dict(found=True,prefix=str(prefix),user_dir=str(user)))['changed'])
    def test_20_discovery_same_session_only(self):
        root=Path(self.tmp.name);a=root/'Logs/a';b=root/'Logs/b';a.mkdir(parents=True);b.mkdir()
        (a/'Power.log').write_text('');(b/'Arena.log').write_text('')
        self.assertIsNone(discover(root)['arena']);(a/'Arena.log').write_text('')
        self.assertEqual(discover(root)['arena']['path'],str(a/'Arena.log'))
    def test_21_arena_bridge_does_not_change_normal_game(self):
        from test_tracking import TrackingTests
        fixture=TrackingTests();fixture.setUp()
        try:
            fixture.p.arena=self.a;self.begin();self.block()
            self.assertEqual(fixture.p.view(fixture.cards)['own'][0]['initial'],2)
            fixture.p.game.game_type='GT_ARENA';fixture.p.game.start=START+timedelta(seconds=201)
            self.assertEqual(fixture.p.view(fixture.cards)['own'][0]['initial'],2)
            self.assertEqual(fixture.p.initial_dbf,{1:2,2:28})
        finally:fixture.doCleanups()
    def test_22_static_snapshot_has_provenance_and_real_entries(self):
        ratings=ArenaRatings();meta=ratings.metadata()
        self.assertGreater(meta['entries'],100);self.assertTrue(meta['captured_at']);self.assertEqual(len(meta['source_sha256']),64)
        self.assertIn('heartharena.com',meta['url'])
    def test_23_overflow_is_not_a_thirty_one_card_deck(self):
        self.begin()
        for i in range(31):self.pick()
        self.assertEqual(self.a.view()['count'],30);self.assertEqual(self.a.view()['overflow_choices'],1)
    def test_24_invalid_ratings_fail_optional_not_backend_startup(self):
        self.assertTrue(ArenaRatings(data=dict(schema=1,classes={'MAGE':[]})).error)
        self.assertIsNone(ArenaRatings(data=dict(schema=1,classes={'MAGE':{'TEST_A':dict(score=float('nan'),tier='bad')}})).get('MAGE','TEST_A'))
    def test_25_decks_rotation_discards_stale_definitions_and_replays(self):
        self.begin();self.block();self.a.reset_decks()
        self.assertEqual(self.a.definition_for_game(START+timedelta(seconds=250)),{})
        self.block(counts={3:30})
        self.assertEqual(self.a.definition_for_game(START+timedelta(seconds=250)),{3:30})
    def test_26_new_arena_does_not_reuse_old_picks_or_manual_round(self):
        self.begin();self.a.manual_pick('42',self.a.phase,1,'TEST_A')
        self.feed('Got new draft deck with ID: 99');self.assertEqual(self.a.view()['count'],0)
        self.assertEqual(self.a.next_round(),1)

    def test_27_old_unresolved_choices_do_not_poison_new_arena(self):
        self.begin();self.pick('UNKNOWN_OLD')
        self.feed('Got new draft deck with ID: 99')
        self.assertEqual(self.a.view()['unresolved_choices'],0)
        self.assertTrue(self.a.view()['count_exact'])
