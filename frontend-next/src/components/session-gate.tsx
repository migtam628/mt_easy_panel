"use client";

import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";

type User = { username: string; role: string };
type SessionContextValue = { user: User; logout: () => Promise<void> };
const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("Session is not ready");
  return context;
}

export function SessionGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    api<User>("/api/auth/me")
      .then((identity) => { if (active) setUser(identity); })
      .catch((error: unknown) => {
        if (active && !(error instanceof ApiError && error.status === 401)) {
          setNotice("Cannot reach the MT Panel API. Check the current FastAPI service.");
        }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    const username = String(form.get("username") || "");
    const password = String(form.get("password") || "");
    setBusy(true);
    setNotice("");
    try {
      const identity = await api<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setUser(identity);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try { await api("/api/auth/logout", { method: "POST" }); }
    finally { setUser(null); }
  }

  if (loading) return <main className="session-screen"><p>Checking your session…</p></main>;
  if (!user) return (
    <main className="session-screen">
      <div className="login-panel">
        <div className="brand"><span className="brand-mark">M</span><span>MT <strong>Panel</strong></span></div>
        <div className="eyebrow">NEXT.JS MIGRATION PREVIEW</div>
        <h1>Secure workspace</h1>
        <p className="muted">Sign in using your existing MT Panel account. No separate Next.js authentication or session store is created.</p>
        <form onSubmit={login} className="login-form">
          <label>Username<input name="username" autoComplete="username" required maxLength={64} /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
          {notice && <p className="error" role="alert">{notice}</p>}
          <button className="primary" disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        <p className="footnote">Private, same-origin API · HttpOnly session cookie · Docker writes remain disabled</p>
      </div>
    </main>
  );
  return <SessionContext.Provider value={{ user, logout }}>{children}</SessionContext.Provider>;
}
