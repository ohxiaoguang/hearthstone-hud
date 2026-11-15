"""HearthstoneJSON card metadata in any of its fourteen locales, plus a bounded
asynchronous image cache.

Metadata approach follows hs-decktracker-linux/cards.py (MIT). Network work runs
in a worker thread, never in log parsing or the OpenGL loop.

Each locale keeps its own cache file (`cards-<locale>.json`) so switching
languages never re-downloads data that is already on disk. Card art is language
independent and stays in one shared directory.
"""
import asyncio
from collections import deque
import queue
import json
import re
import shutil
import ssl
import threading
import time
import urllib.request
from pathlib import Path
from . import i18n
from .io import atomic_json
from .tls import verified_context, diagnostic as tls_diagnostic
from .images import TileStore, valid_id, validate_png, atomic_image, MAX_IMAGE

DATA_URL='https://api.hearthstonejson.com/v1/latest/{locale}/cards.json'
IMAGE_URL='https://art.hearthstonejson.com/v1/tiles/{card_id}.png'
FIELDS=('id','dbfId','name','cost','cardClass','type')
LEGACY_CACHE='cards.json'


def fetch(url, limit, verify=True):
    if verify:
        context=verified_context()
    else:
        # Explicit image-only testing option. Never modifies the verified context.
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname=False
        context.verify_mode=ssl.CERT_NONE
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Hearthstone-HUD'}),timeout=12,context=context) as r:
        data=r.read(limit+1)
        if len(data)>limit:raise ValueError(i18n.t('cards.size_limit'))
        return data


MIN_CARDS=100
MAX_JSON=64*1024*1024


def validate_dataset(data):
    if not isinstance(data,list):
        raise ValueError(i18n.t('cards.import_shape'))
    rows=[];seen=set()
    for c in data:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_]+',c['id']):
            raise ValueError(i18n.t('cards.import_card_id'))
        if c['id'] in seen:raise ValueError(i18n.t('cards.import_duplicate'))
        seen.add(c['id'])
        if not isinstance(c.get('dbfId'),int) or isinstance(c['dbfId'],bool) or c['dbfId']<=0:
            continue
        if not isinstance(c.get('name'),str) or not c['name'].strip() or len(c['name'])>512:
            continue
        if c.get('cost') is not None and (not isinstance(c['cost'],int) or isinstance(c['cost'],bool)):
            raise ValueError(i18n.t('cards.import_cost'))
        rows.append({k:c[k] for k in FIELDS if k in c})
    if len(rows)<MIN_CARDS:raise ValueError(i18n.t('cards.import_min',min=MIN_CARDS))
    return rows


