"""All memory is synthetic. Passing does not validate a live Mono layout."""
import asyncio
import copy
from datetime import datetime
import fcntl
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from engine import mono_memory as m
from engine.arena_memory import HearthstoneMemory, DraftChoice,DraftState
from engine.memory_watch import MemoryWatch
from engine.arena_memory_view import ArenaPreview
from engine.arena_class_ratings import ClassRatings,aggregate
from engine.arena import Arena
from engine.cards import Cards
from fake_mono_memory import FakeProcess
from memory_support import hearthstone_heap


def reader(heap,found=None,factory=None):
    return HearthstoneMemory(process_factory=factory or (lambda pid:FakeProcess(heap)),finder=found or (lambda:dict(found=True,pid=1234,instance='1234:1')))

class MonoTests(unittest.TestCase):
    def test_torn_deck_copy_count_is_not_published(self):
        memory=reader(hearthstone_heap())
        with patch.object(memory,'_deck_cards',side_effect=[['CARD_A'],['CARD_B']]):
            state,diag=memory.poll()
        self.assertIsNone(state);self.assertEqual(diag['code'],'not_ready')

    def test_01_real_shaped_mono_and_assembly_initialization(self):
        mono=m.Mono(FakeProcess(hearthstone_heap()));self.assertEqual(mono.version[:2],(6000,3))
        self.assertIn('DraftDisplay',mono.classes());self.assertIn('DraftManager',mono.classes())
    def test_02_card_choices_packages_and_underground_deck(self):
        r=reader(hearthstone_heap());state,diag=r.poll()
        self.assertEqual(diag['code'],'card_selection');self.assertEqual(state.slot,'CARD');self.assertTrue(state.underground)
        self.assertEqual([c.card_id for c in state.choices],['CARD_A','CARD_B','CARD_C']);self.assertEqual(state.choices[2].package,('CARD_Z',))
        self.assertEqual(state.deck,('CARD_A','CARD_A','CARD_B'));self.assertEqual((state.wins,state.losses),(3,1));r.close()
    def test_deck_copy_lists_are_summed_per_variant(self):
        r=reader(hearthstone_heap());state,diag=r.poll()
        self.assertEqual(state.deck,('CARD_A','CARD_A','CARD_B'))
        self.assertEqual((state.deck_object,state.deck_slots,state.deck_reason),(True,2,''))
        self.assertEqual((diag['deck_object'],diag['deck_slots'],diag['deck_parsed']),(True,2,3));r.close()

    def test_scalar_deck_copy_count_is_accepted_and_reported(self):
        r=reader(hearthstone_heap(slots=[('CARD_A',2),('CARD_B',1)],count_field=m.T_I4));state,diag=r.poll()
        self.assertEqual(state.deck,('CARD_A','CARD_A','CARD_B'))
        self.assertEqual(state.deck_reason,'');self.assertEqual(state.deck_note,'int_count')
        self.assertEqual(state.deck_slots,2);self.assertEqual(diag['deck_note'],'int_count');r.close()

    def test_empty_deck_is_published_with_a_reason_not_a_failure(self):
        r=reader(hearthstone_heap(slots=[('CARD_A',[0,0])]));state,diag=r.poll()
        self.assertEqual(diag['code'],'card_selection');self.assertEqual(state.deck,())
        self.assertEqual(state.deck_reason,'empty');self.assertEqual(state.deck_slots,1)
        self.assertEqual(len(state.choices),3);r.close()

    def test_implausible_deck_size_is_refused_but_candidates_survive(self):
        r=reader(hearthstone_heap(slots=[('CARD_A',[30]),('CARD_B',[30])]));state,diag=r.poll()
        self.assertEqual(diag['code'],'card_selection');self.assertEqual(len(state.choices),3)
        self.assertEqual(state.deck,());self.assertEqual(state.deck_reason,'deck_overflow')
        self.assertEqual(state.deck_id,'777');r.close()

    def test_missing_deck_object_is_reported(self):
        h=hearthstone_heap();r=reader(h);self.assertTrue(r.connect())
        manager=r._manager();klass=manager.klass
        for name,value in [('m_undergroundActive',False),('m_currentSlotType',1),('m_draftDeck',0)]:
            offset,kind,_=h.layouts[klass][0][name];h._store(manager.addr+offset,kind,value)
        state=r.draft_state()
        self.assertEqual((state.deck_object,state.deck_id,state.deck_reason),(False,'','no_deck_object'))
        self.assertEqual(len(state.choices),3);r.close()

    def test_null_slot_list_is_reported(self):
        h=hearthstone_heap();r=reader(h);self.assertTrue(r.connect())
        deck=r._manager()['m_undergroundDraftDeck'];klass=deck.klass
        offset,kind,_=h.layouts[klass][0]['m_slots'];h._store(deck.addr+offset,kind,0)
        state=r.draft_state()
        self.assertEqual((state.deck,state.deck_reason),((),'no_slots_null'));r.close()

    def test_missing_slot_list_field_is_reported(self):
        r=reader(hearthstone_heap(deck_slots='missing'));state,diag=r.poll()
        self.assertEqual(diag['code'],'card_selection');self.assertEqual(len(state.choices),3)
        self.assertEqual((state.deck,state.deck_reason,state.deck_slots),((),'no_slots_field',0));r.close()

    def test_broken_slot_container_keeps_candidates(self):
        h=hearthstone_heap();r=reader(h);self.assertTrue(r.connect())
        slots=r._manager()['m_undergroundDraftDeck']['m_slots']
        offset,kind,_=h.layouts[slots.klass][0]['_size'];h._store(slots.addr+offset,kind,9999)
        state,diag=r.poll()
        self.assertEqual(diag['code'],'card_selection');self.assertEqual(len(state.choices),3)
        self.assertEqual((state.deck,state.deck_reason),((),'slot_layout'));r.close()

    def test_slot_without_card_id_field_is_reported(self):
        r=reader(hearthstone_heap(slot_fields=('m_count',)));state,diag=r.poll()
        self.assertEqual(diag['code'],'card_selection');self.assertEqual(len(state.choices),3)
        self.assertEqual((state.deck,state.deck_reason),((),'no_card_id_field'));r.close()

    def test_slot_with_null_card_id_is_reported(self):
        r=reader(hearthstone_heap(slots=[(None,[1])]));state,diag=r.poll()
        self.assertEqual((state.deck,state.deck_reason,state.deck_slots),((),'slot_without_card_id',1))
        self.assertEqual(len(state.choices),3);r.close()

    def test_slot_without_count_field_is_reported(self):
        r=reader(hearthstone_heap(slot_fields=('m_cardId',)));state,diag=r.poll()
        self.assertEqual(diag['code'],'card_selection');self.assertEqual(len(state.choices),3)
        self.assertEqual((state.deck,state.deck_reason),((),'no_count_field'));r.close()

    def test_null_count_list_follows_upstream_zero_copies(self):
        r=reader(hearthstone_heap(slots=[('CARD_A',None),('CARD_B',[2])]));state,diag=r.poll()
        self.assertEqual(state.deck,('CARD_B','CARD_B'))
        self.assertEqual((state.deck_reason,state.deck_note),('','null_count'))
        self.assertEqual(diag['deck_note'],'null_count');r.close()

    def test_all_null_counts_is_an_empty_deck_not_a_structure_error(self):
        r=reader(hearthstone_heap(slots=[('CARD_A',None)]));state,diag=r.poll()
        self.assertEqual((state.deck,state.deck_reason,state.deck_note),((),'empty','null_count'))
        self.assertEqual(len(state.choices),3);r.close()

    def test_invalid_card_in_later_slot_publishes_no_partial_deck(self):
        r=reader(hearthstone_heap(slots=[('CARD_A',[2]),('bad id',[1])]));state,diag=r.poll()
        self.assertEqual((state.deck,state.deck_reason),((),'slot_invalid_card_id'))
        self.assertEqual(state.deck_slots,2);self.assertEqual(len(state.choices),3);r.close()

    def test_verification_read_cannot_overwrite_published_deck_reason(self):
        memory=reader(hearthstone_heap());real=memory._deck_cards;calls=[]
        def tracking(deck):
            calls.append(1)
            cards=real(deck)
            memory.deck_meta=dict(slots=2,reason='' if len(calls)==1 else 'slot_layout',notes=[])
            return cards
        with patch.object(memory,'_deck_cards',side_effect=tracking):
            state,diag=memory.poll()
        self.assertEqual(len(calls),2);self.assertEqual(state.deck,('CARD_A','CARD_A','CARD_B'))
        self.assertEqual(state.deck_reason,'');self.assertEqual(diag['deck_reason'],'');memory.close()

    def test_snapshot_window_bounds_the_deck_read(self):
        h=hearthstone_heap();memory=reader(h);real=HearthstoneMemory._deck_cards
        clock={'now':1000.0};marks=[]
        def tracking(self,deck):
            clock['now']+=10
            marks.append(clock['now'])
            return real(self,deck)
        with patch('engine.arena_memory.wall_clock',lambda:clock['now']), patch.object(HearthstoneMemory,'_deck_cards',tracking):
            state,diag=memory.poll()
        self.assertEqual(len(marks),2)                        # published read + verification
        # The window opens before the content is read and closes at the verification
        # read, so a pick between the two can never be claimed as history.
        self.assertEqual(diag['observed_start'],1000.0)
        self.assertLess(diag['observed_start'],marks[0])
        self.assertEqual(diag['observed_wall'],marks[1])
        self.assertLess(diag['observed_start'],diag['observed_wall'])
        self.assertEqual((memory.snapshot_start,memory.snapshot_wall),(1000.0,1020.0))
        memory.close()

    def test_snapshot_window_is_empty_without_a_deck(self):
        h=hearthstone_heap(choices=('HERO_08','HERO_09','HERO_01'));r=reader(h);self.assertTrue(r.connect())
        manager=r._manager();klass=manager.klass
        for name,value in [('m_undergroundActive',False),('m_currentSlotType',2),('m_draftDeck',0)]:
            offset,kind,_=h.layouts[klass][0][name];h._store(manager.addr+offset,kind,value)
        state,diag=r.poll()
        self.assertEqual((diag['observed_start'],diag['observed_wall']),(0,0));r.close()

    def test_memory_watch_takes_the_reader_snapshot_window(self):
        class Reader:
            def poll(self):return None,dict(code='reading',status='mock',pid=1,observed_start=120.0,observed_wall=123.0,error='')
            def close(self):pass
        watch=MemoryWatch(lambda stop:Reader(),normal=.01)
        watch.start()
        try:
            for _ in range(100):
                if watch.snapshot()[1].get('observed_wall'):break
                time.sleep(.01)
            diag=watch.snapshot()[1]
            self.assertEqual((diag['observed_start'],diag['observed_wall']),(120.0,123.0))
            self.assertLess(diag['observed_start'],diag['observed_wall'])
        finally:
            watch.request_stop();watch.join()

    def test_03_hero_selection_three_heroes_without_deck(self):
        h=hearthstone_heap(choices=('HERO_08','HERO_09','HERO_01'));r=reader(h);self.assertTrue(r.connect())
        manager=r._manager();klass=manager.klass
        for name,value in [('m_undergroundActive',False),('m_currentSlotType',2),('m_draftDeck',0)]:
            offset,kind,_=h.layouts[klass][0][name];h._store(manager.addr+offset,kind,value)
        state=r.draft_state();self.assertEqual(state.slot,'HERO');self.assertEqual(len(state.choices),3);self.assertEqual(state.deck_id,'');self.assertFalse(state.underground);r.close()
    def test_04_game_exit_closes_descriptor(self):
        found=dict(found=True,pid=1234,instance='1234:1');r=reader(hearthstone_heap(),lambda:found)
        r.poll();p=r.process;found.clear();found['found']=False
        state,diag=r.poll();self.assertIsNone(state);self.assertEqual(diag['code'],'not_running');self.assertTrue(p.closed)
    def test_05_pid_reuse_reconnects_and_closes_old(self):
        found=dict(found=True,pid=1234,instance='1234:1');r=reader(hearthstone_heap(),lambda:found)
        r.poll();old=r.process;found['instance']='1234:2';r.poll();self.assertTrue(old.closed);self.assertIsNot(old,r.process)
        old=r.process;found.update(pid=2345,instance='2345:3');r.poll();self.assertTrue(old.closed);self.assertEqual(r.pid,2345);r.close()
    def test_06_permissions_are_reported_not_bypassed(self):
        def denied(pid):raise PermissionError('synthetic permission denied')
        state,diag=reader(None,factory=denied).poll();self.assertIsNone(state);self.assertEqual(diag['code'],'permission_denied')
    def test_07_no_mono_and_initialization_failure_release_resources(self):
        h=hearthstone_heap();h.module=None;p=FakeProcess(h)
        state,diag=reader(h,factory=lambda pid:p).poll();self.assertEqual(diag['code'],'mono_missing');self.assertTrue(p.closed)
    def test_08_incompatible_unity_rejected_before_offsets(self):
        h=hearthstone_heap();h.put('I',h.version_addr+8,(2022<<16)|3)
        state,diag=reader(h).poll();self.assertIsNone(state);self.assertEqual(diag['code'],'incompatible')
    def test_09_invalid_pointer_fails_closed(self):
        h=hearthstone_heap();h.put('Q',h.image+m.IMAGE_CLASS_CACHE+m.HASH_TABLE_TABLE,1)
        state,diag=reader(h).poll();self.assertIsNone(state);self.assertEqual(diag['code'],'read_error')
    def test_10_excessive_array_and_list_lengths(self):
        h=hearthstone_heap();r=reader(h);r.connect();options=r.mono.static('DraftDisplay','s_instance')['m_choices'];items=options['_items']
        h.put('Q',items.addr+m.ARRAY_LENGTH,999999)
        with self.assertRaises(m.UnsupportedLayout):options.list_objects(3)
        h.put('Q',items.addr+m.ARRAY_LENGTH,5);offset,_,_=h.layouts[options.klass][0]['_size'];h.put('i',options.addr+offset,-1)
        with self.assertRaises(m.UnsupportedLayout):options.list_objects(3)
        r.close()
    def test_11_unknown_enum_and_partial_choices_not_published(self):
        h=hearthstone_heap(choices=('CARD_A','CARD_B'));state,diag=reader(h).poll();self.assertEqual(state.choices,())
        r=reader(h);r.connect();display=r.mono.static('DraftDisplay','s_instance');offset,_,_=h.layouts[display.klass][0]['m_currentMode'];h.put('i',display.addr+offset,999)
        state,diag=r.poll();self.assertIsNone(state);self.assertEqual(diag['code'],'incompatible')
    def test_12_readonly_open_and_mapped_read_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'10';root.mkdir();(root/'maps').write_text('00010000-00011000 r--p 00000000 00:00 0 /mock\n')
            with (root/'mem').open('wb') as f:f.seek(0x10000);f.write(b'test'+b'\0'*4092)
            p=m.Process(10,Path(folder));self.assertEqual(fcntl.fcntl(p._fd,fcntl.F_GETFL)&os.O_ACCMODE,os.O_RDONLY)
            self.assertEqual(p.read(0x10000,4),b'test')
            for addr,size in [(0,4),(0x10fff,4),(0x10000,2*1024*1024)]:
                with self.assertRaises(m.UnsupportedLayout):p.read(addr,size)
            p.close();p.close();self.assertIsNone(p._fd)
    def test_13_corrupt_pe_and_export_code(self):
        h=hearthstone_heap();h.write(h.module,b'XX');self.assertEqual(reader(h).poll()[1]['code'],'incompatible')
        h=hearthstone_heap();p=FakeProcess(h);mono=m.Mono(p);address=mono._export(h.module,b'mono_get_root_domain');h.write(address,b'\x90')
        self.assertEqual(reader(h).poll()[1]['code'],'incompatible')
    def test_14_hero_power_stage(self):
        h=hearthstone_heap();r=reader(h);r.connect();manager=r._manager();offset,kind,_=h.layouts[manager.klass][0]['m_currentUndergroundSlotType'];h._store(manager.addr+offset,kind,3)
        self.assertEqual(r.poll()[1]['code'],'hero_power_selection');r.close()

    def test_27_layout_signature_mismatch_and_closed_fd(self):
        h=hearthstone_heap();klass=next(k for k in h.classes if 's_instance' in h.layouts[k][0])
        p=FakeProcess(h);address=p.ptr(klass+m.CLASS_FIELDS);typ=p.ptr(address)
        h.put('B',typ+10,m.T_I4)
        state,diag=reader(h,factory=lambda pid:p).poll()
        self.assertIsNone(state);self.assertEqual(diag['code'],'incompatible');self.assertTrue(p.closed)
    def test_28_missing_assembly_is_not_reported_as_success(self):
        h=hearthstone_heap();p=FakeProcess(h);mono=m.Mono(p)
        node=p.ptr(mono.domain+m.DOMAIN_ASSEMBLIES);assembly=p.ptr(node)
        h.put('Q',assembly+m.ASSEMBLY_NAME,h.cstr('Other-Assembly'))
        state,diag=reader(h).poll();self.assertIsNone(state);self.assertEqual(diag['code'],'not_ready')
    def test_29_cooperative_stop_rejects_further_reads(self):
        stop=threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'1';root.mkdir();(root/'maps').write_text('00010000-00011000 r--p 00000000 00:00 0 /mock\n');(root/'mem').write_bytes(b'')
            p=m.Process(1,Path(folder),stop=stop);stop.set()
            with self.assertRaises(m.Cancelled):p.read(0x10000,1)
            p.close()

    def test_30_field_must_fit_object_instance(self):
        h=hearthstone_heap();r=reader(h);r.connect();display=r.mono.static('DraftDisplay','s_instance');klass=display.klass
        h.put('i',klass+m.CLASS_INSTANCE_SIZE,16)
        with self.assertRaises(m.UnsupportedLayout):display['m_currentMode']
        r.close()

