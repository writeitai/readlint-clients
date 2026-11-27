# TypeScript SDK

The maintained installation, authentication, examples and recovery guide is at
[TypeScript SDK](https://readlint.com/docs/typescript).

The on-site guides are the source of user instructions. This repository keeps
implementation and [development/release notes](development.md).


## Read agent permissions

```ts
const policy = await client.getAgentPermissions();
```

The response has `agents_can_start_trials`, `agents_can_confirm_paid_orders`
and `agents_can_cancel_plans` booleans. Reads may be retried. Only the owner
can change policy at https://readlint.com/app/settings#agent-permissions.
Keys can read billing, request quotes, cancel plans and get Stripe links when billing is available. Trial setup and key paid orders are still being prepared.
Ordinary checks continue to use credits and incur usage charges under the
account's plan. MCP remains limited to evaluations.

## Billing

`getBillingStatus()`, `createBillingQuote()` and `createBillingPortal()` are typed.
`confirmBillingOrder(quoteId, {termsVersion, paidOrderConfirmed: true,
idempotencyKey})` requires explicit consent. `cancelBillingPlan({idempotencyKey})`
freezes the original target. Both keys are caller-supplied UUIDs, with no automatic
retries. Read status after uncertainty and reuse the same input to recover.

The generated response types are `AgentBillingStatus`, `AgentQuote`,
`OrderAccepted`, `Cancellation` and `PortalLink`. An accepted order and current
payment/access state are separate; a private invoice action URL may require a
human payment step. Key orders remain gated pending email and legal verification.
`ReadlintError.details` preserves validated permission `action`, `settings_url`
and `retryable`, and known Stripe recovery `action_url`. Settings URLs use the
configured API origin. Other server text stays sanitized.
