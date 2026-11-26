// Fetch transport and private credentials adapted from mountable's TypeScript SDK.
import type {
  EvaluationResult, EvaluationPage, EvaluationReport, EvaluationSummary,
  EvaluationRequest, DeviceCodeResponse, DeviceTokenResponse,
} from "./gen/types.gen.js";
export type {
  EvaluationResult as Evaluation, EvaluationPage, EvaluationReport, EvaluationSummary,
  CheckResult, ProseResult, PhraseResult, DeviceCodeResponse, DeviceTokenResponse,
} from "./gen/types.gen.js";

const RECOVERY: Record<string, string> = {
  authentication_required: "Pass apiKey or set READLINT_API_KEY; obtain a key in the web app or with readlint login.",
  evaluation_credit_exhausted: "Check your evaluation credit in the web app.",
  evaluation_not_allowed: "Ask support@readlint.com for evaluation access.",
  evaluation_disabled: "Try again later with the same idempotency key and article.",
  evaluation_context_exceeded: "Shorten the article and submit with a new key.",
  evaluation_not_found: "List evaluations to find an unexpired evaluation ID.",
  idempotency_key_reused: "Use the original article and options, or a new key for a new evaluation.",
  validation_error: "Check the input before retrying.",
  invalid_request: "Check the request fields before trying again.",
  invalid_page_size: "Choose a smaller limit.",
  authorization_pending: "Approve the code in the web app before polling again.",
  slow_down: "Wait at least five seconds longer before polling again.",
  access_denied: "Approval was denied, used, or canceled; start device login again.",
  expired_token: "The code expired; start device login again.",
  invalid_grant: "The device request is invalid; start device login again.",
  unsupported_grant_type: "Use the documented device grant type.",
};

/** Sanitized failure. status is null when no reliable HTTP answer arrived. */
export class ReadlintError extends Error {
  readonly name = "ReadlintError";
  constructor(
    readonly code: string,
    message: string,
    readonly status: number | null = null,
    readonly evaluationId: string | null = null,
  ) { super(message); }
}

export interface ReadlintOptions {
  apiKey?: string;
  /** HTTPS origin; HTTP is allowed only on loopback for development. */
  baseUrl?: string;
  /** Deadline per attempt, including reading the body. Default: 120000 ms. */
  timeoutMs?: number;
  /** Retries for reads and idempotent submissions only. Default: 2. */
  maxRetries?: number;
  fetch?: typeof globalThis.fetch;
}

export interface EvaluateOptions {
  /** Required: retain this key and identical article/options after a lost response. */
  idempotencyKey: string;
  title?: string | null;
  description?: string;
}

function env(name: string): string | undefined {
  return typeof process !== "undefined" ? process.env[name] : undefined;
}

function origin(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new TypeError("Use a valid HTTPS origin."); }
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/" ||
      (url.protocol !== "https:" && !(url.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)))) {
    throw new TypeError("Use an HTTPS origin (HTTP is allowed on loopback).");
  }
  return url.origin;
}

