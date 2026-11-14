"""HearthstoneJSON zhCN metadata and bounded asynchronous image cache.

Metadata approach follows hs-decktracker-linux/cards.py (MIT). Network work
runs in a worker thread, never in log parsing or the OpenGL loop.
"""
import asyncio
from collections import deque
import queue
import json
import re
import shutil
import struct
import ssl
import threading
import time
import urllib.request
from pathlib import Path
from .io import atomic_json
from .tls import verified_context, diagnostic as tls_diagnostic
from .images import TileStore, valid_id, validate_png, atomic_image, MAX_IMAGE

DATA_URL='https://api.hearthstonejson.com/v1/latest/zhCN/cards.json'
IMAGE_URL='https://art.hearthstonejson.com/v1/tiles/{card_id}.png'
FIELDS=('id','dbfId','name','cost','cardClass','type')


def fetch(url, limit, verify=True):
    if verify:
        context=verified_context()
    else:
        # Explicit image-only testing option. Never modifies the verified context.
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname=False
        context.verify_mode=ssl.CERT_NONE
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Hearthstone-HUD/0.2.4'}),timeout=12,context=context) as r:
        data=r.read(limit+1)
        if len(data)>limit:raise ValueError('下载超出大小限制')
        return data


MIN_CARDS=100
MAX_JSON=64*1024*1024


def validate_dataset(data):
    if not isinstance(data,list):
        raise ValueError('卡牌 JSON 顶层必须是数组')
    rows=[];seen=set()
    for c in data:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_]+',c['id']):
            raise ValueError('卡牌记录缺少有效 ID')
        if c['id'] in seen:raise ValueError('卡牌 ID 重复')
        seen.add(c['id'])
        if not isinstance(c.get('dbfId'),int) or isinstance(c['dbfId'],bool) or c['dbfId']<=0:
            continue
        if not isinstance(c.get('name'),str) or not c['name'].strip() or len(c['name'])>512:
            continue
        if c.get('cost') is not None and (not isinstance(c['cost'],int) or isinstance(c['cost'],bool)):
            raise ValueError('卡牌法力值格式错误')
        rows.append({k:c[k] for k in FIELDS if k in c})
    if len(rows)<MIN_CARDS:raise ValueError('有效卡牌不足 %d 张，保留旧缓存'%MIN_CARDS)
    return rows


