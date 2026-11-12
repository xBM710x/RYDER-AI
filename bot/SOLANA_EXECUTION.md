# Solana execution preparation

Status: **unsigned preflight only, not a live connection**.

`solana_preflight.py` uses Jupiter Swap API V2 `/order` and Solana
`simulateTransaction`. It neither loads signing keys nor submits transactions.
It does not change the runner, paper ledger, UI, or protective exits.

The operator supplies a wallet, input/output mints, amount and per-request cap
in integer atomic units, and slippage (1–100 bps). No budget is inferred from
paper equity. A Jupiter developer API key is required in the local environment
as `JUPITER_API_KEY`; do not commit it, publish it in data.json, or send it in chat.
This is an API credential, not a wallet private key.

Run `python solana_preflight.py --help` for arguments. The CLI prints a small
JSON report and exits 2 when blocked. A simulation success is not authorization,
proof of profit, or evidence a future transaction will land. It does not reserve
funds. Minimum output is checked against slippage, but the serialized provider
transaction is still untrusted. It must never be passed straight to a signer.

Before live execution, remaining implementation gates are:

- Decode and independently validate message instructions, programs, accounts,
  signer, recipients, exact spend, minimum received, fees and account creation.
- Secure local signing and explicit wallet/budget configuration (no private keys
  in this repository, dashboard, logs, or chat).
- Persistent atomic budget reservations, loss limits and duplicate-order guards.
- Expiry handling, simulation account-delta checks and confirmation reconciliation
  that handles dropped/ambiguous transactions without blind retries.
- Integrate approved agent decisions while retaining independent protective exits.
- Verify with fault-injection tests and dry runs before enabling execution.

Offline checks: `python -m unittest test_solana_message test_solana_preflight` from `bot/`.
Tests use fabricated transactions and mocked responses; they do not test live
provider credentials, valid transaction decoding, or actual swaps.

Provider reference: https://developers.jup.ag/docs/swap/order-and-execute

## Transaction envelope validation

Before simulation, `solana_message.py` parses the provider bytes as legacy or v0.
It checks canonical compact lengths, full consumption, bounded account indices,
unique static accounts, readonly static program references, and the configured
wallet as the writable fee payer and sole required signer. Signed inputs, extra
signers, unsupported versions, and malformed or truncated messages are rejected.

The report lists program IDs and the number of unresolved lookup accounts.
This is structural inspection only: a malicious but well-formed instruction
can pass it. Lookup resolution, program allowlisting, instruction decoding,
recipient/spend/fee checks and simulation balance-delta checks are still missing.
`authorized_to_sign` and `live_ready` remain false, including after simulation
success. Routes using sponsored fee payers, extra signers, or v1 are currently
unsupported. This does not add Phantom auto-approval or unattended trading.

## Persistent budget reservations

`execution_budget.Budget` is a standalone SQLite ledger for a single explicitly
configured wallet and input mint. It requires total and per-request caps in
atomic units; there are no defaults and no inferred live budget. Use a separate
local database, never the paper ledger or a public feed.

Reservations use BEGIN IMMEDIATE so competing processes cannot overspend.
A stable intent ID is persisted; replay returns `new_reservation=False`, which
must never authorize another submission. Conflicting reuse is rejected.
Persist `mark_submitted` with the signed transaction signature BEFORE any network
submission. Ambiguous submission retains its reservation after restart. This
module cannot release submitted reservations; a future independently verified
reconciler must handle failed/expired transactions and actual costs.

Confirmed spending stays charged against the lifetime allocation. Sale proceeds
do not automatically replenish it. Fee allowances in the input currency must be
included in the reserved amount; other fee currencies, actual wallet balance
checks, positions, daily loss accounting and policy-authorized renewal remain
unimplemented. `confirm` is an internal state transition, not an RPC verifier.
The persisted halt blocks reservations and submission transitions; it is not
an on-chain cancellation and cannot stop transactions already sent.

This ledger is not connected to runner decisions, signing, or submissions.
Do not apply an entry-only budget halt to protective exits without a separately
validated exit policy. Existing paper exits are unchanged. No real budget has
been configured. Run `python -m unittest test_execution_budget` for restart,
concurrency, idempotency and halt tests.
