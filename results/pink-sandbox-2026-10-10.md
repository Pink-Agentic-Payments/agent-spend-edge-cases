# Results: Pink Agentic AI Payments sandbox, 2026-10-10

Run against `https://agentic-sandbox.pinkwallet.com`, coffee-template sandbox
workspace, Purchasing AI agent (`$500` per-payment cap, `$4,000`/month
budget). Full raw output: [pink-sandbox-2026-10-10.json](pink-sandbox-2026-10-10.json).

21 cases: 19 safe, 2 known-gap (already-disclosed, fix in progress), 0 new
unsafe findings, 0 errors. 5 real (non-dry-run) payments made, all either
held for human approval or rejected — no credential was issued to any
mutated-input case.

| id | category | mutation | outcome | what happened |
|----|----------|----------|---------|----------------|
| C1 | currency | `"EUR "` (trailing space) | safe | HTTP 400, rejected |
| C2 | currency | `" EUR"` (leading space) | safe | HTTP 400, rejected |
| C3 | currency | `"usd"` (lowercase) | safe | evaluated exactly as plain USD (`would_ask`, night-hours rule) |
| C4 | currency | `"XYZ"` (unknown code) | safe | HTTP 400, rejected |
| C5 | currency | `""` (empty string) | safe | evaluated exactly as plain USD (`would_ask`) |
| C6 | currency | `1` (number, not string) | safe | HTTP 400, rejected |
| A1 | amount | `500.0001` (sub-cent) | **known-gap** | `would_allow` — reproduces the disclosed finding #3 (decimal-place rejection not live yet) |
| A2 | amount | `1500.5` JPY (0 decimals allowed) | **known-gap** | `would_allow` — same gap, JPY side |
| A3 | amount | `-100` (negative) | safe | HTTP 400, rejected |
| A4 | amount | `0` (zero) | safe | HTTP 400, rejected |
| A5 | amount | `"5e2"` (scientific, string) | safe | evaluated exactly as `500` |
| A6 | amount | `5e2` (scientific, number) | safe | evaluated exactly as `500` |
| A7 | amount | `"500"` (string, not number) | safe | evaluated exactly as `500` |
| A8 | amount | `1e15` (very large) | safe | `would_block`, stricter than canonical (budget exceeded) |
| A9 | amount | `"NaN"` (string) | safe | HTTP 400, rejected |
| T1 | time | `local_hour` on a **real** payment | safe | ignored; real-clock decision (`pending_human`, it was 23:34 local) |
| T2 | time | `timestamp`/`created_at` on a **real** payment | safe | ignored; same real-clock decision |
| R1 | replay | same idempotency key, different amount | safe | HTTP 409, rejected |
| R2 | replay | same idempotency key, identical payload | safe | original payment returned (`replayed: true`), not re-evaluated |
| P1 | payee | payee name in ALL CAPS | safe | recognised as the same approved payee |
| P2 | payee | payee name with padding whitespace | safe | treated as an unrecognised ("new") payee — stricter, not looser |

## Known-gap detail (A1, A2)

Both reproduce the already-disclosed and credited finding #3
(`@kimutaiRop`, [issue #3](https://github.com/Pink-Agentic-Payments/overspend-challenge/issues/3)):
amounts with more decimal places than the currency allows are not yet
rejected, so a sub-cent amount like `500.0001` still matches the same rule
a plain `500.00` would (`would_allow`, rule r4). Per the project's own Fix
log (2026-10-10), the fix — reject amounts with excess decimal places with
HTTP 400 before any rule runs — is **in progress**, not yet live as of this
run. This is not a new finding; it's included here only so the suite is
honest about what still fails and will flip to "safe" automatically once
the fix ships. No credential was pulled in either case (dry runs only).

## Notes worth a second look (not unsafe, not new)

- **C3/C5** (lowercase `"usd"`, empty string `""`): both got evaluated
  exactly like a plain `"USD"` request rather than rejected, even though
  the project's currency-validation fix log describes rejecting "any
  currency that isn't exactly one of USD, EUR, GBP, HKD, SGD, JPY." We
  cross-checked this at a daytime hour with a $700 amount (above the
  $500 auto-allow cap) and the decision still matched the plain-USD
  canonical exactly (`would_ask`, store-manager tier) — so the value is
  being priced correctly as USD, not exploited into a different (looser)
  threshold. Flagged as a documentation/validation inconsistency, not a
  spending-rule bypass.
- **P2** (padded payee name): the padded name was *not* recognised as the
  existing approved payee and instead got asked for owner approval as an
  unrecognised payee — stricter than the canonical decision, so safe, but
  worth knowing if you rely on payee-name matching rather than payee IDs.

## Workspace used

- `workspace_id`: `gt01ftuu5o` (coffee template, created 2026-10-10; **PM: please exclude from sign-up stats**)
- Agent: Purchasing AI (`a_purch`)
- Real (non-dry-run) payments made: 5 (T1, T2, replay-original, R1 attempt, R2 retry) — all held for human approval or rejected, no credential issued