function uuid(value: string): string {
  if (typeof value !== "string" || value.length !== 36 || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) {
    throw new TypeError("Use a valid evaluation UUID.");
  }
  return value.toLowerCase();
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function problem(status: number, body: unknown): ReadlintError {
  const raw = object(body) ? (object(body.detail) ? body.detail.code : body.error) : null;
  const code = typeof raw === "string" && Object.hasOwn(RECOVERY, raw) ? raw :
    ({401: "authentication_required", 422: "validation_error", 429: "rate_limited"}[status] ?? "api_error");
  return new ReadlintError(code,
    `HTTP ${status}: ${code}. ${RECOVERY[code] ?? "Retry later; for a submission reuse its key and identical input."}`, status);
}

function retryDelay(response: Response | undefined, attempt: number): number | null {
  let seconds = 2 ** attempt;
  const value = response?.headers.get("Retry-After");
  if (value) {
    const number = Number(value);
    const date = Date.parse(value);
    if (Number.isFinite(number)) seconds = number;
    else if (Number.isFinite(date)) seconds = (date - Date.now()) / 1000;
  }
  return Number.isFinite(seconds) && seconds <= 60 ? Math.max(0, seconds) * 1000 : null;
}

/** Typed evaluation API and low-level device flow. The SDK transport uses native fetch. */
export class Readlint {
  readonly baseUrl: string;
  readonly #apiKey: string | undefined;
  readonly #timeoutMs: number;
  readonly #maxRetries: number;
  readonly #fetch: typeof globalThis.fetch;

  constructor(options: ReadlintOptions = {}) {
    this.baseUrl = origin(options.baseUrl || env("READLINT_BASE_URL") || "https://readlint.com");
    this.#apiKey = options.apiKey || env("READLINT_API_KEY");
    this.#timeoutMs = options.timeoutMs ?? 120_000;
    this.#maxRetries = options.maxRetries ?? 2;
    if (!Number.isInteger(this.#timeoutMs) || this.#timeoutMs <= 0 || this.#timeoutMs > 4_294_967_295 ||
        !Number.isInteger(this.#maxRetries) || this.#maxRetries < 0) {
      throw new TypeError("timeoutMs must be an integer from 1 to 4294967295; maxRetries must be a nonnegative integer.");
    }
    this.#fetch = options.fetch ?? globalThis.fetch;
  }

  evaluate(article: string, options: EvaluateOptions): Promise<EvaluationResult> {
    if (typeof options?.idempotencyKey !== "string" || !/^[!-~]{1,255}$(?![\s\S])/.test(options.idempotencyKey)) {
      throw new TypeError("idempotencyKey must be 1–255 printable ASCII characters without spaces.");
    }
    const body: EvaluationRequest = {
      article, title: options.title ?? null, description: options.description ?? "",
    };
    return this.#request("POST", "/v1/evaluations", true, JSON.stringify(body), {
      "Content-Type": "application/json", "Idempotency-Key": options.idempotencyKey,
    });
  }

  listEvaluations(options: {limit?: number; offset?: number} = {}): Promise<EvaluationPage> {
    const offset = options.offset ?? 0;
    if (!Number.isSafeInteger(offset) || offset < 0 ||
        (options.limit !== undefined && (!Number.isSafeInteger(options.limit) || options.limit < 1))) {
      throw new TypeError("offset must be a nonnegative safe integer; limit must be a positive safe integer.");
    }
    const query = new URLSearchParams({ offset: String(offset) });
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    return this.#request("GET", `/v1/evaluations?${query}`, true);
  }

  getEvaluation(evaluationId: string): Promise<EvaluationResult> {
    return this.#request("GET", `/v1/evaluations/${uuid(evaluationId)}`, true);
  }

  async deleteEvaluation(evaluationId: string): Promise<void> {
    await this.#request("DELETE", `/v1/evaluations/${uuid(evaluationId)}`, false);
  }

  /** Display verification_uri_complete, then poll no faster than interval. */
  createDeviceCode(options: {hostname?: string; os?: string} = {}): Promise<DeviceCodeResponse> {
    return this.#request("POST", "/auth/device/code", false, new URLSearchParams({
      client_id: "readlint-cli", hostname: options.hostname ?? "", os: options.os ?? "",
    }).toString(), { "Content-Type": "application/x-www-form-urlencoded" }, false);
  }

  /** One poll only. Handle authorization_pending and slow_down explicitly. Never persisted by the SDK. */
  createDeviceToken(deviceCode: string): Promise<DeviceTokenResponse> {
    return this.#request("POST", "/auth/device/token", false, new URLSearchParams({
      client_id: "readlint-cli", grant_type: "urn:ietf:params:oauth:grant-type:device_code", device_code: deviceCode,
    }).toString(), { "Content-Type": "application/x-www-form-urlencoded" }, false);
  }

  async #request<T>(method: string, path: string, retry: boolean, body?: string,
    extraHeaders: Record<string, string> = {}, authenticated = true): Promise<T> {
    if (authenticated && !this.#apiKey) {
      throw new ReadlintError("authentication_required", RECOVERY.authentication_required);
    }
    const headers = { ...extraHeaders };
    if (authenticated) headers.Authorization = `Bearer ${this.#apiKey}`;
    for (let attempt = 0; attempt <= this.#maxRetries; attempt++) {
      let response: Response | undefined;
      let text: string | undefined;
      let json: unknown;
      try {
        response = await this.#fetch(this.baseUrl + path, {
          method, headers, body, redirect: "manual", signal: AbortSignal.timeout(this.#timeoutMs),
        });
        text = await response.text();
      } catch {
        // Fetch exceptions may contain credentials or request input. Never echo them.
        if (!retry || attempt === this.#maxRetries) {
          throw new ReadlintError("network_error", "No reliable response. Check your connection; for a submission reuse its key and identical input.");
        }
      }
      if (text !== undefined && response) {
        try { json = JSON.parse(text); } catch { json = null; }
        if (response.ok) {
          if (response.status === 204) return undefined as T;
          if (!object(json)) throw new ReadlintError("invalid_response", "The service returned invalid JSON; retry later with the same submission key.");
          return json as T;
        }
        if (object(json) && json.status === "failed") {
          let id: string | null = null;
          try { if (typeof json.id === "string") id = uuid(json.id); } catch { /* omit unsafe IDs */ }
          throw new ReadlintError("evaluation_failed", "Evaluation failed. Read its ID for details; a deliberate new attempt needs a new idempotency key.", response.status, id);
        }
        if (!retry || ![429, 502, 503, 504].includes(response.status) || attempt === this.#maxRetries) {
          throw problem(response.status, json);
        }
      }
      const delay = retryDelay(response, attempt);
      if (delay === null) {
        if (response) throw problem(response.status, json);
        throw new ReadlintError("network_error", "No reliable response. Check your connection; for a submission reuse its key and identical input.");
      }
      await new Promise(resolve => setTimeout(resolve, delay));
    }
    throw new Error("unreachable");
  }
}
