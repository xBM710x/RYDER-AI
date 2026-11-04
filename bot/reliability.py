"""Read-only checks on the shared paper-account snapshot."""
import math


def number(value, positive=False):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and (not positive or n > 0) else None


def assess(positions, market, shared, now):
    def report(name, state, text):
        return dict(name=name, stat=state, text=text, role='Paper account checks')
    quote, ledger = 'Quote Guard', 'Ledger Auditor'
    if shared is None:
        return [report(name,'unknown','Shared account snapshot unavailable.') for name in (quote,ledger)]
    gaps = stale = unknown_age = 0
    value = cost = 0.0
    valid = True
    for position in positions:
        pair = market.get(position['mint']) or {}
        price = number(pair.get('priceUsd'), True)
        stamp = number(pair.get('_ts'), True)
        gaps += price is None
        unknown_age += stamp is None
        stale += stamp is not None and not 0 <= now-stamp <= 120
        qty = number(position['qty'], True)
        basis = number(position['cost'], True)
        if price is not None and qty is not None:
            value += price*qty
        if basis is not None:
            cost += basis
        valid = valid and qty is not None and basis is not None
    flag = 'idle' if not positions else 'warning' if gaps or stale else 'unknown' if unknown_age else 'checked'
    qt = report(quote,flag,f'{len(positions)} open · {gaps} missing prices · {stale} stale · {unknown_age} unknown quote ages')
    totals = [number(shared.get(k)) for k in ('cash','equity','realized','start')]
    if not valid or None in totals:
        return [qt,report(ledger,'unknown','Missing ledger quantities or totals.')]
    cash,equity,realized,start = totals
    cash_gap = cash + cost - start - realized
    equity_gap = cash + value - equity
    if abs(cash_gap) > .02 or (not gaps and abs(equity_gap) > .02):
        audit = report(ledger,'mismatch',f'Cash difference ${cash_gap:+.2f} · equity difference '+(f'${equity_gap:+.2f}' if not gaps else 'unknown'))
    elif gaps:
        audit = report(ledger,'partial','Cash reconciled. Missing market price for equity check.')
    else:
        audit = report(ledger,'balanced',f'Cash and equity reconcile within $0.02 across {len(positions)} open positions.')
    return [qt,audit]
