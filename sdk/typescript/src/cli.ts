#!/usr/bin/env node
import { realpathSync } from "node:fs";
import { parseArgs } from "node:util";
import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import { Readlint, ReadlintError, type ReadlintOptions } from "./index.js";
import { loadCredentials, login, logout } from "./auth.js";
import { VERSION } from "./version.js";

let activeSubmissionKey: string | undefined;

const HELP = `Review articles through readlint.com.
Usage: readlint [options] <command>
Commands:
  check FILE, evaluate FILE  Submit Markdown/MDX (- reads stdin)
  list                      List evaluations (--limit N --offset N)
  get UUID, delete UUID      Read or delete an evaluation
  login, logout             Approve device login or remove local credentials
  mcp                       Serve four MCP tools over stdio
  version                   Print the installed version
Options (before or after command):
  --json                    JSON stdout and JSON errors on stderr
  --api-key KEY              Prefer READLINT_API_KEY to shell history
  --base-url URL             HTTPS API origin; default https://readlint.com
  --timeout SECONDS          HTTP timeout; default 120
  --title TEXT --description TEXT --idempotency-key KEY  Submission options
  --help, -h; --version
`;
async function stdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
  return new TextDecoder("utf-8", {fatal: true}).decode(Buffer.concat(chunks));
}
export async function main(argv = process.argv.slice(2)): Promise<number> {
  const machine = argv.includes("--json");
  let submissionKey: string | undefined;
  try {
    const {values, positionals} = parseArgs({args: argv, allowPositionals: true, strict: true, options: {
      json: {type: "boolean"}, "api-key": {type: "string"}, "base-url": {type: "string"}, timeout: {type: "string"},
      help: {type: "boolean", short: "h"}, version: {type: "boolean"}, title: {type: "string"},
      description: {type: "string"}, "idempotency-key": {type: "string"}, limit: {type: "string"}, offset: {type: "string"},
    }});
    if (values.help) { console.log(HELP); return 0; }
    if (values.version) { console.log(`readlint ${VERSION}`); return 0; }
    const [command, argument] = positionals;
    const takesArgument = ["check", "evaluate", "get", "delete"].includes(command);
    if (!command || !["check", "evaluate", "list", "get", "delete", "login", "logout", "version", "mcp"].includes(command) ||
        positionals.length !== (takesArgument ? 2 : 1)) throw new TypeError();
    for (const flag of ["title", "description", "idempotency-key", "limit", "offset"] as const) {
      if (values[flag] !== undefined && !(["check", "evaluate"].includes(command) ? ["title", "description", "idempotency-key"] : command === "list" ? ["limit", "offset"] : []).includes(flag)) throw new TypeError();
    }
    const timeoutMs = values.timeout === undefined ? 120_000 : Number(values.timeout) * 1000;
    const options: ReadlintOptions = {apiKey: values["api-key"], baseUrl: values["base-url"], timeoutMs};
    let result: unknown;
    if (command === "version") result = {version: VERSION};
    else if (command === "logout") { await logout(); result = {signed_in: false, message: "Local login removed. Revoke its API key at https://readlint.com/app/api-keys."}; }
    else if (command === "mcp") {
      const {serve} = await import("./mcp.js");
      await serve(options); return 0;
    } else {
      let client = new Readlint(options);
      if (command === "login") { await login(client); result = {signed_in: true}; }
      else {
        const apiKey = values["api-key"] || process.env.READLINT_API_KEY || await loadCredentials(client.baseUrl);
        client = new Readlint({...options, apiKey});
        if (command === "check" || command === "evaluate") {
          const article = argument === "-" ? await stdin() : new TextDecoder("utf-8", {fatal: true}).decode(await readFile(argument));
          submissionKey = values["idempotency-key"] || randomUUID();
          activeSubmissionKey = submissionKey;
          console.error(`Idempotency key: ${submissionKey}`);
          result = await client.evaluate(article, {idempotencyKey: submissionKey, title: values.title, description: values.description});
        } else if (command === "list") {
          for (const field of ["limit", "offset"] as const) if (values[field] !== undefined && !/^\+?\d+$/.test(values[field]!)) throw new TypeError();
          result = await client.listEvaluations({limit: values.limit === undefined ? undefined : Number(values.limit), offset: values.offset === undefined ? 0 : Number(values.offset)});
        } else if (command === "get") result = await client.getEvaluation(argument);
        else { await client.deleteEvaluation(argument); result = {deleted: true, id: argument}; }
      }
    }
    console.log(JSON.stringify(result, null, machine ? undefined : 2));
    return 0;
  } catch (error) {
    const problem: Record<string, unknown> = error instanceof ReadlintError ? {code: error.code, message: error.message, status: error.status, evaluation_id: error.evaluationId} : {
      code: "invalid_input", message: "Check the command, UTF-8 input file, URL and credential file permissions. Run `readlint --help`.",
    };
    if (submissionKey) problem.idempotency_key = submissionKey;
    console.error(machine ? JSON.stringify({error: problem}) : `${problem.code}: ${problem.message}`);
    return 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) {
  process.once("SIGINT", () => {
    const error: Record<string, unknown> = {code: "interrupted", message: activeSubmissionKey ? "Interrupted. Reuse the submission key and identical input to check its outcome." : "Interrupted."};
    if (activeSubmissionKey) error.idempotency_key = activeSubmissionKey;
    console.error(process.argv.includes("--json") ? JSON.stringify({error}) : `interrupted: ${error.message}`);
    process.exit(1);
  });
  process.exitCode = await main();
}
