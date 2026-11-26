import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, chmod, writeFile, symlink, unlink, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { credentialsPath, saveCredentials, loadCredentials } from "../dist/auth.js";
test("saved credentials reject expired, wrong-origin, readable and symlink files", async () => {
  const temporary = await mkdtemp(join(tmpdir(), "readlint-auth-"));
  const home = process.env.HOME, config = process.env.XDG_CONFIG_HOME;
  process.env.HOME = temporary; process.env.XDG_CONFIG_HOME = temporary;
  try {
    await saveCredentials("https://readlint.com", "rlk_shared", 60);
    assert.equal(await loadCredentials("https://readlint.com"), "rlk_shared");
    await assert.rejects(loadCredentials("https://other.example"), {code: "authentication_required"});
    await chmod(credentialsPath(), 0o644);
    await assert.rejects(loadCredentials("https://readlint.com"), {code: "authentication_required"});
    await saveCredentials("https://readlint.com", "rlk_shared", -1);
    await assert.rejects(loadCredentials("https://readlint.com"), {code: "authentication_required"});
    const target = join(temporary, "target");
    await writeFile(target, JSON.stringify({api: "https://readlint.com", access_token: "rlk_shared", expires_at: Date.now() / 1000 + 60}), {mode: 0o600});
    await unlink(credentialsPath()); await symlink(target, credentialsPath());
    await assert.rejects(loadCredentials("https://readlint.com"), {code: "authentication_required"});
  } finally {
    if (home === undefined) delete process.env.HOME; else process.env.HOME = home;
    if (config === undefined) delete process.env.XDG_CONFIG_HOME; else process.env.XDG_CONFIG_HOME = config;
    await rm(temporary, {recursive: true, force: true});
  }
});
