"""Separate on-demand full-card worker. No work is added to the tile queues."""
import json
import os
import math
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from .cards import fetch
from .images import atomic_image, valid_id, validate_png

URL = 'https://art.hearthstonejson.com/v1/render/latest/{locale}/512x/{cid}.png'
LIMIT = 4*1024*1024
DISK_LIMIT = 256*1024*1024
RETRY_SECONDS = 60

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
        self.status=dict(stage='idle',error='',id='',locale='')
        self.last_error=''

    def diagnostic(self):
        with self.condition:
            return dict(self.status,last_error=self.last_error,worker_alive=bool(self.thread and self.thread.is_alive()))

    def _report(self,target,stage,error='',**extra):
        with self.condition:
            if error:self.last_error=str(error)[:300]
            self.status=dict(stage=stage,error=str(error)[:300],id=target[1] if target else '',
                             locale=target[0] if target else '',updated=time.time(),**extra)

    def _read_request(self,locale):
        path=self.runtime/'hover.json'
        if path.stat().st_size>=1024:raise ValueError('hover.json exceeds size limit')
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise ValueError('hover.json must be an object')
        stamp=data.get('updated',0)
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp):raise ValueError('invalid hover timestamp')
        if not data.get('id'):return None,'idle'
        if not valid_id(data.get('id')):raise ValueError('invalid hover card ID')
        if data.get('locale')!=locale:return None,'locale_mismatch'
        if not 0 <= time.time()-stamp < 2:return None,'request_expired'
        return data,'requested'

    def request(self, locale, enabled=True, verify=True):
        target=None;stage='disabled';error=''
        if enabled:
            try:
                data,stage=self._read_request(locale)
                if data:target=(locale,data['id'],verify)
            except FileNotFoundError:stage='awaiting_request'
            except (OSError,ValueError,TypeError) as exc:stage='request_error';error=str(exc)
        with self.condition:
            changed=target!=self.target
            self.target=target
            if changed or target is None:self._report(target,stage,error)
            if target and self.thread is None and not self.stopped:
                self.thread=threading.Thread(target=self._run,name='hud-full-cards',daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def _current(self,target):
        with self.condition:
            if self.stopped or self.target!=target:return False
        try:
            data,_=self._read_request(target[0])
            return bool(data and data['id']==target[1])
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
                self._report(target,'cached')
                return
            except (OSError,ValueError):path.unlink(missing_ok=True)
        if self.failed.get(target,0)>time.monotonic():return
        missing=[]
        for language in dict.fromkeys((locale,'enUS')):
            if not self._current(target):return
            try:
                self._report(target,'downloading',source_locale=language)
                data=self.fetcher(URL.format(locale=language,cid=cid),LIMIT,verify=verify)
                self._report(target,'validating',source_locale=language)
                validate_png(data,full=True)
                if self._current(target):
                    atomic_image(path,data)
                    self._trim(path)
                    self._report(target,'ready',source_locale=language,bytes=len(data))
                else:self._report(target,'cancelled')
                return
            except HTTPError as exc:
                if exc.code not in (404,403):raise
                missing.append(language+': HTTP '+str(exc.code))
        raise ValueError('No full card render ('+', '.join(missing)+')')

    def _run(self):
        last=None
        while True:
            with self.condition:
                retry=self.failed.get(last,0) if last else 0
                timeout=max(.01,retry-time.monotonic()) if retry else None
                self.condition.wait_for(lambda:self.stopped or self.target!=last,timeout)
                if self.stopped:return
                target=self.target;last=target
            if target:
                if self.failed.get(target,0)>time.monotonic():continue
                try:
                    self._load(target)
                    self.failed.pop(target,None)
                except Exception as exc:
                    if len(self.failed)>256:self.failed.clear()
                    self.failed[target]=time.monotonic()+RETRY_SECONDS
                    self._report(target,'download_failed',exc)

    def close(self):
        with self.condition:self.stopped=True;self.target=None;self.condition.notify_all()
        if self.thread:self.thread.join()
