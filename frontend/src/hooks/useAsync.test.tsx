import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { useAsync } from "./useAsync";

interface Pending<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (cause: unknown) => void;
}

function pending<T>(): Pending<T> {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAsync", () => {
  it("loads, then reports the data", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.resolve("plant 1"), [1]));
    expect(result.current).toMatchObject({ loading: true, data: null, error: null });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current).toMatchObject({ data: "plant 1", error: null });
  });

  it("never shows the data of the previous subject under the new one", async () => {
    const answers: Record<number, Pending<string>> = { 1: pending(), 2: pending() };
    const { result, rerender } = renderHook(({ id }) => useAsync(() => answers[id]!.promise, [id]), { initialProps: { id: 1 } });
    await act(async () => answers[1]!.resolve("plant 1"));
    expect(result.current.data).toBe("plant 1");

    rerender({ id: 2 });
    expect(result.current).toMatchObject({ loading: true, data: null });
    await act(async () => answers[2]!.resolve("plant 2"));
    expect(result.current).toMatchObject({ loading: false, data: "plant 2" });
  });

  it("ignores an answer that arrives after its subject was left", async () => {
    const answers: Record<number, Pending<string>> = { 1: pending(), 2: pending() };
    const signals: AbortSignal[] = [];
    const { result, rerender } = renderHook(
      ({ id }) => useAsync((signal) => { signals.push(signal); return answers[id]!.promise; }, [id]),
      { initialProps: { id: 1 } },
    );
    rerender({ id: 2 });
    expect(signals[0]?.aborted).toBe(true);
    await act(async () => answers[2]!.resolve("plant 2"));
    await act(async () => answers[1]!.resolve("plant 1, late"));
    expect(result.current.data).toBe("plant 2");
  });

  it("keeps what is on screen while it reloads", async () => {
    const queue = [pending<string>(), pending<string>()];
    let call = 0;
    const { result } = renderHook(() => useAsync(() => queue[call++]!.promise, ["a"]));
    await act(async () => queue[0]!.resolve("first"));
    act(() => result.current.reload());
    expect(result.current).toMatchObject({ loading: true, data: "first" });
    await act(async () => queue[1]!.resolve("second"));
    expect(result.current).toMatchObject({ loading: false, data: "second" });
  });

  it("reports a failure as an API error and keeps earlier data of the same subject", async () => {
    const queue = [pending<string>(), pending<string>()];
    let call = 0;
    const { result } = renderHook(() => useAsync(() => queue[call++]!.promise, ["a"]));
    await act(async () => queue[0]!.resolve("first"));
    act(() => result.current.reload());
    await act(async () => queue[1]!.reject(new ApiError(503, "EXTERNAL_UNAVAILABLE", "the service did not answer")));
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBe("first");
    expect(result.current.error).toMatchObject({ status: 503, code: "EXTERNAL_UNAVAILABLE" });
  });

  it("wraps an unexpected failure", async () => {
    const { result } = renderHook(() => useAsync<string>(() => Promise.reject(new Error("boom")), []));
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toMatchObject({ code: "UNEXPECTED", message: "boom" });
    expect(result.current.data).toBeNull();
  });

  it("aborts the request when the component goes away", () => {
    const signals: AbortSignal[] = [];
    const { unmount } = renderHook(() => useAsync((signal) => { signals.push(signal); return new Promise<string>(() => {}); }, []));
    expect(signals[0]?.aborted).toBe(false);
    unmount();
    expect(signals[0]?.aborted).toBe(true);
  });
});
