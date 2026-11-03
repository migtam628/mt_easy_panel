"use client";

import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";

type User = { username: string; role: string };
type SessionContextValue = { user: User; logout: () => Promise<void> };
const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Session not ready");
  return session;
}

export function SessionGate({ children }: {children: ReactNode}) {
  const [user,setUser] = useState<User|null>(null);
  const [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(false);
  const [notice,setNotice] = useState("");

  useEffect(()=>{
    let active=true;
    api<User>("/api/auth/me")
      .then(identity=>{if(active)setUser(identity);})
      .catch(async (error: unknown)=>{
        if (!active) return;
        if (!(error instanceof ApiError && error.status===401)) {
          setNotice("Cannot reach MT Panel API. Check the FastAPI service.");
          return;
        }
        try {
          const setup=await api<{needs_setup:boolean}>("/api/setup");
          if (active && setup.needs_setup) {
            setNotice("Initial setup required: run python -m panel.cli create-admin on the server.");
          }
        } catch { /* Show the existing login form offline. */ }
      })
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[]);

  async function login(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();if(busy)return;
    const form=event.currentTarget;
    const values=new FormData(form);
    setBusy(true);setNotice("");
    try {
      const identity=await api<User>("/api/auth/login",{method:"POST",body:JSON.stringify({
        username:String(values.get("username")||""),
        password:String(values.get("password")||""),
      })});
      form.reset();
      setUser(identity);
    }catch(error) {
      setNotice(error instanceof Error?error.message:"Sign-in failed");
    }finally{setBusy(false);}
  }

  async function logout() {
    try{await api("/api/auth/logout",{method:"POST"});}
    finally{setUser(null);}
  }

  if(loading) return <main className="login-wrap" aria-live="polite">
    <div className="login-card"><div className="logo large">
      <span className="logo-mark">M</span><span>MT <strong>Panel</strong></span></div>
      <div className="eyebrow">SELF-HOSTED INFRASTRUCTURE</div>
      <h1>Checking your session…</h1>
      <p className="muted">Verifying your existing MT Panel session.</p>
    </div>
  </main>;

  if(!user) return <main className="login-wrap">
    <div className="login-card">
      <div className="logo large"><span className="logo-mark">M</span>
        <span>MT <strong>Panel</strong></span></div>
      <div className="eyebrow">SELF-HOSTED INFRASTRUCTURE</div>
      <h1>Welcome back.</h1>
      <p className="muted">Sign in to view your servers and container inventory.</p>
      <form onSubmit={login}>
        <label htmlFor="mt-next-username">Username</label>
        <input id="mt-next-username" name="username" autoComplete="username"
          required defaultValue="admin" maxLength={64}/>
        <label htmlFor="mt-next-password">Password</label>
        <input id="mt-next-password" name="password" autoComplete="current-password"
          type="password" required maxLength={1024}/>
        {notice && <p className="error" role="alert">{notice}</p>}
        <button type="submit" className="button primary wide" disabled={busy}>
          {busy?"Signing in…":"Sign in"} <span>↗</span>
        </button>
      </form>
      <div className="login-foot">Next.js Preview · Private server operations</div>
    </div>
  </main>;
  return <SessionContext.Provider value={{user,logout}}>{children}</SessionContext.Provider>;
}
