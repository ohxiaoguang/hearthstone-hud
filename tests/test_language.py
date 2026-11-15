"""Interface language and card-language behaviour, without network or game access."""
import asyncio
import importlib.util
import json
import re
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import i18n
from engine.cards import MIN_CARDS, Cards, validate_dataset


def dataset(name='Sample', cost=1):
    return [dict(id='SAMPLE_'+str(i),dbfId=i+1,name=name+str(i),cost=cost) for i in range(MIN_CARDS)]


def localized(locale,name):
    return dict(updated=time.time(),source='HearthstoneJSON '+locale,locale=locale,
                cards=[dict(id='SAMPLE_'+str(i),dbfId=i+1,name=name+str(i),cost=1) for i in range(MIN_CARDS)])


class CatalogTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_ui_language('en')

    def test_fourteen_card_locales_and_two_interface_languages(self):
        self.assertEqual(len(i18n.CARD_LANGUAGES),14)
        self.assertEqual(len(set(i18n.CARD_CODES)),14)
        for code in ('enUS','zhCN','zhTW','deDE','esES','esMX','frFR','itIT','jaJP','koKR','plPL','ptBR','ruRU','thTH'):
            self.assertIn(code,i18n.CARD_CODES)
        self.assertEqual([code for code,_ in i18n.UI_LANGUAGES],['en','zh-CN'])
        self.assertEqual(i18n.DEFAULT_UI,'en')
        self.assertEqual(i18n.CARD_FOR_UI,{'en':'enUS','zh-CN':'zhCN'})

    def test_both_languages_cover_the_same_keys_and_placeholders(self):
        en,zh=i18n.MESSAGES['en'],i18n.MESSAGES['zh-CN']
        self.assertEqual(set(en),set(zh))
        self.assertTrue(all(isinstance(v,str) and v.strip() for v in en.values()))
        self.assertTrue(all(isinstance(v,str) and v.strip() for v in zh.values()))
        for key in en:
            self.assertEqual(set(re.findall(r'\{(\w+)\}',en[key])),set(re.findall(r'\{(\w+)\}',zh[key])),key)

    def test_default_is_english_and_unknown_values_fall_back(self):
        self.assertEqual(i18n.t('arena.picked',count=3),'Selected 3/30')
        self.assertEqual(i18n.class_label('MAGE'),'Mage')
        self.assertEqual(i18n.set_ui_language('zh-CN'),'zh-CN')
        self.assertEqual(i18n.t('arena.picked',count=3),'已选牌 3/30')
        self.assertEqual(i18n.class_label('MAGE'),'法师')
        self.assertEqual(i18n.set_ui_language('frFR'),'en')     # an interface language cannot be a card locale
        self.assertEqual(i18n.t('arena.picked',count=3),'Selected 3/30')
        self.assertEqual(i18n.t('missing.key'),'missing.key')
        self.assertEqual(i18n.class_label('NOT_A_CLASS'),'Class not identified')

    def test_card_locale_resolution(self):
        self.assertEqual(i18n.card_language('auto','en'),'enUS')
        self.assertEqual(i18n.card_language('auto','zh-CN'),'zhCN')
        self.assertEqual(i18n.card_language('jaJP','zh-CN'),'jaJP')   # explicit wins
        self.assertEqual(i18n.card_language('nonsense','zh-CN'),'zhCN')
        self.assertEqual(i18n.card_language_name('jaJP','en'),'Japanese')
        self.assertEqual(i18n.card_language_name('jaJP','zh-CN'),'日本語')


class CardLanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);i18n.set_ui_language('en')

    def tearDown(self):
        i18n.set_ui_language('en')

    def download(self,cards,locale,name):
        """Serve one locale through the real validation and commit path."""
        def fake(url,limit,verify=True):
            self.assertIn('/'+locale+'/',url)
            return json.dumps(dataset(name)).encode()
        with patch('engine.cards.fetch',side_effect=fake):
            cards.apply(cards.refresh())

    def test_default_language_follows_the_interface(self):
        self.assertEqual(Cards(self.root/'cache').language,'enUS')
        i18n.set_ui_language('zh-CN')
        self.assertEqual(Cards(self.root/'cache2').language,'zhCN')

    def test_each_language_gets_its_own_cache_file(self):
        folder=self.root/'cache';cards=Cards(folder)
        self.download(cards,'enUS','Card')
        self.assertEqual(json.loads((folder/'cards-enUS.json').read_text())['locale'],'enUS')
        self.assertEqual(cards.info('SAMPLE_1')['name'],'Card1')
        self.assertEqual(cards.diagnostic()['cached_languages'],['enUS'])
        cards.set_language('zhCN')
        self.assertTrue(cards.need_download);self.assertEqual(cards.data_language,'enUS')
        self.assertEqual(cards.info('SAMPLE_1')['name'],'Card1')   # names stay until the new file lands
        self.download(cards,'zhCN','卡牌')
        self.assertEqual(cards.info('SAMPLE_1')['name'],'卡牌1')
        self.assertEqual(cards.diagnostic()['cached_languages'],['enUS','zhCN'])
        self.assertEqual(cards.data_language,'zhCN');self.assertFalse(cards.need_download)

    def test_switching_back_reuses_the_cache_without_downloading(self):
        folder=self.root/'cache';cards=Cards(folder)
        self.download(cards,'enUS','Card')
        cards.set_language('zhCN');self.download(cards,'zhCN','卡牌')
        calls=[]
        with patch('engine.cards.fetch',side_effect=lambda *a,**k:calls.append(a[0]) or b'[]'):
            self.assertTrue(cards.set_language('enUS'))
            self.assertEqual(calls,[])                              # cache hit, no network at all
        self.assertEqual(cards.info('SAMPLE_1')['name'],'Card1')
        self.assertFalse(cards.set_language('enUS'))                # already active: no work
        self.assertFalse(cards.need_download)

    def test_unsupported_card_language_is_rejected(self):
        cards=Cards(self.root/'cache')
        with self.assertRaises(ValueError):cards.set_language('xxXX')
        with self.assertRaises(ValueError):cards.set_language('en')   # an interface code is not a card locale

    def test_clear_cache_removes_every_language(self):
        folder=self.root/'cache';cards=Cards(folder)
        self.download(cards,'enUS','Card')
        cards.set_language('zhCN');self.download(cards,'zhCN','卡牌')
        (folder/'cards.json').write_text('{}')
        cards.clear_cache()
        self.assertEqual(sorted(p.name for p in folder.glob('cards*.json')),[])
        self.assertEqual(cards.cached_languages(),[])
        self.assertTrue((folder/'images').is_dir())                 # art lives outside the per-language caches

    def test_import_supports_the_active_language_only(self):
        cards=Cards(self.root/'cache')
        good=self.root/'zhCN-cards.json';good.write_text(json.dumps(localized('enUS','Card')))
        cards.apply(cards.import_file(good))
        self.assertEqual(cards.info('SAMPLE_1')['name'],'Card1')
        other=self.root/'de-cards.json';other.write_text(json.dumps(localized('deDE','Karte')))
        with self.assertRaises(ValueError):cards.import_file(other)
        self.assertEqual(cards.info('SAMPLE_1')['name'],'Card1')    # rejected import changed nothing

    def test_a_legacy_cache_file_is_adopted_once(self):
        folder=self.root/'cache';folder.mkdir(parents=True)
        (folder/'cards.json').write_text(json.dumps(dict(updated=10,cards=dataset('旧'))))
        cards=Cards(folder)
        self.assertEqual(cards.info('SAMPLE_1')['name'],'旧1')
        self.assertEqual(cards.updated,10)
        self.assertFalse(cards.need_download)

    def test_validate_dataset_reports_english_errors_by_default(self):
        with self.assertRaises(ValueError) as caught:validate_dataset('nope')
        self.assertIn('array',str(caught.exception))
        i18n.set_ui_language('zh-CN')
        with self.assertRaises(ValueError) as caught:validate_dataset('nope')
        self.assertIn('数组',str(caught.exception))


class PluginLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        def unavailable(cards):
            cards.attempted=time.time();cards._phase('failed')
            return None
        self.refresh_patch=patch('engine.cards.Cards.refresh',unavailable);self.refresh_patch.start()
        self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name)
        self.old=sys.modules.get('decky')
        sys.modules['decky']=types.SimpleNamespace(DECKY_PLUGIN_SETTINGS_DIR=base/'settings',DECKY_PLUGIN_RUNTIME_DIR=base/'runtime')
        spec=importlib.util.spec_from_file_location('hud_lang',Path(__file__).resolve().parents[1]/'main.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.plugin=module.Plugin();await self.plugin._main()
        await asyncio.sleep(.3)   # the publish loop writes the first state.json

    async def asyncTearDown(self):
        await self.plugin._unload()
        if self.old is None:sys.modules.pop('decky',None)
        else:sys.modules['decky']=self.old
        self.tmp.cleanup();self.refresh_patch.stop();i18n.set_ui_language('en')

    def state(self):
        return json.loads((self.plugin.runtime/'state.json').read_text())

    async def test_defaults_are_english_and_card_locale_follows_it(self):
        status=await self.plugin.status()
        self.assertEqual(status['settings']['ui_language'],'en')
        self.assertEqual(status['settings']['card_language'],'auto')
        self.assertEqual(self.plugin.cards.language,'enUS')
        self.assertEqual(status['match_status'],'No match identified yet')
        state=self.state()
        self.assertEqual(state['labels']['arena_card'],'Arena · Card selection')
        self.assertEqual(state['arena_state']['picked_title'],'Selected 0/30')

    async def test_interface_language_switches_every_surface(self):
        await self.plugin.configure({'ui_language':'zh-CN'})
        state=self.state()
        self.assertEqual(state['labels']['arena_card'],'竞技场 · 卡牌选择')
        self.assertEqual(state['arena_state']['picked_title'],'已选牌 0/30')
        self.assertEqual(self.plugin.cards.language,'zhCN')          # 'auto' follows the interface
        status=await self.plugin.status()
        self.assertEqual(status['match_status'],'尚未识别对局')
        self.assertIn('竞技场',json.dumps(status['arena'],ensure_ascii=False))

    async def test_card_language_can_differ_from_the_interface(self):
        await self.plugin.configure({'ui_language':'zh-CN','card_language':'jaJP'})
        self.assertEqual(self.plugin.cards.language,'jaJP')
        self.assertEqual(self.state()['labels']['arena_card'],'竞技场 · 卡牌选择')
        await self.plugin.configure({'card_language':'auto'})
        self.assertEqual(self.plugin.cards.language,'zhCN')
        await self.plugin.configure({'ui_language':'en'})
        self.assertEqual(self.plugin.cards.language,'enUS')

    async def test_unknown_languages_are_rejected(self):
        with self.assertRaises(ValueError):await self.plugin.configure({'ui_language':'deDE'})
        with self.assertRaises(ValueError):await self.plugin.configure({'card_language':'xxXX'})
        with self.assertRaises(ValueError):await self.plugin.configure({'ui_language':1})
        self.assertEqual(self.plugin.settings['ui_language'],'en')

    async def test_settings_survive_a_reload_and_old_flag_is_migrated(self):
        await self.plugin.configure({'ui_language':'zh-CN','card_language':'frFR'})
        settings=json.loads((self.plugin.settings_dir/'settings.json').read_text())
        self.assertEqual((settings['ui_language'],settings['card_language']),('zh-CN','frFR'))
        saved=dict(settings);saved.pop('show_card_names',None);saved['chinese_names']=False
        (self.plugin.settings_dir/'settings.json').write_text(json.dumps(saved))
        await self.plugin._unload()
        spec=importlib.util.spec_from_file_location('hud_lang2',Path(__file__).resolve().parents[1]/'main.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        reloaded=module.Plugin();await reloaded._main()
        try:
            self.assertEqual(reloaded.settings['ui_language'],'zh-CN')
            self.assertEqual(reloaded.settings['card_language'],'frFR')
            self.assertFalse(reloaded.settings['show_card_names'])
            self.assertNotIn('chinese_names',reloaded.settings)
            self.assertEqual(reloaded.cards.language,'frFR')
        finally:await reloaded._unload()
