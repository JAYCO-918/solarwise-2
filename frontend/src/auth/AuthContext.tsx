import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { clearSession, hasSession, onUnauthorized, restoreSession, setSession } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { Meta, Token, User } from "../api/types";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthState {
  status: Status;
  user: User | null;
  /** What the server is: demonstration mode, limits, optional features. `null` until it has answered. */
  meta: Meta | null;
  /** Set when the session ended because the server stopped accepting it. */
  expired: boolean;
  /** What the server answered when it did. */
  expiredReason: string | null;
  /** Set when the session ended because the visitor signed out. */
  signedOut: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** Sign-up: creates the account and opens its session. */
  register: (fullName: string, email: string, password: string) => Promise<void>;
  demoLogin: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // Reading the stored session is idempotent: without one there is nothing to wait for.
  const [status, setStatus] = useState<Status>(() => (restoreSession() ? "loading" : "anonymous"));
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [expired, setExpired] = useState(false);
  const [expiredReason, setExpiredReason] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    endpoints.meta(controller.signal).then(setMeta).catch(() => undefined);
    if (hasSession()) {
      endpoints
        .me(controller.signal)
        .then((me) => {
          setUser(me);
          setStatus("authenticated");
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          clearSession();
          setStatus("anonymous");
        });
    }
    onUnauthorized((error) => {
      setUser(null);
      setExpired(true);
      setExpiredReason(error.message);
      setStatus("anonymous");
    });
    return () => {
      controller.abort();
      onUnauthorized(null);
    };
  }, []);

  const accept = useCallback((token: Token) => {
    setSession(token.access_token, token.expires_at);
    setUser(token.user);
    setExpired(false);
    setSignedOut(false);
    setStatus("authenticated");
  }, []);

  const login = useCallback(
    async (email: string, password: string) => accept(await endpoints.login(email, password)),
    [accept],
  );
  const register = useCallback(
    async (fullName: string, email: string, password: string) =>
      accept(await endpoints.register({ full_name: fullName, email, password })),
    [accept],
  );
  const demoLogin = useCallback(async () => accept(await endpoints.demoLogin()), [accept]);
  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    setExpired(false);
    setSignedOut(true);
    setStatus(hasSession() ? "authenticated" : "anonymous");
  }, []);

  const value = useMemo<AuthState>(
    () => ({ status, user, meta, expired, expiredReason, signedOut, login, register, demoLogin, logout }),
    [status, user, meta, expired, expiredReason, signedOut, login, register, demoLogin, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
