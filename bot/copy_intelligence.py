"""Read-only wallet-event adapter for RYDER paper intelligence.

Provider-neutral: accepts verified, normalized events supplied by an upstream
Solana indexer. This module does not claim FOMO API access, query wallets,
sign transactions, or execute trades.
"""
import math
from dataclasses import dataclass
from dual_intelligence import Signal, decide


@dataclass(frozen=True)
class WalletEvent:
    wallet: str
    mint: str
    side: str
    observed_at: float
    liquidity_usd: float
    confidence: float = 0.0
    signature: str = ""
    provider: str = "external"


def normalize_copy_event(event, *, approved_wallets):
    """Fail closed on unapproved wallets, malformed data and duplicates upstream.

    Confidence must be independently estimated from historical *net* outcomes;
    an event alone is not evidence that its wallet is profitable.
    """
    if not isinstance(event, WalletEvent) or not event.wallet or event.wallet not in approved_wallets:
        return None
    if not event.mint or not event.signature or event.side not in ("BUY", "SELL"):
        return None
    values = (event.observed_at, event.liquidity_usd, event.confidence)
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values):
        return None
    if event.liquidity_usd < 0 or not 0 <= event.confidence <= 1:
        return None
    return Signal("copy", event.mint, event.side, event.confidence,
                  event.liquidity_usd, event.observed_at, wallet=event.wallet,
                  reason="wallet_event:" + event.provider)


class PaperSignalDesk:
    """Idempotent paper signal journal; does not mutate live bot positions."""
    def __init__(self, approved_wallets=()):
        self.approved_wallets = frozenset(approved_wallets)
        self.seen_signatures = set()
        self.history = []

    def evaluate(self, event, independent_signals, now):
        if event.signature in self.seen_signatures:
            return None
        copy = normalize_copy_event(event, approved_wallets=self.approved_wallets)
        if copy is None:
            return None
        self.seen_signatures.add(event.signature)
        decision = decide([copy] + list(independent_signals), now)
        self.history.append(dict(mint=event.mint, wallet=event.wallet,
                                 signature=event.signature, decision=decision.action,
                                 reason=decision.reason, paper_only=True,
                                 observed_at=now))
        return decision
