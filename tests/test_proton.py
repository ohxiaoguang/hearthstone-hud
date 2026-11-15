"""Small filesystem fixtures for process discovery and safe Power-only edits."""
from pathlib import Path
import tempfile
import unittest
from engine.proton import discover_process, linux_game_dir
from engine.logconfig import ensure_power, inspect_config, diagnostic_state

class ProtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.proc=self.root/'proc';self.proc.mkdir()
        self.prefix=self.root/'compatdata/random-id/pfx'
        self.home=self.prefix/'drive_c/users/custom-user/AppData/Local/Blizzard/Hearthstone'
        self.home.mkdir(parents=True)

    def process(self,pid,comm,args,env):
        p=self.proc/str(pid);p.mkdir()
        (p/'comm').write_text(comm)
        (p/'cmdline').write_bytes(b'\0'.join(a.encode() for a in args)+b'\0')
        (p/'environ').write_bytes(b'\0'.join((k+'='+v).encode() for k,v in env.items())+b'\0')
        return p

    def test_live_environment_precedence_and_z_drive(self):
        self.process(41,'Hearthstone.exe',['Hearthstone.exe',r'Z:\home\deck\Games\battlegame\Hearthstone\Hearthstone.exe'],dict(WINEPREFIX=str(self.prefix)+'/',STEAM_COMPAT_DATA_PATH='/wrong',SteamAppId='random-id'))
        self.process(42,'python3',['python3','hud.py','Hearthstone.exe'],dict(WINEPREFIX='/wrong'))
        p=discover_process(self.proc)
        self.assertEqual(p['pid'],41);self.assertEqual(p['prefix'],str(self.prefix));self.assertEqual(p['user_dir'],str(self.home))
        self.assertEqual(p['game_dir'],'/home/deck/Games/battlegame/Hearthstone')
        self.assertEqual(p['environment']['SteamAppId'],'random-id')

    def test_compat_data_fallback_and_missing_process(self):
        self.assertFalse(discover_process(self.proc)['found'])
        self.process(41,'wine64-preloader',[r'Z:\game\Hearthstone.exe'],dict(WINEPREFIX='/missing',STEAM_COMPAT_DATA_PATH=str(self.prefix.parent)+'/'))
        self.assertEqual(discover_process(self.proc)['prefix'],str(self.prefix))
        self.assertEqual(linux_game_dir(['Hearthstone.exe']),'')

    def test_missing_prefix_and_multiple_profiles_do_not_guess(self):
        p=self.process(41,'Hearthstone.exe',['Hearthstone.exe'],{})
        self.assertEqual(discover_process(self.proc)['prefix'],'')
        (p/'environ').write_bytes(('WINEPREFIX='+str(self.prefix)).encode())
        (self.prefix/'drive_c/users/another/AppData/Local/Blizzard/Hearthstone').mkdir(parents=True)
        result=discover_process(self.proc)
        self.assertEqual(result['user_dir'],'');self.assertFalse(ensure_power(result)['success'])

    def test_create_preserve_backup_idempotent(self):
        p=dict(found=True,prefix=str(self.prefix),user_dir=str(self.home))
        first=ensure_power(p)
        self.assertTrue(first['success']);self.assertTrue(first['restart_required'])
        config=self.home/'log.config';self.assertEqual(config.stat().st_mode&0o777,0o600)
        self.assertFalse(ensure_power(p)['changed'])
        original=b'; user comment\n[Other]\nKeep=unchanged\n\n[Power]\nLogLevel=0\nCustom=preserve\n'
        config.write_bytes(original)
        result=ensure_power(p)
        self.assertEqual(Path(result['backup']).read_bytes(),original)
        self.assertIn('[Other]\nKeep=unchanged',config.read_text())
        self.assertIn('Custom=preserve',config.read_text())
        self.assertEqual(config.read_text().count('[Power]'),1)
        self.assertTrue(inspect_config(self.home)['enabled'])

    def test_no_process_no_write_and_distinct_diagnostics(self):
        self.assertFalse(ensure_power(dict(found=False))['success'])
        self.assertFalse((self.home/'log.config').exists())
        self.assertIn('Game process',diagnostic_state({}, {}, {}))   # English is the default
        from engine import i18n
        try:
            i18n.set_ui_language('zh-CN')
            self.assertIn('游戏进程',diagnostic_state({}, {}, {}))
        finally:i18n.set_ui_language('en')
        self.assertIn('prefix',diagnostic_state(dict(found=True), {}, {}))
        p=dict(found=True,prefix=str(self.prefix))
        self.assertIn('does not exist',diagnostic_state(p,dict(exists=False),{}))
        self.assertIn('not enabled',diagnostic_state(p,dict(exists=True,enabled=False),{}))
        # The same three states in Chinese, so both dictionaries cover them.
        try:
            i18n.set_ui_language('zh-CN')
            self.assertIn('前缀',diagnostic_state(dict(found=True), {}, {}))
            self.assertIn('不存在',diagnostic_state(p,dict(exists=False),{}))
            self.assertIn('未启用',diagnostic_state(p,dict(exists=True,enabled=False),{}))
        finally:i18n.set_ui_language('en')
        config=dict(exists=True,enabled=True)
        self.assertIn('has not been created',diagnostic_state(p,config,{}))
        self.assertIn('not updating yet',diagnostic_state(p,config,dict(power=dict(active=False))))
        self.assertIn('read normally',diagnostic_state(p,config,dict(power=dict(active=True),offset=1)))
        try:
            i18n.set_ui_language('zh-CN')
            self.assertIn('尚未生成',diagnostic_state(p,config,{}))
            self.assertIn('正常读取',diagnostic_state(p,config,dict(power=dict(active=True),offset=1)))
        finally:i18n.set_ui_language('en')
