"""Check compatibility and isolated updates using the published snapshots."""
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import shutil
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
            self.assertIsNone(reloaded.task)
            requests.clear()
            damaged = False
            reloaded.check()
            await reloaded.wait()
            self.assertEqual(reloaded.results, {CARD_FILE: 'updated', CLASS_FILE: 'unchanged'})
            self.assertEqual(requests, [MANIFEST_URL, RAW_URL + CARD_FILE])
            reloaded.set_policy(False, True)

    async def test_daily_check_deadline_follows_manual_check_and_survives_restart(self):
        start = 1_800_000_000
        clock = Mock()
        clock.time.return_value = start
        with tempfile.TemporaryDirectory() as folder, patch('engine.arena_data_update.time', clock), \
                patch('engine.arena_data_update.load_manifest') as fetch:
            cache = Path(folder)
            service = ArenaDataUpdater(cache, Mock())
            fetch.return_value = {
                name: {'url': RAW_URL + name, 'sha256': service.hashes[name]} for name in FILES
            }
            service.set_policy(True, True)
            self.assertIsNotNone(service.task)
            await service.wait()
            self.assertEqual(service.last_checked, start)

            service.set_policy(True, False)
            manual_time = start + INTERVAL
            clock.time.return_value = manual_time
            service.check_if_due()
            self.assertIsNone(service.task)
            service.check()
            self.assertIsNotNone(service.task)
            await service.wait()

            reloaded = ArenaDataUpdater(cache, Mock())
            self.assertEqual(reloaded.last_checked, manual_time)
            reloaded.set_policy(True, True)
            clock.time.return_value = manual_time + INTERVAL - 1
            reloaded.check_if_due()
            self.assertIsNone(reloaded.task)
            self.assertEqual(fetch.call_count, 2)

            clock.time.return_value += 1
            reloaded.check_if_due()
            self.assertIsNotNone(reloaded.task)
            await reloaded.wait()
            self.assertEqual(fetch.call_count, 3)

            clock.time.return_value += 2 * INTERVAL
            overdue = ArenaDataUpdater(cache, Mock())
            overdue.set_policy(True, True)
            self.assertIsNotNone(overdue.task)
            await overdue.wait()
            self.assertEqual(fetch.call_count, 4)

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


class ArenaDataPublisherTests(unittest.TestCase):
    def test_stale_mode_keeps_snapshot_and_invalid_new_mode_leaves_all_files_alone(self):
        spec = importlib.util.spec_from_file_location('arena_publisher', ROOT / 'scripts/update-arena-data.py')
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        modes = read_object((PUBLISHED / CLASS_FILE).read_bytes())['modes']
        modes['arena']['source_lastUpdated'] = '2020-01-01T00:00:00Z'
        cards = read_object((PUBLISHED / CARD_FILE).read_bytes())['classes']
        sources = {row['url']: row for row in modes.values()}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'arena'
            shutil.copytree(PUBLISHED, output)
            original = {path.name: path.read_bytes() for path in output.iterdir()}
            with patch.multiple(publisher, PUBLISHED=output, fetch=lambda url: (b'', None),
                                parse_tierlist=lambda html: cards, fetch_mode=sources.__getitem__):
                publisher.update()
                self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, original)
                modes['arena-underground']['classes'].clear()
                with self.assertRaises(ValueError):
                    publisher.update()
                self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, original)
