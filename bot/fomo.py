"""FOMO mode for the v3x PRACTICE desk only (paper). If v3x has had no entry for IDLE_MIN, soft bars (volume, liquidity,
score) relax step by step toward FLOOR_F of base, never below hard floors. Hard safety checks are never relaxed."""
import time, json, os
from logger import conn
IDLE_MIN = 20; STEP_MIN = 10; FLOOR_F = 0.15; STEP_F = 0.15   # 2026-10-30 14:55 (Braydon approved): 0.85,0.70,0.55,0.40,0.25,0.15 (was floor 0.55, step 0.10)
MIN_VOL_FLOOR = 4_000; MIN_LIQ_FLOOR = 6_000; MIN_SCORE_FLOOR = 0.45   # was 12k / 10k; score floor unchanged
LOW_VOL = 12_000; LOW_VOL_MULT = 0.075   # coins under the old $12k floor trade at quarter size
SIZE_MULT = 0.15      # normal v3x size is 0.3 -> FOMO is half
STOP_PCT = 0.05; TP_PCT = 0.08; FLAT_MIN = 10; FLAT_BAND = 0.03; LEARN_W = 0.25
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fomo_positions.json"); _c = [0, None]
def factor():
    if time.time() - _c[0] < 15: return _c[1]
    try:
        import brain5; c = conn(); r = c.execute("SELECT MAX(opened) FROM positions WHERE version=?", (brain5.EXP,)).fetchone()[0]; c.close()
        idle = (time.time() - (r or 0)) / 60
        f = None if idle < IDLE_MIN else round(max(FLOOR_F, 0.85 - STEP_F * int((idle - IDLE_MIN) // STEP_MIN)), 2)
    except Exception: f = None
    _c[:] = [time.time(), f]; return f
def score_bar(f, base): return max(MIN_SCORE_FLOOR, round(base * f, 3))
def _load():
    try: return json.load(open(P))
    except Exception: return {}
def mark(m): d = _load(); d[m] = time.time(); d = {k: v for k, v in d.items() if time.time() - v < 86400}; json.dump(d, open(P, "w"))
def is_fomo(m): return m in _load()
def size_mult(pair):
    """Quarter size (0.075) when 1h volume is under $12k, else half (0.15)."""
    try: v = float(((pair or {}).get("volume") or {}).get("h1") or 0)
    except Exception: v = 0
    return LOW_VOL_MULT if v < LOW_VOL else SIZE_MULT
