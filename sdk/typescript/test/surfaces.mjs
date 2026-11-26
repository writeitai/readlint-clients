import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { main } from "../dist/cli.js";
import { callTool } from "../dist/mcp.js";
const fixtures = JSON.parse(readFileSync(new URL("../../../contracts/fixtures.json", import.meta.url)));
const calls = [];
const originalFetch = globalThis.fetch;
const log = console.log, error = console.error;
const originalConfig = process.env.XDG_CONFIG_HOME;
const originalHome = process.env.HOME;
const temporary = await mkdtemp(join(tmpdir(), "readlint-contract-"));
process.env.XDG_CONFIG_HOME = temporary;
process.env.HOME = temporary;
// login storage is replaced only in this in-process fixture; real polling/storage
// is exercised separately by the installed-package suite.
let writes = [];
console.log = value => writes.push(value);
console.error = () => {};
globalThis.fetch = async (url, options) => {
  const parsed = new URL(url);
  calls.push({method: options.method, path: parsed.pathname, query: Object.fromEntries(parsed.searchParams),
    headers: options.headers, body: options.body ? options.headers["Content-Type"] === "application/json" ? JSON.parse(options.body) : Object.fromEntries(new URLSearchParams(options.body)) : null});
  const name = parsed.pathname === "/auth/device/code" ? "device_code" : parsed.pathname === "/auth/device/token" ? "device_token" : options.method === "GET" && parsed.pathname === "/v1/evaluations" ? "page" : "evaluation";
  const body = name === "device_code" ? {...fixtures[name], interval: 0} : fixtures[name];
  return new Response(options.method === "DELETE" ? null : JSON.stringify(body), {status: options.method === "DELETE" ? 204 : 200});
};
try {
  const file = join(temporary, "post.md");
  await writeFile(file, "# Article");
  for (const args of [
    ["login"], ["check", file, "--title", "Contract", "--description", "Context", "--idempotency-key", "contract-key"],
    ["list", "--limit", "3", "--offset", "2"], ["get", fixtures.evaluation.id], ["delete", fixtures.evaluation.id],
  ]) { assert.equal(await main(["--api-key", "rlk_contract", "--json", "--timeout", "0.1234", ...args]), 0); JSON.parse(writes.pop()); }
  // Device hostname/OS are platform-specific and validated separately.
  calls[0].body.hostname = "fixture-host"; calls[0].body.os = "fixture-os";
  const node_cli = calls.splice(0);
  for (const [name, args] of [
    ["evaluate_article", {article: "# Article", title: "Contract", description: "Context", idempotency_key: "contract-key"}],
    ["list_evaluations", {limit: 3, offset: 2}], ["get_evaluation", {evaluation_id: fixtures.evaluation.id}], ["delete_evaluation", {evaluation_id: fixtures.evaluation.id}],
  ]) assert.equal((await callTool(name, args, {apiKey: "rlk_contract"})).isError, false);
  console.log = log;
  log(JSON.stringify({node_cli, node_mcp: calls}));
} finally {
  globalThis.fetch = originalFetch; console.log = log; console.error = error;
  if (originalConfig === undefined) delete process.env.XDG_CONFIG_HOME; else process.env.XDG_CONFIG_HOME = originalConfig;
  if (originalHome === undefined) delete process.env.HOME; else process.env.HOME = originalHome;
  await rm(temporary, {recursive: true, force: true});
}