class Cards:
    def __init__(self, directory, language=None):
        self.directory=Path(directory)
        self.images=self.directory/'images'
        self.images.mkdir(parents=True,exist_ok=True)
        self.tiles=TileStore(self.images)
        self.image_batch=dict(status='idle',total=0,success=0,failed=0,skipped=0)
        self.batch_remaining=set();self.image_errors=deque(maxlen=10)
        self.image_totals=dict(success=0,failed=0,skipped=0)
        self.image_verify_tls=True
        self.database_verify_tls=True
        self.import_result=None
        self.by_id={};self.by_dbf={};self.updated=0;self.error=''
        self.language=i18n.card_language(language,None) if language else i18n.card_language('auto',i18n.ui_language())
        self.data_language=''
        self.need_download=False
        self.download_state=i18n.t('cards.download_idle');self.download_phase='idle'
        self.source=i18n.t('cards.source',locale=self.language)
        self.generation=0;self.cache_lock=threading.Lock();self.image_error=''
        self.attempted=0;self.image_attempts={};self.queue=queue.Queue(maxsize=128);self.pending=set()
        self._load_cached(self.language)

    # -- cache files -------------------------------------------------------
    def cache_path(self,locale=None):
        return self.directory/('cards-%s.json'%(locale or self.language))

    def cached_languages(self):
        found=[]
        for code in i18n.CARD_CODES:
            if self.cache_path(code).exists():found.append(code)
        return found

    def _phase(self,phase,**values):
        """Set the structured download phase and its translated label together."""
        self.download_phase=phase
        keys=dict(idle='cards.download_idle',prepare='cards.download_prepare',running='cards.download_running',
                  ok='cards.download_ok',skipped='cards.download_skipped',failed='cards.download_failed')
        self.download_state=i18n.t(keys[phase],**values)

    def _read_cache(self,path):
        data=json.loads(path.read_text())
        rows=validate_dataset(data['cards'])
        return rows,float(data['updated']),data.get('source','')

    def _load_cached(self,locale):
        """Load this locale's cache. Returns True when rows were installed."""
        path=self.cache_path(locale)
        try:
            rows,updated,source=self._read_cache(path)
        except (OSError,ValueError,KeyError,TypeError):
            rows=None
        found=locale
        if rows is None and (self.directory/LEGACY_CACHE).exists():
            # Older builds wrote one language-neutral file name; adopt it once so
            # an upgrade never blanks the card names.
            try:
                rows,updated,source=self._read_cache(self.directory/LEGACY_CACHE)
                try:found=json.loads((self.directory/LEGACY_CACHE).read_text()).get('locale') or locale
                except (OSError,ValueError,TypeError):found=locale
            except (OSError,ValueError,KeyError,TypeError):rows=None
        if rows is None:
            # Nothing on disk for this locale. An empty database is already
            # handled by the worker's staleness check, so only flag an explicit
            # switch away from data we do have.
            self.need_download=bool(self.by_id)
            self._phase('prepare')
            return False
        self.install(rows);self.updated=updated;self.data_language=found
        self.source=source or i18n.t('cards.source',locale=found)
        self.need_download=found!=locale;self.download_phase='ok'
        return True

    def set_language(self,locale):
        """Switch the card database locale, reusing any cache already on disk.

        A switch invalidates downloads that are still in flight: bumping the
        generation makes their commit fail, and `_commit` additionally refuses to
        write for a locale that is no longer selected. The pending download flag
        and the retry timer are reset so the new locale is fetched immediately
        instead of inheriting the previous locale's bookkeeping.
        """
        if locale not in i18n.CARD_CODES:
            raise ValueError('unsupported card language: %s'%locale)
        if locale==self.language and (self.by_id or not self.need_download):return False
        with self.cache_lock:
            self.generation+=1          # Discard results of the previous locale.
            self.language=locale
            self.error=''
            self.attempted=0            # The new locale is due right away.
            self.need_download=True     # Cleared by `_load_cached` on a cache hit.
        if self._load_cached(locale):
            self._phase('ok')
            return True
        # Cache miss: `_load_cached` only flags a switch away from data we already
        # have, so make the pending download explicit here.
        self.need_download=True
        # Keep the previously loaded names visible until the new file arrives;
        # `data_language` records that they belong to another locale.
        self._phase('prepare')
        return True

    # -- metadata ----------------------------------------------------------
    def install(self, data):
        if not isinstance(data,list):raise ValueError(i18n.t('cards.import_shape'))
        rows=[{k:c[k] for k in FIELDS if k in c} for c in data if isinstance(c,dict) and isinstance(c.get('id'),str)]
        self.by_id={c['id']:c for c in rows}
        self.by_dbf={c['dbfId']:c['id'] for c in rows if isinstance(c.get('dbfId'),int)}
        # Rows are installed for whatever language they came from; callers that
        # know better (`_load_cached`) may still request a download afterwards.
        if rows:self.need_download=False

    def id_for_dbf(self,dbf):
        return self.by_dbf.get(dbf,'dbf:'+str(dbf))

    def image_path(self,cid):
        if not valid_id(cid):return None
        p=self.images/(cid+'.png')
        return p

    def info(self,cid):
        card=self.by_id.get(cid,{})
        image=self.tiles.path(cid)
        return dict(id=cid,name=card.get('name') if isinstance(card.get('name'),str) else cid or i18n.t('cards.unknown'),
                    cost=card.get('cost') if isinstance(card.get('cost'),int) else None,image=str(image) if image and image.exists() else '')

    # -- images ------------------------------------------------------------
    def request_images(self,ids):
        for cid in ids:
            if not valid_id(cid) or self.tiles.path(cid) or cid in self.pending or (cid not in self.batch_remaining and time.time()-self.image_attempts.get(cid,0)<3600):
                continue
            if self.queue.full():break
            self.pending.add(cid);self.queue.put_nowait(cid)

    def begin_image_download(self,ids):
        if self.batch_remaining:return dict(self.image_batch)
        unique=set(ids)
        self.image_batch=dict(status='running',total=len(unique),success=0,failed=0,skipped=0)
        self.batch_remaining=set()
        for cid in unique:
            if not valid_id(cid) or self.tiles.path(cid):self.image_batch['skipped']+=1
            else:self.batch_remaining.add(cid)
        self.request_images(sorted(self.batch_remaining))
        if not self.batch_remaining:self.image_batch['status']='complete'
        return dict(self.image_batch)

    def import_images(self,path):
        self.import_result=self.tiles.import_zip(path)
        return self.import_result

    # -- download and import ------------------------------------------------
    def _commit(self,rows,source,expected=None,locale=None):
        """Persist rows for `locale`, never for a locale the user has left."""
        locale=locale or self.language
        with self.cache_lock:
            if locale!=self.language:
                return None  # The user switched languages while this ran.
            if expected is not None and expected!=self.generation:
                return None  # A manual import/newer refresh won the race.
            updated=time.time()
            atomic_json(self.cache_path(locale),dict(updated=updated,source=source,locale=locale,cards=rows))
            self.generation+=1
            return dict(rows=rows,updated=updated,source=source,locale=locale,generation=self.generation)

    def apply(self,record):
        """Install a finished download only if it still describes this locale."""
        with self.cache_lock:
            if not record or record.get('locale')!=self.language or record['generation']!=self.generation:
                return False
            self.install(record['rows']);self.updated=record['updated'];self.source=record['source']
            self.data_language=record.get('locale',self.language);self.need_download=False;self.error=''
            return True

    def import_file(self,path):
        path=Path(path).expanduser()
        if not path.is_absolute():raise ValueError(i18n.t('cards.import_path'))
        with path.open('rb') as f:data=f.read(MAX_JSON+1)
        if len(data)>MAX_JSON:raise ValueError(i18n.t('cards.import_size'))
        value=json.loads(data)
        locale=self.language
        if isinstance(value,dict):
            locale=value.get('locale') or locale
            if locale!=self.language:
                raise ValueError(i18n.t('cards.import_locale',found=locale,wanted=self.language))
            value=value.get('cards')
        rows=validate_dataset(value)
        return self._commit(rows,i18n.t('cards.source_import',locale=locale,name=path.name),locale=locale)

    def refresh(self):
        """Download one locale. Progress and errors never leak into another one."""
        locale=self.language;expected=self.generation
        current=lambda:locale==self.language
        if current():self.attempted=time.time()
        for attempt in range(2):
            if current():self._phase('running',attempt=attempt+1)
            try:
                rows=validate_dataset(json.loads(fetch(DATA_URL.format(locale=locale),MAX_JSON,verify=self.database_verify_tls)))
                record=self._commit(rows,i18n.t('cards.source',locale=locale),expected,locale=locale)
                if current():self._phase('ok' if record else 'skipped')
                return record
            except (OSError,ValueError,TypeError) as exc:
                if current():self.error=str(exc)
                if attempt==0:time.sleep(1)
        if current():self._phase('failed')
        return None

    def download_image(self,cid):
        p=self.image_path(cid)
        if p is None:raise ValueError('invalid Card ID')
        data=fetch(IMAGE_URL.format(card_id=cid),MAX_IMAGE,verify=self.image_verify_tls)
        validate_png(data)
        atomic_image(p,data)
        self.prune_images()

    def prune_images(self):
        # Flat automatic cache only. Never traverse/delete images/manual/.
        files=sorted(self.images.glob('*.png'),key=lambda f:f.stat().st_mtime,reverse=True)
        size=0
        for i,f in enumerate(files):
            size+=f.stat().st_size
            if i>=256 or size>32*1024*1024:f.unlink(missing_ok=True)

    def clear_cache(self):
        """Called after the media worker drains; delete only plugin-owned caches."""
        with self.cache_lock:
            self.generation+=1  # Discard any obsolete refresh/import result.
            for path in self.directory.glob('cards*.json'):
                path.unlink(missing_ok=True)
            if self.images.is_symlink():
                self.images.unlink()
            elif self.images.exists():
                shutil.rmtree(self.images)  # Does not follow links inside this tree.
            self.images.mkdir(parents=True,exist_ok=True)
            self.tiles=TileStore(self.images)
            self.by_id={};self.by_dbf={};self.updated=0;self.attempted=0
            self.error='';self.image_error='';self.data_language=''
            self.source=i18n.t('cards.source',locale=self.language)
            self._phase('prepare')
            self.need_download=True
            self.image_attempts.clear();self.pending.clear();self.queue=queue.Queue(maxsize=128)
            self.batch_remaining.clear();self.image_errors.clear();self.import_result=None
            self.image_batch=dict(status='idle',total=0,success=0,failed=0,skipped=0)
            self.image_totals=dict(success=0,failed=0,skipped=0)

    async def worker(self, stop=None, run_io=asyncio.to_thread):
        # Cooperative shutdown waits for in-flight thread I/O before cache deletion.
        while stop is None or not stop.is_set():
            now=time.time();quiet=self.queue.empty() and not self.batch_remaining
            # 7-day refresh of what we already have, or an explicit language whose
            # cache is missing. Both keep the original retry spacing (one attempt
            # per minute without data, per hour with data) so a failing network
            # cannot turn the loop into a request storm.
            retry=60 if not self.by_id else 3600
            stale=(not self.by_id or quiet) and now-self.updated>7*86400 and now-self.attempted>retry
            switching=self.need_download and now-self.attempted>retry
            if stale or switching:
                record=await run_io(self.refresh)
                self.apply(record)
            if stop is not None and stop.is_set():break
            try:
                cid=self.queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(.2)
                continue
            self.image_attempts[cid]=time.time()
            if len(self.image_attempts)>1024:
                self.image_attempts.pop(next(iter(self.image_attempts)))
            outcome='success'
            try:
                if self.tiles.path(cid):outcome='skipped'
                else:await run_io(self.download_image,cid)
            except (OSError,ValueError) as exc:
                outcome='failed';self.image_error=str(exc)[:300]
                self.image_errors.append(cid+': '+self.image_error)
            finally:
                self.image_totals[outcome]+=1
                if cid in self.batch_remaining:
                    self.batch_remaining.discard(cid);self.image_batch[outcome]+=1
                    if not self.batch_remaining:self.image_batch['status']='complete'
                self.pending.discard(cid);self.queue.task_done()
                self.request_images(sorted(self.batch_remaining))

    def diagnostic(self):
        return dict(database_tls_verify=self.database_verify_tls,image_tls_verify=self.image_verify_tls,tls=tls_diagnostic(),
                    source=self.source,language=self.language,language_name=i18n.card_language_name(self.language),
                    data_language=self.data_language,cached_languages=self.cached_languages(),
                    updated=self.updated,count=len(self.by_id),error=self.error,
                    state=i18n.t('cards.state_ready') if self.by_id else i18n.t('cards.state_missing'),
                    download_state=self.download_state,download_phase=self.download_phase,
                    image_error=self.image_error,images_pending=len(self.pending),image_cache=self.tiles.counts(),
                    image_batch=dict(self.image_batch),image_totals=dict(self.image_totals),image_import=self.import_result,
                    image_errors=list(self.image_errors))
