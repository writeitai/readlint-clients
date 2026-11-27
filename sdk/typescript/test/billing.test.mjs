import assert from "node:assert/strict";
import test from "node:test";
import { Readlint, ReadlintError } from "../dist/index.js";
import { main } from "../dist/cli.js";
const id = "64dfbf5a-2016-41a0-ad7f-b6808929b5ae";
const label = "Agents can cancel plans";
const denial = {code: "agent_permission_disabled", message: `The account has turned off "${label}".`, action: `Ask the account owner to enable "${label}" in Settings → Agent permissions.`, settings_url: "/app/settings#agent-permissions", retryable: false};

test("financial writes are explicit and never automatically retried", async () => {
  for (const kind of ["order", "cancel"]) for (const failure of ["timeout", 503, 403]) {
    let calls = 0;
    const client = new Readlint({apiKey: "key", fetch: async () => {
      calls++;
      if (failure === "timeout") throw new Error("PRIVATE_SECRET");
      return new Response(JSON.stringify({detail: denial}), {status: failure});
    }});
    await assert.rejects(kind === "order" ? client.confirmBillingOrder(id, {termsVersion: "2026-11-25", paidOrderConfirmed: true, idempotencyKey: id}) : client.cancelBillingPlan({idempotencyKey: id}), ReadlintError);
    assert.equal(calls, 1);
  }
  const client = new Readlint({apiKey: "key", fetch: async () => assert.fail("No unconfirmed request")});
  for (const value of [false, "true", 1, undefined]) assert.throws(() => client.confirmBillingOrder(id, {termsVersion: "2026-11-25", paidOrderConfirmed: value, idempotencyKey: id}), TypeError);
});

test("permission details accept only exact known fields and same-origin settings", async () => {
  for (const change of [{}, {message: "PRIVATE_SECRET"}, {action: "PRIVATE_SECRET"}, {settings_url: "https://evil.test/PRIVATE_SECRET"}, {retryable: true}]) {
    const client = new Readlint({apiKey: "key", baseUrl: "https://sandbox.readlint.com", fetch: async () => new Response(JSON.stringify({detail: {...denial, ...change}}), {status: 403})});
    await assert.rejects(client.cancelBillingPlan({idempotencyKey: id}), error => {
      if (!Object.keys(change).length) {
        assert.equal(error.code, "agent_permission_disabled");
        assert.equal(error.details.settings_url, "https://sandbox.readlint.com/app/settings#agent-permissions");
        assert.equal(error.details.retryable, false);
      } else { assert.equal(error.code, "api_error"); assert.deepEqual(error.details, {}); }
      assert.ok(!JSON.stringify(error).includes("PRIVATE_SECRET")); return true;
    });
  }
});

test("CLI cannot infer payment consent and preserves validated denials", async () => {
  const original = globalThis.fetch, log = console.log, err = console.error;
  let sent = 0; const output = [], diagnostics = [];
  globalThis.fetch = async () => { sent++; return new Response(JSON.stringify({detail: denial}), {status: 403}); };
  console.log = value => output.push(value); console.error = value => diagnostics.push(value);
  try {
    const common = ["--json", "--api-key", "rlk_PRIVATE_SECRET", "--idempotency-key", id];
    assert.equal(await main(["billing", "order", ...common, "--quote-id", id, "--terms-version", "2026-11-25"]), 1);
    assert.equal(await main(["billing", "order", ...common, "--quote-id", id, "--terms-version", "2026-11-25", "--yes"]), 1);
    assert.equal(await main(["billing", "cancel", "--json", "--api-key", "key", "--idempotency-key", "rlk_PRIVATE_SECRET"]), 1);
    assert.equal(sent, 0);
    assert.equal(await main(["billing", "cancel", ...common]), 1);
    const problem = JSON.parse(diagnostics.at(-1)).error;
    assert.equal(problem.code, "agent_permission_disabled"); assert.equal(problem.retryable, false);
    assert.equal(problem.idempotency_key, id); assert.equal(output.length, 0);
    assert.ok(!diagnostics.join("\n").includes("PRIVATE_SECRET"));
  } finally { globalThis.fetch = original; console.log = log; console.error = err; }
});
