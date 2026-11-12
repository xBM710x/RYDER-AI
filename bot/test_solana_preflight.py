import base64
import unittest
from urllib.parse import parse_qs, urlparse
from solana_preflight import Blocked, Intent, prepare, address, request_json

SOL = 'So11111111111111111111111111111111111111112'
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
WALLET = 'FhWiTUyScxTneuBJwfnxHuLGtR96qvWG79qTYPsqcZFc'


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.intent = Intent(WALLET, SOL, USDC, 1000, 1000, 50)
        self.order = dict(inputMint=SOL, outputMint=USDC, inAmount='1000',
            outAmount='2000', otherAmountThreshold='1990', slippageBps=50,
            priceImpactPct='0.1', requestId='test-only',
            transaction=base64.b64encode(bytes(100)).decode())
        self.sim = {'result': {'value': {'err': None, 'unitsConsumed': 15000}}}
        self.calls = []

    def transport(self, url, headers=None, payload=None):
        self.calls.append((url, headers, payload))
        return self.order if payload is None else self.sim

    def run_prepare(self, **kwargs):
        return prepare(self.intent, 'test-key', self.transport, **kwargs)

    def test_simulates_without_signing_or_submission(self):
        result = self.run_prepare()
        self.assertFalse(result['live_ready'])
        self.assertEqual(result['status'], 'simulation_passed_unsigned')
        self.assertNotIn('transaction', result)
        self.assertEqual(len(self.calls), 2)
        query = parse_qs(urlparse(self.calls[0][0]).query)
        self.assertEqual(query['amount'], ['1000'])
        self.assertEqual(query['taker'], [WALLET])
        self.assertIsNone(self.calls[1][1])  # Jupiter key never sent to RPC
        self.assertEqual(self.calls[1][2]['method'], 'simulateTransaction')

    def test_no_key_makes_no_request(self):
        with self.assertRaises(Blocked):
            prepare(self.intent, '', self.transport)
        self.assertEqual(self.calls, [])

    def test_amount_cap_and_invalid_slippage(self):
        for overrides in ({'amount': 1001}, {'amount': -1}, {'amount': True},
                          {'max_input': 0}, {'slippage_bps': 101}, {'slippage_bps': True}):
            with self.subTest(overrides=overrides), self.assertRaises(Blocked):
                prepare(Intent(**{**vars(self.intent), **overrides}), 'key', self.transport)
        self.assertEqual(self.calls, [])

    def test_invalid_addresses_and_same_mint(self):
        for bad in ('0'*44, '1'*31, '1'*33, '', None):
            with self.subTest(address=bad), self.assertRaises(Blocked):
                address(bad)
        with self.assertRaises(Blocked):
            prepare(Intent(WALLET, SOL, SOL, 1, 1, 50), 'key', self.transport)

    def test_provider_mismatches_fail_before_simulation(self):
        original = self.order.copy()
        for field, value in [('inputMint', USDC), ('outputMint', SOL),
                ('inAmount', '1001'), ('outAmount', '0'),
                ('otherAmountThreshold', '1989'), ('otherAmountThreshold', '2001'),
                ('slippageBps', 100), ('priceImpactPct', 'NaN'),
                ('priceImpactPct', 'Infinity'), ('priceImpactPct', '1.1'),
                ('transaction', ''), ('transaction', 'not-base64'),
                ('requestId', ''), ('errorCode', 1)]:
            self.order = {**original, field: value}
            self.calls = []
            with self.subTest(field=field, value=value), self.assertRaises(Blocked):
                self.run_prepare()
            self.assertEqual(len(self.calls), 1)

    def test_simulation_failure_and_unknown_are_blocked(self):
        for value in ({'error': {'code': -1}}, {}, {'result': {'value': {}}},
                      {'result': {'value': {'err': {'InstructionError': [0, 'failure']}}}}):
            self.sim = value
            with self.subTest(sim=value), self.assertRaises(Blocked):
                self.run_prepare()

    def test_stale_quote_and_simulation(self):
        for readings in ([0, 16], [0, 1, 31]):
            ticks = iter(readings)
            with self.subTest(readings=readings), self.assertRaises(Blocked):
                self.run_prepare(clock=lambda: next(ticks))

    def test_transport_failure_never_returns_success(self):
        def fail(*args, **kwargs):
            raise Blocked('Provider request failed')
        with self.assertRaises(Blocked):
            prepare(self.intent, 'test', fail)


if __name__ == '__main__':
    unittest.main()
