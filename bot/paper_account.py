"""Opt-in Main + Copy PAPER ledger. No network, wallets, keys or orders.
Stop all bot processes before enabling RYDER_SHARED_PAPER_ACCOUNT=1.
"""
import os
import math
import time

BOOKS = ('v3', 'vC')
KEY = 'cash_main_copy'
MODE = os.environ.get('RYDER_SHARED_PAPER_ACCOUNT') == '1'

def key_for(ver):
    return KEY if MODE and ver in BOOKS else ('cash' if ver == 'v1' else 'cash_' + ver)

def members(ver):
    return BOOKS if MODE and ver in BOOKS else (ver,)

def ensure(c, start=300.0):
    existing = c.execute('SELECT v FROM account WHERE k=?', (KEY,)).fetchone()
    if existing is not None:
        if not MODE:
            raise RuntimeError('Shared paper ledger already active; keep RYDER_SHARED_PAPER_ACCOUNT=1')
        return
    if not MODE:
        return
    if c.in_transaction:
        raise RuntimeError('Initialize shared paper ledger outside a transaction')
    c.execute('BEGIN IMMEDIATE')
    try:
        if c.execute('SELECT 1 FROM account WHERE k=?', (KEY,)).fetchone():
            c.commit()
            return
        cash = []
        for ver in BOOKS:
            row = c.execute('SELECT v FROM account WHERE k=?', ('cash_' + ver,)).fetchone()
            if row is None:
                count = c.execute('SELECT COUNT(*) FROM positions WHERE version=?', (ver,)).fetchone()[0]
                if count:
                    raise RuntimeError('Missing cash account for existing ' + ver + ' positions')
            value = float(row[0]) if row else float(start)
            if not math.isfinite(value) or value < 0:
                raise RuntimeError('Invalid legacy paper cash')
            cash.append(value)
        combined = cash[0] + cash[1] - start
        if combined < -1e-7:
            raise RuntimeError('Existing positions need more than one starting bankroll; close positions before migration')
        c.execute('CREATE TABLE IF NOT EXISTS paper_account_migration (book TEXT PRIMARY KEY, legacy_cash REAL, start REAL)')
        c.executemany('INSERT INTO paper_account_migration VALUES(?,?,?)', [(v, value, start) for v, value in zip(BOOKS, cash)])
        c.execute('INSERT INTO account VALUES(?,?)', (KEY, max(0, combined)))
        c.commit()
    except Exception:
        c.rollback()
        raise

def open_cost(c, ver, mint=None):
    books = members(ver)
    sql = 'SELECT COALESCE(SUM(cost),0) FROM positions WHERE status=\'open\' AND version IN (' + ','.join('?' for _ in books) + ')'
    args = books
    if mint is not None:
        sql += ' AND mint=?'
        args += (mint,)
    return float(c.execute(sql, args).fetchone()[0])

def cash(c, ver, start=300.0):
    ensure(c, start)
    row = c.execute('SELECT v FROM account WHERE k=?', (key_for(ver),)).fetchone()
    return float(row[0]) if row else float(start)

def cap_order(c, ver, proposed, mint, fraction, coin_fraction):
    """Final allocation check inside the caller's write transaction."""
    row = c.execute('SELECT v FROM account WHERE k=?', (key_for(ver),)).fetchone()
    if row is None:
        raise RuntimeError('Paper cash account must be initialized before allocation')
    available = float(row[0])
    total = available + open_cost(c, ver)
    if MODE and ver in BOOKS:
        day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        pnl = c.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed' AND version IN ('v3','vC') AND closed>=?", (day0,)).fetchone()[0]
        seed = c.execute("SELECT start FROM paper_account_migration LIMIT 1").fetchone()[0]
        if pnl <= -0.15 * seed:
            return 0.0
    return max(0.0, min(proposed, available, total * fraction,
                        total * coin_fraction - open_cost(c, ver, mint)))

def summary(c, marks, start=300.0):
    """One bankroll plus both strategies' realized and open P&L."""
    if not MODE:
        return None
    ensure(c, start)
    rows = [dict(r) for r in c.execute("SELECT * FROM positions WHERE version IN ('v3','vC')")]
    available = cash(c, 'v3', start)
    opened = [r for r in rows if r['status'] == 'open']
    value, fallback = 0.0, 0
    for p in opened:
        px = marks.get(p['mint'])
        if px is None or not math.isfinite(float(px)) or float(px) <= 0:
            px = p['entry']
            fallback += 1
        value += p['qty'] * float(px)
    closed = sorted([r for r in rows if r['status'] == 'closed'], key=lambda p: p['closed'] or 0)
    realized = sum(p['pnl'] or 0 for p in closed)
    strategies = {book: round(sum(p['pnl'] or 0 for p in closed if p['version'] == book), 2) for book in BOOKS}
    return dict(start=start, cash=round(available, 2), equity=round(available + value, 2),
                realized=round(realized, 2), open=len(opened), fallback_marks=fallback,
                strategies=strategies, books=list(BOOKS))
