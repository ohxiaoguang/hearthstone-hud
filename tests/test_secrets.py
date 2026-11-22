"""Secret evidence, candidate metadata and upgrade behavior."""
import json
import time
import unittest
from unittest.mock import patch

import test_tracking as fixtures
from engine.cards import Cards, MIN_CARDS


class SecretTests(unittest.TestCase):
    feed = fixtures.TrackingTests.feed
    entity = fixtures.TrackingTests.entity

    def setUp(self):
        fixtures.TrackingTests.setUp(self)
        self.data = [
            dict(id='CORE_A', dbfId=8, name='Alpha', mechanics=['SECRET'], cardClass='MAGE'),
            dict(id='A', dbfId=9, name='Alpha', mechanics=['SECRET'], cardClass='MAGE'),
            dict(id='PRINT_A', dbfId=10, name='Alpha', mechanics=['SECRET'], cardClass='MAGE'),
            dict(id='B', dbfId=11, name='Beta', mechanics=['SECRET'], classes=['MAGE', 'HUNTER']),
            dict(id='C', dbfId=12, name='Gamma', referencedTags=['SECRET'], cardClass='MAGE'),
            dict(id='D', dbfId=13, name='Delta', mechanics=['SECRET'], cardClass='ROGUE'),
            dict(id='HERO_TEST', dbfId=14, name='Hero', cardClass='MAGE'),
        ]
        self.cards.install(self.data)
        self.entity(16, 'HERO_TEST', 'PLAY', 2)
        self.feed('TAG_CHANGE Entity=3 tag=HERO_ENTITY value=16')

    def view(self):
        return self.p.view(self.cards)

    def candidates(self):
        return [row['id'] for row in self.view().get('secret_candidates', [])]

    def active(self):
        return [(r['entity_id'], r['id']) for r in self.view().get('secrets', [])]

    def test_snapshot_zone_and_reveal(self):
        # A snapshot already in SECRET needs no hand/play event.
        self.entity(21, '', 'SECRET', 2)
        self.entity(22, '', 'SECRET', 1)
        self.entity(23, 'C', 'SECRET', 2)  # known non-secret
        self.entity(24, '', 'SECRET', 2)
        self.feed('tag=QUEST value=1')
        self.assertEqual(self.active(), [(21, '')])
        self.assertEqual(self.candidates(), ['A', 'B'])
        self.assertIn('No format filter', self.view()['secret_title'])
        self.feed('TAG_CHANGE Entity=6 tag=ZONE value=SECRET')
        self.feed('SHOW_ENTITY - Updating Entity=6 CardID=CORE_A')
        self.assertEqual(self.active(), [(6, 'CORE_A'), (21, '')])
        self.assertEqual(self.candidates(), ['A', 'B'])
        self.feed('TAG_CHANGE Entity=21 tag=CONTROLLER value=1')
        self.assertEqual(self.active(), [(6, 'CORE_A')])
        self.assertEqual(self.candidates(), [])
        self.feed('CHANGE_ENTITY - Updating Entity=6 CardID=')
        self.assertEqual(self.active(), [(6, '')])
        self.feed('HIDE_ENTITY - Entity=6 tag=ZONE value=GRAVEYARD')
        self.assertEqual(self.active(), [])
        self.assertEqual(self.candidates(), [])

    def test_unknown_class_toggle_and_game_boundaries(self):
        self.entity(21, '', 'SECRET', 2)
        self.feed('TAG_CHANGE Entity=3 tag=HERO_ENTITY value=0')
        self.assertEqual(self.active(), [(21, '')])
        self.assertEqual(self.candidates(), [])
        self.assertTrue(self.view()['secret_empty'])
        self.feed('TAG_CHANGE Entity=3 tag=HERO_ENTITY value=16')
        self.feed('TAG_CHANGE Entity=16 tag=CLASS value=HUNTER')
        self.assertEqual(self.candidates(), ['B'])
        self.assertFalse(self.p.view(self.cards, secret_hints=False).get('secrets'))
        self.assertEqual(self.active(), [(21, '')])
        self.feed('TAG_CHANGE Entity=GameEntity tag=STATE value=COMPLETE')
        self.assertEqual(self.active(), [])
        self.feed('CREATE_GAME')
        self.assertEqual(self.active(), [])

    def test_reconnect_uses_only_entities_in_the_new_snapshot(self):
        self.entity(21, 'B', 'SECRET', 2)
        self.entity(22, '', 'SECRET', 2)
        self.feed('CREATE_GAME')
        self.feed('GameEntity EntityID=1')
        for pid in (1, 2):
            self.feed(f'Player EntityID={pid+1} PlayerID={pid} GameAccountId=[hi=1 lo={pid}]')
        self.feed('PlayerID=1, PlayerName=Local', game=True)
        self.feed('PlayerID=2, PlayerName=UNKNOWN HUMAN PLAYER', game=True)
        self.entity(21, '', 'GRAVEYARD', 2)
        self.entity(22, '', 'SECRET', 2)
        self.assertEqual(self.active(), [(22, '')])

    def test_same_name_with_different_effect_is_a_distinct_candidate(self):
        self.cards.install(self.data + [dict(id='A2', name='Alpha', cardClass='MAGE',
                                             mechanics=['SECRET'], text='Another effect')])
        self.entity(21, '', 'SECRET', 2)
        self.assertEqual(self.candidates(), ['A', 'A2', 'B'])

    def test_old_locale_cache_upgrades_once_and_survives_restart(self):
        rows = self.data + [dict(id='F'+str(i), dbfId=100+i, name='甲'+str(i)) for i in range(MIN_CARDS)]
        legacy = [{k: v for k, v in row.items() if k not in ('mechanics','classes')} for row in rows]
        path = self.cards.cache_path('zhCN')
        path.write_text(json.dumps(dict(updated=time.time(), cards=legacy)), encoding='utf-8')
        cache = Cards(path.parent, language='zhCN')
        self.assertEqual(cache.info('F1')['name'], '甲1')
        self.assertTrue(cache.need_download)
        self.assertFalse(cache.has_mechanics)
        with patch('engine.cards.fetch', return_value=json.dumps(rows).encode()) as fetch:
            self.assertTrue(cache.apply(cache.refresh()))
            fetch.assert_called_once()
        fresh = Cards(path.parent, language='zhCN')
        self.assertFalse(fresh.need_download)
        self.assertEqual(fresh.secrets_by_class['MAGE'], ['A', 'B'])
        self.assertEqual(fresh.by_id['CORE_A']['mechanics'], ['SECRET'])
        fresh.clear_language('zhCN')
        self.assertEqual(fresh.secrets_by_class, {})
