# Python SDK

The maintained installation, authentication, examples and recovery guide is at
[Python SDK](https://readlint.com/docs/python).

The on-site guides are the source of user instructions. This repository keeps
implementation and [development/release notes](development.md).


## Read agent permissions

```python
with Readlint() as client:
    policy = client.get_agent_permissions()
```

The response has `agents_can_start_trials`, `agents_can_confirm_paid_orders`
and `agents_can_cancel_plans` booleans. Reads may be retried. Only the owner
can change policy at https://readlint.com/app/settings#agent-permissions.
Keys can read billing, request quotes, cancel plans and get Stripe links when billing is available. Trial setup and key paid orders are still being prepared.
Ordinary checks continue to use credits and incur usage charges under the
account's plan. MCP remains limited to evaluations.

## Billing

`get_billing_status()`, `create_billing_quote()` and `create_billing_portal()`
return typed dictionaries. `confirm_billing_order(quote_id, terms_version=...,
paid_order_confirmed=True, idempotency_key=...)` requires explicit consent.
`cancel_billing_plan(idempotency_key=...)` freezes the original target.
Both mutation keys are caller-supplied UUIDs, with no automatic retries.
Read status after uncertainty and reuse the same input to recover.

Quote/order/cancel responses export `BillingQuote`, `BillingOrder`,
`BillingCancellation`, `BillingStatus` and `BillingPortal` types. Accepted outcome
and current payment/access state are separate. A declined/authentication invoice
has a private action link; use it for the human payment step, then read status.
Key orders remain gated pending contract-email and legal verification.
`ReadlintError` preserves validated permission `action`, `settings_url` and
`retryable`, and known Stripe recovery `action_url`. `as_dict()` includes them
when present. Other server text stays sanitized.
