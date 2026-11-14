"""Synthetic snapshots/logs; no claim of real-device recovery verification."""
from collections import Counter
from datetime import datetime,timedelta
import time
import tempfile
import unittest
from engine.arena import Arena
from engine.arena_memory import DraftState,DraftChoice
from engine.arena_recovery import ArenaRecovery
from engine.cards import Cards
from engine.deckstring import encode,DeckDefinition


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(self.tmp.name)
        self.cards.install([dict(id='CARD_'+c,dbfId=i+1,name=c,type='MINION') for i,c in enumerate('ABCD')])
        self.arena=Arena(self.cards);self.arena.attach_memory_deck('42','HERO_08','DRAFTING')
        self.recovery=ArenaRecovery();self.t=time.monotonic();self.ts=datetime.now()

    def snapshot(self,cards,mode='DRAFTING',identity='first'):
        state=DraftState(mode,'CARD',False,tuple(DraftChoice('CARD_'+c) for c in 'ABC'),'42','HERO_08',tuple('CARD_'+c for c in cards))
        # The snapshot is read at "now" in this harness: at or after every log
        # line fed so far, which is what the anchor compares against.
        wall=max(time.time(),self.ts.timestamp())
        for _ in range(2):
            self.t+=.01
            self.recovery.observe(self.arena,state,dict(pid=100,process_instance=identity,observed_at=self.t,observed_wall=wall))
        return self.view()

    def pick(self,cid):
        self.ts+=timedelta(seconds=1)
        self.arena.feed(self.ts,'Client chooses: card (CARD_'+cid+')')
        return self.view()

    def view(self):return self.recovery.merge(self.arena,self.arena.view())

    def test_mid_draft_restores_copies_without_invented_order(self):
        view=self.snapshot('AAABBC')
        self.assertEqual(view['count'],6);self.assertEqual(len(view['picks']),0)
        self.assertEqual(Counter(r['id'] for r in view['history_picks']),Counter({'CARD_A':3,'CARD_B':2,'CARD_C':1}))
        self.assertTrue(all(r['round']==0 and not r['order_known'] for r in view['history_picks']))
        self.assertEqual(self.arena.raw_choices,{'draft:42':[]})

    def test_existing_log_history_is_not_added_twice(self):
        self.pick('A');self.pick('B')
        view=self.snapshot('AAABBC')
        self.assertEqual(view['count'],6);self.assertEqual(len(view['picks']),2)
        self.assertEqual(len(view['history_picks']),4)

    def test_log_first_duplicate_card_does_not_consume_old_history_copy(self):
        self.snapshot('AAABBC')
        view=self.pick('A');self.assertEqual(view['count'],7)
        view=self.snapshot('AAAABBC');self.assertEqual(view['count'],7)
        self.assertEqual(len(view['picks']),1);self.assertEqual(len(view['history_picks']),6)
        self.assertEqual(self.pick('A')['count'],8)
        self.assertEqual(self.snapshot('AAAAABBC')['count'],8)

    def test_memory_first_late_log_and_duplicate_line(self):
        self.snapshot('AAB');self.snapshot('AAAB')
        self.assertEqual(self.pick('A')['count'],4)
        self.arena.feed(self.ts,'Client chooses: card (CARD_A)')
        self.assertEqual(self.view()['count'],4);self.assertEqual(len(self.view()['picks']),1)

    def test_memory_unavailable_retains_history_and_log_progress(self):
        self.snapshot('ABC')
        self.recovery.observe(self.arena,None,dict(observed_at=self.t+1))
        view=self.pick('D');self.assertEqual(view['count'],4)
        self.assertEqual(len(view['history_picks']),3)

    def test_final_decks_definition_overrides_memory(self):
        self.snapshot('ABC');self.arena.feed_decks(self.ts,'Finished Editing Deck:')
        self.arena.feed_decks(self.ts,'# Deck ID: 42')
        self.arena.feed_decks(self.ts,encode(DeckDefinition([637],{1:10,2:20})))
        view=self.view();self.assertEqual(view['count'],30);self.assertTrue(view['exact'])
        self.assertEqual(view['history_picks'],[])
        self.assertEqual(Counter(r['id'] for r in view['picks']),Counter({'CARD_A':10,'CARD_B':20}))

    def test_redraft_replaces_instead_of_appending(self):
        self.snapshot('A'*30)
        self.arena.mode='REDRAFTING';self.arena.phase='redraft:99';self.arena.phase_decks[self.arena.phase]='42'
        self.snapshot('A'*29+'B',mode='REDRAFTING')
        self.arena.feed(self.ts,'Client chooses: card (CARD_B)')
        view=self.view();self.assertEqual(view['count'],30)
        self.assertEqual(Counter(r['id'] for r in view['history_picks']),Counter({'CARD_A':29,'CARD_B':1}))

    def test_restart_reanchors_and_log_only_still_works(self):
        self.snapshot('AAB');self.pick('A')
        view=self.snapshot('AAAB',identity='restarted');self.assertEqual(view['count'],4)
        self.recovery.reset();view=self.view()
        self.assertEqual(view['count'],1);self.assertEqual(view['history_picks'],[])

    def test_redraft_does_not_count_removed_original_log_cards_or_old_final(self):
        for _ in range(30):self.pick('A')
        self.arena.exact_dbf={1:30};self.arena.exact_phase=self.arena.phase
        self.arena.feed(self.ts,'Got new redraft deck with ID: 99')
        view=self.snapshot('A'*29+'B',mode='REDRAFTING')
        self.assertEqual(view['count'],30);self.assertFalse(view['exact'])
        self.assertEqual(len(view['picks']),29);self.assertEqual(len(view['history_picks']),1)

    def test_requires_two_independent_reads_and_excludes_candidates(self):
        state=DraftState('DRAFTING','CARD',False,tuple(DraftChoice('CARD_D') for _ in range(3)),'42','HERO_08',('CARD_A',))
        diag=dict(pid=100,process_instance='first',observed_at=self.t)
        self.recovery.observe(self.arena,state,diag);self.recovery.observe(self.arena,state,diag)
        self.assertEqual(self.view()['count'],0)
        diag['observed_at']+=.1;self.recovery.observe(self.arena,state,diag)
        self.assertEqual(self.view()['count'],1)
        self.assertEqual([r['id'] for r in self.view()['history_picks']],['CARD_A'])

    def test_database_arriving_later_reanchors_unresolved_historical_logs(self):
        records=list(self.cards.by_id.values());self.cards.install([])
        self.pick('A');self.snapshot('AAB')
        self.cards.install(records)
        view=self.snapshot('AAB')
        self.assertEqual(view['count'],3);self.assertEqual(len(view['picks']),1)
        self.assertEqual(len(view['history_picks']),2)

    def test_very_late_log_still_matches_memory_growth(self):
        self.snapshot('AAB');self.snapshot('AAAB')
        self.t+=10;self.snapshot('AAAB')
        self.assertEqual(self.pick('A')['count'],4)

    def test_unavailable_memory_does_not_swallow_a_later_same_id_pick(self):
        self.snapshot('AAB');self.snapshot('AAAB')
        self.recovery.observe(self.arena,None,{})
        self.assertEqual(self.pick('A')['count'],5)
        self.assertEqual(self.snapshot('AAAAB')['count'],5)


