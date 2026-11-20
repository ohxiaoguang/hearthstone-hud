#!/usr/bin/env python3
"""Publish validated schema 1 snapshots from HearthArena and Zero-to-Heroes."""
import gzip
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.arena_class_ratings import aggregate
from engine.arena_data import (
    CARD_FILE, CARD_URL, CLASS_FILE, FILES, MODE_URLS, RAW_URL, TIERS,
    read_object, validate_mode, validate_snapshot,
)

PUBLISHED = ROOT / 'data' / 'arena'
MAX_RESPONSE = 8 * 1024 * 1024

# Adapted from justfaked/hs-decktracker-linux ratings.py at
# 649534be99f35cb499ed2fae371625bd04b95b1d (MIT; see licenses/).
SECTION = re.compile(r'<section class="tab tierlist ([a-z-]+)')
ITEM = re.compile(
    r'<li class="tier [a-z-]+"><header[^>]*>([^<]+)</header>'
    r'|renders/\w+/([A-Za-z0-9_]+)\.webp">[^<]*(?:<span[^>]*>[^<]*</span>[^<]*)*</dt>'
    r'<dd class="score[^"]*">(-?\d+)(?=<)'
)
RENDER = re.compile(r'renders/\w+/[A-Za-z0-9_]+\.webp')


def parse_tierlist(html):
    result = {}
    for section in SECTION.finditer(html):
        name = section[1]
        cls = 'NEUTRAL' if name == 'any' else name.replace('-', '').upper()
        end = html.find('</section>', section.end())
        if cls in result or end < 0 or SECTION.search(html, section.end(), end):
            raise ValueError(f'Invalid HearthArena section {name}')
        cards = result[cls] = {}
        tier = ''
        content = html[section.end():end]
        scored = 0
        for match in ITEM.finditer(content):
            if match[1]:
                tier = match[1].strip()
                if tier not in TIERS:
                    raise ValueError(f'Unknown HearthArena tier {tier}')
            else:
                scored += 1
                cards[match[2]] = {'score': int(match[3]), 'tier': tier}
        if scored != content.count('<dd class="score') or scored != len(RENDER.findall(content)):
            raise ValueError(f'Unrecognized HearthArena card row in {name}')
    return result


def fetch(url):
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if not raw or len(raw) > MAX_RESPONSE:
                    raise ValueError(f'Invalid response size for {url}')
                return raw, response.headers.get('Last-Modified')
        except (URLError, TimeoutError, HTTPException, ConnectionError) as exc:
            if attempt == 2 or (isinstance(exc, HTTPError) and exc.code < 500 and exc.code != 429):
                raise RuntimeError(f'Could not fetch {url}: {exc}') from exc
            time.sleep(2 ** attempt)


def fetch_mode(url, previous):
    raw, _ = fetch(url)
    decoded = raw
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
            decoded = compressed.read(MAX_RESPONSE + 1)
        if len(decoded) > MAX_RESPONSE:
            raise ValueError(f'Invalid decompressed response size for {url}')
    source = read_object(decoded)
    mode = {
        'url': url,
        'source_sha256': sha256(raw).hexdigest(),
        'json_sha256': sha256(decoded).hexdigest(),
        'source_bytes': len(raw),
        'source_lastUpdated': source['lastUpdated'],
        'source_timePeriod': source['timePeriod'],
        'source_rows': len(source['stats']),
        'validated': True,
        'classes': aggregate(source),
    }
    validate_mode(mode, url, previous)
    return mode


def serialize(data):
    return (json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')


def update():
    manifest_path = PUBLISHED / 'manifest.json'
    publishing = manifest_path.is_file()
    old_manifest = read_object(manifest_path.read_bytes()) if publishing else {}
    base = PUBLISHED if publishing else ROOT / 'engine'
    original = {name: (base / name).read_bytes() for name in FILES}
    snapshots = {name: read_object(raw) for name, raw in original.items()}
    for name, snapshot in snapshots.items():
        validate_snapshot(name, snapshot)
    old_cards, old_classes = snapshots[CARD_FILE], snapshots[CLASS_FILE]

    with ThreadPoolExecutor(max_workers=3) as pool:
        page = pool.submit(fetch, CARD_URL)
        stats = {mode: pool.submit(fetch_mode, url, old_classes['modes'][mode]) for mode, url in MODE_URLS.items()}
        html, last_modified = page.result()
        modes = {mode: future.result() for mode, future in stats.items()}
    cards = parse_tierlist(html.decode('utf-8'))
    upstream_date = parsedate_to_datetime(last_modified).isoformat() if last_modified else None
    captured = datetime.now(timezone.utc).isoformat()
    next_cards = dict(old_cards, classes=cards, captured_at=captured, source_sha256=sha256(html).hexdigest())
    next_classes = dict(old_classes, modes=modes, captured_at=captured)
    validate_snapshot(CARD_FILE, next_cards, old_cards)
    validate_snapshot(CLASS_FILE, next_classes, old_classes)

    if publishing and cards == old_cards['classes']:
        next_cards = old_cards
        upstream_date = old_manifest['files'][CARD_FILE]['upstream_updated_at']
    if publishing:
        for mode, row in modes.items():
            if row['classes'] == old_classes['modes'][mode]['classes']:
                modes[mode] = old_classes['modes'][mode]
        if modes == old_classes['modes']:
            next_classes = old_classes

    new = {CARD_FILE: next_cards, CLASS_FILE: next_classes}
    payloads = {name: original[name] if new[name] is snapshots[name] else serialize(new[name]) for name in FILES}
    files = {name: {
        'url': RAW_URL + name,
        'sha256': sha256(payload).hexdigest(),
        'source': new[name]['source'],
        'captured_at': new[name]['captured_at'],
    } for name, payload in payloads.items()}
    files[CARD_FILE].update(source_url=CARD_URL, upstream_updated_at=upstream_date)
    files[CLASS_FILE]['modes'] = {
        mode: {'source_url': row['url'], 'upstream_updated_at': row['source_lastUpdated']}
        for mode, row in next_classes['modes'].items()
    }
    if files == old_manifest.get('files'):
        print('Arena data is unchanged.')
        return

    PUBLISHED.mkdir(parents=True, exist_ok=True)
    payloads['manifest.json'] = serialize({'schema': 1, 'updated_at': captured, 'files': files})
    for name, payload in payloads.items():
        if not publishing or name == 'manifest.json' or payload != original[name]:
            path = PUBLISHED / name
            tmp = path.with_suffix('.tmp')
            tmp.write_bytes(payload)
            tmp.replace(path)
    print(f'Validated {sum(map(len, cards.values()))} card ratings and {len(modes)} class-statistics modes.')


if __name__ == '__main__':
    update()
