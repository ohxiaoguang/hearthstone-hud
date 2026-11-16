"""Separate on-demand full-card worker. No work is added to the tile queues."""
import json
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from .cards import fetch
from .images import atomic_image, valid_id, validate_png

URL = 'https://art.hearthstonejson.com/v1/render/latest/{locale}/512x/{cid}.png'
LIMIT = 4*1024*1024
DISK_LIMIT = 256*1024*1024

class FullCards:
    def __init__(self, runtime, fetcher=fetch):
        self.runtime=Path(runtime)
        self.root=self.runtime/'cache'/'full-cards'
        self.fetcher=fetcher
        self.condition=threading.Condition()
        self.target=None
        self.stopped=False
        self.thread=None
        self.failed={}

    def request(self, locale, enabled=True, verify=True):
        target=None
        try:
            path=self.runtime/'hover.json'
            if enabled and path.stat().st_size < 1024:
                data=json.loads(path.read_text())
                if (valid_id(data.get('id')) and data.get('locale')==locale and
                    0 <= time.time()-data.get('updated',0) < 1):
                    target=(locale,data['id'],verify)
        except (OSError,ValueError,TypeError):pass
        with self.condition:
            self.target=target
            if target and self.thread is None and not self.stopped:
                self.thread=threading.Thread(target=self._run,name='hud-full-cards',daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def _current(self,target):
        with self.condition:
            if self.stopped or self.target!=target:return False
        try:
            data=json.loads((self.runtime/'hover.json').read_text())
            return data.get('id')==target[1] and data.get('locale')==target[0] and 0 <= time.time()-data.get('updated',0) < 1
        except (OSError,ValueError,TypeError):return False

    def _trim(self,keep):
        files=[]
        for p in self.root.glob('*/*.png'):
            if not p.is_symlink():
                st=p.stat();files.append((st.st_mtime,p,st.st_size))
        total=sum(x[2] for x in files)
        for _,p,size in sorted(files):
            if total <= DISK_LIMIT:break
            if p!=keep:p.unlink(missing_ok=True);total-=size

    def _load(self,target):
        locale,cid,verify=target
        path=self.root/locale/(cid+'.png')
        if path.is_file() and not path.is_symlink():
            try:
                with path.open('rb') as cached:validate_png(cached.read(LIMIT+1),full=True)
                os.utime(path,None)
                return
            except (OSError,ValueError):path.unlink(missing_ok=True)
        if self.failed.get(target,0)>time.monotonic():return
        for language in dict.fromkeys((locale,'enUS')):
            if not self._current(target):return
            try:
                data=self.fetcher(URL.format(locale=language,cid=cid),LIMIT,verify=verify)
                validate_png(data,full=True)
                if self._current(target):
                    atomic_image(path,data)
                    self._trim(path)
                return
            except HTTPError as exc:
                if exc.code not in (404,403):raise
        raise ValueError('No full card render')

    def _run(self):
        last=None
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.stopped or self.target!=last)
                if self.stopped:return
                target=self.target;last=target
            if target:
                try:self._load(target)
                except Exception:
                    if len(self.failed)>256:self.failed.clear()
                    self.failed[target]=time.monotonic()+60

    def close(self):
        with self.condition:self.stopped=True;self.target=None;self.condition.notify_all()
        if self.thread:self.thread.join()
