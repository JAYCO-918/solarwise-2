import { describe, expect, it, vi } from "vitest";

import { apiError, json, mockApi } from "../test/http";
import { ApiError, TOKEN_HEADER, api, hasSession, onUnauthorized, restoreSession, setSession } from "./client";

const LATER = new Date(Date.now() + 3_600_000).toISOString();

describe("the access token", () => {
  it("is not sent before a session exists", async () => {
    const calls = mockApi({ "GET /meta": json({ demo_mode: true }) });
    await api.get("/meta");
    expect(calls[0]?.headers.authorization).toBeUndefined();
    expect(calls[0]?.headers[TOKEN_HEADER.toLowerCase()]).toBeUndefined();
  });

  it("travels in both headers, so that a proxy rewriting Authorization does not close the session", async () => {
    const calls = mockApi({ "GET /plants": json([]) });
    setSession("abc.def.ghi", LATER);
    await api.get("/plants");
    expect(calls[0]?.headers.authorization).toBe("Bearer abc.def.ghi");
    expect(calls[0]?.headers["x-solarwise-token"]).toBe("abc.def.ghi");
  });

  it("is kept for the tab only, and forgotten once expired or unreadable", () => {
    setSession("abc", LATER);
    expect(window.localStorage.length).toBe(0);
    expect(JSON.parse(window.sessionStorage.getItem("solarwise.session") ?? "{}")).toEqual({ token: "abc", expiresAt: LATER });
    expect(restoreSession()).toBe(true);

    window.sessionStorage.setItem("solarwise.session", JSON.stringify({ token: "abc", expiresAt: "2020-01-01T00:00:00Z" }));
    expect(restoreSession()).toBe(false);
    window.sessionStorage.setItem("solarwise.session", "{not json");
    expect(restoreSession()).toBe(false);
    expect(hasSession()).toBe(false);
  });
});

describe("a refused request", () => {
  it("carries the server's code, message and details", async () => {
    mockApi({ "POST /plants/1/datasets": apiError(409, "DUPLICATE_DATASET", "this file was already imported", { dataset_id: 4 }) });
    const error = await api.post("/plants/1/datasets", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "DUPLICATE_DATASET", message: "this file was already imported", details: { dataset_id: 4 } });
  });

  it("is still an error when the answer is not the server's (a gateway page)", async () => {
    mockApi({ "GET /plants": new Response("<html>Bad gateway</html>", { status: 502, statusText: "Bad Gateway" }) });
    await expect(api.get("/plants")).rejects.toMatchObject({ status: 502, code: "HTTP_502", message: "Bad Gateway" });
  });

  it("says so when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(api.get("/plants")).rejects.toMatchObject({ status: 0, code: "NETWORK" });
  });

  it("lets an aborted request through as an abort, not as a failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new DOMException("aborted", "AbortError"))));
    await expect(api.get("/plants")).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("a session the server no longer accepts", () => {
  it("is closed, and the server's answer is handed to the application", async () => {
    mockApi({ "GET /plants": apiError(401, "NOT_AUTHENTICATED", "the access token is invalid or has expired") });
    const closed = vi.fn();
    onUnauthorized(closed);
    setSession("abc", LATER);
    await expect(api.get("/plants")).rejects.toMatchObject({ status: 401 });
    expect(hasSession()).toBe(false);
    expect(window.sessionStorage.getItem("solarwise.session")).toBeNull();
    expect(closed).toHaveBeenCalledTimes(1);
    expect(closed.mock.calls[0]?.[0]).toMatchObject({ message: "the access token is invalid or has expired" });
  });

  it("is not confused with a wrong password: a 401 without a session closes nothing", async () => {
    mockApi({ "POST /auth/login": apiError(401, "INVALID_CREDENTIALS", "e-mail address or password is incorrect") });
    const closed = vi.fn();
    onUnauthorized(closed);
    await expect(api.post("/auth/login", { email: "a@b.c", password: "x" })).rejects.toMatchObject({ code: "INVALID_CREDENTIALS" });
    expect(closed).not.toHaveBeenCalled();
  });

  it("is not closed by a refusal that is not about the session", async () => {
    mockApi({ "DELETE /plants/1": apiError(403, "FORBIDDEN", "this action requires the ADMIN role") });
    const closed = vi.fn();
    onUnauthorized(closed);
    setSession("abc", LATER);
    await expect(api.delete("/plants/1")).rejects.toMatchObject({ status: 403 });
    expect(hasSession()).toBe(true);
    expect(closed).not.toHaveBeenCalled();
  });
});

describe("requests", () => {
  it("send JSON bodies and leave absent query values out", async () => {
    const calls = mockApi({
      "POST /datasets/2/analyses": json({ id: 1 }, 201),
      "GET /analyses/1/forecast?horizon_days=30": json({ points: [] }),
      "DELETE /plants/3": new Response(null, { status: 204 }),
    });
    await api.post("/datasets/2/analyses", { options: null, weather_dataset_id: null });
    await api.get("/analyses/1/forecast", { query: { horizon_days: 30, start: null, end: undefined } });
    await expect(api.delete("/plants/3")).resolves.toBeUndefined();
    expect(calls[0]).toMatchObject({ method: "POST", body: { options: null, weather_dataset_id: null } });
    expect(calls[0]?.headers["content-type"]).toBe("application/json");
    expect(calls[1]?.path).toBe("/analyses/1/forecast?horizon_days=30");
  });

  it("leave the content type of a file upload to the browser", async () => {
    const calls = mockApi({ "POST /plants/1/datasets/validate": json({ ok: true }) });
    const form = new FormData();
    form.set("file", new Blob(["timestamp,actual_energy_kwh\n"]), "a.csv");
    await api.upload("/plants/1/datasets/validate", form);
    expect(calls[0]?.headers["content-type"]).toBeUndefined();
    expect(calls[0]?.body).toBe(form);
  });
});
