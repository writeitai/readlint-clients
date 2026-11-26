import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, stat, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
const fixtures = JSON.parse(await readFile(process.argv[2], "utf8"));
const cli = resolve("node_modules/readlint.com/dist/cli.js");
const temporary = await mkdtemp(join(tmpdir(), "readlint-cli-"));
let pending = 0, effects = 0, stored = false, drop = true;
const keys = new Map();
const server = createServer(async (request, response) => {
  let raw = ""; for await (const chunk of request) raw += chunk;
  const answer = (status, body) => { response.writeHead(status, {"Content-Type": "application/json"}); response.end(body === undefined ? undefined : JSON.stringify(body)); };
  if (request.url === "/auth/device/code") return answer(200, {...fixtures.device_code, interval: 1});
  if (request.url === "/auth/device/token") return ++pending === 1 ? answer(400, {error: "authorization_pending"}) : answer(200, {...fixtures.device_token, access_token: "rlk_installed"});
  if (request.headers.authorization !== "Bearer rlk_installed") return answer(401, {detail: {code: "authentication_required"}});
  const url = new URL(request.url, "http://localhost");
  if (request.method === "POST") {
    const key = request.headers["idempotency-key"];
    if (keys.has(key) && keys.get(key) !== raw) return answer(409, {detail: {code: "idempotency_key_reused"}});
    if (!keys.has(key)) { keys.set(key, raw); effects++; stored = true; }
    if (drop) { drop = false; request.socket.destroy(); return; }
    return answer(200, fixtures.evaluation);
  }
  if (request.method === "DELETE") { stored = false; return answer(204); }
  if (url.pathname === "/v1/evaluations") return answer(200, {...fixtures.page, items: stored ? fixtures.page.items : []});
  return stored ? answer(200, fixtures.evaluation) : answer(404, {detail: {code: "evaluation_not_found"}});
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const baseUrl = `http://127.0.0.1:${server.address().port}`;
const env = {...process.env, HOME: temporary, USERPROFILE: temporary, XDG_CONFIG_HOME: temporary, READLINT_BASE_URL: baseUrl};
delete env.READLINT_API_KEY;
function run(args, extra = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [cli, ...args], {env: {...env, ...extra}, stdio: ["ignore", "pipe", "pipe"]});
    let out = "", err = ""; child.stdout.on("data", c => out += c); child.stderr.on("data", c => err += c);
    child.on("error", reject); child.on("close", code => resolve({code, out, err}));
  });
}
try {
  let result = await run(["login", "--json"]);
  assert.equal(result.code, 0, result.err); assert.deepEqual(JSON.parse(result.out), {signed_in: true}); assert.match(result.err, /BCDF-GHJK/);
  const credentials = process.platform === "darwin" ? join(temporary, "Library/Application Support/readlint/credentials.json") : join(temporary, "readlint/credentials.json");
  assert.equal((await stat(credentials)).mode & 0o777, 0o600);
  const saved = JSON.parse(await readFile(credentials, "utf8")); assert.equal(saved.api, baseUrl);
  const file = join(temporary, "post.md"); await writeFile(file, "# Article");
  result = await run(["check", file, "--idempotency-key", "cli-once", "--json"]);
  assert.equal(result.code, 0, result.err); assert.equal(JSON.parse(result.out).id, fixtures.evaluation.id); assert.equal(effects, 1); assert.match(result.err, /cli-once/);
  for (const args of [["list"], ["get", fixtures.evaluation.id]]) { result = await run([...args, "--json"]); assert.equal(result.code, 0, result.err); JSON.parse(result.out); }
  result = await run(["list", "--json"], {READLINT_API_KEY: "secret-wrong"});
  assert.equal(result.code, 1); assert.equal(result.out, ""); assert.equal(JSON.parse(result.err).error.code, "authentication_required"); assert.ok(!result.err.includes("secret-wrong"));
  result = await run(["list", "--api-key", "rlk_installed", "--json"], {READLINT_API_KEY: "secret-wrong"}); assert.equal(result.code, 0, result.err);
  result = await run(["evaluate", file, "--bad-secret", "secret-wrong", "--json"]); assert.equal(result.code, 1); assert.equal(result.out, ""); assert.equal(JSON.parse(result.err).error.code, "invalid_input"); assert.ok(!result.err.includes("secret-wrong"));
  const transport = new StdioClientTransport({command: process.execPath, args: [cli, "mcp"], env, stderr: "pipe"});
  const client = new Client({name: "installed-test", version: "1"});
  try {
    await client.connect(transport);
    const {tools} = await client.listTools(); assert.deepEqual(tools.map(t => t.name), ["evaluate_article", "get_evaluation", "list_evaluations", "delete_evaluation"]);
    assert.ok(Buffer.byteLength(JSON.stringify(tools)) <= 6000);
    for (const [name, args] of [["evaluate_article", {article: "# Article", idempotency_key: "mcp-once"}], ["get_evaluation", {evaluation_id: fixtures.evaluation.id}], ["list_evaluations", {}]]) {
      const result = await client.callTool({name, arguments: args}); assert.equal(result.isError, false); assert.deepEqual(result.structuredContent, JSON.parse(result.content[0].text));
    }
    const before = effects;
    assert.equal((await client.callTool({name: "evaluate_article", arguments: {article: "# Article", idempotency_key: "mcp-once"}})).isError, false); assert.equal(effects, before);
    let failure = await client.callTool({name: "evaluate_article", arguments: {article: "changed", idempotency_key: "mcp-once"}}); assert.equal(failure.isError, true); assert.equal(failure.structuredContent.error.code, "idempotency_key_reused"); assert.equal(failure.structuredContent.error.idempotency_key, "mcp-once");
    failure = await client.callTool({name: "get_evaluation", arguments: {evaluation_id: "secret-invalid"}}); assert.equal(failure.isError, true); assert.equal(failure.structuredContent.error.code, "invalid_input"); assert.ok(!JSON.stringify(failure).includes("secret-invalid"));
    assert.equal((await client.callTool({name: "delete_evaluation", arguments: {evaluation_id: fixtures.evaluation.id}})).isError, false);
    failure = await client.callTool({name: "get_evaluation", arguments: {evaluation_id: fixtures.evaluation.id}}); assert.equal(failure.structuredContent.error.code, "evaluation_not_found");
  } finally { await client.close(); }
  result = await run(["logout", "--json"]); assert.equal(result.code, 0);
  result = await run(["list", "--json"]); assert.equal(JSON.parse(result.err).error.code, "authentication_required");
  await writeFile(credentials, JSON.stringify({...saved, api: "https://other.example"}), {mode: 0o600});
  result = await run(["list", "--json"]); assert.equal(result.code, 1); assert.equal(JSON.parse(result.err).error.code, "authentication_required");
  console.log("Installed CLI + real stdio MCP: device login, shared owner-only credentials, precedence, CRUD, errors, retry identity and one stored effect passed.");
} finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await rm(temporary, {recursive: true, force: true}); }
