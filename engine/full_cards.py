"""Separate on-demand full-card worker. No work is added to the tile queues."""
from collections import deque
import json
import os
import math
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from .cards import fetch
from .images import atomic_image, valid_id, validate_png

RESOLUTION = '256x'
URL = 'https://art.hearthstonejson.com/v1/render/latest/{locale}/256x/{cid}.png'
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
        self.target_serial=0
        self.stopped=False
        self.thread=None
        self.failed={}
        self.status=dict(stage='idle',error='',id='',locale='')
        self.last_error=''
        self.batch=dict(status='idle',total=0,success=0,failed=0,missing=0,skipped=0,retried=0,locale='')
        self.batch_queue=deque();self.batch_remaining=set();self.batch_attempts={}
        self.batch_token=0
        self.usage_lock=threading.Lock();self.usage_cache=None;self.usage_at=0

    def _start(self):
        if self.thread is None and not self.stopped:
            self.thread=threading.Thread(target=self._run,name='hud-full-cards',daemon=True)
            self.thread.start()

    def batch_view(self):
        with self.condition:
            batch=dict(self.batch)
            batch['done']=sum(batch[key] for key in ('success','failed','missing','skipped'))
            return batch

    def begin_download(self,ids,locale,verify=True):
        with self.condition:
            if self.stopped:raise RuntimeError('Full-card worker stopped')
            if self.batch['status']=='running':return self.batch_view()
            targets={(locale,cid,verify) for cid in ids if valid_id(cid)}
            self.batch_token+=1;self.batch_remaining=targets
            self.batch_attempts={};self.batch_queue=deque(sorted(targets))
            self.batch=dict(status='running' if targets else 'complete',total=len(targets),success=0,
                            failed=0,missing=0,skipped=0,retried=0,locale=locale)
            for target in targets:self.failed.pop(target,None)
            if targets:self._start()
            self.condition.notify_all();return self.batch_view()

    def cancel_download(self):
        with self.condition:
            self.batch_token+=1;self.batch_queue.clear();self.batch_remaining.clear();self.batch_attempts.clear()
            if self.batch['status']=='running':self.batch['status']='cancelled'
            self.condition.notify_all();return self.batch_view()

    def _files(self,include_manual=True):
        if self.root.is_symlink():return
        for directory,dirs,files in os.walk(self.root,followlinks=False):
            directory=Path(directory)
            dirs[:]=[name for name in dirs if not (directory/name).is_symlink() and (include_manual or name!='manual')]
            for name in files:
                path=directory/name
                if name.endswith('.png') and path.is_file() and not path.is_symlink():yield path

    def usage(self,locale,total):
        # Stats may cover a manually downloaded collection. Scan on the I/O pool,
        # at most once per two seconds; live batch progress is never cached.
        with self.usage_lock:
            if self.usage_cache and self.usage_cache['locale']==locale and self.usage_cache['total']==total and time.monotonic()-self.usage_at<2:
                return dict(self.usage_cache,batch=self.batch_view(),last_error=self.last_error)
            size=0;current=set();manual=0
            auto_root=self.root/RESOLUTION/locale
            for path in self._files():
                try:
                    size+=path.stat().st_size
                    if path.parent in (auto_root,auto_root/'manual'):
                        current.add(path.stem)
                        if path.parent.name=='manual':manual+=1
                except OSError:continue
            self.usage_cache=dict(cached=len(current),bytes=size,total=total,manual=manual,locale=locale,resolution=RESOLUTION)
            self.usage_at=time.monotonic()
            return dict(self.usage_cache,batch=self.batch_view(),last_error=self.last_error)

    def clear(self):
        # Caller has drained this worker before deletion; do not follow symlinks.
        if not self.stopped:raise RuntimeError('Stop full-card worker before clearing')
        for path in self._files():path.unlink(missing_ok=True)
        with self.usage_lock:self.usage_cache=None

    def diagnostic(self):
        with self.condition:
            return dict(self.status,last_error=self.last_error,resolution=RESOLUTION,worker_alive=bool(self.thread and self.thread.is_alive()))

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
            if changed:self.target_serial+=1
            if self.batch['status']=='running' and self.batch['locale']!=locale:self.cancel_download()
            if changed or target is None:self._report(target,stage,error)
            if target:self._start()
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
        for p in self._files(include_manual=False):
            if p.parent.name!='manual':
                st=p.stat();files.append((st.st_mtime,p,st.st_size))
        total=sum(x[2] for x in files)
        for _,p,size in sorted(files):
            if total <= DISK_LIMIT:break
            if p!=keep:p.unlink(missing_ok=True);total-=size

    def _batch_current(self,target,token):
        with self.condition:
            return not self.stopped and token==self.batch_token and target in self.batch_remaining

    def _wanted(self,target,token):
        return self._batch_current(target,token) or self._current(target)

    def _load(self,target,token=None):
        locale,cid,verify=target
        auto=self.root/RESOLUTION/locale/(cid+'.png');manual=auto.parent/'manual'/auto.name
        if self.root.is_symlink() or any(p.is_symlink() for p in manual.parents if self.root in p.parents):
            raise ValueError('Full-card cache directory cannot be a symlink')
        for path in (manual,auto):
            if path.is_file() and not path.is_symlink():
                try:
                    with path.open('rb') as cached:validate_png(cached.read(LIMIT+1),full=True)
                    with self.condition:
                        if path==auto and self._batch_current(target,token):
                            manual.parent.mkdir(parents=True,exist_ok=True);os.replace(auto,manual);path=manual
                    os.utime(path,None);self._report(target,'cached');return 'skipped'
                except (OSError,ValueError):path.unlink(missing_ok=True)
        missing=[]
        for language in dict.fromkeys((locale,'enUS')):
            if not self._wanted(target,token):return 'cancelled'
            try:
                self._report(target,'downloading',source_locale=language)
                data=self.fetcher(URL.format(locale=language,cid=cid),LIMIT,verify=verify)
                self._report(target,'validating',source_locale=language);validate_png(data,full=True)
                with self.condition:
                    if not self._wanted(target,token):self._report(target,'cancelled');return 'cancelled'
                    path=manual if self._batch_current(target,token) else auto
                    atomic_image(path,data)
                if path==auto:self._trim(path)
                self._report(target,'ready',source_locale=language,bytes=len(data));return 'success'
            except HTTPError as exc:
                if exc.code not in (404,403):raise
                missing.append(language+': HTTP '+str(exc.code))
        self._report(target,'download_failed','No full card render ('+', '.join(missing)+')')
        return 'missing'

    def _run(self):
        last=None
        while True:
            with self.condition:
                while True:
                    if self.stopped:return
                    target=self.target
                    due=bool(target and self.failed.get(target,0)<=time.monotonic())
                    if target and ((target,self.target_serial)!=last or target in self.failed) and due:
                        token=self.batch_token if target in self.batch_remaining else None;last=(target,self.target_serial);break
                    while self.batch_queue and self.batch_queue[0] not in self.batch_remaining:self.batch_queue.popleft()
                    if self.batch_queue:
                        target=self.batch_queue.popleft();token=self.batch_token;break
                    retry=self.failed.get(self.target,0)
                    self.condition.wait(max(.01,retry-time.monotonic()) if retry else None)
            outcome='cancelled';error=None
            try:outcome=self._load(target,token)
            except Exception as exc:error=exc;self._report(target,'download_failed',exc)
            with self.condition:
                if error is not None or outcome=='missing':
                    if len(self.failed)>256:self.failed.clear()
                    self.failed[target]=time.monotonic()+RETRY_SECONDS
                else:self.failed.pop(target,None)
                if self._batch_current(target,token):
                    if error is not None and not self.batch_attempts.get(target):
                        self.batch_attempts[target]=1;self.batch['retried']+=1;self.batch_queue.append(target)
                    else:
                        self.batch_remaining.discard(target)
                        self.batch['failed' if error is not None else outcome if outcome in ('success','skipped','missing') else 'failed']+=1
                        if not self.batch_remaining:self.batch['status']='complete'

    def close(self):
        with self.condition:
            self.cancel_download();self.stopped=True;self.target=None;self.condition.notify_all()
        if self.thread:self.thread.join()
