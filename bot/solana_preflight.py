"""Unsigned Solana swap preparation. Never signs, submits, or changes paper books.

Provider transaction bytes remain UNTRUSTED even after simulation. This is not
a signing policy or a live executor; see SOLANA_EXECUTION.md.
"""
import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from solana_message import inspect_unsigned, InvalidMessage

JUPITER = 'https://api.jup.ag/swap/v2/order'
RPC = 'https://api.mainnet-beta.solana.com'
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


class Blocked(ValueError):
    pass


def address(value):
    if not isinstance(value, str) or not 32 <= len(value) <= 44:
        raise Blocked('Invalid public address')
    number = 0
    for char in value:
        if char not in ALPHABET:
            raise Blocked('Invalid public address')
        number = number * 58 + ALPHABET.index(char)
    size = (number.bit_length() + 7) // 8 + len(value) - len(value.lstrip('1'))
    if size != 32:
        raise Blocked('Public address must decode to 32 bytes')
    return value


def positive_int(value):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
        raise Blocked('Expected positive integer atomic units')
    value = int(value)
    if not 0 < value <= 2**64 - 1:
        raise Blocked('Atomic amount outside u64 range')
    return value


@dataclass(frozen=True)
class Intent:
    wallet: str
    input_mint: str
    output_mint: str
    amount: int
    max_input: int
    slippage_bps: int

    def validate(self):
        for value in (self.wallet, self.input_mint, self.output_mint):
            address(value)
        if self.input_mint == self.output_mint:
            raise Blocked('Input and output mint must differ')
        if positive_int(self.amount) > positive_int(self.max_input):
            raise Blocked('Input exceeds configured per-request cap')
        if type(self.slippage_bps) is not int or not 1 <= self.slippage_bps <= 100:
            raise Blocked('Preflight slippage must be 1–100 bps')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Blocked('Provider redirects are not allowed')


def request_json(url, headers=None, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
        headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=12) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise Blocked('Provider response too large')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise Blocked('Invalid provider response')
        return result
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        if isinstance(exc, Blocked):
            raise
        # Never echo request headers, API keys, or provider response bodies.
        raise Blocked('Provider request failed or returned invalid JSON') from None


def prepare(intent, api_key, transport=request_json, clock=time.monotonic):
    intent.validate()
    if not api_key:
        raise Blocked('JUPITER_API_KEY is required; do not paste it into chat')
    started = clock()
    params = dict(inputMint=intent.input_mint, outputMint=intent.output_mint,
        amount=str(intent.amount), taker=intent.wallet,
        slippageBps=str(intent.slippage_bps))
    order = transport(JUPITER + '?' + urllib.parse.urlencode(params),
                      headers={'x-api-key': api_key})
    if not isinstance(order, dict):
        raise Blocked('Invalid order response')
    if order.get('errorCode') is not None or order.get('error'):
        raise Blocked('Provider could not prepare this swap')
    for key, expected in [('inputMint', intent.input_mint), ('outputMint', intent.output_mint)]:
        if order.get(key) != expected:
            raise Blocked('Provider mint mismatch')
    if positive_int(order.get('inAmount')) != intent.amount:
        raise Blocked('Provider input amount mismatch')
    out = positive_int(order.get('outAmount'))
    minimum = positive_int(order.get('otherAmountThreshold'))
    if not (out * (10000-intent.slippage_bps) // 10000 <= minimum <= out):
        raise Blocked('Provider minimum output violates slippage cap')
    if type(order.get('slippageBps')) is not int or order['slippageBps'] != intent.slippage_bps:
        raise Blocked('Provider slippage mismatch')
    try:
        impact = Decimal(str(order['priceImpactPct']))
    except (KeyError, InvalidOperation):
        raise Blocked('Missing valid price impact') from None
    if not impact.is_finite() or abs(impact) > Decimal('1'):
        raise Blocked('Price impact exceeds preflight 1 percent cap')
    tx = order.get('transaction')
    try:
        decoded = base64.b64decode(tx, validate=True)
    except (ValueError, TypeError):
        raise Blocked('Missing valid unsigned transaction') from None
    if not 65 <= len(decoded) <= 1232:
        raise Blocked('Transaction size outside Solana limits')
    try:
        message = inspect_unsigned(decoded, intent.wallet)
    except InvalidMessage as exc:
        raise Blocked(str(exc)) from None
    if not isinstance(order.get('requestId'), str) or not order['requestId']:
        raise Blocked('Missing provider request ID')
    if clock() - started > 15:
        raise Blocked('Prepared response is stale; request a fresh quote')
    simulation = transport(RPC, payload={'jsonrpc': '2.0', 'id': 1,
        'method': 'simulateTransaction', 'params': [tx, {
            'encoding': 'base64', 'sigVerify': False,
            'replaceRecentBlockhash': True, 'commitment': 'confirmed'}]})
    if not isinstance(simulation, dict) or not isinstance(simulation.get('result'), dict):
        raise Blocked('Simulation unavailable')
    value = simulation['result'].get('value')
    if simulation.get('error') or not isinstance(value, dict) or 'err' not in value:
        raise Blocked('Simulation unavailable')
    if value['err'] is not None:
        raise Blocked('Transaction simulation failed')
    if clock() - started > 30:
        raise Blocked('Simulation result is stale')
    # Do not expose transaction bytes as signing-ready or persist expiring orders.
    return dict(status='simulation_passed_unsigned', live_ready=False,
        wallet=intent.wallet, input_mint=intent.input_mint,
        output_mint=intent.output_mint, input_atomic=intent.amount,
        expected_output_atomic=out, minimum_output_atomic=minimum,
        units_consumed=value.get('unitsConsumed'),
        message_inspection=message,
        blockers=['instruction_and_account_validation', 'secure_signer',
                  'persistent_budget_and_duplicate_guard', 'confirmation_reconciliation'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('wallet', 'input-mint', 'output-mint'):
        parser.add_argument('--'+flag, required=True)
    for flag in ('amount', 'max-input', 'slippage-bps'):
        parser.add_argument('--'+flag, type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(Intent(**vars(args)), os.getenv('JUPITER_API_KEY')), indent=2))
    except Blocked as exc:
        print(json.dumps({'status': 'blocked', 'live_ready': False, 'reason': str(exc)}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
