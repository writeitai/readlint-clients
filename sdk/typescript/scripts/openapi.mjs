// Adapted from fsit's regenerate-into-a-temporary-directory freshness check.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const check = process.argv.includes("--check");
const temporary = mkdtempSync(join(tmpdir(), "readlint-types-"));
try {
  execFileSync("openapi-ts", [], {
    stdio: "inherit",
    env: { ...process.env, READLINT_OPENAPI_OUTPUT: check ? temporary : "src/gen" },
  });
  if (check) execFileSync("diff", ["-ru", "src/gen", temporary], { stdio: "inherit" });
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
