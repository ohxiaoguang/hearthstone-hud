"""Check compatibility and isolated updates using the published snapshots."""
import asyncio
import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from engine.arena_data import CARD_FILE, CLASS_FILE, FILES, RAW_URL, read_object, validate_snapshot
from engine.arena_data_update import ArenaDataUpdater, INTERVAL, MANIFEST_URL

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / 'data' / 'arena'


class ArenaDataUpdateTests(unittest.IsolatedAsyncioTestCase):
    def test_published_snapshots_match_manifest_and_bundled_schema(self):
        manifest = read_object((PUBLISHED / 'manifest.json').read_bytes())
        for name in FILES:
            with self.subTest(file=name):
                raw = (PUBLISHED / name).read_bytes()
                bundled = read_object((ROOT / 'engine' / name).read_bytes())
                self.assertEqual(sha256(raw).hexdigest(), manifest['files'][name]['sha256'])
                self.assertEqual(set(bundled), set(read_object(raw)))
                validate_snapshot(name, read_object(raw), bundled)

    async def test_one_failed_file_does_not_block_the_other_and_only_changed_files_download(self):
        manifest = (PUBLISHED / 'manifest.json').read_bytes()
        valid = {RAW_URL + name: (PUBLISHED / name).read_bytes() for name in FILES}
        requests = []
        damaged = True

        def download(url, limit):
            requests.append(url)
            if url == MANIFEST_URL:
                return manifest
            if url == RAW_URL + CARD_FILE and damaged:
                return b'corrupted bytes'
            return valid[url]

        with tempfile.TemporaryDirectory() as folder, patch('engine.arena_data_update.download', download):
            cache = Path(folder)
            install = Mock()
            service = ArenaDataUpdater(cache, install)
            service.set_policy(True, False)
            service.check()
            first = service.task
            service.check()
            self.assertIs(service.task, first)
            await service.wait()
            self.assertEqual(service.results, {CARD_FILE: 'failed', CLASS_FILE: 'updated'})
            self.assertFalse((cache / CARD_FILE).exists())
            self.assertEqual((cache / CLASS_FILE).read_bytes(), valid[RAW_URL + CLASS_FILE])
            install.assert_called_once_with(CLASS_FILE, service.models[CLASS_FILE])

            reloaded = ArenaDataUpdater(cache, install)
            self.assertEqual(reloaded.last_checked, service.last_checked)
            reloaded.set_policy(True, True)
            self.assertGreater(reloaded.timer.when() - asyncio.get_running_loop().time(), INTERVAL - 5)
            requests.clear()
            damaged = False
            reloaded.check()
            await reloaded.wait()
            self.assertEqual(reloaded.results, {CARD_FILE: 'updated', CLASS_FILE: 'unchanged'})
            self.assertEqual(requests, [MANIFEST_URL, RAW_URL + CARD_FILE])
            reloaded.set_policy(False, True)
            self.assertIsNone(reloaded.timer)

    async def test_matching_hash_cannot_install_an_empty_class_table(self):
        manifest = read_object((PUBLISHED / 'manifest.json').read_bytes())
        cards = read_object((PUBLISHED / CARD_FILE).read_bytes())
        cards['classes']['MAGE'].clear()
        raw = json.dumps(cards).encode()
        manifest['files'][CARD_FILE]['sha256'] = sha256(raw).hexdigest()
        manifest['files'].pop(CLASS_FILE)
        responses = {MANIFEST_URL: json.dumps(manifest).encode(), RAW_URL + CARD_FILE: raw}

        with tempfile.TemporaryDirectory() as folder, patch('engine.arena_data_update.download',
                                                            side_effect=lambda url, limit: responses[url]):
            cache = Path(folder)
            original = (PUBLISHED / CARD_FILE).read_bytes()
            (cache / CARD_FILE).write_bytes(original)
            install = Mock()
            service = ArenaDataUpdater(cache, install)
            service.set_policy(True, False)
            service.check()
            await service.wait()
            self.assertEqual(service.results[CARD_FILE], 'failed')
            self.assertEqual((cache / CARD_FILE).read_bytes(), original)
            install.assert_not_called()
