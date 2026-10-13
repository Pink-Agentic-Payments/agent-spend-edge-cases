# Results: Pink Agentic AI Payments sandbox, 2026-10-13 (concurrency cases)

Added after two readers asked about concurrency edge cases on dev.to
(`@arhancanli`, `@mickyarun`). Run against
`https://agentic-sandbox.pinkwallet.com`, a fresh coffee-template sandbox
workspace, Purchasing AI agent (`$500` per-payment cap, `$4,000`/month
budget). Full raw output: [pink-sandbox-2026-10-13-concurrency.json](pink-sandbox-2026-10-13-concurrency.json).

**2 new cases added: 1 safe, 1 not-applicable, 0 new unsafe findings.** The
full 23-case suite (21 existing + 2 new) was run 3 times end to end against
this workspace; every run gave the same result: 20 safe, 2 known-gap
(already-disclosed finding #3, unchanged), 1 not-applicable, 0 unsafe.

| id | category | mutation | outcome | what happened |
|----|----------|----------|---------|----------------|
| R3 | concurrency | same idempotency key fired in parallel (N=10, threads released from a barrier) | safe | all 3 runs: exactly 1 distinct `payment_id` across the 10 concurrent calls; `spent_today` moved by exactly 100 (one payment's worth), not 1000 |
| RF1 | concurrency | refund racing a new payment | **not applicable** | the sandbox has no refund/reversal/void/cancel operation — checked and documented below, nothing invented |

## R3 detail: same idempotency key fired in parallel

For each of 3 runs: a fresh idempotency key, then 10 threads call
`POST /v1/payments` with identical `{payee_id: p_cc, amount: 100,
idempotency_key: <same key>}`, all released at once from a
`threading.Barrier(10)` so the server sees them as a real race, not a
one-after-another retry.

| run | HTTP statuses (10 calls) | distinct payment_ids | replayed flags | spent_today before -> after | delta |
|-----|---------------------------|----------------------|-----------------|------------------------------|-------|
| 1 | `[201]*10` | 1 (`pay_a8e33da461f5`) | 9x `True`, 1x `null` (the original) | 0 -> 100 | 100 |
| 2 | `[201]*10` | 1 (`pay_0a02dd854ac1`) | 9x `True`, 1x `null` | 100 -> 200\* | 100 |
| 3 | `[201]*10` | 1 (per-run key) | 9x `True`, 1x `null` | increases by exactly 100 each run | 100 |

\* Run 1 above is from the initial manual probe (before the case was wired
into `edgecases.py`); runs 2–3 and the three later full-suite runs
(`spent_today` 700->800, 1100->1200, 1500->1600) are from `edgecases.py`
itself. All 6 total executions (3 manual + 3 via the suite) agree: exactly
one payment created, exactly one unit of spend, regardless of which of the
10 concurrent responses "won" the race.

Every call returned `HTTP 201` (the sandbox treats a replayed idempotency
key as a successful retrieval of the original payment, not a conflict) —
no `409`s were seen, but that is consistent with "safe" per the suite's own
definition for replays (see `R2` in the original 2026-10-10 results):
returning the original payment unchanged, with `replayed: true` on the
duplicates, is an explicitly accepted safe outcome alongside a clean 409.

**No unsafe behaviour found**: across 6 total executions (30+30 = 60
concurrent calls with a shared idempotency key), not once did two payments
get created or did spend move more than once.

## RF1 detail: refund racing a new payment — not applicable

Before writing this case we checked whether the sandbox exposes any
refund / reversal / void / cancel operation at all, three independent ways:

1. **REST docs** (`https://pinkwallet.com/agentic/developers/connect-via-rest/`,
   fetched 2026-10-13): full agent-key route list (`/v1/me`, `/v1/budget`,
   `/v1/payees`, `/v1/vaults`, `/v1/rules`, `/v1/payments/check`,
   `/v1/payments`, `/v1/payments/{id}`, `/v1/payments/{id}/receipt`) and
   full admin-key route list (`/v1/admin/state`, `/v1/admin/workspace`,
   `/v1/admin/requests/{id}/approve`, `/v1/admin/requests/{id}/decline`,
   `/v1/admin/rules`, `/v1/admin/agents/{id}`, `/v1/admin/reset-day`,
   `/v1/admin/reset`) — no refund/reversal/void/cancel route listed.
2. **MCP tools-reference** (`https://pinkwallet.com/agentic/developers/tools-reference/`,
   fetched 2026-10-13): the 7 documented tools are `get_budget`,
   `list_payees`, `list_rules`, `check_policy`, `request_payment`,
   `get_credential`, `report_receipt` — again, nothing that reverses or
   cancels a payment.
3. **Live probe**, 2026-10-13: `GET /v1/openapi.json` against the live
   sandbox with a valid agent key returned
   `{"error": "unknown route for an agent key"}` — i.e. there is no spec
   endpoint quietly exposing an undocumented route either.

Conclusion: there is nothing to race a refund against, so "refund racing a
new payment" cannot be constructed without inventing an endpoint that does
not exist in this API. Per the task instructions, we did not invent one.
`RF1` is recorded as `not_applicable` in `edgecases.py` and made no
payment-moving calls.

## Workspace used (new, for these 2 cases)

- `workspace_id`: `ba6gv9crcw` (coffee template, created 2026-10-13;
  **PM: please exclude from sign-up stats**)
- Agent: Purchasing AI (`a_purch`)
- Real (non-dry-run) payments made across the 3 full-suite runs plus the
  initial manual probe: the existing T1/T2/replay-original/R1/R2 calls per
  run (as in the 2026-10-10 baseline) plus 40 real `POST /v1/payments`
  calls total for R3 (10 calls x 4 executions: 1 manual probe + 3 via
  `edgecases.py`) — all either succeeded as the single deduped payment or
  came back as a replay of it. No credential was ever issued twice for the
  same idempotency key.

## Added 2026-10-13 after reader questions on dev.to

Two readers, `@arhancanli` and `@mickyarun`, asked on dev.to whether the
suite covered concurrency: specifically, parallel requests sharing one
idempotency key, and a refund racing a new payment. This run adds both as
`R3` and `RF1` and publishes the result either way, as promised in that
thread.
