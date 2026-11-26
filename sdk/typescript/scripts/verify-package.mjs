// Install the exact tarball outside the source tree, type-check the documented
// example using shipped declarations, then exercise real fetch over loopback.
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const sdk = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const temporary = mkdtempSync(join(tmpdir(), "readlint-installed-"));
const run = (command, args) => execFileSync(command, args, {cwd: temporary, stdio: "inherit"});
try {
  writeFileSync(join(temporary, "package.json"), JSON.stringify({private: true, type: "module"}));
  run("npm", ["install", "--ignore-scripts", "--no-package-lock", resolve(process.argv[2])]);
  for (const file of ["example.mts", "installed.mjs"]) copyFileSync(join(sdk, "test", file), join(temporary, file));
  run(process.execPath, [join(sdk, "node_modules/typescript/bin/tsc"), "--strict", "--noEmit", "--target", "ES2022", "--module", "NodeNext", "example.mts"]);
  run(process.execPath, ["installed.mjs", join(sdk, "../../contracts/fixtures.json")]);
} finally {
  rmSync(temporary, {recursive: true, force: true});
}
