# CLI

The maintained installation, authentication, examples and recovery guide is at
[CLI](https://readlint.com/docs/cli).

The on-site guides are the source of user instructions. This repository keeps
implementation and [development/release notes](development.md).


## Read agent permissions

```sh
readlint agent-permissions get --json
```

The response has `agents_can_start_trials`, `agents_can_confirm_paid_orders`
and `agents_can_cancel_plans` booleans. Reads may be retried. Only the owner
can change policy at https://readlint.com/app/settings#agent-permissions.
Keys can read billing, request quotes, cancel plans and get Stripe links when billing is available. Trial setup and key paid orders are still being prepared.
Ordinary checks continue to use credits and incur usage charges under the
account's plan. MCP remains limited to evaluations.

## Billing

```sh
readlint billing status --json
readlint billing quote --json
readlint billing portal --json
readlint billing cancel --idempotency-key "$CANCEL_UUID" --json
readlint billing order --quote-id "$QUOTE_UUID" --terms-version "$TERMS_VERSION" --agree-to-pay --idempotency-key "$ORDER_UUID" --json
```

Review the full quote and its dated legal links before confirming. Order/cancel
require a UUID you retain. There is no `--yes` substitute for `--agree-to-pay`.
Financial writes are never automatically retried. After uncertainty, read status
and reuse the original UUID and body; never request a different quote just to
recover. Commands work without a TTY and never open a browser. Results use
stdout; diagnostics and JSON errors use stderr and a nonzero exit status.

Key order confirmation returns `agent_orders_unavailable` until contract-email
and legal gates pass. The command does not bypass that gate. Cancellation and
billing reads are available when billing is enabled. `agent_permission_disabled`
includes the exact label, action, configured-origin `settings_url` and
`retryable: false`. Portal/invoice URLs are private; do not log or commit them.
