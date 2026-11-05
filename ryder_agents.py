"""RYDER optional paper-only intelligence agents.

Import evaluate_agents(snapshot) in the Mac publisher and merge its returned
records into data.json["agents"]. No orders, wallet access or network requests.
Missing evidence is reported as unknown, never fabricated.
"""
from datetime import datetime, timezone
from math import isfinite

def _number(value):
    try:
        v = float(value)
        return v if isfinite(v) else None
    except (ValueError, TypeError):
        return None

def evaluate_agents(snapshot):
    """Return three evidence-based agent summaries from a publisher snapshot."""
    tokens = snapshot.get("candidates", [])
    if not isinstance(tokens, list):
        tokens = []
    ranked = []
    suspicious = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        symbol = str(token.get("symbol") or "Unknown")[:24]
        volume = _number(token.get("volume_24h"))
        liquidity = _number(token.get("liquidity_usd"))
        change = _number(token.get("price_change_1h"))
        if volume is not None and liquidity is not None and change is not None and liquidity > 0:
            score = min(volume / liquidity, 20) + max(min(change, 100), -100) / 20
            ranked.append((score, symbol))
        if liquidity is not None and liquidity < 25000:
            suspicious.append(symbol + ": low liquidity")
        if token.get("mint_authority_enabled") is True:
            suspicious.append(symbol + ": mint authority enabled")
        if token.get("freeze_authority_enabled") is True:
            suspicious.append(symbol + ": freeze authority enabled")
    ranked.sort(reverse=True)
    closed = snapshot.get("closed", [])
    closed = closed if isinstance(closed, list) else []
    returns = [_number(t.get("pnl")) for t in closed if isinstance(t, dict)]
    returns = [v for v in returns if v is not None]
    hunter = ("Top candidate: " + ranked[0][1] + " (review required)") if ranked else "Waiting for scored token evidence"
    strategist = (f"{len(returns)} recorded outcomes · net ${sum(returns):+.2f}; no parameter changes" if returns else "Waiting for recorded trade outcomes")
    sentinel = (f"{len(suspicious)} risk flag(s): " + suspicious[0] if suspicious else
                ("No flagged risks in available fields; safety unverified" if tokens else "Waiting for token safety evidence"))
    return [
        {"name": "Hunter", "stat": f"{len(ranked)} ranked", "text": hunter, "tone": ""},
        {"name": "Strategist", "stat": f"{len(returns)} outcomes", "text": strategist, "tone": ""},
        {"name": "Sentinel", "stat": f"{len(suspicious)} flags", "text": sentinel, "tone": "red" if suspicious else ""},
    ]

if __name__ == "__main__":
    sample = {"candidates": [{"symbol": "TEST", "volume_24h": 100000, "liquidity_usd": 15000,
                               "price_change_1h": 5, "mint_authority_enabled": True}],
              "closed": [{"pnl": 2.4}]}
    result = evaluate_agents(sample)
    assert len(result) == 3 and result[0]["name"] == "Hunter"
    assert "TEST" in result[2]["text"]
    print("RYDER agent smoke test passed")
