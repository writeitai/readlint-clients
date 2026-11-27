import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { inspect } from "node:util";
import { test } from "node:test";
import { Readlint, ReadlintError } from "../dist/index.js";
import { exercise } from "./contract.mjs";
const fixtures = JSON.parse(readFileSync(new URL("../../../contracts/fixtures.json", import.meta.url)));
const result = fixtures.evaluation;
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), {status, headers});

test("all operations expose their inputs and return typed JSON", async () => {
  const calls = await exercise({Readlint}, fixtures);
  assert.equal(calls.length, 7);
  assert.equal(calls[2].headers.Authorization, "Bearer rlk_contract");
  assert.equal(calls[0].headers.Authorization, undefined);
  assert.deepEqual(calls[2].body, {article: "# Article", title: "Contract", description: "Context"});
});

for (const kind of ["network", "429", "503"]) {
  test(`idempotent submission retries identical bytes: ${kind}`, async () => {
    const calls = [];
    const client = new Readlint({apiKey: "secret", fetch: async (url, options) => {
      calls.push(options);
      if (calls.length === 1) {
        if (kind === "network") throw new Error("secret must never escape");
        return json({}, Number(kind), {"Retry-After": "0"});
      }
      return json(result);
    }});
    assert.deepEqual(await client.evaluate("article", {idempotencyKey: "same-key"}), result);
    assert.equal(calls.length, 2);
    assert.equal(calls[0].body, calls[1].body);
    assert.deepEqual(calls[0].headers, calls[1].headers);
    assert.equal(calls[0].redirect, "manual");
    assert(calls[0].signal instanceof AbortSignal);
  });
}

test("Retry-After long waits are not retried early", async () => {
  for (const value of ["120", new Date(Date.now() + 120000).toUTCString()]) {
    let calls = 0;
    const client = new Readlint({apiKey: "key", fetch: async () => {
      calls++;
      return json({}, 429, {"Retry-After": value});
    }});
    await assert.rejects(client.listEvaluations(), {code: "rate_limited", status: 429});
    assert.equal(calls, 1);
  }
});

for (const [status, body, code] of [
  [401, {detail: {code: "authentication_required"}}, "authentication_required"],
  [422, {detail: {code: "validation_error", input: "rlk_secret"}}, "validation_error"],
  [500, {detail: {code: "rlk_secret"}}, "api_error"],
  [500, ["rlk_secret"], "api_error"],
  [400, {error: "authorization_pending"}, "authorization_pending"],
  [400, {error: "slow_down"}, "slow_down"],
]) {
  test(`sanitized HTTP ${status} / ${code}`, async () => {
    const client = new Readlint({apiKey: "rlk_secret", maxRetries: 0, fetch: async () => json(body, status)});
    await assert.rejects(client.listEvaluations(), error => {
      assert(error instanceof ReadlintError);
      assert.equal(error.code, code);
      assert.equal(error.status, status);
      assert(!inspect(error).includes("rlk_secret"));
      return true;
    });
    assert(!inspect(client).includes("rlk_secret"));
  });
}

test("terminal failed evaluation preserves its safe ID and is not retried", async () => {
  let calls = 0;
  const client = new Readlint({apiKey: "key", fetch: async () => {
    calls++;
    return json({...result, status: "failed"}, 502);
  }});
  await assert.rejects(client.evaluate("article", {idempotencyKey: "once"}),
    {code: "evaluation_failed", evaluationId: result.id, status: 502});
  assert.equal(calls, 1);
});

test("redirects, deletes and device exchange are never retried", async () => {
  for (const operation of [c => c.deleteEvaluation(result.id), c => c.createDeviceToken("device")]) {
    let calls = 0;
    const client = new Readlint({apiKey: "key", fetch: async () => {
      calls++;
      throw new Error("rlk_secret");
    }});
    await assert.rejects(operation(client), {code: "network_error"});
    assert.equal(calls, 1);
  }
  const client = new Readlint({apiKey: "key", fetch: async (_url, options) => {
    assert.equal(options.redirect, "manual");
    return new Response(null, {status: 307, headers: {Location: "https://other.invalid"}});
  }});
  await assert.rejects(client.listEvaluations(), {code: "api_error", status: 307});
});

test("body reads have a deadline and malformed successes fail", async () => {
  const client = new Readlint({apiKey: "key", maxRetries: 0, timeoutMs: 10, fetch: async (_url, options) => ({
    text: () => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new Error("secret")));
    }),
  })});
  // AbortSignal.timeout does not keep the process alive on its own.
  const keepAlive = setTimeout(() => {}, 500);
  try { await assert.rejects(client.listEvaluations(), {code: "network_error"}); }
  finally { clearTimeout(keepAlive); }
  for (const body of ["not json", "[]", "null"]) {
    const invalid = new Readlint({apiKey: "key", fetch: async () => new Response(body)});
    await assert.rejects(invalid.listEvaluations(), {code: "invalid_response"});
  }
});

test("unsafe origins and inputs fail before sending credentials", async () => {
  for (const baseUrl of ["http://example.com", "https://user:pass@example.com", "https://example.com?key=x", "https://example.com/path", "file:///tmp/a"]) {
    assert.throws(() => new Readlint({baseUrl}), TypeError);
  }
  const client = new Readlint({apiKey: "key", fetch: () => assert.fail("unexpected request")});
  assert.throws(() => client.getEvaluation("../auth"), TypeError);
  assert.throws(() => client.getEvaluation(fixtures.evaluation.id + "\n"), TypeError);
  for (const idempotencyKey of ["has spaces", "", undefined, null]) {
    assert.throws(() => client.evaluate("text", {idempotencyKey}), TypeError);
  }
  assert.throws(() => client.listEvaluations({limit: 0}), TypeError);
  assert.throws(() => client.listEvaluations({offset: 0.5}), TypeError);
  assert.throws(() => new Readlint({timeoutMs: Infinity}), TypeError);
  assert.throws(() => new Readlint({maxRetries: 1.5}), TypeError);
  const oldKey = process.env.READLINT_API_KEY;
  delete process.env.READLINT_API_KEY;
  try { await assert.rejects(new Readlint().listEvaluations(), {code: "authentication_required"}); }
  finally { if (oldKey !== undefined) process.env.READLINT_API_KEY = oldKey; }
});


test("a long server wait preserves its documented error code", async () => {
  const client = new Readlint({apiKey: "key", fetch: async () =>
    json({detail: {code: "evaluation_disabled"}}, 503, {"Retry-After": "120"})});
  await assert.rejects(client.listEvaluations(), {code: "evaluation_disabled", status: 503});
});

test("large retry limits retain sanitized network errors after the backoff cap", async t => {
  t.mock.method(globalThis, "setTimeout", callback => { queueMicrotask(callback); return 0; });
  let calls = 0;
  const client = new Readlint({apiKey: "key", maxRetries: 8, fetch: async () => {
    calls++;
    throw new Error("rlk_secret");
  }});
  await assert.rejects(client.listEvaluations(), error =>
    error instanceof ReadlintError && error.code === "network_error" && !error.message.includes("rlk_secret"));
  assert.equal(calls, 7);
});
