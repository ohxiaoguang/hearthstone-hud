"""Interface language and card-language behaviour, without network or game access."""
import asyncio
import importlib.util
import json
import re
import sys
import tempfile
import threading
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
        self.assertNotIn('card_language',status['settings'])   # the card database follows the UI
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

    async def test_card_database_follows_the_interface_language(self):
        await self.plugin.configure({'ui_language':'zh-CN'})
        self.assertEqual(self.plugin.cards.language,'zhCN')
        self.assertEqual(self.state()['labels']['arena_card'],'竞技场 · 卡牌选择')
        await self.plugin.configure({'ui_language':'en'})
        self.assertEqual(self.plugin.cards.language,'enUS')
        self.assertEqual([d['code'] for d in self.plugin.cards.diagnostic()['databases'].values()],['enUS','zhCN'])
        # The engine still knows every HearthstoneJSON locale for later expansion.
        self.assertEqual(len(i18n.CARD_CODES),14)

    async def test_unknown_languages_are_rejected(self):
        with self.assertRaises(ValueError):await self.plugin.configure({'ui_language':'deDE'})
        with self.assertRaises(ValueError):await self.plugin.configure({'ui_language':1})
        # The retired per-database setting is not accepted any more.
        with self.assertRaises(ValueError):await self.plugin.configure({'card_language':'jaJP'})
        self.assertEqual(self.plugin.settings['ui_language'],'en')

    async def test_settings_survive_a_reload_and_old_keys_are_migrated(self):
        await self.plugin.configure({'ui_language':'zh-CN'})
        settings=json.loads((self.plugin.settings_dir/'settings.json').read_text())
        self.assertEqual(settings['ui_language'],'zh-CN')
        saved=dict(settings);saved.pop('show_card_names',None)
        saved['chinese_names']=False
        saved['card_language']='frFR'      # written by an older version
        (self.plugin.settings_dir/'settings.json').write_text(json.dumps(saved))
        await self.plugin._unload()
        spec=importlib.util.spec_from_file_location('hud_lang2',Path(__file__).resolve().parents[1]/'main.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        reloaded=module.Plugin();await reloaded._main()
        try:
            self.assertEqual(reloaded.settings['ui_language'],'zh-CN')
            self.assertFalse(reloaded.settings['show_card_names'])
            self.assertNotIn('chinese_names',reloaded.settings)
            self.assertNotIn('card_language',reloaded.settings)   # dropped, not honoured
            self.assertEqual(reloaded.cards.language,'zhCN')
        finally:await reloaded._unload()


class LanguageSwitchRaceTests(unittest.IsolatedAsyncioTestCase):
    """Real async ordering: a download is in flight while the user switches."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'cache'
        i18n.set_ui_language('en')

    def tearDown(self):
        i18n.set_ui_language('en')

    def names(self,locale,prefix):return dataset(prefix)

    def run_worker(self,cards,fake):
        """Start the real worker with a controllable fetch and return (stop, task)."""
        stop=asyncio.Event()
        patcher=patch('engine.cards.fetch',side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        task=asyncio.create_task(cards.worker(stop))
        self.addCleanup(lambda:stop.set())
        return stop,task

    async def test_switch_during_download_never_installs_the_old_language(self):
        cards=Cards(self.folder)
        self.assertEqual(cards.language,'enUS')
        first=threading.Event();seen=threading.Event()
        def fake(url,limit,verify=True):
            seen.set()
            if '/enUS/' in url:first.wait(5)
            else:time.sleep(.05)
            if '/enUS/' in url:return json.dumps(dataset('English')).encode()
            return json.dumps(dataset('日本語')).encode()
        stop,task=self.run_worker(cards,fake)
        try:
            self.assertTrue(await asyncio.to_thread(seen.wait,5))
            for _ in range(100):
                if cards.download_phase=='running':break
                await asyncio.sleep(.02)
            self.assertEqual(cards.download_phase,'running')
            cards.set_language('jaJP')                     # the user switches mid-download
            self.assertEqual(cards.language,'jaJP')
            self.assertTrue(cards.need_download)
            first.set()                                    # the enUS payload arrives late
            for _ in range(200):
                if (self.folder/'cards-jaJP.json').exists():break
                await asyncio.sleep(.02)
        finally:
            stop.set();await task
        self.assertEqual(cards.language,'jaJP')
        self.assertFalse((self.folder/'cards-enUS.json').exists())   # stale payload never written
        self.assertTrue((self.folder/'cards-jaJP.json').exists())
        self.assertEqual(cards.data_language,'jaJP')
        self.assertEqual(cards.info('SAMPLE_1')['name'],'日本語1')
        self.assertFalse(cards.need_download)
        self.assertEqual(cards.download_phase,'ok')

    async def test_a_late_old_payload_cannot_clear_the_new_pending_state(self):
        cards=Cards(self.folder)
        first=threading.Event();seen=threading.Event()
        started_new=threading.Event();release_new=threading.Event()
        def fake(url,limit,verify=True):
            if '/enUS/' in url:
                seen.set();first.wait(5)
                raise OSError('the old download failed after the switch')
            started_new.set();release_new.wait(5)
            return json.dumps(dataset('日本語')).encode()
        stop,task=self.run_worker(cards,fake)
        try:
            self.assertTrue(await asyncio.to_thread(seen.wait,5))
            cards.set_language('jaJP')
            first.set()                                    # old request finishes (with an error)
            for _ in range(200):
                if started_new.is_set():break              # the jaJP download is in flight
                await asyncio.sleep(.02)
            self.assertTrue(started_new.is_set())
            self.assertTrue(cards.need_download)           # still pending for jaJP
            self.assertNotEqual(cards.download_phase,'ok')
            self.assertEqual(cards.error,'')               # the old error did not leak
            self.assertEqual(cards.data_language,'')       # nothing installed from enUS
            release_new.set()
            for _ in range(200):
                if (self.folder/'cards-jaJP.json').exists():break
                await asyncio.sleep(.02)
        finally:
            stop.set();await task
        self.assertEqual(cards.download_phase,'ok')
        self.assertFalse(cards.need_download)

    async def test_rapid_switching_applies_only_the_last_language(self):
        cards=Cards(self.folder)
        gate=threading.Event();seen=threading.Event()
        def fake(url,limit,verify=True):
            seen.set();gate.wait(5)
            if '/deDE/' in url:return json.dumps(dataset('Deutsch')).encode()
            return json.dumps(dataset('Wrong')).encode()
        stop,task=self.run_worker(cards,fake)
        try:
            self.assertTrue(await asyncio.to_thread(seen.wait,5))   # enUS download in flight
            for locale in ('jaJP','koKR','deDE'):
                cards.set_language(locale)
            gate.set()
            for _ in range(200):
                if (self.folder/'cards-deDE.json').exists():break
                await asyncio.sleep(.02)
        finally:
            stop.set();await task
        self.assertEqual(cards.language,'deDE')
        self.assertEqual(cards.data_language,'deDE')
        self.assertEqual(cards.info('SAMPLE_1')['name'],'Deutsch1')
        self.assertEqual([p.name for p in sorted(self.folder.glob('cards-*.json'))],['cards-deDE.json'])

    def test_apply_rejects_another_locale_or_a_stale_generation(self):
        cards=Cards(self.folder);cards.install(dataset('English'))
        rows=dataset('日本語')
        self.assertFalse(cards.apply(dict(rows=rows,updated=1,source='x',locale='jaJP',generation=cards.generation)))
        self.assertEqual(cards.info('SAMPLE_1')['name'],'English1')   # nothing installed
        self.assertFalse(cards.apply(dict(rows=rows,updated=1,source='x',locale='enUS',generation=cards.generation+5)))
        self.assertEqual(cards.info('SAMPLE_1')['name'],'English1')
        cards.set_language('jaJP')
        self.assertFalse(cards.apply(dict(rows=rows,updated=1,source='x',locale='enUS',generation=cards.generation)))
        self.assertEqual(cards.info('SAMPLE_1')['name'],'English1')

    def test_commit_refuses_a_locale_the_user_has_left(self):
        cards=Cards(self.folder)
        cards.set_language('jaJP')
        generation=cards.generation
        self.assertIsNone(cards._commit(dataset('English'),'late enUS download',generation,locale='enUS'))
        self.assertFalse((self.folder/'cards-enUS.json').exists())
        record=cards._commit(dataset('日本語'),'jaJP download',generation,locale='jaJP')
        self.assertTrue(record and record['locale']=='jaJP')
        self.assertTrue((self.folder/'cards-jaJP.json').exists())


class VisibleTextTests(unittest.IsolatedAsyncioTestCase):
    """Everything the HUD or the settings panel renders follows the interface language."""

    CJK=re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]')

    async def asyncSetUp(self):
        def unavailable(cards):
            cards.attempted=time.time();cards._phase('failed')
            return None
        self.refresh_patch=patch('engine.cards.Cards.refresh',unavailable);self.refresh_patch.start()
        self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name)
        self.old=sys.modules.get('decky')
        sys.modules['decky']=types.SimpleNamespace(DECKY_PLUGIN_SETTINGS_DIR=base/'settings',DECKY_PLUGIN_RUNTIME_DIR=base/'runtime')
        spec=importlib.util.spec_from_file_location('hud_text',Path(__file__).resolve().parents[1]/'main.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.plugin=module.Plugin();await self.plugin._main()
        self.plugin.cards.install([dict(id='CARD_A',dbfId=1,name='Alpha',cost=1,type='MINION'),
                                   dict(id='CARD_B',dbfId=2,name='Beta',cost=2,type='MINION')])
        await asyncio.sleep(.3)

    async def asyncTearDown(self):
        await self.plugin._unload()
        if self.old is None:sys.modules.pop('decky',None)
        else:sys.modules['decky']=self.old
        self.tmp.cleanup();self.refresh_patch.stop();i18n.set_ui_language('en')

    def state(self):
        return json.loads((self.plugin.runtime/'state.json').read_text())

    async def test_english_ui_contains_no_chinese(self):
        state=self.state()
        self.assertEqual(state['labels']['deck_original'],'Original deck')
        self.assertEqual(state['labels']['deck_added'],'Added / transformed · currently in deck')
        self.assertEqual(state['labels']['arena_card'],'Arena · Card selection')
        self.assertEqual(state['labels']['empty_own'],'No remaining cards or waiting for log evidence')
        status=await self.plugin.status()
        visible=[state['labels'],state['tracking'],state['arena_state'],state.get('settings',{}),
                 status['error'],status['match_status'],status['identity_status'],status['deck_status'],
                 status['decks_log_status'],status['arena_log_status'],status['log_status'],
                 status['cards']['download_state'],status['cards']['state']]
        chinese=[value for value in visible if self.CJK.search(json.dumps(value,ensure_ascii=False))]
        self.assertEqual(chinese,[])   # nothing user visible is Chinese in English mode

    async def test_chinese_ui_translates_the_same_surfaces(self):
        await self.plugin.configure({'ui_language':'zh-CN'})
        state=self.state()
        self.assertEqual(state['labels']['deck_original'],'原始牌库')
        self.assertEqual(state['labels']['deck_added'],'后加入 / 变形 · 当前在库')
        self.assertEqual(state['labels']['arena_card'],'竞技场 · 卡牌选择')
        self.assertEqual(state['arena_state']['picked_title'],'已选牌 0/30')
        status=await self.plugin.status()
        self.assertEqual(status['match_status'],'尚未识别对局')
        for value in (state['labels'],state['tracking'],state['arena_state'],status['match_status'],status['log_status']):
            self.assertTrue(self.CJK.search(json.dumps(value,ensure_ascii=False)))

    async def test_errors_follow_the_interface_language(self):
        with self.assertRaises(ValueError) as raised:
            await self.plugin.configure({'font_size':999})
        self.assertIn('out of range',str(raised.exception))
        await self.plugin.configure({'ui_language':'zh-CN'})
        with self.assertRaises(ValueError) as raised:
            await self.plugin.configure({'font_size':999})
        self.assertIn('超出范围',str(raised.exception))
        with self.assertRaises(ValueError) as raised:
            await self.plugin.configure({'nope':1})
        self.assertIn('未知配置项',str(raised.exception))

    async def test_switch_is_immediate_and_survives_a_reload(self):
        await self.plugin.configure({'ui_language':'zh-CN'})
        self.assertIn('已选牌',self.state()['arena_state']['picked_title'])
        await self.plugin.configure({'ui_language':'en'})
        self.assertIn('Selected',self.state()['arena_state']['picked_title'])
        await self.plugin.configure({'ui_language':'zh-CN'})
        await self.plugin._unload()
        spec=importlib.util.spec_from_file_location('hud_text2',Path(__file__).resolve().parents[1]/'main.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        reloaded=module.Plugin();await reloaded._main()
        try:
            await asyncio.sleep(.3)
            state=json.loads((reloaded.runtime/'state.json').read_text())
            self.assertEqual(state['labels']['deck_added'],'后加入 / 变形 · 当前在库')
        finally:await reloaded._unload()


class DownloadRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_failing_download_is_not_retried_in_a_tight_loop(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        cards=Cards(Path(tmp.name)/'cache')
        calls=[]
        def fake(url,limit,verify=True):
            calls.append(url);raise OSError('offline')
        stop=asyncio.Event()
        with patch('engine.cards.fetch',side_effect=fake),patch('engine.cards.time.sleep'):
            task=asyncio.create_task(cards.worker(stop))
            await asyncio.sleep(.6)
            stop.set();await task
        self.assertEqual(len(calls),2)          # one refresh = two attempts, then back off
        self.assertEqual(cards.download_phase,'failed')
