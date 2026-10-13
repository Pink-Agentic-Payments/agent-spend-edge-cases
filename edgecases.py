#!/usr/bin/env python3
"""
agent-spend-edge-cases: inputs that break AI agent spending rules.

Runs ~20 edge-case payment requests against a spending-rules API (through an
adapter) and checks that each one is handled *safely*: either rejected
outright, or evaluated with a decision that is at least as strict as the
same request would get with a clean, canonical input. A case fails if the
mutated input gets a *looser* decision than the canonical one, or if a
credential ends up covering a different amount/currency than what was
actually evaluated.

Python 3.9+, stdlib only.

Usage:
  python3 edgecases.py --target pink --base https://agentic-sandbox.pinkwallet.com
  python3 edgecases.py --target pink --base <url> --workspace-id <id> --agent-key <key>

Reuse a workspace (recommended; workspace creation is rate limited):
  export PINK_WORKSPACE_ID=...
  export PINK_AGENT_KEY=...
  python3 edgecases.py --target pink --base https://agentic-sandbox.pinkwallet.com
"""

import argparse
import importlib
import json
import os
import sys
import threading
import time

ADAPTERS = {
    "pink": "adapters.pink_rest",
}

# Decision strictness, highest = most conservative. Used to tell a safe
# "evaluated more strictly than canonical" result (fine) apart from an
# unsafe "evaluated more loosely than canonical" result (not fine).
STRICTNESS = {
    "would_block": 3, "blocked": 3,
    "would_ask": 2, "pending_human": 2,
    "would_allow": 1, "allowed": 1,
}


def mask(key):
    if not key or len(key) < 4:
        return "****"
    return "sk_***" + key[-4:]


def strictness(decision):
    return STRICTNESS.get(decision, -1)


def is_rejected(status):
    return status in (400, 401, 403, 404, 409, 422)


class Case:
    def __init__(self, id, category, mutation, expected, run_fn):
        self.id = id
        self.category = category
        self.mutation = mutation
        self.expected = expected
        self.run_fn = run_fn  # callable(ctx) -> dict result

    def run(self, ctx):
        result = {"id": self.id, "category": self.category, "mutation": self.mutation,
                  "expected": self.expected}
        try:
            result.update(self.run_fn(ctx))
        except Exception as e:
            result["outcome"] = "error"
            result["note"] = "exception: %s" % e
        return result


class Ctx:
    def __init__(self, adapter, payee_id, payee_name):
        self.adapter = adapter
        self.payee_id = payee_id
        self.payee_name = payee_name
        self.idem_counter = 0

    def idem(self, tag):
        self.idem_counter += 1
        return "edgecases-%s-%d-%d" % (tag, int(time.time()), self.idem_counter)


# ---------------------------------------------------------------------------
# generic "dry-run against a canonical baseline" helper used by most cases
# ---------------------------------------------------------------------------

def check_case(ctx, payload, baseline_decision, known_gap=False, extra_note=""):
    status, body = ctx.adapter.check(payload)
    decision = body.get("decision")
    if is_rejected(status):
        outcome = "safe"
        note = "rejected: HTTP %s %s" % (status, body.get("error", body))
    elif decision == baseline_decision:
        outcome = "safe"
        note = "evaluated exactly as canonical (%s)" % decision
    elif strictness(decision) > strictness(baseline_decision):
        outcome = "safe"
        note = "evaluated MORE strictly than canonical (%s vs canonical %s)" % (decision, baseline_decision)
    elif strictness(decision) < strictness(baseline_decision):
        outcome = "known_gap" if known_gap else "unsafe"
        note = "LOOSER than canonical: got %s, canonical was %s" % (decision, baseline_decision)
    else:
        outcome = "safe"
        note = "decision %s" % decision
    if extra_note:
        note = note + " — " + extra_note
    return {"outcome": outcome, "status": status, "decision": decision,
            "response": body, "note": note}


def make_currency_case(id, mutation, currency_value):
    def run(ctx):
        payload = {"payee_id": ctx.payee_id, "amount": 100, "currency": currency_value,
                   "purpose": "edgecases %s" % id}
        baseline_status, baseline_body = ctx.adapter.check(
            {"payee_id": ctx.payee_id, "amount": 100, "purpose": "edgecases %s baseline" % id})
        baseline_decision = baseline_body.get("decision")
        return check_case(ctx, payload, baseline_decision)
    return Case(id, "currency", mutation,
                "rejected (4xx) OR evaluated exactly as plain USD would be — never priced looser",
                run)


