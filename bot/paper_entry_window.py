"""Volume admission for liquid, active candidates on the main paper desk."""
import math


def positive(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0


def threshold(pair, standard, now):
    pair=pair or {}
    volume=(pair.get('volume') or {}).get('h1')
    liquidity=(pair.get('liquidity') or {}).get('usd')
    trades=(pair.get('txns') or {}).get('m5') or {}
    buys,sells=trades.get('buys'),trades.get('sells')
    stamp=pair.get('_ts')
    if not all(positive(x) for x in (volume,liquidity,stamp,buys)): return standard
    if not isinstance(sells,int) or sells<0: return standard
    lower=max(20000,standard*.75)
    if 0<=now-stamp<=30 and liquidity>=50000 and buys>=10 and buys>sells and volume>=lower:
        return min(standard,lower)
    return standard
