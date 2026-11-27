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
This release reads saved policy; agent billing commands are still being built.
Ordinary checks continue to use credits and incur usage charges under the
account's plan. MCP remains limited to evaluations.
