"""Bound pending candidates and executor backlog; round-robin across discovery sources."""
import collections
import threading
import time
class Scheduler:
    def __init__(self,capacity=1000,ttl=600,max_inflight=16):
        self.capacity=capacity;self.ttl=ttl;self.max_inflight=max_inflight;self.pending=collections.OrderedDict();self.turn=0;self.lock=threading.Lock();self.stats=collections.Counter();self.waits=collections.deque(maxlen=256)
    def offer(self,candidates,clock=time.time):
        now=clock()
        with self.lock:
            for cd in candidates:
                if cd['mint'] in self.pending:
                    first,_=self.pending[cd['mint']];self.pending[cd['mint']]=(first,dict(cd));continue
                if len(self.pending)>=self.capacity:self.stats['overflow']+=1;continue
                self.pending[cd['mint']]=(now,dict(cd));self.stats['queued']+=1
    def take(self,inflight,rejected=lambda m:False,clock=time.time):
        now=clock()
        with self.lock:
            for m,(ts,cd) in list(self.pending.items()):
                if now-ts>self.ttl or rejected(m):self.pending.pop(m);self.stats['expired_or_rejected']+=1
            budget=max(0,self.max_inflight-len(inflight));groups=collections.OrderedDict()
            for m,(ts,cd) in self.pending.items():
                if m not in inflight:groups.setdefault(cd.get('source') or 'unknown',[]).append(m)
            sources=list(groups);out=[]
            while budget and sources:
                idx=self.turn%len(sources);src=sources[idx];m=groups[src].pop(0);queued,cd=self.pending.pop(m);self.waits.append(max(0,now-queued));out.append(cd);budget-=1;self.turn+=1
                if not groups[src]:sources.remove(src)
            self.stats['dispatched']+=len(out);return out
    def has_room_for_pending(self, inflight):
        with self.lock:
            return len(inflight)<self.max_inflight and any(m not in inflight for m in self.pending)
    def status(self):
        with self.lock:return dict(self.stats,wait_p90_s=round(sorted(self.waits)[int(.9*(len(self.waits)-1))],2) if self.waits else None,pending=len(self.pending),max_pending=self.capacity,max_inflight=self.max_inflight,ttl_s=self.ttl)
INSTANCE=Scheduler()
