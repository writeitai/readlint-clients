import assert from "node:assert/strict";
// Used by the shared Python contract check and by the installed-package check.
export async function exercise(module, fixtures) {
  const calls = [];
  const client = new module.Readlint({apiKey: "rlk_contract", maxRetries: 0,
    fetch: async (url, options) => {
      const parsed = new URL(url);
      calls.push({method: options.method, path: parsed.pathname,
        query: Object.fromEntries(parsed.searchParams), headers: options.headers,
        body: options.body ? (options.headers["Content-Type"] === "application/json" ?
          JSON.parse(options.body) : Object.fromEntries(new URLSearchParams(options.body))) : null});
      const name = parsed.pathname.startsWith("/v1/billing/") ? "billing_" + parsed.pathname.split("/").at(-1) : parsed.pathname === "/v1/agent-permissions" ? "agent_permissions" : parsed.pathname === "/auth/device/code" ? "device_code" :
        parsed.pathname === "/auth/device/token" ? "device_token" :
        options.method === "GET" && parsed.pathname === "/v1/evaluations" ? "page" : "evaluation";
      return new Response(options.method === "DELETE" ? null : JSON.stringify(fixtures[name]),
        {status: options.method === "DELETE" ? 204 : 200});
    }});
  assert.deepEqual(await client.createDeviceCode({hostname: "fixture-host", os: "fixture-os"}), fixtures.device_code);
  assert.deepEqual(await client.createDeviceToken("device-fixture"), fixtures.device_token);
  assert.deepEqual(await client.evaluate("# Article", {title: "Contract", description: "Context", idempotencyKey: "contract-key"}), fixtures.evaluation);
  assert.deepEqual(await client.getAgentPermissions(), fixtures.agent_permissions);
  assert.deepEqual(await client.listEvaluations({limit: 3, offset: 2}), fixtures.page);
  assert.deepEqual(await client.getEvaluation(fixtures.evaluation.id), fixtures.evaluation);
  assert.equal(await client.deleteEvaluation(fixtures.evaluation.id), undefined);
  assert.deepEqual(await client.getBillingStatus(), fixtures.billing_status);
  assert.deepEqual(await client.createBillingQuote(), fixtures.billing_quote);
  assert.deepEqual(await client.confirmBillingOrder(fixtures.evaluation.id, {termsVersion: "2026-11-25", paidOrderConfirmed: true, idempotencyKey: fixtures.evaluation.id}), fixtures.billing_order);
  assert.deepEqual(await client.cancelBillingPlan({idempotencyKey: fixtures.evaluation.id}), fixtures.billing_cancel);
  assert.deepEqual(await client.createBillingPortal(), fixtures.billing_portal);
  return calls;
}
