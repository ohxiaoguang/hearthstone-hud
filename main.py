"""Decky backend. No network listeners or privileged game access."""
import asyncio
import base64
from collections import deque
import contextlib
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
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
from engine.full_cards import FullCards
from engine.arena import Arena
from engine.memory_watch import MemoryWatch
from engine.arena_class_ratings import ClassRatings
from engine.arena_memory_view import ArenaPreview
from engine.discovery import discover, gamescope_status, LogClock
from engine.proton import discover_process, local_x11_display
from engine import i18n
from engine.diagnostics import format_diagnostics
from engine.logconfig import ensure_power, ensure_decks, ensure_arena, inspect_config, diagnostic_state

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'https://github.com/ohxiaoguang/hearthstone-hud'
VERSION = json.loads((ROOT/'package.json').read_text())['version']
DEFAULTS = dict(enabled=True,game_dir='/home/deck/Games/battlegame/Hearthstone',
    proton_prefix='',
    log_dir='', display=':0', x=40, y=80, scale=1.0, opacity=0.85,
    visible=True, own_deck=True, opponent_deck=True, opponent_hand=True, arena=True, right_x=1540, right_y=80, card_images=True, show_card_names=True, image_tls_verify=False, database_tls_verify=False, own_played=True, opponent_played=True, show_summary=True, panel_width=320, font_size=22, hide_exhausted=False, arena_memory=False, auto_logs=False,
    ui_language=i18n.DEFAULT_UI)


def active_operation(method):
    @wraps(method)
    async def guarded(self,*args,**kwargs):
        async with self.lifecycle_lock:
            if not self.settings['enabled'] or self.io_pool is None:raise RuntimeError(i18n.t('plugin.disabled_error'))
            return await method(self,*args,**kwargs)
    return guarded

