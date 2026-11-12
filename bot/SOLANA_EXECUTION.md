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

Offline checks: `python -m unittest test_solana_preflight` from `bot/`.
Tests use fabricated transactions and mocked responses; they do not test live
provider credentials, valid transaction decoding, or actual swaps.

Provider reference: https://developers.jup.ag/docs/swap/order-and-execute