def make_amount_case(id, mutation, amount_value, currency=None, known_gap=False, extra_note=""):
    def run(ctx):
        payload = {"payee_id": ctx.payee_id, "amount": amount_value, "purpose": "edgecases %s" % id,
                   "local_hour": 14}
        if currency:
            payload["currency"] = currency
        baseline_status, baseline_body = ctx.adapter.check(
            {"payee_id": ctx.payee_id, "amount": 500, "purpose": "edgecases %s baseline" % id, "local_hour": 14})
        baseline_decision = baseline_body.get("decision")
        return check_case(ctx, payload, baseline_decision, known_gap=known_gap, extra_note=extra_note)
    return Case(id, "amount", mutation,
                "rejected (4xx) OR evaluated exactly as the canonical $500 request would be",
                run)


def make_decimal_precision_case(id, mutation, amount_value, currency=None, extra_note=""):
    """
    A3-decimal-places-only check used for A1/A2: the expected *fixed* safe
    behaviour (per the disclosed, fix-in-progress finding #3) is HTTP 400
    before any rule runs, because the amount has more decimal places than
    the currency allows. A decision match against a canonical amount is
    not the right test here -- that comparison is exactly how the original
    bug (rule matching on the rounded amount while the credential used the
    unrounded one) stayed hidden. So this case checks for the rejection
    directly and reports "known_gap", not "unsafe", if the fix isn't live
    yet, since it's the already-disclosed and credited finding #3, not a
    new discovery.
    """
    def run(ctx):
        payload = {"payee_id": ctx.payee_id, "amount": amount_value, "purpose": "edgecases %s" % id,
                   "local_hour": 14}
        if currency:
            payload["currency"] = currency
        status, body = ctx.adapter.check(payload)
        if is_rejected(status):
            return {"outcome": "safe", "status": status, "decision": body.get("decision"),
                    "response": body,
                    "note": "rejected for excess decimal places: HTTP %s %s" % (status, body.get("error", body))}
        return {"outcome": "known_gap", "status": status, "decision": body.get("decision"),
                "response": body,
                "note": ("not rejected, got decision '%s' — matches disclosed finding #3 "
                         "(kimutaiRop), fix in progress per README Fix log. %s"
                         % (body.get("decision"), extra_note))}
    return Case(id, "amount", mutation,
                "HTTP 400 (amount has more decimal places than the currency allows) — "
                "currently fix-in-progress per the disclosed finding #3",
                run)


def make_payee_case(id, mutation, payee_name_value):
    def run(ctx):
        payload = {"payee_name": payee_name_value, "amount": 60, "purpose": "edgecases %s" % id,
                   "local_hour": 14}
        baseline_status, baseline_body = ctx.adapter.check(
            {"payee_name": ctx.payee_name, "amount": 60, "purpose": "edgecases %s baseline" % id,
             "local_hour": 14})
        baseline_decision = baseline_body.get("decision")
        return check_case(ctx, payload, baseline_decision)
    return Case(id, "payee", mutation,
                "rejected, OR recognised as the same approved payee, OR (safe-but-stricter) "
                "treated as an unrecognised payee and asked for approval — never allowed looser "
                "than the canonical approved-payee decision",
                run)


# ---------------------------------------------------------------------------
# time category: client-supplied local_hour / timestamp on a REAL payment
# ---------------------------------------------------------------------------

def time_local_hour_case(ctx):
    canon_status, canon_body = ctx.adapter.pay(
        {"payee_id": ctx.payee_id, "amount": 60, "purpose": "edgecases T-canon",
         "idempotency_key": ctx.idem("t-canon")})
    status, body = ctx.adapter.pay(
        {"payee_id": ctx.payee_id, "amount": 60, "purpose": "edgecases T1 local_hour spoof",
         "local_hour": 14, "idempotency_key": ctx.idem("t1")})
    canon_decision, decision = canon_body.get("decision"), body.get("decision")
    safe = decision == canon_decision
    return {"outcome": "safe" if safe else "unsafe", "status": status, "decision": decision,
            "response": body,
            "note": ("local_hour=14 ignored on a real payment, decision matches the no-spoof "
                      "canonical (%s)" % decision) if safe else
                     ("UNSAFE: spoofed local_hour changed the real-payment decision (%s) vs "
                      "canonical (%s)" % (decision, canon_decision))}