class PollerTests(unittest.IsolatedAsyncioTestCase):
    async def test_15_disable_stops_thread_and_releases(self):
        closed=threading.Event();calls=[]
        class Reader:
            def poll(self):calls.append(1);return None,dict(code='reading',status='test',pid=1,error='')
            def close(self):closed.set()
        watch=MemoryWatch(lambda stop:Reader(),normal=.01);watch.start()
        for _ in range(100):
            if calls:break
            await asyncio.sleep(.005)
        watch.request_stop();await asyncio.to_thread(watch.join);n=len(calls);await asyncio.sleep(.03)
        self.assertEqual(len(calls),n);self.assertTrue(closed.is_set());self.assertIsNone(watch.thread);self.assertEqual(watch.snapshot()[1]['code'],'disabled')
    async def test_16_errors_rate_limited(self):
        class Reader:
            def poll(self):return None,dict(code='permission_denied',status='test',pid=1,error='same')
            def close(self):pass
        watch=MemoryWatch(lambda stop:Reader(),idle=.005);watch.start();await asyncio.sleep(.05)
        self.assertEqual(watch.snapshot()[1]['errors'],1);self.assertGreater(watch.snapshot()[1]['suppressed_errors'],0)
        watch.request_stop();await asyncio.to_thread(watch.join)

