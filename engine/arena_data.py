"""Schema and source information shared by the publisher and the HUD."""
import json
import re
from datetime import datetime

from .arena import CLASS_NAMES
from .arena_class_ratings import aggregate

CARD_FILE = 'arena_ratings.json'
CLASS_FILE = 'arena_class_ratings.json'
FILES = (CARD_FILE, CLASS_FILE)
RAW_URL = 'https://raw.githubusercontent.com/ohxiaoguang/hearthstone-hud/main/data/arena/'
CARD_URL = 'https://www.heartharena.com/tierlist'
MODE_URLS = {
    mode: f'https://static.zerotoheroes.com/api/arena/stats/classes/{mode}/last-patch/overview.gz.json'
    for mode in ('arena', 'arena-underground')
}
TIERS = {'Great', 'Good', 'Above average', 'Average', 'Below average', 'Bad', 'Terrible'}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing data timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Data timestamp has no timezone')
    return result


def valid_sha256(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def read_object(raw):
    def unique_pairs(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError('Duplicate JSON keys')
        return result

    data = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    return data


def validate_snapshot(name, data, previous=None):
    try:
        if type(data['schema']) is not int or data['schema'] != 1:
            raise ValueError('Unsupported snapshot schema')
        timestamp(data['captured_at'])
        if not isinstance(data['source'], str) or not data['source'].strip():
            raise ValueError('Missing data attribution')
        if name == CARD_FILE:
            validate_cards(data, previous)
        elif name == CLASS_FILE:
            if not isinstance(data['aggregation'], str) or not data['aggregation'].strip():
                raise ValueError('Missing aggregation description')
            if set(data['modes']) != set(MODE_URLS):
                raise ValueError('Missing or unknown arena mode')
            for mode, url in MODE_URLS.items():
                old = previous['modes'][mode] if previous else None
                validate_mode(data['modes'][mode], url, old)
        else:
            raise ValueError('Unknown arena data file')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Invalid snapshot structure') from exc


def validate_cards(data, previous):
    if data['url'] != CARD_URL or not valid_sha256(data['source_sha256']):
        raise ValueError('Invalid HearthArena source metadata')
    if not isinstance(data['parser_reference'], str) or not data['parser_reference'].strip():
        raise ValueError('Missing parser attribution')
    classes = data['classes']
    if set(classes) != set(CLASS_NAMES) | {'NEUTRAL'}:
        raise ValueError('Missing or unknown HearthArena class')
    for cls, cards in classes.items():
        if not cards or (previous and len(cards) * 10 < len(previous['classes'][cls]) * 7):
            raise ValueError(f'HearthArena card count dropped for {cls}')
        for card_id, entry in cards.items():
            if not re.fullmatch(r'[A-Za-z0-9_]+', card_id) or type(entry['score']) is not int or entry['tier'] not in TIERS:
                raise ValueError(f'Invalid HearthArena rating for {card_id}')


def validate_mode(data, url, previous):
    if data['url'] != url or data['source_timePeriod'] != 'last-patch' or data['validated'] is not True:
        raise ValueError('Invalid Firestone source metadata')
    if not valid_sha256(data['source_sha256']) or not valid_sha256(data['json_sha256']):
        raise ValueError('Invalid Firestone source hash')
    timestamp(data['source_lastUpdated'])
    rows, size = data['source_rows'], data['source_bytes']
    if type(rows) is not int or not len(CLASS_NAMES) <= rows <= 10000 or type(size) is not int or size <= 0:
        raise ValueError('Invalid Firestone response size')
    classes = data['classes']
    if set(classes) != set(CLASS_NAMES):
        raise ValueError('Missing or unknown Firestone class')
    aggregate({'stats': [dict(playerClass=cls, **row) for cls, row in classes.items()]})
    games = sum(row['totalGames'] for row in classes.values())
    if any(row['totalGames'] == 0 for row in classes.values()):
        raise ValueError('Missing Firestone samples')
    if previous:
        old_games = sum(row['totalGames'] for row in previous['classes'].values())
        if rows * 10 < previous['source_rows'] * 7 or games * 10 < old_games * 7:
            raise ValueError('Firestone sample size dropped')
        if timestamp(data['source_lastUpdated']) < timestamp(previous['source_lastUpdated']):
            raise ValueError('Firestone statistics are older than the installed data')