def time_timestamp_case(ctx):
    canon_status, canon_body = ctx.adapter.pay(
        {"payee_id": ctx.payee_id, "amount": 60, "purpose": "edgecases T-canon-2",
         "idempotency_key": ctx.idem("t-canon2")})
    status, body = ctx.adapter.pay(
        {"payee_id": ctx.payee_id, "amount": 60, "purpose": "edgecases T2 timestamp spoof",
         "timestamp": "2026-10-11T14:00:00-05:00", "created_at": "2026-10-11T14:00:00-05:00",
         "idempotency_key": ctx.idem("t2")})
    canon_decision, decision = canon_body.get("decision"), body.get("decision")
    safe = decision == canon_decision
    return {"outcome": "safe" if safe else "unsafe", "status": status, "decision": decision,
            "response": body,
            "note": ("client-supplied timestamp/created_at ignored, decision matches canonical "
                      "(%s)" % decision) if safe else
                     ("UNSAFE: spoofed timestamp changed the real-payment decision (%s) vs "
                      "canonical (%s)" % (decision, canon_decision))}


# ---------------------------------------------------------------------------
# replay category: same idempotency key, different payload
# ---------------------------------------------------------------------------

def replay_different_amount_case(ctx):
    key = ctx.idem("replay")
    orig_status, orig_body = ctx.adapter.pay(
        {"payee_id": ctx.payee_id, "amount": 60, "purpose": "edgecases replay original",
         "idempotency_key": key})
    status, body = ctx.adapter.pay(
        {"payee_id": ctx.payee_id, "amount": 480, "purpose": "edgecases replay different amount",
         "idempotency_key": key})
    ctx.replay_key = key
    ctx.replay_original = orig_body
    if is_rejected(status):
        return {"outcome": "safe", "status": status, "decision": body.get("decision"),
                "response": body, "note": "reused key with a different amount correctly rejected"}
    if body.get("payment_id") == orig_body.get("payment_id") and body.get("amount") == orig_body.get("amount"):
        return {"outcome": "safe", "status": status, "decision": body.get("decision"),
                "response": body, "note": "reused key returned the original payment unchanged, "
                                           "the different amount was never evaluated"}
    return {"outcome": "unsafe", "status": status, "decision": body.get("decision"), "response": body,
            "note": "UNSAFE: reused key with a different amount was evaluated/credentialed as new"}


def replay_same_payload_case(ctx):
    key = getattr(ctx, "replay_key", None)
    orig = getattr(ctx, "replay_original", None)
    if not key or not orig:
        return {"outcome": "error", "note": "ran before replay_different_amount_case; no key to reuse"}
    status, body = ctx.adapter.pay(
        {"payee_id": ctx.payee_id, "amount": 60, "purpose": "edgecases replay original",
         "idempotency_key": key})
    same_payment = body.get("payment_id") == orig.get("payment_id")
    safe = same_payment and body.get("decision") == orig.get("decision")
    return {"outcome": "safe" if safe else "unsafe", "status": status, "decision": body.get("decision"),
            "response": body,
            "note": "identical retry returned the same payment_id/decision (replayed=%s), not "
                    "re-evaluated or double-charged" % body.get("replayed")
                    if safe else "UNSAFE: identical retry did not return the original payment"}


# ---------------------------------------------------------------------------
# concurrency category: same idempotency key fired in parallel; a refund
# racing a new payment
# ---------------------------------------------------------------------------

def parallel_idempotency_case(ctx):
    """
    Fire N identical pay() calls (same payee, amount, idempotency_key) all
    released at once from a barrier, so the server actually sees them
    concurrently instead of one-after-another. Safe outcome: exactly one
    payment_id across all N responses, and spend moves exactly once.
    Unsafe outcome: more than one distinct payment_id (the idempotency key
    did not dedupe under a real race) or spend moved more than once.
    """
    n = 10
    amount = 100
    budget_status_before, budget_before = ctx.adapter.get_budget()
    key = ctx.idem("parallel")
    results = [None] * n
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        results[i] = ctx.adapter.pay(
            {"payee_id": ctx.payee_id, "amount": amount,
             "purpose": "edgecases R3 parallel idempotency", "idempotency_key": key})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    budget_status_after, budget_after = ctx.adapter.get_budget()
    statuses = [r[0] for r in results]
    bodies = [r[1] for r in results]
    payment_ids = sorted(set(b.get("payment_id") for b in bodies if b.get("payment_id")))
    replayed_flags = [b.get("replayed") for b in bodies]
    spent_before = budget_before.get("spent_today")
    spent_after = budget_after.get("spent_today")
    spent_delta = (spent_after - spent_before) if isinstance(spent_before, (int, float)) and \
        isinstance(spent_after, (int, float)) else None

    detail = {"statuses": statuses, "replayed_flags": replayed_flags,
              "payment_ids": payment_ids, "spent_before": spent_before,
              "spent_after": spent_after, "spent_delta": spent_delta,
              "n_requests": n, "amount_per_request": amount}

    if len(payment_ids) > 1:
        outcome = "unsafe"
        note = ("UNSAFE: %d distinct payment_ids were created from %d parallel calls using "
                 "the same idempotency key (%s)" % (len(payment_ids), n, key))
    elif len(payment_ids) == 1:
        if spent_delta == amount:
            outcome = "safe"
            note = ("exactly 1 payment_id across %d parallel calls, spend moved by %s exactly "
                     "once (spent_today %s -> %s), replayed flags: %s"
                     % (n, amount, spent_before, spent_after, replayed_flags))
        else:
            outcome = "unsafe"
            note = ("UNSAFE: 1 payment_id but spend moved by %s (expected %s) across %d parallel "
                     "calls (spent_today %s -> %s)" % (spent_delta, amount, n, spent_before, spent_after))
    else:
        if spent_delta == 0:
            outcome = "safe"
            note = "all %d parallel calls were rejected, no payment created, spend unchanged" % n
        else:
            outcome = "unsafe"
            note = ("UNSAFE: no payment_id returned but spend moved by %s across %d parallel "
                     "calls" % (spent_delta, n))

    return {"outcome": outcome, "status": statuses, "decision": None,
            "response": detail, "note": note}


