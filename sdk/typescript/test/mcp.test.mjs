import assert from "node:assert/strict";
import { test } from "node:test";
import { callTool } from "../dist/mcp.js";
for (const [name, args] of [
  ["secret-token", {}], ["list_evaluations", {api_key: "secret-token"}],
  ["evaluate_article", {article: "text", idempotency_key: "secret-token\n"}],
  ["evaluate_article", {article: "", idempotency_key: "retained"}],
  ["get_evaluation", {evaluation_id: "secret-token"}],
]) test(`sanitized invalid tool input: ${name}`, async () => {
  const result = await callTool(name, args, {apiKey: "secret-token"});
  assert.equal(result.isError, true); assert.equal(result.structuredContent.error.code, "invalid_input");
  assert.ok(!JSON.stringify(result).includes("secret-token"));
});
for (const [status, code] of [[401, "authentication_required"], [422, "validation_error"], [503, "api_error"]]) {
  test(`MCP HTTP ${status} errors retain submission key`, async () => {
    const result = await callTool("evaluate_article", {article: "text", idempotency_key: "retained"}, {apiKey: "secret-token", maxRetries: 0,
      fetch: async () => new Response(JSON.stringify({detail: {code: "secret-token"}}), {status})});
    assert.equal(result.isError, true); assert.equal(result.structuredContent.error.code, code);
    assert.equal(result.structuredContent.error.idempotency_key, "retained"); assert.equal(result.structuredContent.error.status, status);
    assert.deepEqual(result.structuredContent, JSON.parse(result.content[0].text)); assert.ok(!JSON.stringify(result).includes("secret-token"));
  });
}
