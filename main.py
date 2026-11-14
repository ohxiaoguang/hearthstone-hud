"""Decky backend. No network listeners or privileged game access."""
import asyncio
from collections import deque
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
from engine.proton import discover_process
from engine.diagnostics import format_diagnostics
from engine.logconfig import ensure_power, ensure_decks, inspect_config, diagnostic_state

ROOT = Path(__file__).resolve().parent
VERSION = json.loads((ROOT/'package.json').read_text())['version']
DEFAULTS = dict(game_dir='/home/deck/Games/battlegame/Hearthstone',
    proton_prefix='',
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
        self.config_lock = asyncio.Lock()
        self.error = ''
        self.recent_errors = deque(maxlen=10)
        self.decks = DeckLog()
        self.parser = Tracker(self.decks)
        self.deck_tail = Tail()
        self.cards = Cards(self.runtime/'cache')
        self.media_task = None
        self.discovery = {}
        self.process = {}
        self.power_config = {}
        self.decks_config = {}
        self.decks_receipt = {}
        try:
            self.decks_receipt = json.loads((self.settings_dir/'decks-config-receipt.json').read_text())
        except (OSError,ValueError):
            pass
        self.restart_receipt = {}
        try:
            self.restart_receipt = json.loads((self.settings_dir/'power-config-receipt.json').read_text())
        except (OSError,ValueError):
            pass
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

    async def enable_decks_logging(self):
        async with self.config_lock:
            process = await asyncio.to_thread(discover_process)
            result = await asyncio.to_thread(ensure_decks,process)
            if not result.get('success'):
                raise RuntimeError(result.get('state','Decks 配置失败'))
            if result.get('changed'):
                self.decks_receipt = dict(instance=process.get('instance'),path=result['path'],backup=result.get('backup',''))
                atomic_json(self.settings_dir/'decks-config-receipt.json',self.decks_receipt)
            self.decks_config = result
        self.last_scan = float('-inf')
        return await self.status()

    async def import_card_database(self, path: str):
        record = await asyncio.to_thread(self.cards.import_file,path)
        self.cards.apply(record)
        self._publish()
        return await self.status()

    async def retry_card_database(self):
        record = await asyncio.to_thread(self.cards.refresh)
        self.cards.apply(record)
        self._publish()
        return await self.status()

    def _ensure_media_worker(self):
        if self.media_task is None or self.media_task.done():
            self.media_task = asyncio.create_task(self.cards.worker())

    async def download_missing_images(self):
        tracking = self.parser.view(self.cards)
        ids={r['id'] for key in ('own','opponent') for r in tracking.get(key,[])}
        ids.update(self.cards.id_for_dbf(dbf) for dbf in self.parser.initial_dbf)
        game=self.parser.game
        if game:
            for ent in game.entities.values():
                if ent.card_id and (ent.controller==game.friendly_id or (ent.id,ent.card_id) in self.parser.public):
                    ids.add(ent.card_id)
        self.cards.begin_image_download(ids)
        self._ensure_media_worker()
        return await self.status()

    async def import_card_images(self,path: str):
        await asyncio.to_thread(self.cards.import_images,path)
        self._publish()
        return await self.status()

    async def diagnostic_text(self):
        data=await self.status()
        tail=''
        try:
            with (self.runtime/'renderer.log').open('rb') as f:
                f.seek(0,2);size=f.tell();f.seek(max(0,size-3000))
                tail=f.read(3000).decode('utf-8',errors='replace')
                if size>3000:tail='[TRUNCATED: renderer tail only]\n'+tail
        except OSError:
            pass
        errors=list(self.recent_errors)+list(self.parser.recent_errors)
        return format_diagnostics(data,VERSION,errors,tail)

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
            self._ensure_media_worker()
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
        game = self.parser.game
        tracking = self.parser.view(self.cards) if self.active and self.caught_up else dict(status='waiting')
        stage = '对局已识别' if game and not game.complete else '对局已结束' if game else '尚未识别对局'
        identities = '双方身份已识别' if game and game.friendly and game.opponent else '双方身份尚未完整识别'
        deck_stage = '已读取完整初始牌组' if game and self.parser.initial_dbf else '完整卡组未知；只显示 Power 确认的信息'
        diag = {}
        try:
            diag = json.loads((self.runtime / 'diagnostic.json').read_text())
        except (OSError, ValueError):
            pass
        return dict(version=VERSION,settings=self.settings, running=bool(self.proc and self.proc.returncode is None),
                    error=self.error, diagnostic=diag, log_path=str(self.log_path or ''),
                    parse_errors=self.parser.failures, gamescope_running=self.gamescope.startswith('检测到'),
                    gamescope_status=self.gamescope, logs=self.discovery, cards=self.cards.diagnostic(),
                    process=self.process, power_config=self.power_config, decks_config=self.decks_config,
                    match_status=stage, identity_status=identities, deck_status=deck_stage,
                    decks_log_status='已找到同会话 Decks.log' if self.discovery.get('decks') else '未找到同会话 Decks.log；启用后重启并选定卡组排队',
                    log_status=diagnostic_state(self.process,self.power_config,self.discovery),
                    tracking=tracking,
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
                    process = await asyncio.to_thread(discover_process)
                    async with self.config_lock:
                        config = await asyncio.to_thread(ensure_power,process)
                        decks_config = await asyncio.to_thread(inspect_config,process.get('user_dir'),'Decks')
                        if decks_config.get('enabled') and self.decks_receipt.get('path')==decks_config.get('path'):
                            decks_config['restart_required'] = self.decks_receipt.get('instance')==process.get('instance')
                            decks_config['backup'] = self.decks_receipt.get('backup','')
                    if config.get('changed') and config.get('success'):
                        self.restart_receipt = dict(instance=process.get('instance'),path=config['path'],backup=config.get('backup',''))
                        atomic_json(self.settings_dir/'power-config-receipt.json',self.restart_receipt)
                    if config.get('enabled') and self.restart_receipt.get('path')==config.get('path'):
                        config['restart_required'] = self.restart_receipt.get('instance')==process.get('instance')
                        config['backup'] = self.restart_receipt.get('backup','')
                    result = await asyncio.to_thread(discover,process.get('game_dir') or scan_key[0],scan_key[1])
                    if scan_key != (self.settings['game_dir'],self.settings['log_dir']):
                        continue
                    self.process = process
                    self.power_config = config
                    self.decks_config = decks_config
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
                        self.deck_tail = Tail()
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
                    self.discovery['deck_candidates'] = len(self.decks.candidates)
                    self.discovery['deck_parse_errors'] = self.decks.errors
                    self.discovery['read_state'] = '日志已读取'
                    self.discovery['parse_state'] = '对局已结束' if self.parser.game and self.parser.game.complete else '已识别对局' if self.parser.game else '等待 CREATE_GAME；可能需下一局'
                if self.proc and self.proc.returncode is not None:
                    self.error = '渲染器已退出，代码 %s' % self.proc.returncode
                self._publish()
            except Exception as exc:
                self.error = str(exc)
                self.recent_errors.append(type(exc).__name__+': '+str(exc)[:250])
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
        # Preserve user configuration and backups on uninstall; never overwrite later edits.
        pass
