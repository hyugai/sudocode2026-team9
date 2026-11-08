"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createAuthClient, type AuthUser } from "@/utils/auth-api";
import { syncAuthOwner } from "@/utils/auth-storage";
import { ConversationProvider } from "./conversation-provider";
import { PurchaseProvider } from "./purchase-provider";

type AuthState = { user: AuthUser | null; ready: boolean; error: string };
type AuthContextValue = AuthState & {
  busy: boolean;
  scope: number;
  register: (name: string, email: string, password: string) => Promise<AuthUser>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => createAuthClient());
  const [state, setState] = useState<AuthState>({ user: null, ready: false, error: "" });
  const [busy, setBusy] = useState(false);
  const [scope, setScope] = useState(0);
  const lock = useRef(false);
  const revision = useRef(0);
  const applyUser = useCallback((user: AuthUser | null, reset = false) => {
    try { syncAuthOwner(user?.id ?? null, window.sessionStorage, window.localStorage, reset); }
    catch {
      setState({ user: null, ready: false, error: "Chưa xóa được dữ liệu phiên cũ. Hãy cho phép lưu trữ trên trình duyệt rồi thử lại." });
      throw new Error("Chưa xóa được dữ liệu phiên cũ.");
    }
    if (reset) setScope(previous => previous + 1);
    setState({ user, ready: true, error: "" });
  }, []);
  const refresh = useCallback(async () => {
    const current = ++revision.current;
    try {
      const user = await client.me();
      if (current === revision.current) applyUser(user);
    } catch (error) {
      if (current === revision.current) setState(previous => ({ ...previous, error: error instanceof Error ? error.message : "Chưa kiểm tra được phiên đăng nhập." }));
    }
  }, [applyUser, client]);
  useEffect(() => {
    const requests = revision;
    void refresh();
    const onFocus = () => { if (!lock.current) void refresh(); };
    window.addEventListener("focus", onFocus);
    return () => { requests.current++; window.removeEventListener("focus", onFocus); };
  }, [refresh]);
  const changeUser = async (operation: () => Promise<AuthUser | null>) => {
    if (lock.current) throw new Error("Đang xử lý tài khoản. Vui lòng chờ.");
    lock.current = true; revision.current++; setBusy(true);
    try { applyUser(await operation(), true); }
    finally { lock.current = false; setBusy(false); }
  };
  return <AuthContext.Provider value={{ ...state, busy, scope, register: client.register, refresh,
    login: (email, password) => changeUser(() => client.login(email, password)),
    logout: () => changeUser(async () => { await client.logout(); return null; }),
  }}>
    {state.error && <div className="container" role="alert"><p>{state.error}</p><button className="commerce-secondary" type="button" disabled={busy} onClick={() => void refresh()}>Kiểm tra lại phiên</button></div>}
    {children}
  </AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("AuthProvider is required");
  return auth;
}

/** Remount private state on login/logout; never import a guest draft into an account. */
export function SessionProviders({ children }: { children: ReactNode }) {
  const { user, ready, scope } = useAuth();
  return <ConversationProvider key={`${scope}:${ready ? user?.id ?? "guest" : "checking"}`} persistGuest={ready && !user} enabled={ready}>
    <PurchaseProvider enabled={ready}>{children}</PurchaseProvider>
  </ConversationProvider>;
}
