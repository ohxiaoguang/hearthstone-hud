"""HearthstoneJSON zhCN metadata and bounded asynchronous image cache.

Metadata approach follows hs-decktracker-linux/cards.py (MIT). Network work
runs in a worker thread, never in log parsing or the OpenGL loop.
"""
import asyncio
import queue
import json
import re
import struct
import time
import urllib.request
from pathlib import Path
from .io import atomic_json

DATA_URL='https://api.hearthstonejson.com/v1/latest/zhCN/cards.json'
IMAGE_URL='https://art.hearthstonejson.com/v1/tiles/{card_id}.png'
FIELDS=('id','dbfId','name','cost','cardClass','type')


def fetch(url, limit):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Hearthstone-HUD/0.2.0'}),timeout=12) as r:
        data=r.read(limit+1)
        if len(data)>limit:raise ValueError('下载超出大小限制')
        return data


class Cards:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.images=self.directory/'images'
        self.images.mkdir(parents=True,exist_ok=True)
        self.by_id={};self.by_dbf={};self.updated=0;self.error='';self.source='HearthstoneJSON zhCN'
        self.attempted=0;self.image_attempts={};self.queue=queue.Queue(maxsize=128);self.pending=set()
        try:
            data=json.loads((self.directory/'cards.json').read_text())
            self.install(data['cards']);self.updated=data['updated']
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
        if not re.fullmatch(r'[A-Za-z0-9_]+',cid):return None
        p=self.images/(cid+'.png')
        return p

    def info(self,cid):
        card=self.by_id.get(cid,{})
        image=self.image_path(cid)
        return dict(id=cid,name=card.get('name') if isinstance(card.get('name'),str) else cid or '未知卡牌',cost=card.get('cost') if isinstance(card.get('cost'),int) else None,image=str(image) if image and image.exists() else '')

    def request_images(self,ids):
        for cid in ids:
            path=self.image_path(cid)
            if not path or path.exists() or cid in self.pending or time.time()-self.image_attempts.get(cid,0)<3600:
                continue
            if self.queue.full():break
            self.pending.add(cid);self.queue.put_nowait(cid)

    def refresh(self):
        self.attempted=time.time()
        try:
            rows=json.loads(fetch(DATA_URL,64*1024*1024))
            if not isinstance(rows,list) or len(rows)<100:raise ValueError('卡牌数据库不完整')
            # Validate before replacing a usable cache.
            slim=[{k:c[k] for k in FIELDS if k in c} for c in rows if isinstance(c,dict) and 'id' in c]
            atomic_json(self.directory/'cards.json',dict(updated=time.time(),cards=slim))
            return slim
        except (OSError,ValueError,TypeError) as exc:
            self.error=str(exc)
            return None

    def download_image(self,cid):
        p=self.image_path(cid)
        if not p:return
        data=fetch(IMAGE_URL.format(card_id=cid),1024*1024)
        if len(data)<24 or data[:8]!=b'\x89PNG\r\n\x1a\n' or max(struct.unpack('>II',data[16:24]))>1024:raise ValueError('图片格式或尺寸不合规')
        tmp=p.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(p)
        files=sorted(self.images.glob('*.png'),key=lambda f:f.stat().st_mtime,reverse=True)
        size=0
        for i,f in enumerate(files):
            size+=f.stat().st_size
            if i>=256 or size>32*1024*1024:f.unlink(missing_ok=True)

    async def worker(self):
        if time.time()-self.updated>7*86400 and time.time()-self.attempted>3600:
            rows=await asyncio.to_thread(self.refresh)
            if rows is not None:
                self.install(rows);self.updated=time.time();self.error=''
        while True:
            try:
                cid=self.queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(.2)
                continue
            self.image_attempts[cid]=time.time()
            if len(self.image_attempts)>1024:
                self.image_attempts.pop(next(iter(self.image_attempts)))
            try:
                await asyncio.to_thread(self.download_image,cid)
            except (OSError,ValueError) as exc:
                self.error=str(exc)
            finally:
                self.pending.discard(cid);self.queue.task_done()

    def diagnostic(self):
        return dict(source=self.source,updated=self.updated,count=len(self.by_id),error=self.error,
                    state='缓存可用' if self.by_id else '尚无数据库；显示卡牌 ID',images_pending=len(self.pending))
