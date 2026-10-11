"""
Default adapter: Pink Agentic AI Payments' public sandbox, over REST.

Docs: https://pinkwallet.com/agentic/developers/connect-via-rest/
Sandbox base: https://agentic-sandbox.pinkwallet.com (test money only).

Stdlib only. Sets an explicit User-Agent (the sandbox's Cloudflare used to
reject Python's default urllib UA; a normal-looking one always works).
"""

import json
import sys
import urllib.error
import urllib.request

USER_AGENT = "agent-spend-edge-cases/0.1 (+https://github.com/Pink-Agentic-Payments/overspend-challenge)"


class PaymentRulesAdapter:
    name = "pink"

    def __init__(self, base_url, admin_key=None, agent_key=None, workspace_id=None):
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        self.agent_key = agent_key
        self.workspace_id = workspace_id

    def _http(self, method, path, token=None, body=None):
        url = self.base_url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode())
            except Exception:
                return e.code, {"error": str(e)}

    def ensure_workspace(self):
        if self.agent_key and self.workspace_id:
            return {
                "workspace_id": self.workspace_id,
                "default_payee_id": "p_cc",
                "default_payee_name": "Counter Culture Coffee",
                "currency": "USD",
                "reused": True,
            }

        print(
            "No --workspace-id/--agent-key given. Creating a new sandbox "
            "workspace (coffee template). Workspace creation is rate limited; "
            "reuse PINK_WORKSPACE_ID/PINK_AGENT_KEY on the next run.",
            file=sys.stderr,
        )
        status, body = self._http(
            "POST",
            "/v1/sandbox/workspaces",
            body={"name": "edgecases-run", "template": "coffee"},
        )
        if status != 201:
            raise RuntimeError("workspace creation failed: HTTP %s %s" % (status, body))

        self.workspace_id = body["workspace_id"]
        purchasing = next(a for a in body["agents"] if a["id"] == "a_purch")
        self.agent_key = purchasing["key"]
        print("Created workspace %s. Export these to reuse it:" % self.workspace_id, file=sys.stderr)
        print("  export PINK_WORKSPACE_ID=%s" % self.workspace_id, file=sys.stderr)
        print("  export PINK_AGENT_KEY=%s   # keep private" % self.agent_key, file=sys.stderr)
        return {
            "workspace_id": self.workspace_id,
            "default_payee_id": "p_cc",
            "default_payee_name": "Counter Culture Coffee",
            "currency": "USD",
            "reused": False,
        }

    def check(self, payload):
        return self._http("POST", "/v1/payments/check", token=self.agent_key, body=payload)

    def pay(self, payload, idempotency_key=None):
        body = dict(payload)
        if idempotency_key and "idempotency_key" not in body:
            body["idempotency_key"] = idempotency_key
        return self._http("POST", "/v1/payments", token=self.agent_key, body=body)

    def get_payment(self, payment_id):
        return self._http("GET", "/v1/payments/%s" % payment_id, token=self.agent_key)
