# agent-spend-edge-cases: inputs that break AI agent spending rules

Spending rules for AI agents (amount limits, blocked payees, approval
thresholds) are usually right about the cases everyone thinks to test.
They get broken by the inputs around the edges: a currency code with a
trailing space, an amount with one extra decimal place, a client that
supplies its own clock, a replayed request with a different payload. None
of those are exotic attacks; they're the kind of thing a real AI agent
sends by accident, and a kind an adversarial one sends on purpose.

This is a small, vendor-neutral, open-source test suite of ~20 such edge
cases. Point it at your own spending-rules API (write one adapter) and it
tells you, case by case, whether each mutated input was rejected, evaluated
exactly as a clean input would be, or — the failure mode — evaluated
*looser* than a clean input, which is how a rule silently gets bypassed.

## Origin

The suite came out of the [Pink Overspend Challenge](https://github.com/Pink-Agentic-Payments/overspend-challenge),
where outside testers found 3 input-handling gaps in Pink Agentic AI
Payments' spending rules in one day (2026-10-10):

1. [#1](https://github.com/Pink-Agentic-Payments/overspend-challenge/issues/1) — a currency code with a trailing space (`"EUR "`) wasn't recognised, got priced 1:1 as USD, and slipped a EUR 999 payment under a "known vendors under $1,000" auto-allow rule instead of the CFO approval it should have needed. Fixed: unknown/malformed currency codes now get rejected outright.
2. [#2](https://github.com/Pink-Agentic-Payments/overspend-challenge/issues/2) — a night-hours approval rule labelled in Singapore time was evaluated against the server's UTC clock, and a real payment could pass its own `local_hour` to pick which hour the rule saw. Fixed: every workspace now has a timezone, time rules run on the server clock in that timezone, and `local_hour` only works on dry runs.
3. [#3](https://github.com/Pink-Agentic-Payments/overspend-challenge/issues/3) — a sub-cent amount (`$500.0001`) matched a `≤$500` auto-allow rule because the rule matched on the rounded amount while the credential was issued for the unrounded one. Fix in progress: amounts with more decimal places than the currency allows will be rejected with HTTP 400 before any rule runs.

Three findings, three different categories of bug (string normalization,
clock/timezone trust, and rounding), all in the same narrow part of the
system: how the edges of an input get handled before the actual rule
engine ever sees it. That pattern is the generator for this suite — instead
of three one-off reports, ~20 cases across currency strings, amounts, time,
idempotency replays and payee-name matching.

## Running it against your own API

`edgecases.py` is stdlib-only Python 3.9+. It doesn't know about any
specific vendor; it talks to whatever `PaymentRulesAdapter` you give it.

```bash
python3 edgecases.py --target pink --base https://agentic-sandbox.pinkwallet.com
```

To test your own service:

1. Copy [`adapters/TEMPLATE.py`](adapters/TEMPLATE.py) to `adapters/yourname.py` and implement `ensure_workspace()`, `check()`, `pay()`, `get_payment()` against your API.
2. Add `"yourname": "adapters.yourname"` to the `ADAPTERS` dict at the top of `edgecases.py`.
3. Run `python3 edgecases.py --target yourname --base <your base url>`.

Most cases only call `check()` (a dry run — nothing moves). A few
(`local_hour`/timestamp spoofing, idempotency replays) need a real `pay()`
call, because a dry run can't show what a real credential or a real replay
actually does. Keep real calls rare in your own adapter too.

**Never point an adapter at a service you don't have authorization to
test.** This repo ships exactly one working adapter (Pink's own public,
test-money-only sandbox) and a template for your own — no other vendor's
API, authorized or not, is referenced here.

## Results: Pink's sandbox, 2026-10-10

Run against `https://agentic-sandbox.pinkwallet.com` (coffee-template
workspace, test money only). Full table and raw JSON:
[results/pink-sandbox-2026-10-10.md](results/pink-sandbox-2026-10-10.md) ·
[results/pink-sandbox-2026-10-10.json](results/pink-sandbox-2026-10-10.json).

**21 cases run: 19 safe, 2 known-gap (already-disclosed, fix in progress), 0 new unsafe findings.**

| category | cases | safe | known-gap |
|----------|-------|------|-----------|
| currency strings | 6 | 6 | 0 |
| amounts | 9 | 7 | 2 (sub-cent / excess-decimal, matches disclosed finding #3) |
| time (client-supplied clock) | 2 | 2 | 0 |
| idempotency replays | 2 | 2 | 0 |
| payee name matching | 2 | 2 | 0 |

The 2 known-gap cases reproduce finding #3 above and are expected to flip
to "safe" once that fix ships — they're not a new issue, just the suite
checking the one that's already public.

## What "safe" means here

For each mutated input, the suite checks it against a clean/canonical
version of the same request:

- **safe** — the mutated input was rejected (4xx), or evaluated to exactly
  the same decision as the canonical input, or evaluated to a *stricter*
  decision (e.g. asked for approval when the canonical input would have
  been auto-allowed).
- **unsafe** — the mutated input got a *looser* decision than the
  canonical input (e.g. auto-allowed when the canonical input would have
  been blocked or held), or a credential ended up covering a different
  amount/currency than what was actually evaluated.

## Design partners wanted

We're looking for 3 design partners to try Pink Agentic AI Payments before general availability, free during the design-partner period, with hands-on setup and early access. Try the sandbox at [agentic-sandbox.pinkwallet.com/demo](https://agentic-sandbox.pinkwallet.com/demo), then reach us at [support@pinkwallet.com](mailto:support@pinkwallet.com) or open an issue titled "Design partner" in this repo.

## License

MIT, see [LICENSE](LICENSE). The three findings this suite is built on are
Pink's own disclosed, credited findings from the Pink Overspend Challenge
(see links above) — nothing here discloses anything new.
