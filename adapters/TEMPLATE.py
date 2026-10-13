"""
Template adapter: implement this interface against your own spending-rules API
and pass --target <yourname> (after registering it in edgecases.py's ADAPTERS
dict) to run the same ~20 cases against your own service.

Only two calls matter for most cases: check() (a dry run, no money moves) and
pay() (a real call, only used where a dry run can't show the behaviour, e.g.
a credential's max_amount or an idempotency replay). get_payment() is used by
the one case that polls a held payment.

Do not point this, or any adapter, at a vendor's API without authorization.
"""


class PaymentRulesAdapter:
    name = "template"

    def __init__(self, base_url, admin_key=None, agent_key=None, workspace_id=None):
        """Store connection details. Do not perform network calls here."""
        self.base_url = base_url
        self.admin_key = admin_key
        self.agent_key = agent_key
        self.workspace_id = workspace_id

    def ensure_workspace(self):
        """
        Create or reuse a test workspace/tenant with test money only.
        Must set self.agent_key (and self.workspace_id if applicable) and
        return a dict describing it, e.g.:
            {"workspace_id": "...", "default_payee_id": "...",
             "default_payee_name": "...", "currency": "USD"}
        Raise rather than silently create more than one workspace per run.
        """
        raise NotImplementedError

    def check(self, payload):
        """
        Dry run: evaluate `payload` against the spending rules without
        creating a real payment. Must return (status_code, body_dict).
        body_dict should include a decision-like field comparable across
        runs (e.g. "would_allow" / "would_ask" / "would_block") so
        edgecases.py can compare a mutated case's decision to the
        canonical one.
        """
        raise NotImplementedError

    def pay(self, payload, idempotency_key=None):
        """
        Real call: may move test money / issue a credential. Must return
        (status_code, body_dict). Keep real calls rare; most cases should
        use check() instead.
        """
        raise NotImplementedError

    def get_payment(self, payment_id):
        """Fetch a previously created payment/hold. Returns (status, body)."""
        raise NotImplementedError

    def get_budget(self):
        """
        Optional: fetch current budget/spend status, e.g.
            {"spent_today": ..., "spent_this_month": ..., ...}
        Only used by the concurrency cases (same idempotency key fired in
        parallel) to show spend moved exactly once. Returns (status, body).
        """
        raise NotImplementedError