def refund_race_case(ctx):
    """
    Before writing this case we checked whether the sandbox exposes any
    refund / reversal / void operation at all:
      - REST docs (https://pinkwallet.com/agentic/developers/connect-via-rest/,
        fetched 2026-10-13): lists the full agent-key route set (/v1/me,
        /v1/budget, /v1/payees, /v1/vaults, /v1/rules, /v1/payments/check,
        /v1/payments, /v1/payments/{id}, /v1/payments/{id}/receipt) and the
        full admin-key route set (/v1/admin/state, /v1/admin/workspace,
        /v1/admin/requests/{id}/approve, /v1/admin/requests/{id}/decline,
        /v1/admin/rules, /v1/admin/agents/{id}, /v1/admin/reset-day,
        /v1/admin/reset) — no refund/reversal/void/cancel route anywhere.
      - MCP tools-reference (https://pinkwallet.com/agentic/developers/tools-reference/,
        fetched 2026-10-13): the 7 documented tools are get_budget,
        list_payees, list_rules, check_policy, request_payment,
        get_credential, report_receipt — again, nothing that reverses or
        cancels a payment.
      - A GET on /v1/openapi.json with a valid agent key against the live
        sandbox returned {"error": "unknown route for an agent key"} (checked
        2026-10-13), i.e. there is no spec endpoint exposing a hidden route
        either.
    Conclusion: the sandbox has no refund operation to race against a new
    payment, so the "refund racing a new payment" scenario cannot be
    constructed without inventing an endpoint that does not exist. We do not
    invent one; this case is marked not_applicable rather than run.
    """
    note = ("not applicable: the sandbox has no refund/reversal/void/cancel operation. "
             "Checked the REST route list and the MCP tools-reference (7 tools: get_budget, "
             "list_payees, list_rules, check_policy, request_payment, get_credential, "
             "report_receipt) on 2026-10-13 — neither lists one, and a live GET on "
             "/v1/openapi.json with an agent key returned "
             "{\"error\": \"unknown route for an agent key\"}. No endpoint was invented or "
             "guessed; no payment-moving calls were made for this case.")
    return {"outcome": "not_applicable", "status": None, "decision": None,
            "response": {"checked": ["connect-via-rest docs", "tools-reference docs",
                                      "GET /v1/openapi.json with agent key"]},
            "note": note}


# ---------------------------------------------------------------------------
# case list
# ---------------------------------------------------------------------------

