// Device login and credential format shared with the Python CLI.
import { constants } from "node:fs";
import { open, mkdir, rename, unlink } from "node:fs/promises";
import { homedir, hostname, platform } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { Readlint, ReadlintError } from "./index.js";

export function credentialsPath(): string {
  const root = platform() === "darwin" ? join(homedir(), "Library", "Application Support") :
    platform() === "win32" ? process.env.APPDATA || join(homedir(), "AppData", "Roaming") :
    process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
  return join(root, "readlint", "credentials.json");
}

export async function loadCredentials(api: string): Promise<string> {
  try {
    const file = await open(credentialsPath(), constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    try {
      const info = await file.stat();
      if (!info.isFile() || (platform() !== "win32" && ((info.mode & 0o077) || info.uid !== process.getuid?.()))) throw new Error();
      const data = JSON.parse(await file.readFile("utf8"));
      if (data.api !== api || !Number.isFinite(data.expires_at) || data.expires_at <= Date.now() / 1000 ||
          typeof data.access_token !== "string" || !data.access_token) throw new Error();
      return data.access_token;
    } finally { await file.close(); }
  } catch {
    throw new ReadlintError("authentication_required", "No usable saved login. Run `readlint login` or set READLINT_API_KEY.");
  }
}

export async function saveCredentials(api: string, token: string, expiresIn: number): Promise<void> {
  if (platform() === "win32") throw new ReadlintError("unsupported_platform", "Saved login requires POSIX file permissions. Use READLINT_API_KEY on this platform.");
  const path = credentialsPath();
  await mkdir(join(path, ".."), {recursive: true, mode: 0o700});
  const temporary = join(path, "..", `.credentials-${randomUUID()}`);
  try {
    const file = await open(temporary, "wx", 0o600);
    try { await file.writeFile(JSON.stringify({api, access_token: token, expires_at: Date.now() / 1000 + expiresIn})); }
    finally { await file.close(); }
    await rename(temporary, path);
  } finally { await unlink(temporary).catch(() => {}); }
}

export async function logout(): Promise<void> {
  await unlink(credentialsPath()).catch(error => { if (error.code !== "ENOENT") throw error; });
}

export async function login(client: Readlint): Promise<void> {
  if (platform() === "win32") throw new ReadlintError("unsupported_platform", "Saved login requires POSIX file permissions. Use READLINT_API_KEY on this platform.");
  const code = await client.createDeviceCode({hostname: hostname().slice(0, 200), os: platform()});
  if (typeof code.device_code !== "string" || typeof code.verification_uri_complete !== "string" ||
      typeof code.user_code !== "string" || !Number.isFinite(code.expires_in) || code.expires_in <= 0 ||
      !Number.isFinite(code.interval) || code.interval < 0) throw new ReadlintError("invalid_response", "Invalid device response. Update readlint or retry login later.");
  let interval = Math.max(1, code.interval);
  const deadline = performance.now() + code.expires_in * 1000;
  console.error(`Open ${code.verification_uri_complete}\nCheck and approve code ${code.user_code}.`);
  while (performance.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, Math.min(interval * 1000, Math.max(0, deadline - performance.now()))));
    if (performance.now() >= deadline) break;
    try {
      const token = await client.createDeviceToken(code.device_code);
      if (typeof token.access_token !== "string" || !token.access_token || !Number.isFinite(token.expires_in) || token.expires_in <= 0 ||
          typeof token.token_type !== "string" || token.token_type.toLowerCase() !== "bearer") throw new ReadlintError("invalid_response", "Invalid token response. Run `readlint login` again.");
      await saveCredentials(client.baseUrl, token.access_token, token.expires_in);
      return;
    } catch (error) {
      if (!(error instanceof ReadlintError)) throw error;
      if (error.code === "authorization_pending") continue;
      if (error.code === "slow_down") { interval += 5; continue; }
      if (error.code === "network_error") { interval *= 2; continue; }
      throw error;
    }
  }
  throw new ReadlintError("expired_token", "The code expired; run `readlint login` again.");
}
