"""Exercise the SteamOS memory reader and HUD model using a synthetic Mono heap."""
from pathlib import Path
import tempfile
import unittest

from engine import i18n, mono_memory
from engine.arena_class_ratings import ClassRatings
from engine.arena_memory import DRAFT_MODES, HearthstoneMemory
from engine.arena_memory_view import ArenaPreview
from engine.arena_ratings import ArenaRatings
from engine.cards import Cards
from fake_mono_memory import FakeProcess
from memory_support import hearthstone_heap


class RedraftTests(unittest.TestCase):
    def setUp(self):
        self.heap = hearthstone_heap(slots=[('CARD_C', 25), ('CARD_B', 5), ('CARD_A', 4)],
                                     count_field=mono_memory.T_I4)
        self.reader = HearthstoneMemory(process_factory=lambda pid: FakeProcess(self.heap),
                                        finder=lambda: dict(found=True, pid=1, instance='one'))
        self.reader.connect()
        self.addCleanup(self.reader.close)
        self.display = self.reader.mono.static('DraftDisplay', 's_instance')
        self.deck = self.reader._manager()['m_undergroundDraftDeck']
        self.slots = self.deck['m_slots'].list_objects()
        self.set_mode('REDRAFTING')
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cards = Cards(Path(folder.name))
        self.ratings = ArenaRatings(data=dict(schema=1, classes={'PRIEST': {
            'CARD_A': dict(score=0, tier=''), 'CARD_B': dict(score=0, tier=''),
            'CARD_C': dict(score=80, tier='')}}))
        self.preview = ArenaPreview(ClassRatings())
        self.addCleanup(i18n.set_ui_language, i18n.ui_language())
        i18n.set_ui_language('en')

    def write(self, obj, field, value):
        offset, kind, _ = self.heap.layouts[obj.klass][0][field]
        self.heap._store(obj.addr + offset, kind, value)

    def set_mode(self, mode):
        self.write(self.display, 'm_currentMode', DRAFT_MODES.index(mode))

    def view(self):
        state, diagnostic = self.reader.poll()
        self.assertFalse(diagnostic['error'], diagnostic)
        return self.preview.view(self.cards, self.ratings, state, diagnostic)

    @staticmethod
    def marked(view):
        return [row['id'] for row in view['picks'] if row.get('suggest_remove')]

    def test_offer_then_real_deletions_through_finished_deck(self):
        offer = self.view()
        self.assertTrue(offer['offer_title'].endswith('34/35'))
        self.assertEqual(self.marked(offer), [])
        self.assertEqual([r['best'] for r in offer['candidates']], [False,False,True])
        self.write(self.slots[0], 'm_count', 26)
        full = self.view()
        self.assertEqual(full['picked_title'], '35 cards · Suggested cuts: 5')
        self.assertEqual(full['offer_title'], '')
        self.assertEqual(full['candidates'], [])
        self.assertEqual(self.marked(full), ['CARD_A']*4 + ['CARD_B'])
        i18n.set_ui_language('zh-CN')
        for count in range(34, 30, -1):
            # Player removes high-scoring copies, ignoring the recommendations.
            self.write(self.slots[0], 'm_count', count-9)
            view = self.view()
            self.assertEqual(view['offer_title'], '')
            self.assertEqual(view['candidates'], [])
            self.assertEqual(view['picked_title'], f'{count} 张 · 建议移除 {count-30} 张')
            self.assertEqual(self.marked(view), ['CARD_A']*(count-30))
        self.write(self.slots[0], 'm_count', 21)
        for mode in ('REDRAFTING', 'ACTIVE_DRAFT_DECK'):
            self.set_mode(mode)
            final = self.view()
            self.assertEqual(final['picked_title'], '已选牌 30/30')
            self.assertFalse(self.marked(final))
            self.assertFalse(final['candidates'])

    def test_missing_scores_and_uncertain_reads(self):
        self.write(self.slots[0], 'm_count', 26)
        self.ratings.data['classes']['PRIEST'].pop('CARD_B')
        self.ratings.data['classes']['PRIEST'].pop('CARD_C')
        full = self.view()
        self.assertEqual(self.marked(full), ['CARD_A']*4)
        self.assertEqual(sum(r['rating_label']=='No rating' for r in full['picks']), 31)
        self.write(self.slots[1], 'm_count', -1)
        stale = self.view()
        self.assertTrue(stale['deck_stale'])
        self.assertEqual(stale['picked_title'], '35 cards (count unconfirmed)')
        self.assertNotIn('35/30', stale['offer_title'])
        self.assertFalse(self.marked(stale))
        self.write(self.slots[1], 'm_count', 4)
        self.assertEqual(len(self.marked(self.view())), 4)
        self.write(self.deck, 'ID', 123)
        self.assertFalse(self.marked(self.view()))

    def test_other_modes_and_conflicting_snapshots(self):
        self.write(self.slots[0], 'm_count', 26)
        self.set_mode('DRAFTING')
        self.assertFalse(self.marked(self.view()))
        self.set_mode('REDRAFTING')
        self.assertEqual(len(self.marked(self.view())), 5)
        self.write(self.slots[1], 'm_count', 3)
        self.write(self.slots[2], 'm_count', 5)
        self.assertFalse(self.marked(self.view()))  # A copy appeared while cutting.

    def test_active_mode_can_precede_or_follow_the_first_full_pool(self):
        for first_mode in ('REDRAFTING','ACTIVE_DRAFT_DECK'):
            with self.subTest(first_mode=first_mode):
                self.set_mode('REDRAFTING')
                self.write(self.slots[0], 'm_count', 25)
                self.view()
                self.set_mode(first_mode)
                self.write(self.display['m_choices'], '_size', 0)
                self.write(self.slots[0], 'm_count', 26)
                self.assertEqual(self.view()['stage'], 'removal')
                self.set_mode('ACTIVE_DRAFT_DECK')
                for count in range(35,29,-1):
                    self.write(self.slots[0], 'm_count', count-9)
                    view=self.view()
                    self.assertEqual(len(view['picks']), count)
                    self.assertEqual(len(self.marked(view)), count-30)
                    self.assertFalse(view['candidates'])
                    self.assertEqual(view['memory']['snapshot_cards'], count)
                    self.assertIn('ACTIVE_DRAFT_DECK', view['memory']['last_transition'])

    def test_confirmed_pool_can_outlive_display(self):
        self.write(self.slots[0], 'm_count', 26)
        self.assertEqual(self.view()['stage'], 'removal')
        self.heap.set_static(self.display.klass, 's_instance', None)
        self.write(self.slots[0], 'm_count', 25)
        view=self.view()
        self.assertFalse(view['memory']['display_present'])
        self.assertEqual(len(self.marked(view)), 4)
        self.write(self.slots[0], 'm_count', 21)
        self.assertEqual(self.view()['count'], 30)
        self.assertTrue(self.view()['memory']['inactive'])

    def test_partial_offer_then_empty_offer_and_no_slot(self):
        self.write(self.slots[0], 'm_count', 26)
        options = self.display['m_choices']
        self.write(options, '_size', 2)
        partial = self.view()
        self.assertFalse(self.marked(partial))
        self.assertEqual(partial['picked_title'], '35 cards')
        self.assertEqual(partial['offer_title'], 'Arena · Card selection')
        self.write(options, '_size', 0)
        self.write(self.reader._manager(), 'm_currentUndergroundSlotType', 0)
        self.assertEqual(len(self.marked(self.view())), 5)
        self.write(self.slots[0], 'm_count', 21)
        self.set_mode('ACTIVE_DRAFT_DECK')
        self.assertEqual(self.view()['count'], 30)
        self.set_mode('REDRAFTING')
        self.write(options, '_size', 3)
        self.write(self.reader._manager(), 'm_currentUndergroundSlotType', 1)
        self.assertEqual(len(self.view()['candidates']), 3)
