"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, asObject, asRows, formatBytes, formatTime, show, type ApiRow, type Envelope } from "@/lib/api";
import { useSession } from "@/components/session-gate";
import { SECTIONS, type Section } from "@/lib/sections";

const META: Record<Section, { title: string; subtitle: string; icon: string }> = {
  overview: { title: "Overview", subtitle: "Local host inventory at a glance", icon: "◫" },
  containers: { title: "Containers", subtitle: "Read-only Docker container inventory", icon: "▤" },
  monitoring: { title: "Monitoring", subtitle: "Signed fleet reports and local diagnostics", icon: "◉" },
  servers: { title: "Servers", subtitle: "Registered identities and pairing state", icon: "◇" },
  projects: { title: "Projects", subtitle: "Saved workspaces and configuration metadata", icon: "▦" },
  deployments: { title: "Deployments", subtitle: "Draft readiness and audit-only job history", icon: "↗" },
  activity: { title: "Activity", subtitle: "Administrative audit events", icon: "≡" },
  settings: { title: "Security", subtitle: "Effective policy, without secret disclosure", icon: "⚙" },
};

const SOURCES: Record<Section, string[]> = {
  overview: ["/api/server/overview"],
  containers: ["/api/server/containers"],
  monitoring: ["/api/monitoring/overview", "/api/monitoring/diagnostics"],
  servers: ["/api/catalog/servers"],
  projects: ["/api/catalog/projects"],
  deployments: ["/api/deployments/readiness", "/api/deployments/jobs?limit=50"],
  activity: ["/api/audit/events?limit=50"],
  settings: ["/api/settings/security"],
};