class PreviewTests(unittest.TestCase):
    """The selected deck is the memory DraftDeck; logs and candidates never add."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(Path(self.tmp.name))
        self.cards.install([
            dict(id='HERO_08',name='英雄甲',cardClass='MAGE',type='HERO'),
            dict(id='HERO_09',name='英雄乙',cardClass='PRIEST',type='HERO'),
            dict(id='HERO_01',name='英雄丙',cardClass='WARRIOR',type='HERO'),
            dict(id='CARD_A',name='测试A',cost=2,type='MINION'),
            dict(id='CARD_B',name='测试B',cost=2,type='MINION'),
            dict(id='CARD_C',name='测试C',cost=0,type='MINION'),
            dict(id='CARD_D',name='测试D',cost=None,type='MINION')])
        from engine.arena_ratings import ArenaRatings
        self.arena=Arena(self.cards,ArenaRatings(data=dict(schema=1,classes={'MAGE':{'CARD_A':dict(score=80,tier='synthetic'),'CARD_B':dict(score=80,tier='synthetic')}})))
        self.stats=ClassRatings(data=dict(schema=1,modes={m:dict(classes={'MAGE':dict(totalGames=100,totalsWins=60),'PRIEST':dict(totalGames=200,totalsWins=100),'WARRIOR':dict(totalGames=100,totalsWins=60)}) for m in ('arena','arena-underground')}))
        self.preview=ArenaPreview(self.stats)

    def diag(self,code='card_selection',**extra):
        data=dict(enabled=True,observed_at=time.monotonic(),code=code,pid=123,process_instance='inst-1',error='')
        data.update(extra);return data

    def state(self,slot='CARD',deck=(),deck_id='42',hero='HERO_08',mode='DRAFTING',**extra):
        choices=('HERO_08','HERO_09','HERO_01') if slot in ('HERO','HERO_POWER') else ('CARD_A','CARD_B','CARD_C')
        return DraftState(mode,slot,False,tuple(DraftChoice(c) for c in choices),deck_id,hero,tuple(deck),**extra)

    def view(self,state,diag=None):return self.preview.view(self.cards,self.arena.ratings,state,diag or self.diag())

    def test_17_hero_preview_without_arena_id_and_tied_recommendations(self):
        v=self.view(self.state('HERO',deck_id='',hero=''))
        self.assertEqual(v['stage'],'hero_selection');self.assertFalse(v['show_count']);self.assertEqual(len(v['candidates']),3)
        self.assertEqual([r['best'] for r in v['candidates']],[True,False,True]);self.assertEqual(v['candidates'][0]['hero_stats']['rank'],1)
        self.assertEqual(v['count'],0);self.assertEqual(self.arena.raw_choices,{})

    def test_18_card_preview_scores_candidates_without_touching_the_deck(self):
        v=self.view(self.state(deck=('CARD_C',)))
        self.assertEqual(v['stage'],'card_selection')
        self.assertEqual([r['best'] for r in v['candidates']],[True,True,False])
        self.assertEqual(v['candidates'][2]['rating_label'],'No rating')
        self.assertEqual(v['count'],1);self.assertEqual([r['id'] for r in v['picks']],['CARD_C'])

    def test_30_selected_cards_and_count_come_from_the_memory_deck(self):
        deck=('CARD_A','CARD_B','CARD_C','CARD_A','CARD_B','CARD_D')
        v=self.view(self.state(deck=deck))
        self.assertEqual(v['count'],6);self.assertTrue(v['count_exact']);self.assertFalse(v['deck_stale'])
        self.assertEqual(sorted(r['id'] for r in v['picks']),sorted(deck))
        self.assertNotIn('history_picks',v)

    def test_31_duplicate_cards_keep_their_copies(self):
        v=self.view(self.state(deck=('CARD_A','CARD_A')))
        self.assertEqual(v['count'],2);self.assertEqual([r['id'] for r in v['picks']],['CARD_A','CARD_A'])

    def test_32_repeated_client_chooses_lines_never_change_the_count(self):
        from datetime import datetime
        self.arena.feed(datetime(2026,11,15,7,54,20),'Got new draft deck with ID: 42')
        for i in range(10):
            self.arena.feed(datetime(2026,11,15,7,54,25+i),'Client chooses: 腐臭吞噬者 (CARD_A)')
        self.assertEqual(self.arena.view()['count'],10)   # the log model still sees ten
        v=self.view(self.state(deck=('CARD_B',)))
        self.assertEqual(v['count'],1);self.assertEqual([r['id'] for r in v['picks']],['CARD_B'])

    def test_33_candidates_never_join_the_selected_deck(self):
        v=self.view(self.state(deck=('CARD_C',)))
        self.assertEqual(len(v['candidates']),3)
        self.assertEqual([r['id'] for r in v['picks']],['CARD_C'])
        self.assertNotIn({r['id'] for r in v['candidates']},{r['id'] for r in v['picks']} - {'CARD_C'})

    def test_34_growing_deck_replaces_instead_of_appending(self):
        self.assertEqual(self.view(self.state(deck=('CARD_A',)*6))['count'],6)
        v=self.view(self.state(deck=('CARD_A',)*7))
        self.assertEqual(v['count'],7)

    def test_35_selected_cards_are_sorted_by_mana(self):
        v=self.view(self.state(deck=('CARD_A','CARD_C','CARD_D')))
        self.assertEqual([r['cost'] for r in v['picks']],[0,2,None])

    def test_36_same_cost_is_sorted_by_name(self):
        v=self.view(self.state(deck=('CARD_B','CARD_A','CARD_C')))
        self.assertEqual([r['name'] for r in v['picks']],['测试C','测试A','测试B'])

    def test_37_unknown_cost_stays_last_and_loses_no_card(self):
        v=self.view(self.state(deck=('CARD_D','CARD_D','CARD_C')))
        self.assertEqual([r['id'] for r in v['picks']],['CARD_C','CARD_D','CARD_D'])
        self.assertEqual(v['count'],3)

    def test_38_failed_read_keeps_the_last_deck_but_marks_it_stale(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(None,self.diag(code='read_error',error='memory read failed'))
        self.assertEqual(v['count'],2);self.assertEqual(v['stage'],'none')
        self.assertFalse(v['count_exact']);self.assertTrue(v['deck_stale'])

    def test_44_a_good_read_after_a_failure_clears_the_stale_hint(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        self.assertTrue(self.view(None,self.diag(code='read_error',error='boom'))['count_exact'] is False)
        v=self.view(self.state(deck=('CARD_A','CARD_B','CARD_C')))
        self.assertEqual(v['count'],3);self.assertTrue(v['count_exact']);self.assertFalse(v['deck_stale'])

    def test_45_finished_draft_is_not_a_failed_read(self):
        # A successful poll with no active draft must not raise the hint, even
        # though the previous deck is the one being shown.
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(None,self.diag(code='reading'))
        self.assertEqual(v['count'],2);self.assertTrue(v['count_exact']);self.assertFalse(v['deck_stale'])

    def test_confirmed_inactive_draft_clears_previous_selection(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(None,self.diag(code='reading',inactive=True))
        self.assertEqual(v['count'],0);self.assertEqual(v['picks'],[])
        self.assertEqual(v['deck_id'],'')

    def test_46_expired_snapshot_marks_the_kept_deck_stale(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(None,self.diag(code='reading',stale_read=True))
        self.assertEqual(v['count'],2);self.assertFalse(v['count_exact']);self.assertTrue(v['deck_stale'])
        # ...and a fresh read clears it again.
        v=self.view(self.state(deck=('CARD_A','CARD_B')))
        self.assertTrue(v['count_exact']);self.assertFalse(v['deck_stale'])

    def test_39_a_new_arena_clears_the_previous_deck(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(self.state(deck=('CARD_C',),deck_id='99',hero='HERO_09'))
        self.assertEqual(v['deck_id'],'99');self.assertEqual([r['id'] for r in v['picks']],['CARD_C'])

    def test_40_process_restart_does_not_keep_the_old_deck(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(self.state(deck=(),deck_id='42'),self.diag(process_instance='inst-2'))
        self.assertEqual(v['count'],0);self.assertEqual(v['picks'],[])
        v=self.view(None,self.diag(code='not_running'))
        self.assertEqual(v['count'],0)

    def test_41_hero_selection_clears_the_finished_arena(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(self.state('HERO',deck=(),deck_id='',hero=''))
        self.assertEqual(v['count'],0);self.assertFalse(v['show_count'])

    def test_42_redraft_replaces_the_deck_instead_of_extending_it(self):
        self.view(self.state(deck=('CARD_A',)*5))
        v=self.view(self.state(deck=('CARD_B',)*3,mode='REDRAFTING'))
        self.assertEqual(v['stage'],'redrafting');self.assertEqual(v['count'],3)
        self.assertEqual({r['id'] for r in v['picks']},{'CARD_B'})

    def test_43_unreadable_deck_keeps_the_previous_selection_marked_stale(self):
        self.view(self.state(deck=('CARD_A','CARD_B')))
        v=self.view(self.state(deck=(),deck_reason='slot_layout'))
        self.assertEqual(v['count'],2);self.assertFalse(v['count_exact'])

    def test_24_class_aggregation_modes_missing_and_source_snapshot(self):
        raw=dict(stats=[dict(playerClass='mage',totalGames=100,totalsWins=60),dict(playerClass='mage',totalGames=50,totalsWins=20)])
        self.assertEqual(aggregate(raw)['MAGE'],dict(totalGames=150,totalsWins=80))
        self.assertIsNone(self.stats.get(False,'DRUID'))
        data=copy.deepcopy(self.stats.data);data['modes']['arena-underground']['classes']['MAGE']['totalsWins']=20
        ratings=ClassRatings(data=data);self.assertNotEqual(ratings.get(False,'MAGE')['rank'],ratings.get(True,'MAGE')['rank'])
        self.assertEqual(len(ClassRatings().metadata()['modes']),2)
        partial=copy.deepcopy(data);partial['modes'].pop('arena-underground')
        single=ClassRatings(data=partial);self.assertIsNotNone(single.get(False,'MAGE'));self.assertIsNone(single.get(True,'MAGE'))
        with self.assertRaises(ValueError):aggregate(dict(stats=[dict(playerClass='mage',totalGames=1,totalsWins=2)]))

    def test_26_process_discovery_proton_and_hud_exclusion(self):
        from engine.proton import discover_process
        root=Path(self.tmp.name)/'proc';root.mkdir();prefix=Path(self.tmp.name)/'prefix';(prefix/'drive_c').mkdir(parents=True)
        for pid,exe in [('42','Hearthstone.exe'),('43','hearthstone-hud-renderer')]:
            p=root/pid;p.mkdir();(p/'comm').write_text(exe);(p/'cmdline').write_bytes((r'Z:\home\deck\Games\Hearthstone.exe' if pid=='42' else exe).encode()+b'\0');(p/'environ').write_bytes(('WINEPREFIX='+str(prefix)).encode()+b'\0')
        self.assertEqual(discover_process(root)['pid'],42)
