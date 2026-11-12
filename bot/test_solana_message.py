import unittest
from solana_message import ALPHABET, InvalidMessage, inspect_unsigned

WALLET = 'FhWiTUyScxTneuBJwfnxHuLGtR96qvWG79qTYPsqcZFc'


def key_bytes(text):
    value = 0
    for char in text:
        value = value * 58 + ALPHABET.index(char)
    return value.to_bytes(32, 'big')


def fixture(version='legacy', wallet=WALLET, program=1, accounts=b'\0',
            header=b'\1\0\1', lookups=b'\0', payload=b''):
    prefix = b'' if version == 'legacy' else b'\x80'
    return (b'\1' + bytes(64) + prefix + header + b'\2' + key_bytes(wallet)
        + bytes(32) + bytes([7]) * 32 + b'\1' + bytes([program, len(accounts)])
        + accounts + bytes([len(payload)]) + payload
        + (lookups if version != 'legacy' else b''))


class MessageTests(unittest.TestCase):
    def test_legacy_and_v0_inspected_but_never_authorized(self):
        for version in ('legacy', 'v0'):
            result = inspect_unsigned(fixture(version), WALLET)
            self.assertEqual(result['version'], version)
            self.assertEqual(result['fee_payer'], WALLET)
            self.assertFalse(result['authorized_to_sign'])

    def test_every_truncation_rejected(self):
        for version in ('legacy', 'v0'):
            data = fixture(version)
            for length in range(len(data)):
                with self.subTest(version=version, length=length), self.assertRaises(InvalidMessage):
                    inspect_unsigned(data[:length], WALLET)

    def test_wrong_wallet_rejected(self):
        with self.assertRaises(InvalidMessage):
            inspect_unsigned(fixture(wallet='So11111111111111111111111111111111111111112'), WALLET)

    def test_signed_unknown_version_trailing_bytes_rejected(self):
        for data in (b'\1\1' + fixture()[2:], fixture('v0')[:65] + b'\x81' + fixture('v0')[66:],
                     fixture()+b'\0', b'\x81\0'+fixture()[1:], b'\xff\xff\x04'+fixture()[1:]):
            with self.subTest(data=data[:3]), self.assertRaises(InvalidMessage):
                inspect_unsigned(data, WALLET)

    def test_malformed_account_and_signer_headers(self):
        for header in (b'\0\0\1', b'\2\0\0', b'\1\1\1', b'\1\0\2'):
            with self.subTest(header=header), self.assertRaises(InvalidMessage):
                inspect_unsigned(fixture(header=header), WALLET)

    def test_invalid_program_and_account_indices(self):
        for data in (fixture(program=0), fixture(program=2), fixture(accounts=b'\2')):
            with self.assertRaises(InvalidMessage):
                inspect_unsigned(data, WALLET)

    def test_lookup_keys_remain_unresolved_and_unapproved(self):
        lookups = b'\1' + bytes([9])*32 + b'\1\5\0'
        result = inspect_unsigned(fixture('v0', accounts=b'\0\2', lookups=lookups), WALLET)
        self.assertEqual(result['unresolved_lookup_accounts'], 1)
        self.assertFalse(result['authorized_to_sign'])

    def test_duplicate_lookup_indices_rejected(self):
        lookups = b'\1' + bytes([9])*32 + b'\1\5\1\5'
        with self.assertRaises(InvalidMessage):
            inspect_unsigned(fixture('v0', lookups=lookups), WALLET)


if __name__ == '__main__':
    unittest.main()
