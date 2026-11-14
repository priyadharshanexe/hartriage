import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, onSessionChange, refreshSession, setAccessToken } from "../lib/api";
import type { Role, Session } from "../lib/types";

interface AuthValue {
  session: Session | null;
  role: Role | null;
  canEdit: boolean;
  isAdmin: boolean;
  setSession: (session: Session | null) => void;
  switchOrg: (orgId: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);
const LOGOUT_SIGNAL = "hartriage.loggedOutAt";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSessionState] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  const setSession = useCallback(
    (next: Session | null) => {
      if (next?.access_token) setAccessToken(next.access_token);
      if (next === null) {
        setAccessToken(null);
        queryClient.clear();
      }
      setSessionState(next);
    },
    [queryClient],
  );

  // On load, the refresh cookie (if any) turns into a session without a sign-in.
  useEffect(() => {
    onSessionChange((next) => setSession(next));
    void refreshSession().then((s) => {
      setSession(s);
      setReady(true);
    });
    return () => onSessionChange(null);
  }, [setSession]);

  // Signing out in one tab signs out the others.
  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key === LOGOUT_SIGNAL && event.newValue) setSession(null);
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [setSession]);

  const logout = useCallback(async () => {
    await api<void>("/v1/auth/logout", { method: "POST", skipRefresh: true }).catch(() => undefined);
    setSession(null);
    try {
      localStorage.setItem(LOGOUT_SIGNAL, String(Date.now()));
    } catch {
      // storage can be unavailable; this tab is signed out anyway
    }
  }, [setSession]);

  const switchOrg = useCallback(
    async (orgId: string) => {
      const next = await api<Session>("/v1/auth/switch", { method: "POST", body: { org_id: orgId } });
      queryClient.clear();
      setSession(next);
    },
    [queryClient, setSession],
  );

  const value = useMemo<AuthValue>(
    () => ({
      session,
      role: session?.role ?? null,
      canEdit: session?.role === "admin" || session?.role === "agent",
      isAdmin: session?.role === "admin",
      setSession,
      switchOrg,
      logout,
    }),
    [session, setSession, switchOrg, logout],
  );

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center font-mono text-sm text-ink-3" role="status">
        Loading…
      </div>
    );
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