class Plugin:
    async def _main(self):
        self.settings_dir = Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.runtime = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.runtime.chmod(0o700)
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.settings = dict(DEFAULTS)
        try:
            stored = json.loads((self.settings_dir / 'settings.json').read_text())
        except (OSError, ValueError):
            stored = {}
        # `chinese_names` used to mean "show card names instead of card IDs"; the
        # name is a leftover from the single-language build.
        if 'chinese_names' in stored and 'show_card_names' not in stored:
            stored['show_card_names'] = bool(stored.pop('chinese_names'))
        stored.pop('chinese_names', None)
        self.settings.update(stored)
        # The interface language drives every string this process produces, so it
        # is applied before the card database or any view is created.
        i18n.set_ui_language(self.settings.get('ui_language'))
        self.settings['ui_language'] = i18n.ui_language()
        # The card database now follows the interface language; the retired
        # setting is dropped instead of being silently honoured.
        self.settings.pop('card_language',None)
        # Only an explicit boolean opt-in can enable process memory access.
        if type(self.settings.get('arena_memory')) is not bool:self.settings['arena_memory']=False
        # Migrate the former pair to one switch without silently opting into memory.
        self.settings['arena']=self.settings['arena_memory']=bool(self.settings['arena'] and self.settings['arena_memory'])
        # This testing build uses the user's requested download mode; no UI switch.
        self.settings.update(image_tls_verify=False,database_tls_verify=False)
        if type(self.settings.get('enabled')) is not bool:self.settings['enabled']=True
        self.lifecycle_lock=asyncio.Lock()
        self.io_pool=None;self.task=None;self.loop_stop=asyncio.Event()
        self.lifecycle_state='disabled'
        self.proc = None
        self.lock = asyncio.Lock()
        self.config_lock = asyncio.Lock()
        self.memory_lock = asyncio.Lock()
        self.media_lock = asyncio.Lock()
        self.media_stop = asyncio.Event()
        self.cache_resetting = False
        self.full_cache_resetting = False
        self.full_card_generation = 0
        self.error = ''
        self.recent_errors = deque(maxlen=10)
        self.decks = DeckLog()
        self.parser = Tracker(self.decks)
        self.deck_tail = Tail()
        self.cards = Cards(self.runtime/'cache', language=self.card_locale())
        self.cards.image_verify_tls = self.settings['image_tls_verify']
        self.cards.database_verify_tls = self.settings['database_tls_verify']
        self.media_task = None
        try:
            manual=json.loads((self.settings_dir/'arena-manual.json').read_text())
        except (OSError,ValueError):manual=[]
        self.arena = Arena(self.cards,manual=manual if isinstance(manual,list) else [])
        self.parser.arena = self.arena
        self.memory_watch = MemoryWatch()
        self.arena_preview = ArenaPreview(ClassRatings())
        self.arena_tail = Tail();self.arena_clock = None;self.side_session = None
        self.arena_caught_up = False;self.arena_config = {};self.arena_receipt = {}
        try:
            self.arena_receipt=json.loads((self.settings_dir/'arena-config-receipt.json').read_text())
        except (OSError,ValueError):pass
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
        self.gamescope_running = False
        self.gamescope = ''
        self.active = False
        self.caught_up = False
        self.deck_clock = None
        self.power_clock = None
        self.tail = Tail()
        self.log_path = None
        self.parse_errors = 0
        if self.settings['enabled']:await self._start_services()

    def card_locale(self):
        """Card database locale, derived from the interface language."""
        return i18n.card_language('auto',self.settings.get('ui_language'))

    async def _io(self,method,*args):
        if self.io_pool is None:raise RuntimeError(i18n.t('plugin.stopped_error'))
        return await asyncio.get_running_loop().run_in_executor(self.io_pool,method,*args)

    async def _start_services(self):
        if self.io_pool is not None:return
        self.lifecycle_state='starting'
        self.full_cards=FullCards(self.runtime)
        self.io_pool=ThreadPoolExecutor(max_workers=3,thread_name_prefix='hud-io-'+str(id(self)))
        self.full_cards.prepare()
        self.loop_stop=asyncio.Event();self.last_scan=float('-inf')
        self.task=asyncio.create_task(self._loop())
        if self.settings['arena_memory']:self.memory_watch.start()
        if not self.cards.by_id:self.cards._phase('prepare')
        self._ensure_media_worker()
        if self.settings['visible'] and platform.system()=='Linux':
            try:await self._start_renderer()
            except Exception as exc:self.error=str(exc)
        self.lifecycle_state='running'

    async def _stop_services(self):
        # No cancellation of executor futures: drain requests before disposing workers.
        self.lifecycle_state='stopping'
        self.loop_stop.set();self.media_stop.set();self.memory_watch.request_stop()
        try:await self._stop_renderer(preserve=True)
        except Exception as exc:self.error=i18n.t('hud.stop_error',error=str(exc))
        if self.task:
            with contextlib.suppress(Exception,asyncio.CancelledError):await self.task
            self.task=None
        if self.media_task:
            with contextlib.suppress(Exception,asyncio.CancelledError):await self.media_task
            self.media_task=None
        if self.io_pool is not None:
            await self._io(self.memory_watch.join)
            if getattr(self,'full_cards',None):await self._io(self.full_cards.close)
            pool,self.io_pool=self.io_pool,None
            pool.shutdown(wait=True)
        else:self.memory_watch.join()
        if self.proc and self.proc.returncode is None:
            self.lifecycle_state='stop_failed'
            raise RuntimeError(i18n.t('hud.stop_failed'))
        self.lifecycle_state='disabled'
        try:self._publish()
        except OSError as exc:self.error=i18n.t('hud.publish_failed',error=str(exc))

    async def configure(self,values:dict):
        async with self.lifecycle_lock:
            return await self._configure(values)

    async def _configure(self, values: dict):
        checked = {}
        for key, value in values.items():
            if key not in DEFAULTS:
                raise ValueError(i18n.t('config.unknown_key'))
            expected = type(DEFAULTS[key])
            if key=='ui_language':
                if value not in dict(i18n.UI_LANGUAGES):
                    raise ValueError('unsupported interface language')
            elif expected in (int, float):
                value = float(value)
                low, high = {'x':(0,7680),'y':(0,4320),'scale':(.5,3),'opacity':(.1,1),'right_x':(0,7680),'right_y':(0,4320),'panel_width':(180,640),'font_size':(14,30)}[key]
                if not low <= value <= high:
                    raise ValueError(i18n.t('config.out_of_range'))
                value = int(value) if expected is int else value
            elif type(value) is not expected:
                raise ValueError(i18n.t('config.bad_type'))
            checked[key] = value
        was_enabled=self.settings['enabled']
        # A failed settings write must not leave the master flag changed while
        # its old services are still running.
        atomic_json(self.settings_dir / 'settings.json', dict(self.settings,**checked))
        async with self.memory_lock:
            if 'arena_memory' in checked:
                if checked['arena_memory']!=self.settings['arena_memory']:self.arena.clear_offer()
                if checked['arena_memory'] and self.settings['enabled'] and checked.get('enabled',True):self.memory_watch.start()
                else:
                    self.memory_watch.request_stop()
                    if self.io_pool is not None:await self._io(self.memory_watch.join)
                    else:self.memory_watch.join()
            self.settings.update(checked)
        if 'ui_language' in checked:
            # Apply the interface language before any view or status is built; the
            # card database follows it, reusing a cache when one exists.
            i18n.set_ui_language(checked['ui_language'])
            target=self.card_locale()
            if target!=self.cards.language:self.cards.set_language(target)
            if self.settings['enabled']:self._ensure_media_worker()
        if 'database_tls_verify' in checked:
            self.cards.database_verify_tls = checked['database_tls_verify']
        if 'image_tls_verify' in checked:
            self.cards.image_verify_tls = checked['image_tls_verify']
        if any(k in checked for k in ('game_dir','log_dir')):
            self.arena_caught_up=False
            self.last_scan = float('-inf')
        if was_enabled and not self.settings['enabled']:await self._stop_services()
        elif not was_enabled and self.settings['enabled']:await self._start_services()
        self._publish()
        return await self.status()

    @active_operation
    async def enable_decks_logging(self):
        async with self.config_lock:
            process = await self._io(discover_process)
            result = await self._io(ensure_decks,process)
            if not result.get('success'):
                raise RuntimeError(result.get('state') or i18n.t('log.decks_failed'))
            if result.get('changed'):
                self.decks_receipt = dict(instance=process.get('instance'),path=result['path'],backup=result.get('backup',''))
                atomic_json(self.settings_dir/'decks-config-receipt.json',self.decks_receipt)
            self.decks_config = result
        self.last_scan = float('-inf')
        return await self.status()

    async def _sync_tracking_logs(self, process):
        # Caller holds config_lock. Only the live discovered prefix is eligible.
        for name,ensure in (('decks',ensure_decks),('arena',ensure_arena)):
            result=await self._io(ensure,process)
            receipt=getattr(self,name+'_receipt')
            if result.get('success') and result.get('changed'):
                receipt=dict(instance=process.get('instance'),path=result['path'],backup=result.get('backup',''))
                setattr(self,name+'_receipt',receipt)
                atomic_json(self.settings_dir/(name+'-config-receipt.json'),receipt)
            if result.get('enabled') and receipt.get('path')==result.get('path'):
                result['restart_required']=receipt.get('instance')==process.get('instance')
            setattr(self,name+'_config',result)

    async def _activate_tracking_logs(self):
        self.settings['auto_logs']=True
        atomic_json(self.settings_dir/'settings.json',self.settings)
        process=await self._io(discover_process)
        async with self.config_lock:
            await self._sync_tracking_logs(process)
        self.last_scan=float('-inf')

    @active_operation
    async def enable_arena_logging(self):
        async with self.config_lock:
            process=await self._io(discover_process)
            result=await self._io(ensure_arena,process)
            if not result.get('success'):raise RuntimeError(result.get('state') or i18n.t('log.arena_failed'))
            if result.get('changed'):
                self.arena_receipt=dict(instance=process.get('instance'),path=result['path'],backup=result.get('backup',''))
                atomic_json(self.settings_dir/'arena-config-receipt.json',self.arena_receipt)
            self.arena_config=result
        self.last_scan=float('-inf')
        return await self.status()

    def _arena_view(self):
        """Arena panel state. Selected cards come from the memory DraftDeck only."""
        state,diagnostic=self.memory_watch.snapshot()
        diagnostic['candidate_count']=len(state.choices) if state else 0
        diagnostic['stage']=state.slot if state else ''
        diagnostic['found']=diagnostic.get('pid') is not None and diagnostic.get('code')!='not_running'
        return self.arena_preview.view(self.cards,self.arena.ratings,state,diagnostic)

    def _arena_ui(self):
        view=self._arena_view()
        # QAM cannot read a native cache path. Only the three validated tile PNGs
        # are exposed as data URIs; IPC to the renderer keeps native paths only.
        for row in view['candidates']:
            row['image_data']=''
            path=self.cards.tiles.path(row['id'])
            try:
                if path and path.stat().st_size<=128*1024:
                    row['image_data']='data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()
            except OSError:pass
        return view

    @active_operation
    async def arena_search(self, query: str):
        return self.arena.search(query)

    @active_operation
    async def arena_set_offer(self, deck_id: str, phase: str, ordinal: int, ids: list):
        self.arena.set_offer(deck_id,phase,ordinal,ids)
        self.cards.request_images(ids);self._ensure_media_worker();self._publish()
        return self._arena_ui()

    @active_operation
    async def arena_clear_offer(self):
        self.arena.clear_offer();self._publish();return self._arena_ui()

    @active_operation
    async def arena_manual_pick(self, deck_id: str, phase: str, ordinal: int, cid: str):
        if not self.arena_caught_up:raise ValueError(i18n.t('arena.manual_wait'))
        self.arena.manual_pick(deck_id,phase,ordinal,cid)
        atomic_json(self.settings_dir/'arena-manual.json',self.arena.export_manual())
        self._publish();return self._arena_ui()

    @active_operation
    async def retry_card_database(self):
        # Same single worker handles first use, retries and images.
        if self.cards.download_phase!='running':
            self.cards.auto_download=True     # An explicit retry always downloads.
            self.cards.attempted=0
            self.cards.updated=0
            self.cards._phase('prepare')
        self._ensure_media_worker()
        self._publish()
        return await self.status()

    def _ensure_media_worker(self):
        if self.settings['enabled'] and self.io_pool is not None and not self.cache_resetting and (self.media_task is None or self.media_task.done()):
            self.media_stop = asyncio.Event()
            self.media_task = asyncio.create_task(self.cards.worker(self.media_stop,self._io))

    @active_operation
    async def clear_card_cache(self):
        async with self.media_lock:
            self.cache_resetting=True
            try:
                self.media_stop.set()
                if self.media_task:
                    await self.media_task
                await self._io(self.cards.clear_cache)
            finally:
                self.cache_resetting=False
                self._ensure_media_worker()
            self._publish()
        return await self.status()

    @active_operation
    async def download_missing_images(self):
        tracking = self.parser.view(self.cards)
        ids={r['id'] for key in ('own','own_added','own_played','opponent_seen','opponent_played') for r in tracking.get(key,[])}
        ids.update(self.cards.id_for_dbf(dbf) for dbf in self.parser.initial_dbf)
        game=self.parser.game
        if game:
            for ent in game.entities.values():
                if ent.card_id and (ent.controller==game.friendly_id or (ent.id,ent.card_id) in self.parser.public):
                    ids.add(ent.card_id)
        arena=self._arena_view()
        ids.update(row['id'] for key in ('candidates','picks') for row in arena[key])
        self.cards.begin_image_download(ids)
        self._ensure_media_worker()
        return await self.status()

    @active_operation
    async def download_all_images(self):
        """Fetch art for every Card ID in the loaded database (resumable)."""
        ids=self.cards.all_card_ids()
        if not ids:raise ValueError(i18n.t('cards.no_database'))
        self.cards.begin_image_download(ids)
        self._ensure_media_worker()
        self._publish()
        return await self.status()

    @active_operation
    async def cancel_image_download(self):
        """Stop the running batch; downloaded art is kept, on-demand requests continue."""
        await self._io(self.cards.cancel_image_download)
        self._publish()
        return await self.status()

    @active_operation
    async def clear_card_images(self):
        """Delete downloaded art after stopping the worker that writes it."""
        async with self.media_lock:
            self.cache_resetting=True
            try:
                self.media_stop.set()
                if self.media_task:await self.media_task
                await self._io(self.cards.clear_images)
            finally:
                self.cache_resetting=False
                self._ensure_media_worker()
            self._publish()
        return await self.status()

    @active_operation
    async def download_all_full_card_images(self):
        ids=self.cards.all_card_ids()
        if not ids:raise ValueError(i18n.t('cards.no_database'))
        await self._io(self.full_cards.begin_download,ids,self.card_locale(),self.settings['image_tls_verify'])
        return await self.status()

    @active_operation
    async def cancel_full_card_download(self):
        self.full_cards.cancel_download()
        return await self.status()

    @active_operation
    async def clear_full_card_images(self):
        self.full_cache_resetting=True
        try:
            await self._io(self.full_cards.close)
            await self._io(self.full_cards.clear)
        finally:
            self.full_cards=FullCards(self.runtime)
            self.full_card_generation+=1
            self.full_cache_resetting=False
        self._publish()
        return await self.status()

    @active_operation
    async def clear_card_database(self,locale: str):
        """Delete one language's JSON file; the other language and art stay."""
        if locale not in i18n.MANAGED_CARD_LANGUAGES:
            raise ValueError(i18n.t('cards.unmanaged_language'))
        await self._io(self.cards.clear_language,locale)
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

    @active_operation
    async def start_hud(self):
        return await self._start_renderer()

    async def _start_renderer(self):
        async with self.lock:
            if self.proc and self.proc.returncode is None:
                self.settings['visible'] = True
                await self._activate_tracking_logs()
                atomic_json(self.settings_dir / 'settings.json', self.settings)
                self._publish()
                return await self.status()
            binary = ROOT / 'bin/hearthstone-hud-renderer'
            header = binary.read_bytes()[:20] if binary.exists() else b''
            if platform.system() != 'Linux' or header[:5] != b'\x7fELF\x02' or len(header)<20 or struct.unpack('<H',header[18:20])[0] != 62:
                raise RuntimeError(i18n.t('hud.binary_required'))
            for name in ('diagnostic.json',):
                (self.runtime / name).unlink(missing_ok=True)
            self.error = ''
            self._ensure_media_worker()
            self.settings['visible'] = True
            await self._activate_tracking_logs()
            atomic_json(self.settings_dir / 'settings.json', self.settings)
            self._publish()
            env = dict(os.environ, DISPLAY=self.settings['display'])
            with (self.runtime / 'renderer.log').open('ab') as log:
                self.proc = await asyncio.create_subprocess_exec(str(binary), str(self.runtime / 'state.json'), str(ROOT / 'assets'), str(self.runtime / 'diagnostic.json'), env=env, stdout=log, stderr=log)
            await asyncio.sleep(.3)
            if self.proc.returncode is not None:
                self.error = i18n.t('hud.start_failed')
            return await self.status()

    @active_operation
    async def stop_hud(self):
        return await self._stop_renderer()

    async def _stop_renderer(self,preserve=False):
        async with self.lock:
            if not preserve:
                self.settings['visible'] = False
                atomic_json(self.settings_dir / 'settings.json', self.settings)
            if self.proc and self.proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), 3)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):self.proc.kill()
                    await self.proc.wait()
            self.proc = None
            self._publish()
        return await self.status()

    async def status(self):
        game = self.parser.game
        tracking = self.parser.view(self.cards) if self.active and self.caught_up else dict(status='waiting')
        self._tracking_titles(tracking)
        stage = i18n.t('match.found') if game and not game.complete else i18n.t('match.over') if game else i18n.t('match.none')
        identities = i18n.t('identity.both') if game and game.friendly and game.opponent else i18n.t('identity.partial')
        deck_stage = i18n.t('deck.full') if game and self.parser.initial_dbf else i18n.t('deck.partial')
        diag = {}
        try:
            diag = json.loads((self.runtime / 'diagnostic.json').read_text())
        except (OSError, ValueError):
            pass
        full_resources=await self._io(self.full_cards.usage,self.card_locale(),len(self.cards.by_id)) if self.io_pool is not None and getattr(self,'full_cards',None) else {}
        return dict(full_card_resources=full_resources,version=VERSION,repository=REPOSITORY,settings=self.settings,storage=dict(runtime=str(self.runtime),database=str(self.cards.cache_path()),images=str(self.cards.images),retained_on_uninstall=True), running=bool(self.proc and self.proc.returncode is None),
                    lifecycle=self.lifecycle_state,
                    background=dict(log_monitor=bool(self.task and not self.task.done()),downloads=bool(self.media_task and not self.media_task.done()),memory=self.memory_watch.thread is not None,io_pool=self.io_pool is not None),
                    error=self.error, diagnostic=diag,full_card_preview=self.full_cards.diagnostic() if getattr(self,'full_cards',None) else {}, log_path=str(self.log_path or ''),
                    parse_errors=self.parser.failures, gamescope_running=self.gamescope_running,
                    gamescope_status=self.gamescope, logs=self.discovery, cards=self.cards.diagnostic(),
                    process=self.process, power_config=self.power_config, decks_config=self.decks_config,arena_config=self.arena_config,
                    match_status=stage, identity_status=identities, deck_status=deck_stage,
                    decks_log_status=i18n.t('decks.found') if self.discovery.get('decks') else i18n.t('decks.missing'),
                    log_status=diagnostic_state(self.process,self.power_config,self.discovery),
                    tracking=tracking,
                    visibility='',
                    arena=self._arena_ui(),arena_log_status=i18n.t('arena_log.found') if self.discovery.get('arena') else i18n.t('arena_log.missing'))

    def _labels(self):
        """Static HUD labels in the selected interface language."""
        return dict(waiting=i18n.t('hud.waiting'),loading=i18n.t('hud.loading'),preview_unavailable=i18n.t('hud.preview_unavailable'),arena_hero=i18n.t('arena.hero'),arena_hero_power=i18n.t('arena.hero_power'),arena_card=i18n.t('arena.card'),
                    opponent_played=i18n.t('hud.opponent_played'),own_played=i18n.t('hud.own_played'),
                    empty_own=i18n.t('hud.empty_own'),empty_other=i18n.t('hud.empty_other'),no_rating=i18n.t('arena.no_rating'),
                    deck_original=i18n.t('hud.deck_original'),deck_added=i18n.t('hud.deck_added'))

    def _tracking_titles(self,tracking):
        """Preformatted summary line and deck title, so the renderer holds no copy."""
        status={'playing':'hud.playing','identifying':'hud.identifying','unsupported':'hud.unsupported'}.get(tracking.get('status'),'hud.idle')
        known=lambda value:value if isinstance(value,int) else '?'
        parts=[i18n.t(status),i18n.t('hud.turn',n=known(tracking.get('turn')))]
        if self.settings['opponent_hand']:parts.append(i18n.t('hud.opponent_hand',n=known(tracking.get('opponent_hand'))))
        parts.append(i18n.t('hud.opponent_deck',n=known(tracking.get('opponent_deck'))))
        tracking['summary']=' · '.join(parts)
        tracking['remaining_title']=i18n.t('hud.remaining',n=known(tracking.get('own_remaining')))
        return tracking

    def _publish(self):
        if getattr(self,'full_cards',None) and not self.full_cache_resetting:
            self.full_cards.request(self.card_locale(),self.settings['enabled'] and self.settings['visible'],self.settings['image_tls_verify'])
        tracking = self.parser.view(self.cards) if self.active and self.caught_up else dict(status='waiting',turn=0,own=[],opponent=[],own_label=i18n.t('track.waiting_log'),opponent_hand=None,opponent_deck=None)
        self._tracking_titles(tracking)
        if self.settings['enabled'] and self.settings['card_images'] and not self.cache_resetting:
            self.cards.request_images(r['id'] for key in ('own','own_added','own_played','opponent_seen','opponent_played') for r in tracking.get(key,[]))
        arena=self._arena_view()
        # The panel follows the memory snapshot alone; Arena.log no longer gates it.
        arena['visible']=bool(self.settings['enabled'] and self.settings['arena'] and (arena['count'] or arena['candidates']) and tracking['status']!='playing')
        if self.settings['card_images'] and arena['visible'] and not self.cache_resetting:
            self.cards.request_images(r['id'] for key in ('picks','candidates') for r in arena[key])
        atomic_json(self.runtime / 'state.json', dict(self.settings,updated=time.time(),schema=2,full_card_generation=self.full_card_generation,tracking=tracking,arena_state=arena,
                                                       game_display=local_x11_display(self.process.get('environment',{}).get('DISPLAY')) if self.process.get('found') else '',card_locale=self.card_locale(),idle_visible=bool(self.process.get('pid')),labels=self._labels(),visible=bool(self.settings['enabled'] and self.settings['visible'])))

    async def _loop(self):
        while not self.loop_stop.is_set():
            try:
                if time.monotonic()-self.last_scan >= 3:
                    scan_key = (self.settings['game_dir'],self.settings['log_dir'])
                    process = await self._io(discover_process)
                    async with self.config_lock:
                        config = await self._io(ensure_power,process)
                        if self.settings['auto_logs'] and self.settings['visible']:
                            await self._sync_tracking_logs(process)
                            decks_config=self.decks_config
                            arena_config=self.arena_config
                        else:
                            decks_config = await self._io(inspect_config,process.get('user_dir'),'Decks')
                            arena_config = await self._io(inspect_config,process.get('user_dir'),'Arena')
                        if arena_config.get('enabled') and self.arena_receipt.get('path')==arena_config.get('path'):
                            arena_config['restart_required']=self.arena_receipt.get('instance')==process.get('instance')
                            arena_config['backup']=self.arena_receipt.get('backup','')
                        if decks_config.get('enabled') and self.decks_receipt.get('path')==decks_config.get('path'):
                            decks_config['restart_required'] = self.decks_receipt.get('instance')==process.get('instance')
                            decks_config['backup'] = self.decks_receipt.get('backup','')
                    if config.get('changed') and config.get('success'):
                        self.restart_receipt = dict(instance=process.get('instance'),path=config['path'],backup=config.get('backup',''))
                        atomic_json(self.settings_dir/'power-config-receipt.json',self.restart_receipt)
                    if config.get('enabled') and self.restart_receipt.get('path')==config.get('path'):
                        config['restart_required'] = self.restart_receipt.get('instance')==process.get('instance')
                        config['backup'] = self.restart_receipt.get('backup','')
                    result = await self._io(discover,process.get('game_dir') or scan_key[0],scan_key[1])
                    if scan_key != (self.settings['game_dir'],self.settings['log_dir']):
                        continue
                    self.process = process
                    self.power_config = config
                    self.decks_config = decks_config
                    self.arena_config = arena_config
                    self.discovery = result
                    self.last_scan = time.monotonic()
                    self.gamescope_running, self.gamescope = gamescope_status()
                power = self.discovery.get('power')
                self.active = bool(power and power['active'])
                self.log_path = Path(power['path']) if power else None
                arena_file=self.discovery.get('arena')
                decks_file=self.discovery.get('decks')
                side_active=bool(power and (self.active or any(item and item['active'] for item in (arena_file,decks_file))))
                if side_active:
                    session=str(self.log_path.parent)
                    if session!=self.side_session:
                        self.arena.set_session(session);self.arena_tail=Tail();self.deck_tail=Tail()
                        self.decks=DeckLog();self.parser.decks=self.decks;self.side_session=session
                    side_ready=True
                    # Process Arena before Decks (ID proof), and both before Power.
                    for kind in ('arena','decks'):
                        item=self.discovery.get(kind)
                        if not item:continue
                        tail=self.arena_tail if kind=='arena' else self.deck_tail
                        old_generation=tail.generation;side_lines=tail.read(item['path'])
                        if old_generation!=tail.generation:
                            clock=LogClock(item['path'],item['mtime'])
                            if kind=='arena':
                                self.arena_clock=clock;self.arena.reset_stream()
                                self.arena_caught_up=False
                                # Re-apply final Decks definitions after an Arena rewind.
                                self.deck_tail=Tail();self.decks=DeckLog();self.parser.decks=self.decks
                            else:
                                self.deck_clock=clock;self.decks=DeckLog();self.parser.decks=self.decks;self.arena.reset_decks()
                        clock=self.arena_clock if kind=='arena' else self.deck_clock
                        for line in side_lines:
                            m=LINE.match(line)
                            if not m:continue
                            stamp=clock.timestamp(m[1])
                            if kind=='arena':self.arena.feed(stamp,m[2])
                            else:
                                self.decks.feed(stamp,m[2]);self.arena.feed_decks(stamp,m[2])
                        side_ready=side_ready and tail.offset>=Path(item['path']).stat().st_size
                        self.discovery[kind+'_offset']=tail.offset
                        self.discovery[kind+'_generation']=tail.generation
                        if not side_ready and kind=='arena':break
                    self.arena_caught_up=side_ready and bool(arena_file)
                    if not side_ready:
                        self._publish();await asyncio.sleep(.25);continue
                else:self.arena_caught_up=False
                if self.active:
                    generation = self.tail.generation
                    lines = self.tail.read(self.log_path)
                    if self.tail.generation != generation:
                        self.parser = Tracker(self.decks,arena=self.arena)
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
                    self.discovery['read_state'] = i18n.t('log.read_ok')
                    self.discovery['parse_state'] = i18n.t('log.match_done') if self.parser.game and self.parser.game.complete else i18n.t('log.match_found') if self.parser.game else i18n.t('log.await_create_game')
                if self.proc and self.proc.returncode is not None:
                    self.error = i18n.t('hud.exited_code',code=self.proc.returncode)
                self._publish()
            except Exception as exc:
                self.error = str(exc)
                self.recent_errors.append(type(exc).__name__+': '+str(exc)[:250])
                self.discovery['read_state'] = i18n.t('log.read_failed',error=str(exc));self.discovery['parse_failed'] = True
            try:await asyncio.wait_for(self.loop_stop.wait(),.25)
            except asyncio.TimeoutError:pass

    async def _unload(self):
        async with self.lifecycle_lock:
            await self._stop_services()

    async def _uninstall(self):
        # Preserve user configuration and backups on uninstall; never overwrite later edits.
        pass
