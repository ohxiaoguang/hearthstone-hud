"""Exercise Decky lifecycle against an isolated fake Decky module, not a fake HUD."""
import asyncio
import json
import importlib.util
import sys
import tempfile
import types
import unittest
import time
from unittest.mock import patch
from pathlib import Path

class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # First-use downloads are automatic; keep lifecycle tests network-free.
        def unavailable(cards):
            cards.attempted=time.time();cards.download_state='自动下载失败'
            return None
        self.refresh_patch=patch('engine.cards.Cards.refresh',unavailable)
        self.refresh_patch.start()
        self.tmp=tempfile.TemporaryDirectory()
        base=Path(self.tmp.name)
        self.old=sys.modules.get('decky')
        sys.modules['decky']=types.SimpleNamespace(DECKY_PLUGIN_SETTINGS_DIR=base/'settings',DECKY_PLUGIN_RUNTIME_DIR=base/'runtime')
        spec=importlib.util.spec_from_file_location('hud_backend',Path(__file__).resolve().parents[1]/'main.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.DEFAULTS['arena_data_auto_update']=False
        self.plugin=module.Plugin();await self.plugin._main()
    async def asyncTearDown(self):
        await self.plugin._unload()
        if self.old is None:sys.modules.pop('decky',None)
        else:sys.modules['decky']=self.old
        self.tmp.cleanup()
        self.refresh_patch.stop()
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

    async def test_plugin_master_stops_owned_threads_and_preserves_feature_settings(self):
        import threading
        from engine.memory_watch import MemoryWatch
        closed=threading.Event()
        class Reader:
            def poll(self):return None,dict(code='reading',status='mock',pid=100,error='')
            def close(self):closed.set()
        self.plugin.memory_watch=MemoryWatch(lambda stop:Reader(),normal=.01)
        await self.plugin.configure({'arena':True,'arena_memory':True,'font_size':26})
        class Process:
            returncode=None
            def terminate(self):self.returncode=0
            async def wait(self):return self.returncode
        process=Process();self.plugin.proc=process
        prefix='hud-io-'+str(id(self.plugin))
        await asyncio.sleep(.05)
        await self.plugin.configure({'enabled':False})
        self.assertTrue(closed.is_set());self.assertIsNone(self.plugin.memory_watch.thread)
        self.assertEqual(process.returncode,0);self.assertIsNone(self.plugin.proc)
        self.assertIsNone(self.plugin.io_pool);self.assertIsNone(self.plugin.task);self.assertIsNone(self.plugin.media_task)
        self.assertFalse(any(t.name.startswith(prefix) for t in threading.enumerate()))
        self.assertTrue(self.plugin.settings['visible']);self.assertTrue(self.plugin.settings['arena_memory'])
        self.assertEqual(self.plugin.settings['font_size'],26)
        self.assertFalse(any((await self.plugin.status())['background'].values()))
        for operation in (self.plugin.start_hud,self.plugin.retry_card_database,self.plugin.download_missing_images,self.plugin.clear_card_cache):
            with self.assertRaises(RuntimeError):await operation()
        await self.plugin.configure({'enabled':True})
        self.assertIsNotNone(self.plugin.task);self.assertIsNotNone(self.plugin.memory_watch.thread)
        self.assertEqual(self.plugin.settings['font_size'],26)
        await self.plugin.configure({'enabled':False});await self.plugin.configure({'enabled':False})
        self.assertFalse(any(t.name.startswith(prefix) for t in threading.enumerate()))

    async def test_master_waits_for_inflight_download_before_reporting_off(self):
        import threading
        from image_support import tile_png
        started=threading.Event();release=threading.Event()
        self.plugin.cards.updated=10**12
        def download(cid):
            started.set();release.wait(2)
            (self.plugin.cards.images/(cid+'.png')).write_bytes(tile_png())
        with patch.object(self.plugin.cards,'download_image',side_effect=download):
            self.plugin.cards.request_images(['CARD_A'])
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            closing=asyncio.create_task(self.plugin.configure({'enabled':False}))
            try:
                await asyncio.sleep(.02);self.assertFalse(closing.done())
                self.assertEqual(self.plugin.lifecycle_state,'stopping')
            finally:release.set()
            await closing
        self.assertTrue((self.plugin.cards.images/'CARD_A.png').exists())  # Retained, not deleted.
        self.assertIsNone(self.plugin.io_pool)
        self.assertEqual(self.plugin.lifecycle_state,'disabled')

    async def test_saved_disabled_startup_does_not_scan_or_download_and_restores_hud_choice(self):
        from unittest.mock import AsyncMock
        await self.plugin.configure({'enabled':False})
        plugin_type=type(self.plugin)
        globals_=self.plugin._main.__func__.__globals__
        self.plugin=plugin_type()
        with patch.dict(globals_,discover_process=lambda:(_ for _ in ()).throw(AssertionError('unexpected scan'))):
            await self.plugin._main()
            await asyncio.sleep(.05)
            self.assertIsNone(self.plugin.task);self.assertIsNone(self.plugin.media_task);self.assertIsNone(self.plugin.io_pool)
            self.assertTrue(self.plugin.settings['visible'])
            await self.plugin.configure({'font_size':25})
            self.assertIsNone(self.plugin.io_pool)
        with patch.object(self.plugin,'_start_renderer',new_callable=AsyncMock) as restore,patch.dict(globals_,platform=types.SimpleNamespace(system=lambda:'Linux')):
            await self.plugin.configure({'enabled':True})
            restore.assert_awaited_once()
        self.assertEqual(self.plugin.settings['font_size'],25)

    async def test_disabled_log_monitor_does_not_parse_new_data_then_catches_up(self):
        root=Path(self.tmp.name)/'game';session=root/'Logs/session';session.mkdir(parents=True)
        power=session/'Power.log';power.write_text('D 12:00:00.0000000 GameState.DebugPrintPower() - CREATE_GAME\n')
        await self.plugin.configure({'game_dir':str(root),'visible':False})
        await asyncio.sleep(.4)
        await self.plugin.configure({'enabled':False})
        accepted=self.plugin.parser.accepted;scan=self.plugin.last_scan
        with power.open('a') as stream:stream.write('D 12:00:01.0000000 GameState.DebugPrintPower() - CREATE_GAME\n')
        await asyncio.sleep(.3)
        self.assertEqual(self.plugin.parser.accepted,accepted);self.assertEqual(self.plugin.last_scan,scan)
        await self.plugin.configure({'enabled':True});await asyncio.sleep(.4)
        self.assertGreater(self.plugin.parser.accepted,accepted)

    async def test_hud_selected_cards_follow_the_memory_deck_only(self):
        """Memory is the only source; ten identical log lines change nothing."""
        from engine.memory_watch import MemoryWatch
        from engine.arena_memory import DraftState,DraftChoice
        self.plugin.cards.install([dict(id='CARD_'+c,dbfId=i+1,name=c,cost=i,type='MINION') for i,c in enumerate('ABC')])
        deck=['CARD_A','CARD_A','CARD_B']
        class Reader:
            def poll(self):
                return (DraftState('DRAFTING','CARD',False,tuple(DraftChoice('CARD_'+c) for c in 'ABC'),'3386335194','HERO_08',tuple(deck),deck_object=True,deck_slots=2),
                        dict(code='card_selection',status='mock',pid=100,process_instance='same',error='',deck_object=True,deck_slots=2,deck_parsed=len(deck),deck_reason=''))
            def close(self):pass
        self.plugin.memory_watch=MemoryWatch(lambda stop:Reader(),normal=.01)
        root=Path(self.tmp.name)/'game';session=root/'Logs/session';session.mkdir(parents=True)
        (session/'Power.log').write_text('')
        arena=session/'Arena.log';arena.write_text('D 12:00:01.0000000 Got new draft deck with ID: 3386335194\n')
        await self.plugin.configure({'arena':True,'arena_memory':True,'game_dir':str(root),'visible':False})
        for _ in range(100):
            view=self.plugin._arena_view()
            if view['count']==3:break
            await asyncio.sleep(.02)
        self.assertEqual(view['count'],3);self.assertEqual(len(view['picks']),3)
        self.assertEqual([r['id'] for r in view['picks']],['CARD_A','CARD_A','CARD_B'])
        self.assertNotIn('history_picks',view)
        # The exact sequence reported from the device: repeated picks of one card.
        with arena.open('a') as f:
            for second in range(25,35):
                f.write(f'D 12:00:{second}.0000000 Client chooses: 腐臭吞噬者 (CARD_A)\n')
        for _ in range(60):
            await asyncio.sleep(.02)
            if self.plugin.arena.raw_choices.get('draft:3386335194') and len(self.plugin.arena.raw_choices['draft:3386335194'])==10:break
        await asyncio.sleep(.2)
        view=self.plugin._arena_view()
        self.assertEqual(view['count'],3)
        self.assertEqual(self.plugin.arena.view()['count'],10)   # log model sees them, HUD ignores them
        deck.append('CARD_C')
        await asyncio.sleep(.2)
        self.assertEqual(self.plugin._arena_view()['count'],4)   # replaced, not appended
        state=json.loads((self.plugin.runtime/'state.json').read_text())
        self.assertEqual(state['arena_state']['count'],4);self.assertTrue(state['arena_state']['visible'])

    async def test_memory_deck_shows_without_any_arena_log(self):
        """No Arena.log at all: the panel still shows the memory deck."""
        from engine.memory_watch import MemoryWatch
        from engine.arena_memory import DraftState,DraftChoice
        self.plugin.cards.install([dict(id='CARD_'+c,dbfId=i+1,name=c,cost=i,type='MINION') for i,c in enumerate('ABC')])
        class Reader:
            def poll(self):
                return (DraftState('DRAFTING','CARD',False,tuple(DraftChoice('CARD_'+c) for c in 'ABC'),'3386335194','HERO_08',('CARD_A','CARD_B'),deck_object=True,deck_slots=2),
                        dict(code='card_selection',status='mock',pid=100,process_instance='same',error='',deck_object=True,deck_slots=2,deck_parsed=2,deck_reason=''))
            def close(self):pass
        self.plugin.memory_watch=MemoryWatch(lambda stop:Reader(),normal=.01)
        root=Path(self.tmp.name)/'game';session=root/'Logs/session';session.mkdir(parents=True)
        (session/'Power.log').write_text('')
        await self.plugin.configure({'arena':True,'arena_memory':True,'game_dir':str(root),'visible':False})
        for _ in range(100):
            view=self.plugin._arena_view()
            if view['count']==2:break
            await asyncio.sleep(.02)
        self.assertFalse(self.plugin.arena_caught_up);self.assertEqual(view['count'],2)
        self.assertEqual(view['deck_id'],'3386335194');self.assertTrue(view['count_exact'])
        text=await self.plugin.diagnostic_text()
        self.assertIn('[Arena]',text);self.assertIn('Deck Source: memory DraftDeck only',text)
        self.assertIn('[Arena Memory]',text);self.assertIn('deck_parsed: 2',text)

    async def test_failed_read_keeps_the_last_deck_in_the_hud(self):
        """A read failure must not empty the panel or fall back to the log."""
        from engine.memory_watch import MemoryWatch
        from engine.arena_memory import DraftState,DraftChoice
        self.plugin.cards.install([dict(id='CARD_'+c,dbfId=i+1,name=c,cost=i,type='MINION') for i,c in enumerate('ABC')])
        state={'good':True}
        class Reader:
            def poll(self):
                deck=('CARD_A','CARD_B') if state['good'] else ()
                reason='' if state['good'] else 'slot_layout'
                return (DraftState('DRAFTING','CARD',False,tuple(DraftChoice('CARD_'+c) for c in 'ABC'),'3386335194','HERO_08',deck,deck_object=True,deck_slots=2,deck_reason=reason),
                        dict(code='card_selection',status='mock',pid=100,process_instance='same',error='',deck_object=True,deck_slots=2,deck_parsed=len(deck),deck_reason=reason))
            def close(self):pass
        self.plugin.memory_watch=MemoryWatch(lambda stop:Reader(),normal=.01)
        root=Path(self.tmp.name)/'game';session=root/'Logs/session';session.mkdir(parents=True)
        (session/'Power.log').write_text('')
        (session/'Arena.log').write_text('D 12:00:01.0000000 Got new draft deck with ID: 3386335194\nD 12:00:02.0000000 Client chooses: 卡 (CARD_C)\n')
        await self.plugin.configure({'arena':True,'arena_memory':True,'game_dir':str(root),'visible':False})
        for _ in range(100):
            if self.plugin._arena_view()['count']==2:break
            await asyncio.sleep(.02)
        state['good']=False
        await asyncio.sleep(.2)
        view=self.plugin._arena_view()
        self.assertEqual(view['count'],2)                  # stale snapshot kept
        self.assertFalse(view['count_exact'])
        self.assertEqual([r['id'] for r in view['picks']],['CARD_A','CARD_B'])  # log pick CARD_C not used

    async def test_display_defaults_font_size_and_immediate_publication(self):
        self.assertTrue(self.plugin.settings['own_deck'])
        self.assertFalse(self.plugin.settings['arena'])  # Merged memory feature is opt-in.
        self.assertFalse(self.plugin.settings['arena_memory'])
        self.assertEqual(self.plugin.settings['font_size'],22)
        await self.plugin.configure({'font_size':28,'visible':False})
        state=json.loads((self.plugin.runtime/'state.json').read_text())
        saved=json.loads((self.plugin.settings_dir/'settings.json').read_text())
        self.assertEqual(state['font_size'],28)
        self.assertFalse(state['visible'])
        self.assertEqual(saved['font_size'],28)
        for value in (13,31,float('inf'),float('nan')):
            with self.assertRaises(ValueError):await self.plugin.configure({'font_size':value})

    async def test_master_start_restores_hidden_renderer_and_stop_persists(self):
        class Process:
            returncode=None
            def terminate(self):self.returncode=0
            async def wait(self):return self.returncode
        process=Process()
        self.plugin.proc=process
        await self.plugin.configure({'visible':False})
        status=await self.plugin.start_hud()
        self.assertTrue(status['running']);self.assertTrue(status['settings']['visible'])
        self.assertIs(self.plugin.proc,process)  # No duplicate renderer launch.
        self.assertTrue(json.loads((self.plugin.runtime/'state.json').read_text())['visible'])
        await self.plugin.stop_hud()
        self.assertEqual(process.returncode,0)
        self.assertFalse(json.loads((self.plugin.runtime/'state.json').read_text())['visible'])
        self.assertFalse(json.loads((self.plugin.settings_dir/'settings.json').read_text())['visible'])

    async def test_hud_activation_configures_both_logs_and_preserves_other_sections(self):
        from engine.logconfig import inspect_config
        root=Path(self.tmp.name)/'pfx';user=root/'drive_c/users/actual/AppData/Local/Blizzard/Hearthstone'
        user.mkdir(parents=True)
        original=b'[Other]\nKeep=Yes\n'
        (user/'log.config').write_bytes(original)
        process=dict(found=True,prefix=str(root),user_dir=str(user),instance='first')
        with patch.dict(self.plugin._activate_tracking_logs.__func__.__globals__,discover_process=lambda:process):
            await self.plugin._activate_tracking_logs()
        self.assertTrue(inspect_config(user,'Decks')['enabled'])
        self.assertTrue(inspect_config(user,'Arena')['enabled'])
        self.assertIn('[Other]\nKeep=Yes',(user/'log.config').read_text())
        backups=list(user.glob('log.config.backup-*'))
        self.assertIn(original,[p.read_bytes() for p in backups])
        self.assertTrue(self.plugin.arena_config['restart_required'])
        async with self.plugin.config_lock:await self.plugin._sync_tracking_logs(process)
        self.assertEqual(len(backups),len(list(user.glob('log.config.backup-*'))))

    async def test_first_use_worker_and_clear_preserves_settings_and_game_data(self):
        self.assertIsNotNone(self.plugin.media_task)
        await self.plugin.configure({'font_size':26})
        game_log=Path(self.tmp.name)/'Power.log';game_log.write_text('private game data')
        source=Path(self.tmp.name)/'original.json';source.write_text('user import')
        (self.plugin.cards.directory/'cards.json').write_text('{}')
        (self.plugin.cards.images/'old.png').write_bytes(b'old')
        legacy=self.plugin.cards.images/'manual';legacy.mkdir(parents=True,exist_ok=True)
        (legacy/'manual.png').write_bytes(b'old')
        old_worker=self.plugin.media_task
        await self.plugin.clear_card_cache()
        self.assertTrue(old_worker.done());self.assertIsNot(old_worker,self.plugin.media_task)
        self.assertFalse((self.plugin.cards.images/'old.png').exists())
        self.assertFalse(legacy.exists())
        self.assertEqual(self.plugin.settings['font_size'],26)
        self.assertEqual(game_log.read_text(),'private game data');self.assertEqual(source.read_text(),'user import')

    async def test_merged_arena_setting_migrates_without_unrequested_memory_access(self):
        from engine.memory_watch import MemoryWatch
        for arena,memory in ((False,True),(True,False),(True,True)):
            await self.plugin._unload()
            (self.plugin.settings_dir/'settings.json').write_text(json.dumps(dict(arena=arena,arena_memory=memory)))
            self.plugin=type(self.plugin)()
            with patch.object(MemoryWatch,'start') as start:
                await self.plugin._main()
                self.assertEqual(self.plugin.settings['arena'],arena and memory)
                self.assertEqual(self.plugin.settings['arena_memory'],arena and memory)
                self.assertEqual(start.call_count,int(arena and memory))

    async def test_clear_waits_for_inflight_download_then_allows_fresh_download(self):
        import threading
        from image_support import tile_png
        started=threading.Event();release=threading.Event()
        self.plugin.cards.updated=10**12
        def download(cid):
            started.set();release.wait(2)
            (self.plugin.cards.images/(cid+'.png')).write_bytes(tile_png())
        with patch.object(self.plugin.cards,'download_image',side_effect=download):
            self.plugin.cards.request_images(['OLD_CARD'])
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            clearing=asyncio.create_task(self.plugin.clear_card_cache())
            try:
                await asyncio.sleep(.02)
                self.assertFalse(clearing.done())
            finally:release.set()
            await clearing
        self.assertFalse((self.plugin.cards.images/'OLD_CARD.png').exists())
        self.assertEqual(self.plugin.cards.pending,set())

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
        self.assertEqual(status['storage']['database'],str(self.plugin.cards.cache_path()))
        with self.assertRaises(ValueError):await self.plugin.configure({'panel_width':100})
        with self.assertRaises(ValueError):await self.plugin.configure({'show_summary':'no'})

    async def test_arena_log_picks_and_manual_records_never_reach_the_hud(self):
        """Arena.log keeps parsing, but the selected list stays memory-only."""
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
        self.assertEqual(preview['count'],0);self.assertEqual(preview['picks'],[]);self.assertEqual(preview['candidates'],[])
        await self.plugin.arena_manual_pick('42',ctx['phase'],1,'TEST_A')
        with arena.open('a') as f:
            for second in range(3,13):
                f.write(f'D 12:00:{second:02d}.0000000 Client chooses: 卡 (TEST_A)\n')
        for _ in range(80):
            if self.plugin.arena.records() and self.plugin.arena.records()[0]['reconciled']:break
            await asyncio.sleep(.05)
        self.assertTrue(self.plugin.arena.records()[0]['reconciled'])
        self.assertGreaterEqual(self.plugin.arena.view()['count'],1)   # the log model still sees picks
        self.assertEqual(self.plugin._arena_view()['count'],0)         # the HUD does not
        generation=self.plugin.arena_tail.generation
        replacement=session/'replacement';replacement.write_text(begin+'D 12:00:04.0000000 Client chooses: 卡 (TEST_B)\n');replacement.replace(arena)
        for _ in range(80):
            if self.plugin.arena_tail.generation>generation:break
            await asyncio.sleep(.05)
        self.assertGreater(self.plugin.arena_tail.generation,generation)
        self.assertEqual(self.plugin.arena.records()[0]['card_id'],'TEST_B')
        state=json.loads((self.plugin.runtime/'state.json').read_text())
        self.assertFalse(state['arena_state']['visible']);self.assertEqual(state['arena_state']['count'],0)
        self.assertEqual(state['tracking']['status'],'waiting')

    async def test_decks_log_final_definition_still_feeds_match_tracking(self):
        """Decks.log remains the source for arena match tracking, not for the panel."""
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
        # No memory snapshot: the arena panel stays empty even with a final definition.
        self.assertFalse(json.loads((self.plugin.runtime/'state.json').read_text())['arena_state']['visible'])
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

    async def test_resource_management_rpcs_and_status_payload(self):
        """Per-database files, full art download and independent clearing."""
        import json
        from unittest.mock import patch
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from image_support import tile_png
        rows=[dict(id=f'CARD_{i}',dbfId=i+1,name=f'Card {i}',cost=i % 5,type='MINION') for i in range(12)]
        self.plugin.cards.install(rows)
        (self.plugin.cards.directory/'cards-enUS.json').write_text(json.dumps(dict(updated=1,source='t',locale='enUS',cards=rows)))
        (self.plugin.cards.directory/'cards-zhCN.json').write_text(json.dumps(dict(updated=1,source='t',locale='zhCN',cards=rows)))
        status=await self.plugin.status()
        self.assertEqual(status['repository'],'https://github.com/ohxiaoguang/hearthstone-hud')
        databases=status['cards']['databases']
        self.assertEqual(sorted(databases),['enUS','zhCN'])
        self.assertTrue(databases['enUS']['active']);self.assertTrue(databases['zhCN']['exists'])
        self.assertEqual(status['cards']['image_usage']['total'],12)
        downloaded=[]
        def fake(cid):
            downloaded.append(cid)
            (self.plugin.cards.images/(cid+'.png')).write_bytes(tile_png())
        with patch.object(self.plugin.cards,'download_image',side_effect=fake):
            await self.plugin.download_all_images()
            for _ in range(200):
                if self.plugin.cards.image_batch['status']=='complete':break
                await asyncio.sleep(.02)
        self.assertEqual(self.plugin.cards.image_batch['status'],'complete')
        self.assertEqual(sorted(downloaded),sorted(r['id'] for r in rows))
        self.assertEqual(self.plugin.cards.image_usage()['cached'],12)
        # The published batch carries the final counts and finished work.
        batch=(await self.plugin.status())['cards']['image_batch']
        self.assertEqual((batch['success'],batch['failed'],batch['missing'],batch['done']),(12,0,0,12))
        # Clearing art leaves both databases and all card names in place.
        await self.plugin.clear_card_images()
        self.assertEqual(list(self.plugin.cards.images.glob('*.png')),[])
        self.assertEqual((self.plugin.cards.directory/'cards-enUS.json').exists(),True)
        self.assertEqual(self.plugin.cards.info('CARD_1')['name'],'Card 1')
        # Clearing one database leaves the other file untouched.
        await self.plugin.clear_card_database('zhCN')
        self.assertFalse((self.plugin.cards.directory/'cards-zhCN.json').exists())
        self.assertTrue((self.plugin.cards.directory/'cards-enUS.json').exists())
        await self.plugin.clear_card_database('enUS')          # active database
        self.assertFalse((self.plugin.cards.directory/'cards-enUS.json').exists())
        self.assertEqual(self.plugin.cards.by_id,{})
        self.assertEqual((await self.plugin.status())['cards']['databases']['enUS']['exists'],False)
        with self.assertRaises(ValueError):await self.plugin.clear_card_database('deDE')
        with self.assertRaises(ValueError):await self.plugin.download_all_images()   # no database

    async def test_game_pointer_display_reaches_renderer_without_moving_overlay(self):
        for found,value,expected in ((True,':1',':1'),(True,':1.0',':1.0'),
                                     (True,'remote:1',''),(True,None,''),(False,':1','')):
            self.plugin.process=dict(found=found,environment=dict(DISPLAY=value))
            self.plugin._publish()
            state=json.loads((self.plugin.runtime/'state.json').read_text())
            self.assertEqual(state['game_display'],expected)
            self.assertEqual(state['display'],':0')

    async def test_full_card_resources_download_cancel_and_clear_are_independent(self):
        from engine.images import atomic_image
        from image_support import tile_png
        self.plugin.cards.install([dict(id='CARD_A',dbfId=1,name='A',cost=1)])
        self.plugin.full_cards.fetcher=lambda *args,**kwargs:tile_png(256,384)
        tile=self.plugin.cards.images/'CARD_A.png'
        atomic_image(tile,tile_png())
        await self.plugin.download_all_full_card_images()
        for _ in range(100):
            if self.plugin.full_cards.batch_view()['status']=='complete':break
            await asyncio.sleep(.01)
        self.assertEqual(self.plugin.full_cards.batch_view()['success'],1)
        self.plugin.full_cards.usage_at=0  # Disk statistics refresh at most every two seconds.
        resources=(await self.plugin.status())['full_card_resources']
        self.assertEqual(resources['cached'],1);self.assertGreater(resources['bytes'],0)
        await self.plugin.cancel_full_card_download()
        generation=self.plugin.full_card_generation
        await self.plugin.clear_full_card_images()
        self.assertEqual(self.plugin.full_card_generation,generation+1)
        self.assertEqual((await self.plugin.status())['full_card_resources']['bytes'],0)
        state=json.loads((self.plugin.runtime/'state.json').read_text())
        self.assertEqual(state['full_card_generation'],generation+1)
        self.assertTrue(tile.exists());self.assertIn('CARD_A',self.plugin.cards.by_id)

    async def test_preview_scale_is_independent_validated_and_persisted(self):
        self.assertEqual(self.plugin.settings['preview_scale'],1.0)
        original_scale=self.plugin.settings['scale'];original_width=self.plugin.settings['panel_width']
        for value in (0.4,2.1,float('nan'),float('inf'),'large'):
            with self.assertRaises((ValueError,TypeError)):await self.plugin.configure(dict(preview_scale=value))
        await self.plugin.configure(dict(preview_scale=1.5))
        state=json.loads((self.plugin.runtime/'state.json').read_text())
        stored=json.loads((self.plugin.settings_dir/'settings.json').read_text())
        self.assertEqual(state['preview_scale'],1.5);self.assertEqual(stored['preview_scale'],1.5)
        self.assertEqual(state['scale'],original_scale);self.assertEqual(state['panel_width'],original_width)