class Cards:
    def __init__(self, directory):
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
        self.by_id={};self.by_dbf={};self.updated=0;self.error='';self.source='HearthstoneJSON zhCN'
        self.generation=0;self.cache_lock=threading.Lock();self.image_error='';self.download_state='尚未尝试'
        self.attempted=0;self.image_attempts={};self.queue=queue.Queue(maxsize=128);self.pending=set()
        try:
            data=json.loads((self.directory/'cards.json').read_text())
            self.install(validate_dataset(data['cards']));self.updated=float(data['updated']);self.source=data.get('source',self.source)
        except (OSError,ValueError,KeyError,TypeError):
            pass

    def install(self, data):
        if not isinstance(data,list):raise ValueError('卡牌数据库格式错误')
        rows=[{k:c[k] for k in FIELDS if k in c} for c in data if isinstance(c,dict) and isinstance(c.get('id'),str)]
        self.by_id={c['id']:c for c in rows}
        self.by_dbf={c['dbfId']:c['id'] for c in rows if isinstance(c.get('dbfId'),int)}

    def id_for_dbf(self,dbf):
        return self.by_dbf.get(dbf,'dbf:'+str(dbf))

    def image_path(self,cid):
        if not valid_id(cid):return None
        p=self.images/(cid+'.png')
        return p

    def info(self,cid):
        card=self.by_id.get(cid,{})
        image=self.tiles.path(cid)
        return dict(id=cid,name=card.get('name') if isinstance(card.get('name'),str) else cid or '未知卡牌',cost=card.get('cost') if isinstance(card.get('cost'),int) else None,image=str(image) if image and image.exists() else '')

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

    def _commit(self,rows,source,expected=None):
        with self.cache_lock:
            if expected is not None and expected!=self.generation:
                return None  # A manual import/newer refresh won the race.
            updated=time.time()
            atomic_json(self.directory/'cards.json',dict(updated=updated,source=source,locale='zhCN',cards=rows))
            self.generation+=1
            return dict(rows=rows,updated=updated,source=source,generation=self.generation)

    def apply(self,record):
        with self.cache_lock:
            if record and record['generation']==self.generation:
                self.install(record['rows']);self.updated=record['updated'];self.source=record['source'];self.error=''

    def import_file(self,path):
        path=Path(path).expanduser()
        if not path.is_absolute():raise ValueError('请输入离线 JSON 的绝对路径')
        with path.open('rb') as f:data=f.read(MAX_JSON+1)
        if len(data)>MAX_JSON:raise ValueError('离线 JSON 超出 64MiB')
        value=json.loads(data)
        if isinstance(value,dict):
            if value.get('locale','zhCN')!='zhCN':raise ValueError('离线缓存语言必须为 zhCN')
            value=value.get('cards')
        rows=validate_dataset(value)
        return self._commit(rows,'HearthstoneJSON zhCN 离线导入：'+path.name)

    def refresh(self):
        self.attempted=time.time();expected=self.generation
        for attempt in range(2):
            self.download_state='正在下载（第 %d/2 次）'%(attempt+1)
            try:
                rows=validate_dataset(json.loads(fetch(DATA_URL,MAX_JSON,verify=self.database_verify_tls)))
                record=self._commit(rows,'HearthstoneJSON zhCN HTTPS',expected)
                self.download_state='下载校验通过' if record else '已有较新缓存，跳过旧下载'
                return record
            except (OSError,ValueError,TypeError) as exc:
                self.error=str(exc)
                if attempt==0:time.sleep(1)
        self.download_state='自动下载失败；可重试或离线导入'
        return None

    def download_image(self,cid):
        p=self.image_path(cid)
        if p is None:raise ValueError('非法 Card ID')
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
            (self.directory/'cards.json').unlink(missing_ok=True)
            if self.images.is_symlink():
                self.images.unlink()
            elif self.images.exists():
                shutil.rmtree(self.images)  # Does not follow links inside this tree.
            self.images.mkdir(parents=True,exist_ok=True)
            self.tiles=TileStore(self.images)
            self.by_id={};self.by_dbf={};self.updated=0;self.attempted=0
            self.error='';self.image_error='';self.source='HearthstoneJSON zhCN'
            self.download_state='准备下载'
            self.image_attempts.clear();self.pending.clear();self.queue=queue.Queue(maxsize=128)
            self.batch_remaining.clear();self.image_errors.clear();self.import_result=None
            self.image_batch=dict(status='idle',total=0,success=0,failed=0,skipped=0)
            self.image_totals=dict(success=0,failed=0,skipped=0)

    async def worker(self, stop=None):
        # Cooperative shutdown waits for in-flight thread I/O before cache deletion.
        while stop is None or not stop.is_set():
            if (not self.by_id or self.queue.empty() and not self.batch_remaining) and time.time()-self.updated>7*86400 and time.time()-self.attempted>(60 if not self.by_id else 3600):
                record=await asyncio.to_thread(self.refresh)
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
                else:await asyncio.to_thread(self.download_image,cid)
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
        return dict(database_tls_verify=self.database_verify_tls,image_tls_verify=self.image_verify_tls,tls=tls_diagnostic(),source=self.source,updated=self.updated,count=len(self.by_id),error=self.error,
                    state='卡牌数据库可用' if self.by_id else '卡牌数据库不可用；显示卡牌 ID',download_state=self.download_state,
                    image_error=self.image_error,images_pending=len(self.pending),image_cache=self.tiles.counts(),
                    image_batch=dict(self.image_batch),image_totals=dict(self.image_totals),image_import=self.import_result,
                    image_errors=list(self.image_errors))
