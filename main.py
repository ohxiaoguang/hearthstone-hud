"""Decky backend. No network listeners or privileged game access."""
import asyncio
import contextlib
import json
import os
import platform
import struct
import time
from pathlib import Path
import decky
from engine.io import Tail, atomic_json
from engine.tracker import Tracker, DeckLog, LINE
from engine.cards import Cards
from engine.discovery import discover, gamescope_status, LogClock

ROOT = Path(__file__).resolve().parent
DEFAULTS = dict(game_dir='/home/deck/Games/battlegame/Hearthstone',
    proton_prefix='/home/deck/.local/share/Steam/steamapps/compatdata/3443960088/pfx',
    log_dir='', display=':0', x=40, y=80, scale=1.0, opacity=0.85,
    visible=True, own_deck=True, opponent_deck=True, opponent_hand=True, arena=False, right_x=1540, right_y=80, card_images=True, chinese_names=True)


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
        self.decks = DeckLog()
        self.parser = Tracker(self.decks)
        self.deck_tail = Tail()
        self.cards = Cards(self.runtime/'cache')
        self.media_task = None
        self.discovery = {}
        self.last_scan = float('-inf')
        self.gamescope = gamescope_status()
        self.active = False
        self.caught_up = False
        self.deck_clock = None
        self.power_clock = None
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
                low, high = {'x':(0,7680),'y':(0,4320),'scale':(.5,3),'opacity':(.1,1),'right_x':(0,7680),'right_y':(0,4320)}[key]
                if not low <= value <= high:
                    raise ValueError('数值超出范围')
                value = int(value) if expected is int else value
            elif type(value) is not expected:
                raise ValueError('配置类型不正确')
            checked[key] = value
        self.settings.update(checked)
        if any(k in checked for k in ('game_dir','log_dir')):
            self.last_scan = float('-inf')
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
            if self.media_task is None or self.media_task.done():
                self.media_task = asyncio.create_task(self.cards.worker())
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
                    parse_errors=self.parser.failures, gamescope_running=self.gamescope.startswith('检测到'),
                    gamescope_status=self.gamescope, logs=self.discovery, cards=self.cards.diagnostic(),
                    tracking=self.parser.view(self.cards) if self.active and self.caught_up else dict(status='waiting'),
                    visibility='v0.1.x 显示和触控已由用户实测；本版记牌仍待实机验收',
                    arena='尚未加载评分；不支持自动识别候选牌')

    def _publish(self):
        tracking = self.parser.view(self.cards) if self.active and self.caught_up else dict(status='waiting',turn=0,own=[],opponent=[],own_label='等待活动日志',opponent_hand=None,opponent_deck=None)
        if self.settings['card_images']:
            self.cards.request_images(r['id'] for key in ('own','opponent') for r in tracking[key])
        atomic_json(self.runtime / 'state.json', dict(updated=time.time(), **self.settings,
            schema=2, tracking=tracking))

    async def _loop(self):
        while True:
            try:
                if time.monotonic()-self.last_scan >= 3:
                    scan_key = (self.settings['game_dir'],self.settings['log_dir'])
                    result = await asyncio.to_thread(discover,*scan_key)
                    if scan_key != (self.settings['game_dir'],self.settings['log_dir']):
                        continue
                    self.discovery = result
                    self.last_scan = time.monotonic()
                    self.gamescope = gamescope_status()
                power = self.discovery.get('power')
                self.active = bool(power and power['active'])
                self.log_path = Path(power['path']) if power else None
                if self.active:
                    if self.tail.path is not None and self.log_path != self.tail.path:
                        self.decks = DeckLog()
                        self.parser.decks = self.decks
                    # Read matching Decks.log before Power; candidates bind by log timestamp.
                    deck = self.discovery.get('decks')
                    if deck:
                        deck_generation = self.deck_tail.generation
                        deck_lines = self.deck_tail.read(deck['path'])
                        if self.deck_tail.generation != deck_generation:
                            self.deck_clock = LogClock(deck['path'],deck['mtime'])
                            self.decks = DeckLog()
                            self.parser.decks = self.decks
                        for line in deck_lines:
                            m = LINE.match(line)
                            if m:
                                stamp = self.deck_clock.timestamp(m[1])
                                self.decks.feed(stamp,m[2])
                    generation = self.tail.generation
                    lines = self.tail.read(self.log_path)
                    if self.tail.generation != generation:
                        self.parser = Tracker(self.decks)
                        self.power_clock = LogClock(self.log_path,power['mtime'])
                    for line in lines:
                        m = LINE.match(line)
                        if m:
                            self.power_clock.timestamp(m[1])
                        self.parser.feed_line(line,self.power_clock.day)
                    self.caught_up = self.tail.offset >= self.log_path.stat().st_size
                    self.discovery['offset'] = self.tail.offset
                    self.discovery['generation'] = self.tail.generation
                    self.discovery['accepted'] = self.parser.accepted
                    self.discovery['parse_errors'] = self.parser.failures
                    self.discovery['parse_state'] = '对局已结束' if self.parser.game and self.parser.game.complete else '已识别对局' if self.parser.game else '等待 CREATE_GAME；可能需下一局'
                if self.proc and self.proc.returncode is not None:
                    self.error = '渲染器已退出，代码 %s' % self.proc.returncode
                self._publish()
            except Exception as exc:
                self.error = str(exc)
                self.discovery['read_state'] = '读取/解析失败：'+str(exc)
            await asyncio.sleep(.25)

    async def _unload(self):
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task
        await self.stop_hud()
        if self.media_task:
            self.media_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.media_task

    async def _uninstall(self):
        # No game configuration is changed automatically.
        pass
