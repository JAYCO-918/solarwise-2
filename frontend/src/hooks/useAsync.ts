import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

type Dependency = string | number | boolean | null | undefined;

interface Settled<T> {
  /** The dependencies the answer belongs to. */
  depsKey: string;
  /** The request that produced it (dependencies + reload counter). */
  requestKey: string;
  data: T | null;
  error: ApiError | null;
}

/**
 * Load data when the component mounts and whenever `deps` change; a pending request is aborted on change.
 *
 * Data never outlive their dependencies: after `deps` change, `data` is `null` until the new answer arrives, so a page
 * cannot show one plant under the name of another. A `reload()` keeps the current data on screen while it runs.
 */
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>, deps: readonly Dependency[]): AsyncState<T> {
  const depsKey = JSON.stringify(deps);
  const [version, setVersion] = useState(0);
  const requestKey = `${depsKey}#${version}`;
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const loader = useRef(load);
  useEffect(() => {
    loader.current = load;
  });

  useEffect(() => {
    const controller = new AbortController();
    loader.current(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setSettled({ depsKey, requestKey, data: value, error: null });
      },
      (cause: unknown) => {
        if (controller.signal.aborted) return;
        setSettled((previous) => ({
          depsKey,
          requestKey,
          data: previous !== null && previous.depsKey === depsKey ? previous.data : null,
          error: toApiError(cause),
        }));
      },
    );
    return () => controller.abort();
  }, [depsKey, requestKey]);

  const current = settled !== null && settled.depsKey === depsKey ? settled : null;
  const loading = current === null || current.requestKey !== requestKey;
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const setData = useCallback(
    (value: T) => setSettled({ depsKey, requestKey, data: value, error: null }),
    [depsKey, requestKey],
  );
  return { data: current?.data ?? null, error: loading ? null : (current?.error ?? null), loading, reload, setData };
}

export function toApiError(cause: unknown): ApiError {
  if (cause instanceof ApiError) return cause;
  const message = cause instanceof Error ? cause.message : "Unexpected error.";
  return new ApiError(0, "UNEXPECTED", message);
}