class MidJoinTests(unittest.TestCase):
    """Arena.log may lag behind memory: late history must not count twice."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(self.tmp.name)
        self.cards.install([dict(id='CARD_'+c,dbfId=i+1,name=c,type='MINION') for i,c in enumerate('ABCD')])
        self.arena=Arena(self.cards);self.arena.attach_memory_deck('42','HERO_08','DRAFTING')
        # Fixed wall clock so log timestamps can be placed either side of it.
        self.clock=10000.0
        self.recovery=ArenaRecovery(clock=lambda:self.clock)
        self.t=time.monotonic()

    def state(self,deck,slot='CARD',mode='DRAFTING',**extra):
        return DraftState(mode,slot,False,tuple(DraftChoice('CARD_'+c) for c in 'ABC'),'42','HERO_08',
                          tuple('CARD_'+c for c in deck),**extra)

    def observe(self,deck,count=2,observed_wall=None,**extra):
        state=self.state(deck,**extra)
        for _ in range(count):
            self.t+=.5
            diag=dict(pid=100,process_instance='same',observed_at=self.t)
            if observed_wall is not None:diag['observed_wall']=observed_wall
            self.recovery.observe(self.arena,state,diag)
        return self.view()

    def feed(self,offset,cid):
        self.arena.feed(datetime.fromtimestamp(self.clock+offset),'Client chooses: card (CARD_'+cid+')')

    def view(self):return self.recovery.merge(self.arena,self.arena.view())

    def test_midjoin_without_log_history_recovers_whole_deck(self):
        view=self.observe('AAABBC')
        self.assertEqual(view['count'],6);self.assertEqual(view['picks'],[])
        self.assertEqual(Counter(r['id'] for r in view['history_picks']),Counter({'CARD_A':3,'CARD_B':2,'CARD_C':1}))
        self.assertEqual(view['recovery_source'],'memory_and_logs');self.assertEqual(self.recovery.status()['reason'],'recovered')

    def test_snapshot_does_not_need_caught_up_arena_log(self):
        # The arena log will only be read later; recovery must still anchor.
        self.assertTrue(self.observe('AAB')['count']==3)
        self.assertTrue(self.recovery.status()['snapshot'])
        self.feed(-30,'A');self.feed(-20,'B')
        view=self.view()
        self.assertEqual(view['count'],3);self.assertEqual(len(view['picks']),2)
        self.assertEqual(len(view['history_picks']),1)

    def test_late_historical_log_line_does_not_double_count(self):
        self.observe('AAAB')
        self.feed(-5,'A')  # pick happened before the anchor, delivered afterwards
        view=self.view()
        self.assertEqual(view['count'],4);self.assertEqual(len(view['picks']),1)
        self.assertEqual(len(view['history_picks']),3)
        self.assertEqual(self.recovery.status()['pending'],0)

    def test_duplicate_card_pick_after_anchor_counts_once(self):
        self.observe('AAB')
        self.feed(1,'A')
        self.assertEqual(self.view()['count'],4)
        self.feed(2,'A')
        view=self.view()
        self.assertEqual(view['count'],5);self.assertEqual(len(view['picks']),2)
        self.assertEqual(len(view['history_picks']),3)

    def test_same_line_twice_is_deduplicated_by_arena(self):
        self.observe('AAB')
        ts=datetime.fromtimestamp(self.clock+1)
        self.arena.feed(ts,'Client chooses: card (CARD_A)')
        self.arena.feed(ts,'Client chooses: card (CARD_A)')
        self.assertEqual(self.view()['count'],4)

    def test_later_pick_grows_with_memory_and_keeps_history(self):
        self.observe('AAB')
        self.feed(1,'C');self.assertEqual(self.view()['count'],4)
        self.assertEqual(self.observe('AABC')['count'],4)  # memory caught up, no extra copy
        self.feed(2,'B');self.assertEqual(self.view()['count'],5)
        self.assertEqual(self.observe('AABCB')['count'],5)

    def test_duplicate_card_already_in_history_is_not_consumed_by_new_pick(self):
        self.observe('AA')
        self.feed(1,'A')
        view=self.view()
        self.assertEqual(view['count'],3);self.assertEqual(len(view['picks']),1)
        self.assertEqual(Counter(r['id'] for r in view['history_picks']),Counter({'CARD_A':2}))

    def test_empty_memory_deck_reports_reason_and_keeps_logs(self):
        view=self.observe('')
        self.assertEqual(view['count'],0);self.assertIsNone(self.recovery.snapshot)
        status=self.recovery.status()
        self.assertEqual(status['reason'],'deck_empty');self.assertIn('内存牌组',status['reason_text'])

    def test_deck_object_and_slot_evidence_reach_status(self):
        self.observe('AAB',count=1,deck_object=False,deck_slots=0)
        self.assertEqual(self.recovery.status()['reason'],'no_deck')
        self.assertFalse(self.recovery.status()['deck_object'])
        self.observe('AAB',count=1,deck_object=True,deck_slots=2)
        status=self.recovery.status()
        self.assertEqual(status['reason'],'waiting_second_read')
        self.assertEqual(status['slots'],2);self.assertEqual(status['deck_parsed'],3)
        self.assertTrue(status['deck_object'])

    def test_hero_power_in_deck_is_rejected_not_recovered(self):
        state=DraftState('DRAFTING','CARD',False,tuple(DraftChoice('CARD_A') for _ in range(3)),'42','HERO_08',
                         ('CARD_A','HERO_08bp'))
        for _ in range(2):
            self.t+=.5
            self.recovery.observe(self.arena,state,dict(pid=100,process_instance='same',observed_at=self.t))
        self.assertEqual(self.recovery.status()['reason'],'deck_invalid')
        self.assertEqual(self.view()['count'],0)

    def test_mismatched_memory_id_never_replaces_log_identity(self):
        self.arena.feed(datetime.fromtimestamp(self.clock+1),'Got new draft deck with ID: 99')
        state=DraftState('DRAFTING','CARD',False,tuple(DraftChoice('CARD_A') for _ in range(3)),'42','HERO_08',('CARD_A',))
        for _ in range(2):
            self.t+=.5
            self.recovery.observe(self.arena,state,dict(pid=100,process_instance='same',observed_at=self.t))
        self.assertEqual(self.recovery.status()['reason'],'id_mismatch')
        self.assertEqual(self.arena.deck_id,'99')

    def test_anchor_uses_the_memory_read_time_not_the_view_time(self):
        # The view may run long after the read; a pick in between is genuinely
        # new and must not be folded into the snapshot.
        self.clock=20000.0
        self.observe('AAB',observed_wall=10000.0)
        self.feed(5000,'C')
        view=self.view()
        self.assertEqual(view['count'],4);self.assertEqual(len(view['picks']),1)

    def test_manual_record_replaced_by_log_keeps_snapshot(self):
        self.observe('AAB')
        self.arena.manual_pick('42','draft:42',1,'CARD_C')
        self.assertEqual(self.view()['count'],4)
        self.feed(1,'C')  # log now confirms round 1; source changes, mapping must survive
        view=self.view()
        self.assertEqual(view['count'],4);self.assertEqual(len(view['picks']),1)
        self.assertEqual(len(view['history_picks']),3)


class AnchorBoundaryTests(unittest.TestCase):
    """Ordering is decided by the snapshot read time, not by log arrival order."""

    T1=1700000000.0   # the stable memory snapshot is read here
    T2=1700000060.0   # a later pick
    T3=1700000120.0   # one more later pick

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(self.tmp.name)
        self.cards.install([dict(id='CARD_'+c,dbfId=i+1,name=c,type='MINION') for i,c in enumerate('ABCD')])
        self.arena=Arena(self.cards);self.arena.attach_memory_deck('42','HERO_08','DRAFTING')
        self.recovery=ArenaRecovery(clock=lambda:self.T1)
        self.t=time.monotonic()

    def observe(self,deck,wall,count=2,**extra):
        state=DraftState('DRAFTING','CARD',False,tuple(DraftChoice('CARD_'+c) for c in 'ABC'),'42','HERO_08',
                         tuple('CARD_'+c for c in deck),**extra)
        for _ in range(count):
            self.t+=.5
            self.recovery.observe(self.arena,state,dict(pid=100,process_instance='same',observed_at=self.t,observed_wall=wall))

    def feed(self,when,cid):
        self.arena.feed(datetime.fromtimestamp(when),'Client chooses: card (CARD_'+cid+')')

    def view(self):return self.recovery.merge(self.arena,self.arena.view())

    def counts(self,view):
        return (Counter(r['id'] for r in view['history_picks']),Counter(r['id'] for r in view['picks']))

    def test_a_pick_logged_after_the_snapshot_is_counted_separately(self):
        self.observe(('A',),self.T1)
        self.feed(self.T2,'A')
        view=self.view()
        self.assertEqual(view['count'],2)
        history,picks=self.counts(view)
        self.assertEqual((history,picks),(Counter({'CARD_A':1}),Counter({'CARD_A':1})))
        self.assertEqual(view['recovery_source'],'memory_and_logs')

    def test_anchor_is_the_snapshot_time_not_a_log_time(self):
        self.observe(('A',),self.T1)
        self.feed(self.T2,'A');self.view()
        self.assertEqual(self.recovery.anchor,self.T1)   # merging must not move it
        self.feed(self.T1-30,'A');self.view()            # a late, older line must not either
        self.assertEqual(self.recovery.anchor,self.T1)

    def test_b_late_log_of_a_pre_snapshot_pick_covers_history_copy(self):
        self.observe(('A',),self.T2)
        self.feed(self.T1,'A')  # written at T1, delivered only after the snapshot
        view=self.view()
        self.assertEqual(view['count'],1)
        history,picks=self.counts(view)
        self.assertEqual((history,picks),(Counter(),Counter({'CARD_A':1})))
        self.assertEqual(self.recovery.status()['recovered'],0)

    def test_c_different_card_after_snapshot_keeps_both(self):
        self.observe(('A',),self.T1)
        self.feed(self.T2,'B')
        view=self.view()
        self.assertEqual(view['count'],2)
        history,picks=self.counts(view)
        self.assertEqual((history,picks),(Counter({'CARD_A':1}),Counter({'CARD_B':1})))

    def test_d_two_repeated_picks_after_the_snapshot_are_both_counted(self):
        self.observe(('A',),self.T1)
        self.feed(self.T2,'A');self.assertEqual(self.view()['count'],2)
        self.feed(self.T3,'A')
        view=self.view()
        self.assertEqual(view['count'],3)
        history,picks=self.counts(view)
        self.assertEqual((history,picks),(Counter({'CARD_A':1}),Counter({'CARD_A':2})))

    def test_e_repeated_picks_are_not_absorbed_by_memory_growth(self):
        self.observe(('A',),self.T1)
        self.feed(self.T2,'A');self.view()
        self.observe(('A','A'),self.T2+1)   # memory reflects only the first pick
        self.feed(self.T3,'A')
        view=self.view()
        self.assertEqual(view['count'],3)
        history,picks=self.counts(view)
        self.assertEqual((history,picks),(Counter({'CARD_A':1}),Counter({'CARD_A':2})))

    def test_record_without_timestamp_is_counted_and_flagged_not_guessed(self):
        self.observe(('A',),self.T1)
        self.arena.manual[(self.arena.session,'42','draft:42',1)]=dict(card_id='CARD_A',confirmed_at='')
        view=self.view()
        self.assertEqual(view['count'],2)                  # never silently swallowed
        history,picks=self.counts(view)
        self.assertEqual((history,picks),(Counter({'CARD_A':1}),Counter({'CARD_A':1})))
        self.assertFalse(view['count_exact'])              # still marked uncertain
        status=self.recovery.status()
        self.assertEqual(status['untimed'],1)
        self.assertIn('时间戳',view['recovery_note'])

    def test_merge_without_a_snapshot_is_not_a_recovery(self):
        view=self.view()
        status=self.recovery.status()
        self.assertTrue(status['merge_executed']);self.assertFalse(status['executed'])
        self.assertFalse(status['snapshot']);self.assertEqual(status['recovered'],0)
        self.assertEqual(view['history_picks'],[]);self.assertEqual(view['recovery_source'],'logs')

    def test_exact_deck_reports_no_recovery(self):
        self.observe(('A',),self.T1)
        self.arena.exact_dbf={1:1};self.arena.exact_phase=self.arena.phase
        view=self.view()
        status=self.recovery.status()
        self.assertTrue(view['exact']);self.assertFalse(status['executed'])
        self.assertEqual(status['reason'],'exact_deck');self.assertEqual(status['recovered'],0)
