"""Unified full-card storage with prioritized hover and batch queues, independent of tiles."""
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
        self.batch=dict(status='idle',total=0,success=0,failed=0,missing=0,skipped=0,retried=0,locale='')
        self.batch_queue=deque();self.batch_remaining=set();self.batch_attempts={}
        self.high_queue=deque();self.pending={};self.inflight=None
        self.migration_lock=threading.Lock();self.migrated=False;self.migration_errors=[]
        self.migration_moved=0;self.migration_duplicates=0
        self.usage_lock=threading.Lock();self.usage_cache=None;self.usage_at=0

    def _start(self):
        if self.thread is None and not self.stopped:
            self.thread=threading.Thread(target=self._run,name='hud-full-cards',daemon=True)
            self.thread.start()

    def prepare(self):
        with self.condition:
            if not self.migrated:self._start()

    def batch_view(self):
        with self.condition:
            batch=dict(self.batch)
            batch['done']=sum(batch[key] for key in ('success','failed','missing','skipped'))
            return batch

    def _key(self,target):return target[:2]

    def path(self,target):return self.root/RESOLUTION/target[0]/(target[1]+'.png')

    def _exists(self,target):
        path=self.path(target)
        try:return path.is_file() and not path.is_symlink()
        except OSError:return False

    def _enqueue(self,target,high=False):
        key=self._key(target)
        if key in self.pending:
            existing=self.pending[key]
            if high and existing in self.batch_queue:
                self.batch_queue.remove(existing);self.high_queue.append(existing)
            return
        self.pending[key]=target
        (self.high_queue if high else self.batch_queue).append(target)

    def begin_download(self,ids,locale,verify=True):
        self.migrate()
        unique=sorted({cid for cid in ids if valid_id(cid)})
        targets=[(locale,cid,verify) for cid in unique]
        missing=[target for target in targets if not self._exists(target)]
        with self.condition:
            if self.stopped:raise RuntimeError('Full-card worker stopped')
            if self.batch['status']=='running':return self.batch_view()
            self.batch_remaining={self._key(t) for t in missing};self.batch_attempts={}
            self.batch=dict(status='running' if missing else 'complete',total=len(targets),success=0,
                            failed=0,missing=0,skipped=len(targets)-len(missing),retried=0,locale=locale)
            for target in missing:
                self.failed.pop(self._key(target),None);self._enqueue(target)
            if missing:self._start()
            self.condition.notify_all();return self.batch_view()

    def cancel_download(self):
        with self.condition:
            # Promoted high-priority tasks and the in-flight reservation survive.
            for target in self.batch_queue:self.pending.pop(self._key(target),None)
            self.batch_queue.clear();self.batch_remaining.clear();self.batch_attempts.clear()
            if self.batch['status']=='running':self.batch['status']='cancelled'
            self.condition.notify_all();return self.batch_view()

    def _valid_file(self,path):
        try:
            if path.is_symlink() or not path.is_file():return False
            with path.open('rb') as stream:validate_png(stream.read(LIMIT+1),full=True)
            return True
        except (OSError,ValueError):return False

    def migrate(self):
        # Runs on the worker/I/O pool, not in the render or log parsing loop.
        with self.migration_lock:
            if self.migrated:return
            if self.root.is_symlink():
                self.migration_errors.append('Full-card cache directory cannot be a symlink');self.migrated=True;return
            directories=[]
            for directory,dirs,_ in os.walk(self.root,followlinks=False):
                directory=Path(directory)
                dirs[:]=[name for name in dirs if not (directory/name).is_symlink()]
                if directory.name=='manual':directories.append(directory);dirs[:]=[]
            for directory in directories:
                for source in directory.glob('*.png'):
                    if self.stopped:return
                    destination=directory.parent/source.name
                    try:
                        if not valid_id(source.stem) or source.is_symlink():continue
                        if self._valid_file(destination):
                            source.unlink();self.migration_duplicates+=1  # Verified unified copy.
                        elif self._valid_file(source) and not destination.is_symlink():
                            os.replace(source,destination);self.migration_moved+=1
                        else:raise ValueError('Unverified legacy card retained: '+source.name)
                    except (OSError,ValueError) as exc:
                        if len(self.migration_errors)<8:self.migration_errors.append(str(exc)[:200])
                try:directory.rmdir()  # Remove only an empty, successfully merged directory.
                except OSError:
                    if len(self.migration_errors)<8:self.migration_errors.append('Legacy directory retained: '+str(directory.relative_to(self.root)))
            self.migrated=True

    def _files(self):
        if self.root.is_symlink():return
        for directory,dirs,files in os.walk(self.root,followlinks=False):
            directory=Path(directory)
            dirs[:]=[name for name in dirs if not (directory/name).is_symlink()]
            for name in files:
                path=directory/name
                if name.endswith('.png') and path.is_file() and not path.is_symlink():yield path

    def usage(self,locale,total):
        # Stats may cover a large unified collection. Scan on the I/O pool,
        # at most once per two seconds; live batch progress is never cached.
        self.prepare()
        with self.usage_lock:
            if self.usage_cache and self.usage_cache['locale']==locale and self.usage_cache['total']==total and time.monotonic()-self.usage_at<2:
                return dict(self.usage_cache,batch=self.batch_view(),last_error=self.last_error)
            size=0;current=set()
            auto_root=self.root/RESOLUTION/locale
            for path in self._files():
                try:
                    size+=path.stat().st_size
                    if path.parent==auto_root:current.add(path.stem)
                except OSError:continue
            self.usage_cache=dict(cached=len(current),bytes=size,total=total,locale=locale,resolution=RESOLUTION)
            self.usage_at=time.monotonic()
            return dict(self.usage_cache,batch=self.batch_view(),last_error=self.last_error)

    def clear(self):
        # Caller has drained this worker before deletion; do not follow symlinks.
        if not self.stopped:raise RuntimeError('Stop full-card worker before clearing')
        for path in self._files():path.unlink(missing_ok=True)
        if not self.root.is_symlink():
            for directory,_,_ in os.walk(self.root,topdown=False,followlinks=False):
                directory=Path(directory)
                if directory.name=='manual' and not directory.is_symlink():
                    try:directory.rmdir()
                    except OSError:pass
        with self.usage_lock:self.usage_cache=None

    def diagnostic(self):
        with self.condition:
            return dict(self.status,last_error=self.last_error,resolution=RESOLUTION,migration_complete=self.migrated,migration_moved=self.migration_moved,migration_duplicates=self.migration_duplicates,migration_errors=list(self.migration_errors),pending=len(self.pending),worker_alive=bool(self.thread and self.thread.is_alive()))

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
            if self.batch['status']=='running' and self.batch['locale']!=locale:self.cancel_download()
            if changed or target is None:self._report(target,stage,error)
            if target:
                if self._exists(target):
                    self.failed.pop(self._key(target),None);self._report(target,'cached')
                elif self._key(target) in self.pending or self.failed.get(self._key(target),0)<=time.monotonic():
                    self._enqueue(target,high=True);self._start()
            self.condition.notify_all()

    def _current(self,target):
        with self.condition:
            if self.stopped or self._key(self.target or ())!=self._key(target):return False
        try:
            data,_=self._read_request(target[0])
            return bool(data and data['id']==target[1])
        except (OSError,ValueError,TypeError):return False

    def _batch_current(self,target):
        with self.condition:
            return not self.stopped and self._key(target) in self.batch_remaining

    def _wanted(self,target):return self._batch_current(target) or self._current(target)

    def _load(self,target):
        self.migrate()
        locale,cid,verify=target;path=self.path(target)
        if self.root.is_symlink() or any(p.is_symlink() for p in path.parents if self.root in p.parents):
            raise ValueError('Full-card cache directory cannot be a symlink')
        if self._valid_file(path):self._report(target,'cached');return 'skipped'
        if path.is_file() and not path.is_symlink():path.unlink()
        missing=[]
        for language in dict.fromkeys((locale,'enUS')):
            if not self._wanted(target):return 'cancelled'
            try:
                self._report(target,'downloading',source_locale=language)
                data=self.fetcher(URL.format(locale=language,cid=cid),LIMIT,verify=verify)
                self._report(target,'validating',source_locale=language);validate_png(data,full=True)
                with self.condition:
                    if not self._wanted(target):self._report(target,'cancelled');return 'cancelled'
                    atomic_image(path,data)
                self._report(target,'ready',source_locale=language,bytes=len(data));return 'success'
            except HTTPError as exc:
                if exc.code not in (404,403):raise
                missing.append(language+': HTTP '+str(exc.code))
        self._report(target,'download_failed','No full card render ('+', '.join(missing)+')')
        return 'missing'

    def _run(self):
        try:self.migrate()
        except Exception as exc:self._report(None,'migration_failed',exc)
        while True:
            with self.condition:
                while True:
                    if self.stopped:return
                    if self.high_queue:target=self.high_queue.popleft();break
                    if self.batch_queue:target=self.batch_queue.popleft();break
                    target=self.target;retry=self.failed.get(self._key(target or ()),0)
                    if target and retry and retry<=time.monotonic() and not self._exists(target):
                        self._enqueue(target,high=True);continue
                    self.condition.wait(max(.01,retry-time.monotonic()) if retry else None)
                self.inflight=target
            outcome='cancelled';error=None
            try:outcome=self._load(target)
            except Exception as exc:error=exc;self._report(target,'download_failed',exc)
            with self.condition:
                key=self._key(target);self.pending.pop(key,None);self.inflight=None
                if error is not None or outcome=='missing':
                    if len(self.failed)>256:self.failed.clear()
                    self.failed[key]=time.monotonic()+RETRY_SECONDS
                else:self.failed.pop(key,None)
                if self._batch_current(target):
                    if error is not None and not self.batch_attempts.get(key):
                        self.batch_attempts[key]=1;self.batch['retried']+=1
                        self._enqueue(target,high=self._current(target))
                    else:
                        self.batch_remaining.discard(key)
                        self.batch['failed' if error is not None else outcome if outcome in ('success','skipped','missing') else 'failed']+=1
                        if not self.batch_remaining:self.batch['status']='complete'

    def close(self):
        with self.condition:
            self.cancel_download();self.stopped=True;self.target=None
            self.high_queue.clear();self.pending.clear();self.condition.notify_all()
        if self.thread:self.thread.join()