function DataTable({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  return <div className="table-scroll"><table>
    <thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
    <tbody>{rows.length ? rows.map((row, i) =>
      <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>) :
      <tr><td colSpan={headers.length} className="empty">No records available.</td></tr>}</tbody>
  </table></div>;
}

function Summary({ items }: { items: { label: string; value: string; detail: string }[] }) {
  return <div className="summary-grid">{items.map((item) =>
    <div key={item.label} className="metric-card">
      <span className="metric-label">{item.label}</span>
      <strong>{item.value}</strong>
      <span className="metric-detail">{item.detail}</span>
    </div>)}</div>;
}

const str = (row: ApiRow, key: string) => show(row[key]);
const rows = (items: ApiRow[], keys: string[]) => items.map((item) => keys.map((key) => str(item, key)));

export function Dashboard({ section }: { section: Section }) {
  const { user, logout } = useSession();
  const [data, setData] = useState<unknown[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [saving, setSaving] = useState("");
  const meta = META[section];

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    Promise.all(SOURCES[section].map((path) => api<Envelope<unknown>>(path)))
      .then((responses) => { if (active) setData(responses.map((item) => item.data)); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load data");
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [section, revision]);

  async function saveDryRun(id: string, name: string) {
    if (!window.confirm("Save an audited DRY-RUN job for " + name + "? No Docker changes will be made.")) return;
    if (saving) return;
    setSaving(id);
    setError("");
    try {
      await api("/api/deployments/drafts/" + encodeURIComponent(id) + "/jobs", {
        method: "POST",
        body: JSON.stringify({ idempotency_key: crypto.randomUUID().replaceAll("-", ""), execute: false }),
      });
      setRevision((n) => n + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save draft job");
    } finally {
      setSaving("");
    }
  }

  function content() {
    const primary = asObject(data[0]);
    const list = asRows(data[0]);
    if (section === "overview") {
      return <><Summary items={[
        { label: "Containers", value: show(primary.containers_total), detail: show(primary.containers_running) + " running" },
        { label: "CPU cores", value: show(primary.cpus), detail: "Read-only host inventory" },
        { label: "Host memory", value: formatBytes(primary.memory_bytes), detail: "Total reported memory" },
        { label: "Disk used", value: formatBytes(primary.disk_used_bytes), detail: "From local Docker agent" },
      ]}/><div className="panel"><h2>Host status</h2>
        <DataTable headers={["Property", "Reported value"]} rows={[
          ["Hostname", show(primary.hostname)], ["Inventory source", show(primary.source)],
          ["Running containers", show(primary.containers_running)],
          ["Total containers", show(primary.containers_total)],
        ]}/></div></>;
    }
    if (section === "containers") return <div className="panel"><h2>Container inventory</h2>
      <DataTable headers={["Name", "State", "Status", "Image"]} rows={list.map((item) =>
        [str(item,"name"),str(item,"state"),str(item,"status"),str(item,"image")])}/></div>;
    if (section === "monitoring") {
      const fleet = asObject(primary.fleet), count = asObject(fleet.counts);
      const local = asObject(primary.local_host), diagnostics = asObject(data[1]);
      const summary = asObject(diagnostics.diagnostics), warnings = asObject(summary.warnings);
      return <><Summary items={[
        { label: "Local containers", value: show(local.containers_total), detail: show(local.containers_running) + " running" },
        { label: "Signed heartbeats", value: show(count.heartbeat_recent), detail: show(count.heartbeat_stale) + " stale" },
        { label: "Fleet warnings", value: show(count.warning_servers), detail: show(count.critical_servers) + " critical" },
        { label: "Local Docker state", value: show(diagnostics.state), detail: "No continuous polling" },
      ]}/>
      <div className="panel"><h2>Enrolled server reports</h2>
        <DataTable headers={["Server", "Identity", "Heartbeat", "Report"]} rows={rows(
          asRows(fleet.servers), ["name","status","heartbeat_state","report_state"])}/></div>
      <div className="panel"><h2>Local container diagnostics</h2>
        <p className="muted">Unhealthy: {show(warnings.unhealthy)} · Restarting: {show(warnings.restarting)} · Dead: {show(warnings.dead)}</p>
        <DataTable headers={["Container","State","Docker status"]} rows={rows(
          asRows(summary.containers).slice(0,100), ["name","state","status"])}/></div></>;
    }
    if (section === "servers") return <div className="panel"><h2>Registered server identities</h2>
      <DataTable headers={["Server", "Pairing state", "Notes"]} rows={rows(list, ["name","status","notes"])}/></div>;
    if (section === "projects") return <div className="panel"><h2>Project workspaces</h2>
      <DataTable headers={["Name","Slug","Server","Environments"]} rows={rows(
        list, ["name","slug","server_id","environment_count"])}/></div>;
    if (section === "deployments") {
      const drafts = asRows(primary.drafts), jobs = asRows(data[1]);
      return <><div className="panel"><h2>Deployment drafts</h2>
        <p className="muted">Review-only. No production deployment or host traffic change is authorized.</p>
        <div className="table-scroll"><table><thead><tr>
          <th>Draft</th><th>Project</th><th>Server</th><th>Blockers</th><th>Action</th>
        </tr></thead><tbody>{drafts.length ? drafts.map((draft) =>
          <tr key={str(draft, "id")}><td>{str(draft,"name")}</td><td>{str(draft,"project")}</td>
            <td>{str(draft,"server_name")}</td><td>{asRows(draft.blockers).length ? "Review required" :
              Array.isArray(draft.blockers) ? draft.blockers.join(", ") : "Draft only"}</td>
            <td><button className="text-action" disabled={!!saving} onClick={() =>
              saveDryRun(str(draft,"id"),str(draft,"name"))}>{saving === draft.id ? "Saving…" : "Save dry-run"}</button></td>
          </tr>) : <tr><td colSpan={5} className="empty">No saved drafts.</td></tr>}</tbody></table></div>
      </div><div className="panel"><h2>Recent jobs · Audit only</h2>
        <DataTable headers={["Job", "State", "Attempts", "Updated"]} rows={jobs.map((job) => [
          str(job,"id").slice(0,12),str(job,"state"),str(job,"attempt"),
          formatTime(job.updated_at),
        ])}/></div></>;
    }
    if (section === "activity") return <div className="panel"><h2>Audit activity</h2>
      <DataTable headers={["Timestamp","Actor","Action","Result"]} rows={list.map((item) =>
        [formatTime(item.created_at),str(item,"actor"),str(item,"action"),str(item,"result")])}/></div>;
    return <div className="panel"><h2>Security posture</h2>
      <DataTable headers={["Control","Current value"]} rows={[
        ["Application version",str(primary,"app_version")],
        ["Owner",str(primary,"owner")],
        ["Public origin",str(primary,"public_origin")],
        ["Session cookies",primary.secure_cookies ? "Secure · HttpOnly · SameSite=Strict" : "HttpOnly · SameSite=Strict"],
        ["Local agent",str(primary,"agent_connection")],
        ["Remote Docker access",str(primary,"remote_docker_access")],
        ["Lab execution enabled",str(primary,"lab_execution_enabled")],
        ["MFA",str(primary,"multi_factor_auth")],
        ["RBAC",str(primary,"multi_user_roles")],
      ]}/></div>;
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="sidebar-logo"><span className="brand-mark">M</span><span>MT <strong>Panel</strong></span></div>
      <div className="sidebar-label">WORKSPACE</div>
      <nav aria-label="Main navigation">
        {SECTIONS.map((item) => <Link key={item} className={item === section ? "nav-item active" : "nav-item"}
          href={item === "overview" ? "/" : "/" + item} aria-current={item === section ? "page" : undefined}>
          <span className="nav-icon" aria-hidden="true">{META[item].icon}</span>{META[item].title}
        </Link>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="preview-chip"><span className="status-dot"/> NEXT.JS PREVIEW</div>
        <div className="identity">{user.username}<small>{user.role} · Existing FastAPI session</small></div>
        <button className="signout" onClick={() => void logout()}>Sign out</button>
      </div>
    </aside>
    <main className="workspace">
      <header className="workspace-header">
        <div className="eyebrow">MT PANEL / CONTROL PLANE</div>
        <div className="header-actions"><span className="read-only"><span className="status-dot"/> READ-ONLY BY DEFAULT</span>
          <button onClick={() => setRevision((n) => n + 1)} disabled={busy}>Refresh</button></div>
      </header>
      <div className="main-content">
        <div className="section-heading"><div><h1>{meta.title}</h1><p>{meta.subtitle}</p></div>
          <span className="migration-label">Next.js migration</span></div>
        {error && <div className="error-panel" role="alert">{error}</div>}
        {busy ? <div className="panel loading">Loading verified MT Panel API data…</div> : content()}
        <p className="disclaimer">Private preview only · No changes to Docker socket access, agent enrollment, reverse proxies, or host ports.</p>
      </div>
    </main>
  </div>;
}
