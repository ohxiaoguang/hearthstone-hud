"""Decky backend. No network listeners or privileged game access."""
import asyncio
import contextlib
import json
import os
import platform
import struct
import time
from datetime import datetime
from pathlib import Path
import decky
from engine.io import Tail, atomic_json
from engine.power import PowerParser

ROOT = Path(__file__).resolve().parent
DEFAULTS = dict(game_dir='/home/deck/Games/battlegame/Hearthstone',
    proton_prefix='/home/deck/.local/share/Steam/steamapps/compatdata/3443960088/pfx',
    log_dir='', display=':0', x=40, y=80, scale=1.0, opacity=0.85,
    visible=True, own_deck=True, opponent_deck=True, opponent_hand=True, arena=False)


class Plugin:
    async def _main(self):
        self.settings_dir = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.runtime = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.runtime.chmod(0o700)
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.settings = dict(DEFAULTS)
        try:
            self.settings.update(json.loads((self.settings_dir / 'settings.json').read_text()))
        except (OSError, ValueError):
            pass
        self.proc = None
        self.lock = asyncio.Lock()
        self.error = ''
        self.parser = PowerParser()
        self.tail = Tail()
        self.log_path = None
        self.parse_errors = 0
        self.task = asyncio.create_task(self._loop())

    async def configure(self, values: dict):
        checked = {}
        for key, value in values.items():
            if key not in DEFAULTS:
                raise ValueError('未知配置项')
            expected = type(DEFAULTS[key])
            if expected in (int, float):
                value = float(value)
                low, high = {'x':(0,7680),'y':(0,4320),'scale':(.5,3),'opacity':(.1,1)}[key]
                if not low <= value <= high:
                    raise ValueError('数值超出范围')
                value = int(value) if expected is int else value
            elif type(value) is not expected:
                raise ValueError('配置类型不正确')
            checked[key] = value
        self.settings.update(checked)
        atomic_json(self.settings_dir / 'settings.json', self.settings)
        return await self.status()

    async def start_hud(self):
        async with self.lock:
            if self.proc and self.proc.returncode is None:
                return await self.status()
            binary = ROOT / 'bin/hearthstone-hud-renderer'
            header = binary.read_bytes()[:20] if binary.exists() else b''
            if platform.system() != 'Linux' or header[:5] != b'\x7fELF\x02' or len(header)<20 or struct.unpack('<H',header[18:20])[0] != 62:
                raise RuntimeError('需要 Linux x86_64 ELF 渲染器，请安装 Actions 完整构建 ZIP')
            for name in ('diagnostic.json',):
                (self.runtime / name).unlink(missing_ok=True)
            self.error = ''
            self.settings['visible'] = True
            self._publish()
            env = dict(os.environ, DISPLAY=self.settings['display'])
            with (self.runtime / 'renderer.log').open('ab') as log:
                self.proc = await asyncio.create_subprocess_exec(str(binary), str(self.runtime / 'state.json'), str(ROOT / 'assets'), str(self.runtime / 'diagnostic.json'), env=env, stdout=log, stderr=log)
            await asyncio.sleep(.3)
            if self.proc.returncode is not None:
                self.error = '渲染器启动失败，请查看 renderer.log'
            return await self.status()

    async def stop_hud(self):
        async with self.lock:
            if self.proc and self.proc.returncode is None:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), 3)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            self.proc = None
        return await self.status()

    async def status(self):
        diag = {}
        try:
            diag = json.loads((self.runtime / 'diagnostic.json').read_text())
        except (OSError, ValueError):
            pass
        return dict(settings=self.settings, running=bool(self.proc and self.proc.returncode is None),
                    error=self.error, diagnostic=diag, log_path=str(self.log_path or ''),
                    parse_errors=self.parse_errors, gamescope_running=self._gamescope_running(),
                    visibility='合成显示与触控穿透需要实机确认',
                    arena='尚未加载评分；不支持自动识别候选牌')

    def _gamescope_running(self):
        # Process names only; never access game memory or command-line secrets.
        for item in Path('/proc').glob('[0-9]*/comm'):
            try:
                if item.read_text().strip() == 'gamescope':
                    return True
            except OSError:
                continue
        return False

    def _publish(self):
        game = self.parser.game
        lines = ['OVERLAID TEST', '中文测试：炉石记牌器']
        if game and not game.complete:
            lines.append('对局进行中 · 回合 %d' % game.turn)
            for player, label, enabled in [(game.friendly,'己方',self.settings['own_deck']), (game.opponent,'对手',self.settings['opponent_deck'])]:
                if player and enabled:
                    lines.append('%s牌库：%d（仅日志可见身份）' % (label,game.count_zone(player,'DECK')))
            if game.opponent and self.settings['opponent_hand']:
                lines.append('对手手牌：%d' % game.count_zone(game.opponent,'HAND'))
        else:
            lines.append('等待新对局日志')
        atomic_json(self.runtime / 'state.json', dict(updated=time.time(), **self.settings,
            widgets=[dict(type='text',content='\n'.join(lines)),dict(type='image',content='test.png')]))

    async def _loop(self):
        while True:
            try:
                base = Path(self.settings['log_dir'] or (Path(self.settings['game_dir'])/'Logs'))
                candidates = list(base.glob('*/Power.log')) + list(base.glob('Power.log'))
                self.log_path = max(candidates, key=lambda p:p.stat().st_mtime_ns) if candidates else None
                if self.log_path:
                    generation = self.tail.generation
                    lines = self.tail.read(self.log_path)
                    if self.tail.generation != generation:
                        self.parser = PowerParser()
                    for line in lines:
                        try:
                            marker = line.find('GameState.')
                            if marker >= 0:
                                self.parser.feed(datetime.now(), line[marker:])
                        except (ValueError, KeyError, TypeError, IndexError):
                            self.parse_errors += 1
                if self.proc and self.proc.returncode is not None:
                    self.error = '渲染器已退出，代码 %s' % self.proc.returncode
                self._publish()
            except Exception as exc:
                self.error = str(exc)
            await asyncio.sleep(.25)

    async def _unload(self):
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task
        await self.stop_hud()

    async def _uninstall(self):
        # No game configuration is changed automatically.
        pass
