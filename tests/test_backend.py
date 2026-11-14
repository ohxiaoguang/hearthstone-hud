"""Exercise Decky lifecycle against an isolated fake Decky module, not a fake HUD."""
import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        base=Path(self.tmp.name)
        self.old=sys.modules.get('decky')
        sys.modules['decky']=types.SimpleNamespace(DECKY_PLUGIN_SETTINGS_DIR=base/'settings',DECKY_PLUGIN_RUNTIME_DIR=base/'runtime')
        spec=importlib.util.spec_from_file_location('hud_backend',Path(__file__).resolve().parents[1]/'main.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.plugin=module.Plugin();await self.plugin._main()
    async def asyncTearDown(self):
        await self.plugin._unload()
        if self.old is None:sys.modules.pop('decky',None)
        else:sys.modules['decky']=self.old
        self.tmp.cleanup()
    async def test_settings_validation_and_visibility(self):
        with self.assertRaises(ValueError):await self.plugin.configure({'scale':float('nan')})
        with self.assertRaises(ValueError):await self.plugin.configure({'opacity':8})
        with self.assertRaises(ValueError):await self.plugin.configure({'visible':'yes'})
        await self.plugin.configure({'visible':False,'game_dir':self.tmp.name})
        await asyncio.sleep(.3)
        state=(self.plugin.runtime/'state.json').read_text()
        self.assertIn('"visible": false',state)
        self.assertFalse((await self.plugin.status())['running'])
    async def test_no_missing_binary_launch(self):
        with self.assertRaises(RuntimeError):await self.plugin.start_hud()
        self.assertFalse((await self.plugin.status())['running'])
    async def test_stop_idempotent(self):
        await self.plugin.stop_hud();await self.plugin.stop_hud()
        self.assertFalse((await self.plugin.status())['running'])

    async def test_live_nested_log_to_atomic_hud_state_and_truncation(self):
        import json
        game=Path(self.tmp.name)/'game'
        session=game/'Logs/nested/session';session.mkdir(parents=True)
        power=session/'Power.log'
        power.write_text('D 00:01:00.0000000 GameState.DebugPrintPower() - CREATE_GAME\n')
        await self.plugin.configure({'game_dir':str(game)})
        await asyncio.sleep(.6)
        self.assertIsNotNone(self.plugin.parser.game, await self.plugin.status())
        state=json.loads((self.plugin.runtime/'state.json').read_text())
        self.assertEqual(state['schema'],2)
        self.assertEqual(state['tracking']['status'],'identifying')
        self.assertEqual(self.plugin.discovery['accepted'],1)
        power.write_text('D 00:01:01.0000000 GameState.DebugPrintPower() - CREATE_GAME\n')
        await asyncio.sleep(.4)
        self.assertEqual(self.plugin.tail.generation,2)
        self.assertEqual(self.plugin.parser.accepted,1)

    async def test_diagnostic_api_is_redacted_and_does_not_export_files(self):
        self.plugin.recent_errors.append('token=private-secret /home/real-user/file')
        before=set(self.plugin.runtime.rglob('*.txt'))
        text=await self.plugin.diagnostic_text()
        self.assertIn('Hearthstone HUD Diagnostic',text)
        self.assertNotIn('private-secret',text);self.assertNotIn('real-user',text)
        self.assertEqual(before,set(self.plugin.runtime.rglob('*.txt')))

    async def test_database_and_image_tls_settings_are_independent(self):
        self.assertFalse(self.plugin.cards.database_verify_tls)
        await self.plugin.configure({'database_tls_verify':True,'image_tls_verify':False})
        self.assertTrue(self.plugin.cards.database_verify_tls)
        self.assertFalse(self.plugin.cards.image_verify_tls)
        status=await self.plugin.status()
        self.assertTrue(status['cards']['database_tls_verify'])
        self.assertIn('Database Verification: enabled',await self.plugin.diagnostic_text())

    async def test_layout_options_and_actual_storage_paths(self):
        await self.plugin.configure(dict(own_played=False,opponent_played=True,show_summary=False,panel_width=440,hide_exhausted=True))
        status=await self.plugin.status()
        self.assertEqual(status['settings']['panel_width'],440)
        self.assertFalse(status['settings']['own_played'])
        self.assertEqual(status['storage']['database'],str(self.plugin.runtime/'cache/cards.json'))
        self.assertEqual(status['storage']['manual_images'],str(self.plugin.runtime/'cache/images/manual'))
        with self.assertRaises(ValueError):await self.plugin.configure({'panel_width':100})
        with self.assertRaises(ValueError):await self.plugin.configure({'show_summary':'no'})

    async def test_arena_qam_candidates_manual_reconcile_and_inode_rewind(self):
        import json
        from datetime import datetime
        from unittest.mock import patch
        self.plugin.cards.install([dict(id='TEST_A',dbfId=1,name='测试甲',type='MINION'),dict(id='TEST_B',dbfId=2,name='测试乙',type='SPELL')])
        root=Path(self.tmp.name)/'game';session=root/'Logs/Hearthstone_2026_11_15_12_00_00';session.mkdir(parents=True)
        (session/'Power.log').write_text('')
        arena=session/'Arena.log'
        begin='D 12:00:01.0000000 Got new draft deck with ID: 42\nD 12:00:02.0000000 Client chooses: 法师 (HERO_08)\n'
        arena.write_text(begin)
        self.plugin.arena.clock=lambda:datetime(2026,11,15,12,10)
        await self.plugin.configure({'game_dir':str(root),'arena':True})
        for _ in range(80):
            if self.plugin.arena_caught_up and self.plugin.arena.deck_id=='42':break
            await asyncio.sleep(.05)
        self.assertTrue(self.plugin.arena_caught_up)
        ctx=self.plugin.arena.context()
        with patch.object(self.plugin,'_ensure_media_worker'):
            preview=await self.plugin.arena_set_offer(ctx['deck_id'],ctx['phase'],ctx['round'],['TEST_A','TEST_B','TEST_A'])
        self.assertEqual(preview['count'],0);self.assertEqual(len(preview['candidates']),3)
        await self.plugin.arena_manual_pick('42',ctx['phase'],1,'TEST_A')
        self.assertTrue((self.plugin.settings_dir/'arena-manual.json').exists())
        with arena.open('a') as f:f.write('D 12:00:03.0000000 Client chooses: 卡 (TEST_A)\n')
        for _ in range(80):
            if self.plugin.arena.records()[0]['reconciled']:break
            await asyncio.sleep(.05)
        self.assertEqual(len(self.plugin.arena.records()),1);self.assertTrue(self.plugin.arena.records()[0]['reconciled'])
        generation=self.plugin.arena_tail.generation
        replacement=session/'replacement';replacement.write_text(begin+'D 12:00:04.0000000 Client chooses: 卡 (TEST_B)\n');replacement.replace(arena)
        for _ in range(80):
            if self.plugin.arena_tail.generation>generation:break
            await asyncio.sleep(.05)
        self.assertGreater(self.plugin.arena_tail.generation,generation)
        self.assertEqual(self.plugin.arena.view()['count'],1);self.assertEqual(self.plugin.arena.records()[0]['card_id'],'TEST_B')
        state=json.loads((self.plugin.runtime/'state.json').read_text())
        self.assertTrue(state['arena_state']['visible']);self.assertEqual(state['tracking']['status'],'waiting')

    async def test_arena_reads_when_power_idle_and_final_deck_precedes_game(self):
        import json,os,time
        from engine.deckstring import DeckDefinition,encode
        self.plugin.cards.install([dict(id='TEST_A',dbfId=1,name='测试甲',type='MINION')])
        root=Path(self.tmp.name)/'game';session=root/'Logs/session';session.mkdir(parents=True)
        power=session/'Power.log';power.write_text('');os.utime(power,(time.time()-600,time.time()-600))
        (session/'Arena.log').write_text('D 12:00:01.0000000 Got new draft deck with ID: 42\nD 12:00:02.0000000 Client chooses: 法师 (HERO_08)\n')
        code=encode(DeckDefinition([637],{1:30}))
        (session/'Decks.log').write_text('D 12:00:03.0000000 Finished Editing Deck:\nD 12:00:03.0000000 # Deck ID: 42\nD 12:00:03.0000000 '+code+'\n')
        await self.plugin.configure({'game_dir':str(root),'arena':True})
        for _ in range(80):
            if self.plugin.arena.exact_dbf:break
            await asyncio.sleep(.05)
        self.assertFalse(self.plugin.active);self.assertEqual(self.plugin.arena.exact_dbf,{1:30})
        self.assertTrue(json.loads((self.plugin.runtime/'state.json').read_text())['arena_state']['visible'])
        power.write_text('D 12:00:04.0000000 GameState.DebugPrintPower() - CREATE_GAME\nD 12:00:04.1000000 GameState.DebugPrintGame() - GameType=GT_ARENA\n')
        await self.plugin.configure({'game_dir':str(root)})
        for _ in range(80):
            if self.plugin.parser.game and self.plugin.parser.game.game_type=='GT_ARENA':break
            await asyncio.sleep(.05)
        self.assertEqual(self.plugin.arena.definition_for_game(self.plugin.parser.game.start),{1:30})

    async def test_memory_default_off_opt_in_hero_without_logs_and_disable(self):
        import json,threading
        from engine.memory_watch import MemoryWatch
        from engine.arena_memory import DraftState,DraftChoice
        self.assertFalse(self.plugin.settings['arena_memory']);self.assertIsNone(self.plugin.memory_watch.thread)
        closed=threading.Event()
        class Reader:
            def poll(self):return DraftState('DRAFTING','HERO',False,tuple(DraftChoice(c) for c in ('HERO_08','HERO_09','HERO_01'))),dict(code='hero_selection',status='mock hero',pid=100,error='')
            def close(self):closed.set()
        self.plugin.memory_watch=MemoryWatch(lambda stop:Reader(),normal=.01)
        await self.plugin.configure({'arena_memory':True,'arena':True})
        for _ in range(100):
            if self.plugin.memory_watch.snapshot()[0]:break
            await asyncio.sleep(.005)
        self.plugin._publish();state=json.loads((self.plugin.runtime/'state.json').read_text())
        self.assertFalse(self.plugin.arena_caught_up);self.assertTrue(state['arena_state']['visible']);self.assertEqual(state['arena_state']['stage'],'hero_selection')
        self.assertEqual(self.plugin.arena.view()['count'],0);self.assertFalse(state['arena_state']['show_count'])
        await self.plugin.configure({'arena_memory':False})
        self.assertTrue(closed.is_set());self.assertIsNone(self.plugin.memory_watch.thread)
        self.assertEqual((await self.plugin.status())['arena']['memory']['code'],'disabled')

    async def test_memory_does_not_override_normal_match_or_block_event_loop(self):
        import time,threading,json
        from engine.memory_watch import MemoryWatch
        from engine.arena_memory import DraftState,DraftChoice
        class Reader:
            def __init__(self,stop):self.stop=stop
            def poll(self):self.stop.wait(.2);return DraftState('DRAFTING','CARD',False,tuple(DraftChoice(c) for c in ('CARD_A','CARD_B','CARD_C'))),dict(code='card_selection',status='mock cards',pid=100,error='')
            def close(self):pass
        self.plugin.memory_watch=MemoryWatch(lambda stop:Reader(stop),normal=.01)
        await self.plugin.configure({'arena_memory':True})
        start=time.monotonic();await asyncio.sleep(.01)
        self.assertLess(time.monotonic()-start,.15)
        for _ in range(100):
            if self.plugin.memory_watch.snapshot()[0]:break
            await asyncio.sleep(.005)
        from test_tracking import TrackingTests
        fixture=TrackingTests();fixture.setUp()
        try:
            self.plugin.parser=fixture.p;self.plugin.cards=fixture.cards
            self.plugin.active=True;self.plugin.caught_up=True;self.plugin.settings['arena']=True
            before=fixture.p.view(fixture.cards)
            self.plugin._publish();state=json.loads((self.plugin.runtime/'state.json').read_text())
            self.assertEqual(state['tracking']['status'],'playing');self.assertFalse(state['arena_state']['visible'])
            self.assertEqual(fixture.p.view(fixture.cards)['own'],before['own'])
            self.assertEqual(fixture.p.initial_dbf,{1001:2})
            await self.plugin.configure({'arena_memory':False})
        finally:fixture.doCleanups()

    async def test_invalid_saved_memory_flag_is_not_an_opt_in(self):
        import json
        await self.plugin._unload()
        (self.plugin.settings_dir/'settings.json').write_text(json.dumps(dict(arena_memory='true')))
        await self.plugin._main()
        self.assertFalse(self.plugin.settings['arena_memory']);self.assertIsNone(self.plugin.memory_watch.thread)
