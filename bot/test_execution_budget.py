import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from execution_budget import Budget, BudgetBlocked
from solana_message import encode_key

WALLET = 'FhWiTUyScxTneuBJwfnxHuLGtR96qvWG79qTYPsqcZFc'
SOL = 'So11111111111111111111111111111111111111112'
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
SIGNATURE = encode_key(bytes([2])*64)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'execution.db'
        self.budget = self.reopen()

    def reopen(self):
        return Budget(self.path, WALLET, SOL, 100, 40)

    def test_restart_retains_allocation_and_duplicate_identity(self):
        self.assertTrue(self.budget.reserve('one', USDC, 40)['new_reservation'])
        restarted = self.reopen()
        self.assertEqual(restarted.status()['remaining_atomic'], 60)
        self.assertFalse(restarted.reserve('one', USDC, 40)['new_reservation'])
        with self.assertRaises(BudgetBlocked):
            restarted.reserve('one', USDC, 30)

    def test_concurrent_reservations_cannot_overspend(self):
        def attempt(index):
            try:
                return self.reopen().reserve(str(index), USDC, 40)['new_reservation']
            except BudgetBlocked:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(self.budget.status()['remaining_atomic'], 20)

    def test_concurrent_duplicate_gets_one_reservation(self):
        def attempt(_):
            return self.reopen().reserve('same', USDC, 40)['new_reservation']
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(12))), 1)

    def test_uncertain_submission_stays_reserved_after_restart(self):
        self.budget.reserve('one', USDC, 40)
        self.assertTrue(self.budget.mark_submitted('one', SIGNATURE))
        restarted = self.reopen()
        self.assertFalse(restarted.mark_submitted('one', SIGNATURE))
        with self.assertRaises(BudgetBlocked):
            restarted.cancel_unsubmitted('one')
        self.assertEqual(restarted.status()['remaining_atomic'], 60)

    def test_confirmation_does_not_replenish_budget(self):
        self.budget.reserve('one', USDC, 40)
        with self.assertRaises(BudgetBlocked):
            self.budget.confirm('one', SIGNATURE)
        self.budget.mark_submitted('one', SIGNATURE)
        with self.assertRaises(BudgetBlocked):
            self.budget.confirm('one', '3'*87)
        self.budget.confirm('one', SIGNATURE)
        self.budget.confirm('one', SIGNATURE)
        self.assertEqual(self.budget.status()['remaining_atomic'], 60)

    def test_cancelled_id_cannot_be_reused(self):
        self.budget.reserve('one', USDC, 40)
        self.budget.cancel_unsubmitted('one')
        result = self.budget.reserve('one', USDC, 40)
        self.assertEqual(result, {'new_reservation': False, 'state': 'cancelled'})
        with self.assertRaises(BudgetBlocked):
            self.budget.mark_submitted('one', SIGNATURE)
        self.assertEqual(self.budget.status()['remaining_atomic'], 100)

    def test_policy_cannot_be_reset_on_restart(self):
        with self.assertRaises(BudgetBlocked):
            Budget(self.path, WALLET, SOL, 1000, 400)
        self.assertEqual(self.budget.status()['cap_atomic'], 100)

    def test_halt_survives_restart_and_blocks_pending_submission(self):
        self.budget.reserve('one', USDC, 40)
        self.budget.halt()
        restarted = self.reopen()
        self.assertTrue(restarted.status()['halted'])
        with self.assertRaises(BudgetBlocked):
            restarted.reserve('two', USDC, 1)
        with self.assertRaises(BudgetBlocked):
            restarted.mark_submitted('one', SIGNATURE)
        restarted.cancel_unsubmitted('one')

    def test_bad_amounts_and_limits_fail_without_allocation(self):
        for value in (True, 0, -1, 1.5, '2', 41, 2**63):
            with self.subTest(value=value), self.assertRaises(BudgetBlocked):
                self.budget.reserve('one', USDC, value)
        self.assertEqual(self.budget.status()['remaining_atomic'], 100)

    def test_signature_cannot_belong_to_two_intents(self):
        for name in ('one', 'two'):
            self.budget.reserve(name, USDC, 40)
        self.budget.mark_submitted('one', SIGNATURE)
        with self.assertRaises(BudgetBlocked):
            self.budget.mark_submitted('two', SIGNATURE)

    def test_invalid_signature_does_not_advance_state(self):
        self.budget.reserve('one', USDC, 40)
        for signature in ('1'*64, '2'*87, '0'*88, ''):
            with self.subTest(signature=signature), self.assertRaises(BudgetBlocked):
                self.budget.mark_submitted('one', signature)
        self.budget.cancel_unsubmitted('one')


if __name__ == '__main__':
    unittest.main()
