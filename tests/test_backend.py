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
