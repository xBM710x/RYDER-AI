"""Persistent single-wallet, single-input-mint execution reservations.

Standalone infrastructure only. Does not sign, submit, or enable live trading.
Amounts are atomic input units INCLUDING an explicitly reserved fee allowance
when fees use this mint. Other fee currencies need their own policy.
"""
import sqlite3
from contextlib import contextmanager


class BudgetBlocked(ValueError):
    pass


def amount(value):
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise BudgetBlocked('Amount must be a positive SQLite-safe integer')
    return value


class Budget:
    def __init__(self, path, wallet, input_mint, total_cap, per_trade_cap):
        from solana_preflight import address
        address(wallet)
        address(input_mint)
        amount(total_cap)
        amount(per_trade_cap)
        if per_trade_cap > total_cap:
            raise BudgetBlocked('Per-trade cap exceeds total cap')
        self.path = str(path)
        if self.path == ':memory:':
            raise BudgetBlocked('A persistent database path is required')
        with self._write() as db:
            db.execute('CREATE TABLE IF NOT EXISTS execution_policy '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), wallet TEXT, mint TEXT, '
                       'total_cap INTEGER, trade_cap INTEGER, halted INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS execution_reservations '
                       '(intent_id TEXT PRIMARY KEY, output_mint TEXT NOT NULL, '
                       'amount INTEGER NOT NULL, state TEXT NOT NULL, signature TEXT UNIQUE)')
            policy = (wallet, input_mint, total_cap, per_trade_cap)
            row = db.execute('SELECT wallet,mint,total_cap,trade_cap FROM execution_policy WHERE id=1').fetchone()
            if row is None:
                db.execute('INSERT INTO execution_policy VALUES(1,?,?,?,?,0)', policy)
            elif tuple(row) != policy:
                raise BudgetBlocked('Existing policy differs; cannot silently reset budget')

    @contextmanager
    def _write(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(self, intent_id, output_mint, atomic_amount):
        from solana_preflight import address
        address(output_mint)
        amount(atomic_amount)
        if not isinstance(intent_id, str) or not 1 <= len(intent_id) <= 128:
            raise BudgetBlocked('Stable intent ID is required')
        with self._write() as db:
            policy = db.execute('SELECT mint,total_cap,trade_cap,halted FROM execution_policy WHERE id=1').fetchone()
            if policy[3]:
                raise BudgetBlocked('Execution is halted')
            if output_mint == policy[0]:
                raise BudgetBlocked('Input and output mint must differ')
            row = db.execute('SELECT output_mint,amount,state FROM execution_reservations WHERE intent_id=?', (intent_id,)).fetchone()
            if row:
                if (row[0], row[1]) != (output_mint, atomic_amount):
                    raise BudgetBlocked('Intent ID reused with different trade details')
                # A repeat must never be interpreted as permission to submit again.
                return {'new_reservation': False, 'state': row[2]}
            used = db.execute("SELECT COALESCE(SUM(amount),0) FROM execution_reservations WHERE state!='cancelled'").fetchone()[0]
            if atomic_amount > policy[2] or atomic_amount > policy[1] - used:
                raise BudgetBlocked('Execution budget exceeded')
            db.execute("INSERT INTO execution_reservations VALUES(?,?,?,'reserved',NULL)",
                       (intent_id, output_mint, atomic_amount))
            return {'new_reservation': True, 'state': 'reserved'}

    def mark_submitted(self, intent_id, signature):
        # Must be persisted BEFORE sending signed bytes. A crash retains the
        # reservation as uncertain. Reconciliation must not blindly resend it.
        if not isinstance(signature, str) or not 64 <= len(signature) <= 88:
            raise BudgetBlocked('Transaction signature is required')
        from solana_message import ALPHABET
        if any(char not in ALPHABET for char in signature):
            raise BudgetBlocked('Invalid transaction signature')
        number = 0
        for char in signature:
            number = number * 58 + ALPHABET.index(char)
        size = (number.bit_length() + 7) // 8 + len(signature) - len(signature.lstrip('1'))
        if size != 64 or not number:
            raise BudgetBlocked('Expected a nonzero 64-byte transaction signature')
        with self._write() as db:
            if db.execute('SELECT halted FROM execution_policy WHERE id=1').fetchone()[0]:
                raise BudgetBlocked('Execution is halted')
            row = db.execute('SELECT state,signature FROM execution_reservations WHERE intent_id=?', (intent_id,)).fetchone()
            if row and row[0] in ('submitted', 'confirmed') and row[1] == signature:
                return False
            if not row or row[0] != 'reserved':
                raise BudgetBlocked('Intent is not reserved')
            try:
                db.execute("UPDATE execution_reservations SET state='submitted',signature=? WHERE intent_id=?", (signature, intent_id))
            except sqlite3.IntegrityError:
                raise BudgetBlocked('Signature already associated with another intent') from None
            return True

    def confirm(self, intent_id, signature):
        # Called only by a future independently verified on-chain reconciler.
        with self._write() as db:
            row = db.execute('SELECT state,signature FROM execution_reservations WHERE intent_id=?', (intent_id,)).fetchone()
            if not row or row[0] not in ('submitted', 'confirmed') or row[1] != signature:
                raise BudgetBlocked('Confirmation does not match pending transaction')
            db.execute("UPDATE execution_reservations SET state='confirmed' WHERE intent_id=?", (intent_id,))

    def cancel_unsubmitted(self, intent_id):
        with self._write() as db:
            row = db.execute('SELECT state FROM execution_reservations WHERE intent_id=?', (intent_id,)).fetchone()
            if not row or row[0] != 'reserved':
                raise BudgetBlocked('Only unsubmitted reservations can be released')
            db.execute("UPDATE execution_reservations SET state='cancelled' WHERE intent_id=?", (intent_id,))

    def halt(self):
        with self._write() as db:
            db.execute('UPDATE execution_policy SET halted=1 WHERE id=1')

    def status(self):
        with self._write() as db:
            total, halted = db.execute('SELECT total_cap,halted FROM execution_policy WHERE id=1').fetchone()
            used = db.execute("SELECT COALESCE(SUM(amount),0) FROM execution_reservations WHERE state!='cancelled'").fetchone()[0]
            return dict(cap_atomic=total, reserved_or_spent_atomic=used,
                        remaining_atomic=total-used, halted=bool(halted), live_ready=False)
