"""Synthetic logs in upstream-confirmed GameState/Decks line format.
Not real Ally X replay fixtures. IDs/names below are intentionally synthetic.
"""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from engine.cards import Cards
from engine.discovery import discover, gamescope_status
from engine.tracker import Tracker, DeckLog
from engine.deckstring import DeckDefinition, encode

DAY=datetime.now().date()

class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cards=Cards(Path(self.tmp.name)/'cache')
        self.cards.install([dict(id='TEST_A',dbfId=1001,name='测试甲',cost=1),dict(id='TEST_B',dbfId=1002,name='测试乙',cost=2)])
        self.decks=DeckLog()
        self.decks.feed(datetime.combine(DAY,datetime.min.time()),'Finding Game With Deck:')
        self.decks.feed(datetime.combine(DAY,datetime.min.time()),encode(DeckDefinition([813],{1001:2})))
        self.p=Tracker(self.decks);self.counter=0
        self.feed('CREATE_GAME');self.feed('GameEntity EntityID=1')
        for eid,pid in [(2,1),(3,2)]:
            self.feed(f'Player EntityID={eid} PlayerID={pid} GameAccountId=[hi=1 lo={pid}]')
            self.feed(f'tag=CONTROLLER value={pid}')
        for eid,card,pid in [(4,'TEST_A',1),(5,'TEST_A',1),(6,'',2),(7,'',2)]:self.entity(eid,card,'DECK',pid)
        self.feed('PlayerID=1, PlayerName=Local',game=True);self.feed('PlayerID=2, PlayerName=UNKNOWN HUMAN PLAYER',game=True)
        self.feed('TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_READY')

    def feed(self,text,game=False):
        self.counter+=1
        line=f'D 00:01:{self.counter//100:02d}.{self.counter%100:02d}00000 GameState.DebugPrint'+('Game' if game else 'Power')+'() - '+text
        self.p.feed_line(line,DAY)
        return line

    def entity(self,eid,card,zone,pid):
        self.feed(f'FULL_ENTITY - Creating ID={eid} CardID={card}')
        self.feed(f'tag=ZONE value={zone}');self.feed(f'tag=CONTROLLER value={pid}')

    def row(self,cid):
        return next(r for r in self.p.view(self.cards)['own'] if r['id']==cid)

    def test_decks_initialization_and_chinese_mapping(self):
        self.assertEqual(self.row('TEST_A')['initial'],2)
        self.assertEqual(self.row('TEST_A')['remaining'],2)
        self.assertEqual(self.row('TEST_A')['name'],'测试甲')

    def test_draw_play_and_duplicate(self):
        line=self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND')
        self.p.feed_line(line,DAY)
        self.assertEqual(self.row('TEST_A')['remaining'],1)
        self.assertEqual(self.row('TEST_A')['drawn'],1)
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=PLAY')
        self.assertEqual(self.row('TEST_A')['remaining'],1)
        self.assertEqual(self.row('TEST_A')['used'],1)

    def test_generated_copy_does_not_consume_initial_deck(self):
        self.entity(8,'TEST_A','HAND',1)
        self.feed('TAG_CHANGE Entity=8 tag=ZONE value=PLAY')
        self.assertEqual(self.row('TEST_A')['remaining'],2)
        self.assertEqual(self.row('TEST_A')['drawn'],0)

    def test_shuffle_and_draw_generated_card(self):
        self.entity(8,'TEST_B','HAND',1);self.feed('TAG_CHANGE Entity=8 tag=ZONE value=DECK')
        self.assertEqual(self.p.view(self.cards)['own_added'][0]['remaining'],1)
        self.feed('TAG_CHANGE Entity=8 tag=ZONE value=HAND')
        self.assertEqual(self.p.view(self.cards)['own_added'],[])
        self.assertEqual(self.row('TEST_A')['remaining'],2)

    def test_transform_and_return_to_deck(self):
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND')
        self.feed('CHANGE_ENTITY - Updating Entity=4 CardID=TEST_B')
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=DECK')
        self.assertEqual(self.row('TEST_A')['remaining'],1)
        self.assertEqual(self.p.view(self.cards)['own_added'][0]['remaining'],1)
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND')
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=PLAY')
        self.assertEqual(self.p.view(self.cards)['own_added'],[])
        self.assertEqual(self.p.view(self.cards)['own_played'][-1]['card_id'],'TEST_B')

    def test_original_shuffle_back(self):
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND');self.feed('TAG_CHANGE Entity=4 tag=ZONE value=DECK')
        self.assertEqual(self.row('TEST_A')['remaining'],2)

    def test_opponent_reveal_unknown_and_transform(self):
        self.feed('TAG_CHANGE Entity=6 tag=ZONE value=HAND')
        self.assertEqual(self.p.view(self.cards)['opponent'],[])
        self.assertEqual(self.p.view(self.cards)['opponent_hand'],1)
        self.feed('SHOW_ENTITY - Updating Entity=6 CardID=TEST_A')
        self.feed('TAG_CHANGE Entity=6 tag=ZONE value=PLAY')
        self.feed('CHANGE_ENTITY - Updating Entity=6 CardID=TEST_B')
        rows=self.p.view(self.cards)['opponent']
        self.assertEqual({r['id']:r['count'] for r in rows},{'TEST_A':1,'TEST_B':1})
        self.assertEqual(self.p.view(self.cards)['opponent_deck'],1)

    def test_end_and_new_game_reset(self):
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND')
        self.feed('TAG_CHANGE Entity=GameEntity tag=STATE value=COMPLETE')
        self.assertEqual(self.p.view(self.cards)['status'],'waiting')
        self.feed('CREATE_GAME')
        self.assertEqual(self.p.drawn,set());self.assertEqual(self.p.used,[])
        self.assertEqual(self.p.initial_dbf,{})

    def test_missing_deck_is_partial_and_unknown_count_stays_unknown(self):
        self.p.initial_dbf={}
        self.p.decks=DeckLog()  # No Decks evidence, including delayed candidates.
        self.assertIsNone(self.row('TEST_A')['remaining'])
        self.assertIsNone(self.row('TEST_A')['initial'])
        self.assertEqual(self.row('TEST_A')['known_in_deck'],2)

    def test_reconnect_preserves_origin_and_counts(self):
        self.feed('TAG_CHANGE Entity=4 tag=ZONE value=HAND');self.feed('CREATE_GAME')
        self.feed('FULL_ENTITY - Creating ID=4 CardID=TEST_A')
        self.feed('tag=ZONE value=HAND');self.feed('tag=CONTROLLER value=1')
        self.assertTrue(self.p.game.entities[4].in_starting_deck)
        self.assertEqual(self.p.initial_dbf,{1001:2})
        self.assertEqual(self.p.drawn,{4})

