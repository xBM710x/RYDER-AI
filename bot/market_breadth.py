"""Rotating deeper Solana pool discovery; one extra request per 90s, bounded backoff."""
import collections
import re
import time
MINT=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
STABLE={'So11111111111111111111111111111111111111112','EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v','Es9vMFrzaCERmJfrF4H2FYDgLCe5Kq7t4xCn1zAiN1f'}
BASE='https://api.geckoterminal.com/api/v2/networks/solana/'
PLAN=[('new_pools',p) for p in range(3,11)]+[('trending_pools',p) for p in range(2,6)]+[('pools',p) for p in range(2,6)]
class Discovery:
    def __init__(self):self.next=0;self.cursor=0;self.errors=0;self.stats=collections.Counter();self.last=None
    def discover(self,fetch,clock=time.time):
        now=clock()
        if now<self.next:return []
        route,page=PLAN[self.cursor%len(PLAN)];self.cursor+=1;self.next=now+90
        self.stats['requests']+=1
        try:
            response=fetch(BASE+route+'?page='+str(page))
            if not isinstance(response,dict) or not isinstance(response.get('data'),list):raise ValueError('pool schema')
            found={}
            for row in response['data'][:20]:
                try:
                    r=row['relationships'];raw=r['base_token']['data']['id']
                    if not raw.startswith('solana_'):continue
                    mint=raw[len('solana_'):]
                    if not MINT.fullmatch(mint) or mint in STABLE:continue
                    attrs=row.get('attributes') or {};dex=(r.get('dex',{}).get('data') or {}).get('id') or 'unknown'
                    found.setdefault(mint,dict(mint=mint,name=str(attrs.get('name') or '').split(' / ')[0][:80],source='gecko-depth-'+route,dex=dex))
                except (KeyError,TypeError,AttributeError):self.stats['malformed']+=1
            self.errors=0;self.last=now;self.stats['candidates']+=len(found);return list(found.values())
        except Exception:
            self.errors+=1;self.stats['errors']+=1;self.next=now+min(900,90*2**min(self.errors,3));return []
    def status(self,clock=time.time):return dict(self.stats,next_poll_s=max(0,round(self.next-clock())),last_success_age_s=round(clock()-self.last) if self.last else None,next_route=PLAN[self.cursor%len(PLAN)][0],scope='rotating pages 3–10 new pools; 2–5 trending/top pools; existing safety gates unchanged')
INSTANCE=Discovery()
