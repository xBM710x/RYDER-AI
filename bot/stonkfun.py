"""Read-only StonkFun discovery. Candidates always enter RYDER's existing safety pipeline.
Official endpoint: https://www.stonkfunxyz.com/developers
No launch, fee claim, signing or trading endpoint is used.
"""
import json
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode

BASE = 'https://www.stonkfun.xyz/api/public/v1/tokens'
STATE_FILE = Path(__file__).with_name('stonkfun_state.json')
_NEXT = 0.0
_ERRORS = 0
_MINT = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')

def number(v):
    if v is None or isinstance(v, bool): return None
    try: n = float(v)
    except (ValueError, TypeError): return None
    return n if math.isfinite(n) and n >= 0 else None

def rows(body):
    if not isinstance(body, dict) or body.get('error'):
        raise ValueError('Invalid StonkFun response')
    d = body.get('data')
    if isinstance(d, list): return d
    if isinstance(d, dict) and isinstance(d.get('tokens'), list): return d['tokens']
    if isinstance(body.get('tokens'), list): return body['tokens']
    raise ValueError('Unrecognized StonkFun token-list schema')

def normalize(row, fetched_at):
    if not isinstance(row, dict): return None
    # Address is the mint in the documented identity feed. Never substitute a pool address.
    mint = row.get('mint') or row.get('address')
    if not isinstance(mint, str) or not _MINT.fullmatch(mint): return None
    market = row.get('market') if isinstance(row.get('market'), dict) else {}
    quote = row.get('quote') if isinstance(row.get('quote'), dict) else {}
    return dict(mint=mint, name=str(row.get('symbol') or row.get('name') or '')[:80],
                source='stonkfun', dex='stonkfun', launchpad='stonkfun',
                source_url=BASE, observed_at=fetched_at,
                quote_mint=quote.get('mint') or row.get('quoteMint'), quote_symbol=quote.get('symbol'),
                source_price_usd=number(market.get('priceUsd')),
                source_liquidity_usd=number(market.get('liquidityUsd')),
                source_volume_24h_usd=number(market.get('volume24hUsd')),
                graduation_status=row.get('status'),
                transfer_fee_bps=(row.get('transferFee') or {}).get('bps') if isinstance(row.get('transferFee'),dict) else None)

def _save(state):
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state)); os.replace(tmp, STATE_FILE)

def discover(fetch=None, clock=time.time):
    global _NEXT, _ERRORS
    now = clock()
    if os.environ.get('RYDER_STONKFUN_ENABLED', '1') == '0' or now < _NEXT: return []
    if fetch is None:
        from common import http_json
        fetch = lambda url: http_json(url, timeout=8, retries=0)
    _NEXT = now + 60
    found = {}
    try:
        # Bounded two-page newest-first sweep; source rechecks reuse Scout's seen table.
        for page in (1, 2):
            body = fetch(BASE + '?' + urlencode(dict(sort='newest', page=page, pageSize=25)))
            batch = rows(body)
            for row in batch:
                item = normalize(row, now)
                if item: found.setdefault(item['mint'], item)
            if len(batch) < 25: break
        _ERRORS = 0
        _save(dict(source='stonkfun', ok=True, updated_at=now, candidates=len(found), next_poll_at=_NEXT))
        return list(found.values())
    except Exception as e:
        _ERRORS += 1; _NEXT = now + min(600, 60 * 2 ** min(_ERRORS - 1, 4))
        # Drop the partial batch on a schema/network failure; never claim a failed source is live.
        try: _save(dict(source='stonkfun', ok=False, updated_at=now, candidates=0, next_poll_at=_NEXT, error=type(e).__name__))
        except OSError: pass
        return []

def status(clock=time.time):
    try: d = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError): return dict(source='stonkfun', ok=False, status='not observed')
    age = max(0, clock() - d.get('updated_at', 0))
    d['age_s'] = round(age); d['stale'] = age > 180
    d['status'] = 'delayed' if d['stale'] else ('connected' if d.get('ok') else 'unavailable')
    return d
