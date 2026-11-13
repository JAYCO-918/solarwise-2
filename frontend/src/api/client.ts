/**
 * The only place that talks to the server. Every URL is relative: the application and the API share one origin.
 */

const API = "/api/v1";
const STORAGE_KEY = "solarwise.session";
/**
 * The access token travels twice: in the standard `Authorization` header and in a header of its own. Some reverse
 * proxies and hosting gateways remove `Authorization`, or replace it with a credential of their own, before a request
 * reaches the server; the server accepts either header.
 */
export const TOKEN_HEADER = "X-SolarWise-Token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface StoredSession {
  token: string;
  expiresAt: string;
}

let session: StoredSession | null = null;
let unauthorizedHandler: ((error: ApiError) => void) | null = null;

function readStored(): StoredSession | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" && parsed !== null &&
      typeof (parsed as StoredSession).token === "string" &&
      typeof (parsed as StoredSession).expiresAt === "string"
    ) {
      const stored = parsed as StoredSession;
      return new Date(stored.expiresAt).getTime() > Date.now() ? stored : null;
    }
  } catch {
    // Storage unavailable or corrupted: behave as signed out.
  }
  return null;
}

/** The token lives in memory and in sessionStorage: it ends with the tab and is never written to localStorage. */
export function restoreSession(): boolean {
  session = readStored();
  return session !== null;
}

export function setSession(token: string, expiresAt: string): void {
  session = { token, expiresAt };
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Kept in memory only.
  }
}

export function clearSession(): void {
  session = null;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to remove.
  }
}

export function hasSession(): boolean {
  return session !== null;
}

/** Called, with the server's answer, when the server no longer accepts the token (expired, revoked, not received). */
export function onUnauthorized(handler: ((error: ApiError) => void) | null): void {
  unauthorizedHandler = handler;
}

interface RequestOptions {
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | null | undefined>;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  if (!query) return API + path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined) params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${API}${path}?${text}` : API + path;
}

async function toError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`;
  let message = response.statusText || "The request failed.";
  let details: unknown = null;
  try {
    const payload: unknown = await response.json();
    const error = (payload as { error?: { code?: unknown; message?: unknown; details?: unknown } } | null)?.error;
    if (error && typeof error.message === "string") {
      message = error.message;
      if (typeof error.code === "string") code = error.code;
      details = error.details ?? null;
    }
  } catch {
    // Not JSON (for example a gateway page): keep the status text.
  }
  return new ApiError(response.status, code, message, details);
}

async function send(method: string, path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const sentWithToken = session !== null;
  if (session) {
    headers.Authorization = `Bearer ${session.token}`;
    headers[TOKEN_HEADER] = session.token;
  }
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), { method, headers, body, signal: options.signal });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "NETWORK", "The server could not be reached. Check the connection and try again.");
  }
  if (!response.ok) {
    const error = await toError(response);
    if (response.status === 401 && sentWithToken) {
      clearSession();
      unauthorizedHandler?.(error);
    }
    throw error;
  }
  return response;
}

export async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(method, path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("PATCH", path, { ...options, body }),
  delete: (path: string, options?: RequestOptions) => request<void>("DELETE", path, options),
  upload: <T>(path: string, form: FormData, options?: RequestOptions) => request<T>("POST", path, { ...options, form }),
};

function fileNameFrom(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      return fallback;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1] ?? fallback;
}

/** Hand a file that is already in memory to the browser as a download. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * Fetch a file with the session's token and hand it to the browser as a download. With a `form` the file is asked
 * for by POST: that is how the server returns something computed from an upload it does not keep.
 */
export async function download(path: string, fallbackName: string, form?: FormData): Promise<string> {
  const response = form ? await send("POST", path, { form }) : await send("GET", path);
  const blob = await response.blob();
  const name = fileNameFrom(response.headers.get("Content-Disposition"), fallbackName);
  saveBlob(blob, name);
  return name;
}
