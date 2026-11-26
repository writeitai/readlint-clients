import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { Readlint, ReadlintError } from "readlint.com";

const fixtures = JSON.parse(readFileSync(process.argv[2]));
const stored = new Map();
let drop = true;
let effects = 0;
const server = createServer(async (request, response) => {
  const answer = (status, body) => {
    response.writeHead(status, {"Content-Type": "application/json"});
    response.end(body === undefined ? undefined : JSON.stringify(body));
  };
  if (request.headers.authorization !== "Bearer rlk_installed") {
    return answer(401, {detail: {code: "authentication_required"}});
  }
  let raw = "";
  for await (const chunk of request) raw += chunk;
  const url = new URL(request.url, "http://localhost");
  if (request.method === "POST") {
    const key = request.headers["idempotency-key"];
    if (stored.has(key) && stored.get(key) !== raw) return answer(409, {detail: {code: "idempotency_key_reused"}});
    if (!stored.has(key)) { stored.set(key, raw); effects++; }
    if (drop) { drop = false; request.socket.destroy(); return; }
    return answer(200, fixtures.evaluation);
  }
  if (request.method === "DELETE") { stored.clear(); return answer(204); }
  if (url.pathname === "/v1/evaluations") return answer(200, {...fixtures.page, items: stored.size ? fixtures.page.items : []});
  return stored.size ? answer(200, fixtures.evaluation) : answer(404, {detail: {code: "evaluation_not_found"}});
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
try {
  const baseUrl = `http://127.0.0.1:${server.address().port}`;
  const client = new Readlint({baseUrl, apiKey: "rlk_installed"});
  const result = await client.evaluate("# Article", {idempotencyKey: "installed-once"});
  assert.equal(result.id, fixtures.evaluation.id);
  assert.equal(effects, 1);
  assert.equal((await client.listEvaluations()).items[0].id, result.id);
  assert.equal((await client.getEvaluation(result.id)).report.input_tokens, 12);
  const invalid = new Readlint({baseUrl, apiKey: "wrong"});
  await assert.rejects(invalid.listEvaluations(), error => error instanceof ReadlintError && error.code === "authentication_required" && !error.message.includes("wrong"));
  await assert.rejects(client.evaluate("different", {idempotencyKey: "installed-once"}), {code: "idempotency_key_reused"});
  await client.deleteEvaluation(result.id);
  await assert.rejects(client.getEvaluation(result.id), {code: "evaluation_not_found"});
  console.log("Installed TypeScript SDK: typed CRUD, controlled auth failure, real HTTP lost-answer retry with one effect.");
} finally {
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
}