def build_cases():
    cases = []
    cases.append(make_currency_case("C1", 'currency "EUR " (trailing space)', "EUR "))
    cases.append(make_currency_case("C2", 'currency " EUR" (leading space)', " EUR"))
    cases.append(make_currency_case("C3", 'currency "usd" (lowercase)', "usd"))
    cases.append(make_currency_case("C4", 'currency "XYZ" (unknown code)', "XYZ"))
    cases.append(make_currency_case("C5", 'currency "" (empty string)', ""))
    cases.append(make_currency_case("C6", "currency 1 (number instead of string)", 1))

    cases.append(make_decimal_precision_case("A1", "amount 500.0001 (sub-cent, 4 decimal places in USD)",
                                              500.0001))
    cases.append(make_decimal_precision_case("A2", "amount 1500.5 in JPY (JPY allows 0 decimals)", 1500.5,
                                              currency="JPY"))
    cases.append(make_amount_case("A3", "amount -100 (negative)", -100))
    cases.append(make_amount_case("A4", "amount 0 (zero)", 0))
    cases.append(make_amount_case("A5", 'amount "5e2" (scientific notation, string)', "5e2"))
    cases.append(make_amount_case("A6", "amount 5e2 (scientific notation, number)", 5e2))
    cases.append(make_amount_case("A7", 'amount "500" (string instead of number)', "500"))
    cases.append(make_amount_case("A8", "amount 1e15 (very large)", 1e15))
    cases.append(make_amount_case("A9", 'amount "NaN" (string)', "NaN"))

    cases.append(Case("T1", "time", "client-supplied local_hour on a real payment",
                       "ignored; decision matches the no-spoof canonical", time_local_hour_case))
    cases.append(Case("T2", "time", "client-supplied timestamp/created_at on a real payment",
                       "ignored; decision matches the no-spoof canonical", time_timestamp_case))

    cases.append(Case("R1", "replay", "same idempotency key, different amount",
                       "rejected (4xx) or the original payment returned unchanged, never "
                       "re-evaluated for the new amount", replay_different_amount_case))
    cases.append(Case("R2", "replay", "same idempotency key, identical payload (true retry)",
                       "same payment_id/decision returned, not double-charged", replay_same_payload_case))

    cases.append(make_payee_case("P1", "payee_name in ALL CAPS", "COUNTER CULTURE COFFEE"))
    cases.append(make_payee_case("P2", "payee_name with leading/trailing whitespace",
                                  " Counter Culture Coffee "))

    cases.append(Case("R3", "concurrency", "same idempotency key fired in parallel (N=10)",
                       "exactly one payment_id across all N calls; spend moves exactly once",
                       parallel_idempotency_case))
    cases.append(Case("RF1", "concurrency", "refund racing a new payment",
                       "not applicable if the sandbox has no refund operation (checked, "
                       "does not invent an endpoint); otherwise cap must never be exceeded",
                       refund_race_case))
    return cases


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", default="pink", choices=sorted(ADAPTERS.keys()))
    parser.add_argument("--base", required=True, help="base URL of the API under test")
    parser.add_argument("--workspace-id", default=os.environ.get("PINK_WORKSPACE_ID"))
    parser.add_argument("--agent-key", default=os.environ.get("PINK_AGENT_KEY"))
    parser.add_argument("--admin-key", default=os.environ.get("PINK_ADMIN_KEY"))
    parser.add_argument("--out", help="write JSON results to this path")
    args = parser.parse_args()

    mod = importlib.import_module(ADAPTERS[args.target])
    adapter = mod.PaymentRulesAdapter(args.base, admin_key=args.admin_key,
                                       agent_key=args.agent_key, workspace_id=args.workspace_id)
    ws = adapter.ensure_workspace()
    print("workspace: %s" % json.dumps(ws))

    ctx = Ctx(adapter, ws["default_payee_id"], ws["default_payee_name"])
    cases = build_cases()

    results = []
    for case in cases:
        r = case.run(ctx)
        results.append(r)
        print("[%s] %-8s %-40s -> %s (%s)" % (
            r["id"], r.get("outcome", "?"), r.get("mutation", case.mutation),
            r.get("decision") or r.get("status"), r.get("note", "")))

    safe = sum(1 for r in results if r["outcome"] == "safe")
    unsafe = [r for r in results if r["outcome"] == "unsafe"]
    known_gap = [r for r in results if r["outcome"] == "known_gap"]
    not_applicable = [r for r in results if r["outcome"] == "not_applicable"]
    errors = [r for r in results if r["outcome"] == "error"]

    print()
    print("Summary: %d safe, %d known-gap (already disclosed), %d not-applicable, %d unsafe, "
          "%d errors, %d total" % (
        safe, len(known_gap), len(not_applicable), len(unsafe), len(errors), len(results)))
    if unsafe:
        print("NEW UNSAFE BEHAVIOUR FOUND. Do not post publicly. Write up FINDINGS-PRIVATE.md and "
              "escalate to the PM before doing anything else.")
        for r in unsafe:
            print("  - [%s] %s: %s" % (r["id"], r["mutation"], r["note"]))

    out = {"workspace": ws, "results": results,
           "summary": {"safe": safe, "known_gap": len(known_gap),
                       "not_applicable": len(not_applicable), "unsafe": len(unsafe),
                       "errors": len(errors), "total": len(results)}}
    if args.out:
        with open(args.out, "w") as f:
            json.dump(out, f, indent=2)
        print("Wrote %s" % args.out)

    return 1 if unsafe else 0


if __name__ == "__main__":
    sys.exit(main())
