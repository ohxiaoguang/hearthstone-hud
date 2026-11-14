"""Opt-in worker: no event-loop blocking, cooperative stop, owned descriptors."""
import threading
import time
from .arena_memory import HearthstoneMemory

DISABLED=dict(code='disabled',status='内存读取未开启',pid=None,error='')

class MemoryWatch:
    def __init__(self,factory=None,normal=.5,idle=3):
        self.factory=factory or (lambda stop:HearthstoneMemory(stop=stop))
        self.normal=normal;self.idle=idle;self.stop_event=threading.Event();self.lock=threading.Lock()
        self.thread=None;self.state=None;self.diagnostic=dict(DISABLED);self.updated=0;self.updated_wall=0
        self.last_error_key=None;self.last_error_time=0;self.errors=0;self.suppressed=0;self.last_error='';self.last_error_at=0
        self.generation=0

    def start(self):
        if self.thread is not None:return
        self.stop_event.clear()
        with self.lock:self.diagnostic=dict(code='reading',status='正在读取',pid=None,error='')
        self.thread=threading.Thread(target=self._run,name='arena-memory-readonly',daemon=True);self.thread.start()

    def _run(self):
        reader=None
        try:
            reader=self.factory(self.stop_event)
            while not self.stop_event.is_set():
                try:state,diag=reader.poll()
                except Exception as exc:
                    reader.close();state=None;diag=dict(code='read_error',status='内存读取失败',pid=None,error=str(exc)[:300])
                if self.stop_event.is_set():break
                now=time.monotonic()
                # The reader stamps the wall clock after its last consistency
                # check, so the recovery anchor describes the snapshot itself and
                # not the start of the poll.
                wall=diag.get('observed_wall')
                with self.lock:
                    if (diag.get('pid'),diag.get('process_instance'))!=(self.diagnostic.get('pid'),self.diagnostic.get('process_instance')) or diag.get('code') in ('not_running','incompatible','permission_denied','mono_missing'):
                        self.generation+=1
                    self.state=state;self.diagnostic=dict(diag);self.updated=now
                    self.updated_wall=wall if isinstance(wall,(int,float)) and wall>0 else time.time()
                    key=(diag.get('code'),diag.get('error'))
                    if diag.get('error'):
                        if key!=self.last_error_key or now-self.last_error_time>=30:
                            self.last_error_key=key;self.last_error_time=now;self.errors+=1;self.last_error=diag['error'];self.last_error_at=time.time()
                        else:self.suppressed+=1
                self.stop_event.wait(self.normal if diag.get('code') in ('reading','hero_selection','card_selection','hero_power_selection') else self.idle)
        except Exception as exc:
            with self.lock:
                self.state=None;self.last_error=str(exc)[:300];self.last_error_at=time.time();self.diagnostic=dict(code='read_error',status='内存任务初始化失败',pid=None,error=self.last_error)
        finally:
            if reader is not None:reader.close()

    def request_stop(self):self.stop_event.set()

    def join(self):
        thread=self.thread
        if thread is not None:thread.join()
        self.thread=None
        with self.lock:self.state=None;self.updated=0;self.diagnostic=dict(DISABLED);self.generation+=1

    def snapshot(self):
        with self.lock:
            # Never retain stale choices when a worker hangs/exits or stop is requested.
            fresh=bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set() and self.updated and time.monotonic()-self.updated<2)
            diag=dict(self.diagnostic,observed_at=self.updated,observed_wall=self.updated_wall,enabled=self.thread is not None,errors=self.errors,suppressed_errors=self.suppressed,last_error=self.last_error,last_error_at=self.last_error_at)
            if not fresh and self.state is not None:diag.update(code='reading',status='候选已过期，等待新读取')
            return self.state if fresh else None,diag
