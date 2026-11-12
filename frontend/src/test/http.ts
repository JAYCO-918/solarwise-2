import { vi } from "vitest";

export interface RecordedCall {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

type Answer = Response | ((call: RecordedCall) => Response);

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

export function apiError(status: number, code: string, message: string, details: unknown = null): Response {
  return json({ error: { code, message, details } }, status);
}

/**
 * Replace `fetch` by a table of answers keyed by "METHOD /path" (path without the /api/v1 prefix).
 * An unknown request is answered 404 in the server's error format, and every request is recorded.
 */
export function mockApi(routes: Record<string, Answer>): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const call: RecordedCall = {
      method: (init.method ?? "GET").toUpperCase(),
      path: url.pathname.replace(/^\/api\/v1/, "") + url.search,
      headers: Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>).map(([k, v]) => [k.toLowerCase(), v])),
      body: typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : (init.body ?? null),
    };
    calls.push(call);
    const answer = routes[`${call.method} ${call.path}`];
    if (answer === undefined) return apiError(404, "NOT_FOUND", `no such API endpoint: ${call.path}`);
    // A Response can be read once: hand out a copy each time.
    return typeof answer === "function" ? answer(call) : answer.clone();
  }));
  return calls;
}

export const TOKEN = {
  access_token: "token-for-tests",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  user: { id: 7, email: "demo-visitor@solarwise.invalid", full_name: "Demonstration visitor", role: "ENGINEER", is_active: true, is_demo: true },
};