class DiscoveryTests(unittest.TestCase):
    def test_nested_manual_and_old_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            game=Path(folder);session=game/'Logs/a/b/c';session.mkdir(parents=True)
            power=session/'Power.log';power.write_text('sample');deck=session/'Decks.log';deck.write_text('deck')
            d=discover(game);self.assertEqual(d['power']['path'],str(power));self.assertEqual(d['decks']['path'],str(deck))
            self.assertEqual(discover(game,str(power))['power']['path'],str(power))
            os.utime(power,(1,1));self.assertFalse(discover(game)['power']['active'])
            self.assertIn('not replayed',discover(game)['read_state'])
    def test_lowercase_missing_and_gamescope_variant(self):
        with tempfile.TemporaryDirectory() as folder:
            game=Path(folder);(game/'logs').mkdir();(game/'logs/power.log').write_text('')
            self.assertIsNotNone(discover(game)['power'])
            (game/'100').mkdir();(game/'100/comm').write_text('gamescope-wl\n')
            found,text=gamescope_status(game)   # (detected, localized text)
            self.assertTrue(found);self.assertIn('gamescope-wl',text)
            self.assertTrue(discover(game/'missing')['errors'])

class CardTests(unittest.TestCase):
    def test_missing_offline_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            cards=Cards(folder)
            self.assertEqual(cards.info('NEW_CARD')['name'],'NEW_CARD')
            with patch('engine.cards.fetch',side_effect=OSError('offline')):
                self.assertIsNone(cards.refresh())
            self.assertIn('offline',cards.error)
            (Path(folder)/'cards.json').write_text(json.dumps({'updated':10,'cards':[dict(id='A',dbfId=1,name='中文',cost=2)]+[dict(id='CACHE_'+str(i),dbfId=i+2,name='样本'+str(i),cost=1) for i in range(100)]}))
            cached=Cards(folder);self.assertEqual(cached.info('A')['name'],'中文');self.assertEqual(cached.updated,10)
    def test_image_paths_and_queue_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            cards=Cards(folder);self.assertIsNone(cards.image_path('../secret'))
            cards.request_images('CARD_'+str(i) for i in range(500))
            self.assertEqual(cards.queue.qsize(),128)

    def test_image_download_validates_and_limits_disk_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            cards=Cards(folder)
            with patch('engine.cards.fetch',return_value=b'not png'):
                with self.assertRaises(ValueError):cards.download_image('TEST_A')
            from image_support import tile_png
            image=tile_png()
            for i in range(256):(cards.images/(str(i)+'.png')).write_bytes(image)
            with patch('engine.cards.fetch',return_value=image):cards.download_image('TEST_A')
            self.assertLessEqual(len(list(cards.images.glob('*.png'))),256)
            self.assertTrue(cards.info('TEST_A')['image'])

class ClockTests(unittest.TestCase):
    def test_session_date_and_midnight(self):
        from engine.discovery import LogClock
        clock=LogClock('/Logs/Hearthstone_2026_11_13_23_00_00/Power.log',0)
        self.assertEqual(clock.timestamp('23:59:59.0000000').day,13)
        self.assertEqual(clock.timestamp('00:00:01.0000000').day,14)
