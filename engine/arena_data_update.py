"""Background maintenance of the HUD's two local arena snapshots."""
import asyncio
import logging
import os
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

from .arena_class_ratings import ClassRatings
from .arena_data import (
    CARD_FILE, CLASS_FILE, FILES, RAW_URL, read_object, timestamp,
    valid_sha256, validate_snapshot,
)
from .arena_ratings import ArenaRatings
from .io import atomic_json
from .tls import verified_context

INTERVAL = 24 * 60 * 60
MANIFEST_URL = RAW_URL + 'manifest.json'
MODELS = {CARD_FILE: ArenaRatings, CLASS_FILE: ClassRatings}
log = logging.getLogger(__name__)


def download(url, limit):
    request = Request(url, headers={'User-Agent': 'Hearthstone HUD', 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=15, context=verified_context()) as response:
        if response.geturl() != url:
            raise ValueError('Unexpected arena download redirect')
        raw = response.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError('Invalid arena download size')
    return raw


def replace_snapshot(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False)
    temp = Path(stream.name)
    try:
        with stream:
            stream.write(raw)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_manifest():
    manifest = read_object(download(MANIFEST_URL, 64 * 1024))
    if type(manifest.get('schema')) is not int or manifest['schema'] != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported arena manifest')
    timestamp(manifest.get('updated_at'))
    return manifest['files']


class ArenaDataUpdater:
    def __init__(self, directory, on_install, bundled=None):
        self.directory = directory
        self.on_install = on_install
        self.last_checked = 0
        self.results = dict.fromkeys(FILES, 'idle')
        self.task = None
        self.timer = None
        self.enabled = False
        self.automatic = False
        self.models = {}
        self.hashes = {}
        bundled = bundled or Path(__file__).resolve().parent
        for name in FILES:
            self._load_local(name, bundled / name)
            self._load_local(name, directory / name)
            if name not in self.models:
                self.models[name] = MODELS[name](path=bundled / name)
        try:
            state = read_object((directory / 'last-check.json').read_bytes())
            checked = state.get('last_checked')
            if type(checked) in (int, float) and 0 < checked <= time.time():
                self.last_checked = checked
        except (OSError, ValueError):
            pass

    def _load_local(self, name, path):
        try:
            raw = path.read_bytes()
            data = read_object(raw)
            validate_snapshot(name, data)
            current = self.models.get(name)
            if current and timestamp(data['captured_at']) < timestamp(current.data['captured_at']):
                return
            self.models[name] = MODELS[name](data=data)
            self.hashes[name] = sha256(raw).hexdigest()
        except FileNotFoundError:
            pass
        except (OSError, ValueError, RecursionError) as exc:
            log.warning('Ignoring arena snapshot %s: %s', path, exc)

    def set_policy(self, enabled, automatic):
        self.enabled = enabled
        self.automatic = automatic
        self._schedule()

    def _schedule(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.enabled and self.automatic and self.task is None:
            delay = max(0, INTERVAL - max(0, time.time() - self.last_checked))
            if not self.last_checked:
                delay = 0
            self.timer = asyncio.get_running_loop().call_later(delay, self.check)

    def check(self):
        if self.enabled and self.task is None:
            self.results = dict.fromkeys(FILES, 'checking')
            self.last_checked = time.time()
            self.task = asyncio.create_task(self._check())
            self._schedule()

    async def wait(self):
        if self.task is not None:
            await asyncio.shield(self.task)

    def status(self):
        cards = self.models[CARD_FILE].data
        classes = self.models[CLASS_FILE].data
        return {
            'last_checked': self.last_checked,
            'running': self.task is not None,
            'results': dict(self.results),
            'cards': {key: cards.get(key, '') for key in ('source', 'captured_at')},
            'classes': {
                'source': classes.get('source', ''),
                'captured_at': classes.get('captured_at', ''),
                'dates': {
                    mode: data.get('source_lastUpdated', '') for mode, data in classes['modes'].items()
                },
            },
        }

    async def _check(self):
        try:
            files = await asyncio.to_thread(load_manifest)
            await asyncio.gather(*(self._update(name, files.get(name)) for name in FILES))
        except Exception as exc:
            log.warning('Arena manifest check failed: %s', exc)
            self.results = dict.fromkeys(FILES, 'failed')
        finally:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                atomic_json(self.directory / 'last-check.json', {'last_checked': self.last_checked})
            except OSError as exc:
                log.warning('Could not save arena check time: %s', exc)
            self.task = None
            self._schedule()

    async def _update(self, name, entry):
        try:
            if not isinstance(entry, dict) or entry.get('url') != RAW_URL + name or not valid_sha256(entry.get('sha256')):
                raise ValueError('Invalid arena manifest entry')
            expected = entry['sha256']
            if expected == self.hashes.get(name):
                self.results[name] = 'unchanged'
                return
            self.results[name] = 'downloading'
            model = await asyncio.to_thread(self._install, name, entry['url'], expected)
            self.models[name] = model
            self.hashes[name] = expected
            self.on_install(name, model)
            self.results[name] = 'updated'
        except Exception as exc:
            self.results[name] = 'failed'
            log.warning('Arena update failed for %s: %s', name, exc)

    def _install(self, name, url, expected):
        raw = download(url, 4 * 1024 * 1024)
        if sha256(raw).hexdigest() != expected:
            raise ValueError('Arena snapshot SHA256 mismatch')
        data = read_object(raw)
        previous = self.models[name].data if name in self.hashes else None
        validate_snapshot(name, data, previous)
        if previous and timestamp(data['captured_at']) < timestamp(previous['captured_at']):
            raise ValueError('Arena snapshot is older than the installed data')
        model = MODELS[name](data=data)
        replace_snapshot(self.directory / name, raw)
        return model
