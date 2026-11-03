"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, asObject, asRows, formatBytes, formatTime, show, type ApiRow, type Envelope } from "@/lib/api";

export type Modal =
  | { kind: "resource"; resource: "servers" | "projects" }
  | { kind: "server" | "project" | "logs" | "draft" | "job"; item: ApiRow };

type SharedProps = { onClose: () => void; onChange: () => void };
type ItemProps = SharedProps & { item: ApiRow };

const pathId = (row: ApiRow) => encodeURIComponent(show(row.id));
const value = (row: ApiRow, key: string) => show(row[key]);
const json = (body: object): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
function err(error: unknown): string { return error instanceof Error ? error.message : "Request failed"; }

function Frame({ title, eyebrow, children, onClose }: {
  title: string; eyebrow: string; children: ReactNode; onClose: () => void;
}) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="next-dialog-overlay" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="next-dialog" role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-head">
          <div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div>
          <button className="button ghost" type="button" onClick={onClose}>Close ×</button>
        </div>
        {children}
      </section>
    </div>
  );
}

function DetailList({ lines }: { lines: (string | ReactNode)[] }) {
  return <div className="config-list">{lines.length ? lines.map((line, i) =>
    <div key={i} className="config-item">{line}</div>) :
    <div className="config-item">No records available.</div>}</div>;
}

function ResourceDialog({ resource, onClose, onChange }: SharedProps & {
  resource: "servers" | "projects";
}) {
  const isProject = resource === "projects";
  const [servers, setServers] = useState<ApiRow[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!isProject) return;
    let active = true;
    api<Envelope<unknown>>("/api/catalog/servers")
      .then((res) => { if (active) setServers(asRows(res.data)); })
      .catch((e: unknown) => { if (active) setMessage(err(e)); });
    return () => { active = false; };
  }, [isProject]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    const payload = isProject
      ? { name: String(form.get("name")), slug: String(form.get("slug")),
          server_id: String(form.get("server_id") || "") || null }
      : { name: String(form.get("name")), notes: String(form.get("notes") || "") };
    setBusy(true); setMessage("");
    try {
      await api("/api/catalog/" + resource, json(payload));
      onChange(); onClose();
    } catch (e) { setMessage(err(e)); }
    finally { setBusy(false); }
  }
  return <Frame
    title={isProject ? "Create project" : "Register server (configuration only)"}
    eyebrow="CONFIGURATION ONLY — NO DOCKER OPERATIONS" onClose={onClose}>
    <form className="resource-form" onSubmit={submit}>
      <label htmlFor="new-resource-name">Display name</label>
      <input id="new-resource-name" name="name" minLength={2} maxLength={72} required autoFocus/>
      {isProject ? <>
        <label htmlFor="new-resource-slug">Slug (lowercase letters and hyphens)</label>
        <input id="new-resource-slug" name="slug" minLength={2} maxLength={48}
          pattern="[a-z][a-z0-9-]{1,47}" required/>
        <label htmlFor="new-resource-server">Server (optional)</label>
        <select id="new-resource-server" name="server_id">
          <option value="">Unassigned</option>
          {servers.map((server) =>
            <option key={value(server,"id")} value={value(server,"id")}>
              {value(server,"name")} (configuration only)
            </option>)}
        </select>
      </> : <>
        <label htmlFor="new-resource-notes">Notes (optional)</label>
        <textarea id="new-resource-notes" name="notes" rows={3} maxLength={500}/>
      </>}
      {message && <p className="error" role="alert">{message}</p>}
      <button className="button primary" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save configuration"}
      </button>
    </form>
  </Frame>;
}

function SignedHistory({ samples }: { samples: ApiRow[] }) {
  if (!samples.length) return <DetailList lines={["No signed host reports recorded yet."]}/>;
  const points = samples.map((item, i) => {
    const x = 12 + (samples.length === 1 ? 308 : i * 616 / (samples.length - 1));
    const pct = Math.max(0, Math.min(100, Number(item.disk_free_percent) || 0));
    return x.toFixed(1) + "," + (116 - pct).toFixed(1);
  }).join(" ");
  const last = samples[samples.length - 1];
  return <div className="config-list">
    <div className="config-item">{samples.length} signed reports · latest: {formatTime(last.recorded_at)}
      {" · "}{value(last, "disk_free_percent")}% disk free
    </div>
    <svg className="health-chart" viewBox="0 0 640 132" role="img"
      aria-label="Disk free percentage across signed reports, oldest to newest">
      <title>Signed disk free history</title>
      <line x1="12" x2="628" y1="64" y2="64" stroke="currentColor" opacity=".18"/>
      <polyline points={points} stroke="#098a87" strokeWidth="3"
        strokeLinecap="round" strokeLinejoin="round" fill="none"/>
    </svg>
  </div>;
}

function ServerDialog({ item, onClose, onChange }: ItemProps) {
  const [identity, setIdentity] = useState<ApiRow>({});
  const [report, setReport] = useState<ApiRow>({});
  const [samples, setSamples] = useState<ApiRow[]>([]);
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const id = pathId(item);
  async function load() {
    const [a, b, c] = await Promise.all([
      api<Envelope<unknown>>("/api/catalog/servers/" + id + "/identity"),
      api<Envelope<unknown>>("/api/catalog/servers/" + id + "/host-report"),
      api<Envelope<unknown>>("/api/catalog/servers/" + id + "/host-history?limit=96"),
    ]);
    setIdentity(asObject(a.data));
    setReport(asObject(b.data));
    setSamples(asRows(asObject(c.data).samples));
  }
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Envelope<unknown>>("/api/catalog/servers/" + id + "/identity"),
      api<Envelope<unknown>>("/api/catalog/servers/" + id + "/host-report"),
      api<Envelope<unknown>>("/api/catalog/servers/" + id + "/host-history?limit=96"),
    ]).then(([a,b,c]) => {
      if (active) {
        setIdentity(asObject(a.data));
        setReport(asObject(b.data));
        setSamples(asRows(asObject(c.data).samples));
      }
    }).catch((e: unknown) => { if (active) setMessage(err(e)); });
    return () => { active = false; };
  }, [id]);
  async function invitation() {
    setBusy(true); setMessage(""); setSecret("");
    try {
      const answer = await api<Envelope<ApiRow>>(
        "/api/catalog/servers/" + id + "/invites", { method:"POST" });
      setSecret(value(answer.data,"enrollment_code"));
      await load();
    } catch (e) { setMessage(err(e)); }
    finally { setBusy(false); }
  }
  async function revoke() {
    if (!window.confirm("Revoke this server identity and invalidate its invitations? Existing signed heartbeats will be denied.")) return;
    setBusy(true); setMessage("");
    try {
      await api("/api/catalog/servers/" + id + "/revoke", { method: "POST" });
      setSecret("");
      await load();
      onChange();
    } catch(e) { setMessage(err(e)); }
    finally { setBusy(false); }
  }
  const key = asObject(identity.identity);
  const snapshot = asObject(report.snapshot);
  const healthLines = report.snapshot ? [
    "Report: " + value(report,"state") + " · " + formatTime(report.received_at),
    "Host: " + value(snapshot,"hostname") + " · " + value(snapshot,"system"),
    "CPU: " + value(snapshot,"cpu_count") + " · RAM: " + formatBytes(snapshot.memory_total_bytes),
    "Disk available: " + formatBytes(snapshot.disk_free_bytes) + " / " + formatBytes(snapshot.disk_total_bytes),
  ] : ["No available signed host report (" + value(report,"state") + ")"];
  const warnings = asRows(item.warnings);
  return <Frame title={value(item,"name") + " / Agent identity"}
    eyebrow="TRUSTED IDENTITY / NO DOCKER ACCESS" onClose={() => { setSecret(""); onClose(); }}>
    <div className="project-config">
      <p className="small-note">Registration verifies a private Ed25519 key over Tailscale HTTPS.
        No Docker commands or remote container access are enabled.</p>
      <DetailList lines={[
        "Server ID: " + value(item,"id"),
        "Identity: " + value(identity,"status"),
        "Heartbeat: " + value(identity,"heartbeat_state") + " (not Docker connectivity)",
        ...(identity.identity ? [
          "Key fingerprint: " + value(key,"fingerprint"),
          "Last signed heartbeat: " + formatTime(key.last_seen),
          "Last sequence: " + value(key,"last_sequence"),
        ] : []),
      ]}/>
      <h3>Signed host health</h3>
      <DetailList lines={healthLines}/>
      <DetailList lines={warnings.length
        ? warnings.map(w => value(w,"severity").toUpperCase() + " · " + value(w,"message"))
        : ["No warnings based on latest signed data."]}/>
      <h3>Signed disk history</h3>
      <SignedHistory samples={samples}/>
      <p className="small-note">Signed metrics are not a Docker connectivity test.
        Verified identity never grants container operations.</p>
      <div className="next-action-group">
        <button className="button primary" type="button" onClick={() => void invitation()}
          disabled={busy || identity.status === "paired"}>Create one-time enrollment code</button>
        <button className="button ghost" type="button" onClick={() => void revoke()}
          disabled={busy || identity.status === "revoked"}>Revoke identity and invitations</button>
      </div>
      {secret && <div className="config-list">
        <label htmlFor="enrollment-code">One-time code — shown once, expires after 10 minutes</label>
        <input id="enrollment-code" value={secret} readOnly autoComplete="off"
          spellCheck={false} className="mono"/>
        <p className="small-note">Treat this as a secret. Do not share it or commit it to GitHub.</p>
      </div>}
      {message && <p className="error" role="alert">{message}</p>}
    </div>
  </Frame>;
}

function ProjectDialog({ item, onClose, onChange }: ItemProps) {
  const [environments, setEnvironments] = useState<ApiRow[]>([]);
  const [environmentId, setEnvironmentId] = useState("");
  const [drafts, setDrafts] = useState<ApiRow[]>([]);
  const [composeResult, setComposeResult] = useState("No Compose configuration checked.");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const projectId = pathId(item);

  async function reloadEnvironments() {
    const data = await api<Envelope<unknown>>(
      "/api/catalog/projects/" + projectId + "/environments");
    const records = asRows(data.data);
    setEnvironments(records);
    setEnvironmentId(previous => records.some(e => e.id === previous)
      ? previous : records.length ? value(records[0],"id") : "");
    onChange();
  }
  useEffect(() => {
    let active = true;
    api<Envelope<unknown>>("/api/catalog/projects/" + projectId + "/environments")
      .then(data => { if (active) {
        const records = asRows(data.data);
        setEnvironments(records);
        setEnvironmentId(records.length ? value(records[0],"id") : "");
      } }).catch((e: unknown) => { if (active) setMessage(err(e)); });
    return () => { active = false; };
  }, [projectId]);
  useEffect(() => {
    if (!environmentId) { setDrafts([]); return; }
    let active = true;
    api<Envelope<unknown>>("/api/catalog/environments/" +
      encodeURIComponent(environmentId) + "/drafts")
      .then(data => { if (active) setDrafts(asRows(data.data)); })
      .catch((e: unknown) => { if (active) setMessage(err(e)); });
    return () => { active = false; };
  }, [environmentId]);
  async function addEnvironment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setMessage("");
    try {
      await api("/api/catalog/projects/" + projectId + "/environments",
        json({ name: String(data.get("name")), slug: String(data.get("slug")) }));
      form.reset();
      await reloadEnvironments();
    } catch (e) { setMessage(err(e)); }
    finally { setBusy(false); }
  }
  async function addDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return;
    if (!environmentId) { setMessage("Create an environment first."); return; }
    const form = event.currentTarget, data = new FormData(form);
    setBusy(true); setMessage("");
    try {
      await api("/api/catalog/environments/" + encodeURIComponent(environmentId) + "/drafts",
        json({ name: String(data.get("name")), slug: String(data.get("slug")),
               image: String(data.get("image")), container_port: Number(data.get("port")) }));
      form.reset();
      const response = await api<Envelope<unknown>>(
        "/api/catalog/environments/" + encodeURIComponent(environmentId) + "/drafts");
      setDrafts(asRows(response.data));
      onChange();
    } catch (e) { setMessage(err(e)); }
    finally { setBusy(false); }
  }
  async function validateCompose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const source = String(new FormData(event.currentTarget).get("source") || "");
    setComposeResult("Validating — nothing will deploy…");
    try {
      const result = await api<Envelope<unknown>>("/api/validate/compose",
        json({ source }));
      setComposeResult(JSON.stringify(result.data, null, 2));
    } catch (e) {
      setComposeResult("Rejected by safe-preview policy: " + err(e));
    }
  }
  return <Frame title={value(item,"name") + " / Environments"}
    eyebrow="CONFIGURATION ONLY — NO DEPLOYMENTS" onClose={onClose}>
    <div className="project-config">
      <h3>Environments</h3>
      <DetailList lines={environments.length
        ? environments.map(e => value(e,"name") + " (" + value(e,"slug") + ")")
        : ["No environments yet."]}/>
      <form className="inline-config-form" onSubmit={addEnvironment}>
        <input aria-label="Environment name" name="name" required minLength={2} maxLength={72}
          placeholder="Environment name"/>
        <input aria-label="Environment slug" name="slug" required minLength={2} maxLength={48}
          pattern="[a-z][a-z0-9-]{1,47}" placeholder="environment-slug"/>
        <button className="button primary" type="submit" disabled={busy}>Add environment</button>
      </form>
      <h3>Image deployment drafts</h3>
      <p className="small-note">Drafts are stored but cannot launch containers.
        Images must use a full sha256 digest; no host ports or mounts are accepted.</p>
      <label htmlFor="draft-environment">Environment</label>
      <select id="draft-environment" value={environmentId}
        onChange={event => setEnvironmentId(event.target.value)}>
        <option value="">Choose environment</option>
        {environments.map(env => <option key={value(env,"id")} value={value(env,"id")}>
          {value(env,"name")}
        </option>)}
      </select>
      <DetailList lines={drafts.length
        ? drafts.map(d => value(d,"name") + " — " +
          value(asObject(d.manifest),"image") + " (draft only)")
        : [environmentId ? "No drafts configured." : "Choose an environment to view drafts."]}/>
      <form className="inline-config-form" onSubmit={addDraft}>
        <input name="name" aria-label="Service name" required minLength={2} maxLength={72}
          placeholder="Service name"/>
        <input name="slug" aria-label="Service slug" required minLength={2} maxLength={48}
          pattern="[a-z][a-z0-9-]{1,47}" placeholder="service-slug"/>
        <input name="image" aria-label="Pinned image" required
          placeholder="registry/image@sha256:..."/>
        <input name="port" aria-label="Container port" type="number" min={1} max={65535}
          required placeholder="Container port"/>
        <button className="button primary" type="submit" disabled={!environmentId || busy}>
          Save draft
        </button>
      </form>
      <h3>Compose compatibility check</h3>
      <p className="small-note">Strict limited preview only. No application will deploy.
        Do not paste secrets.</p>
      <form className="resource-form" onSubmit={validateCompose}>
        <label htmlFor="compose-source">Compose YAML</label>
        <textarea id="compose-source" name="source" rows={7} maxLength={32768}
          required placeholder={"services:\n  web:\n    image: registry/image@sha256:...\n    read_only: true\n    expose: [8080]"}/>
        <button className="button ghost" type="submit">Validate only</button>
      </form>
      <pre aria-live="polite">{composeResult}</pre>
      {message && <p className="error" role="alert">{message}</p>}
    </div>
  </Frame>;
}

function LogsDialog({ item, onClose }: ItemProps) {
  const [logs, setLogs] = useState("Loading logs…");
  const id = pathId(item);
  useEffect(() => {
    let active = true;
    api<Envelope<unknown>>("/api/server/containers/" + id + "/logs")
      .then(response => { if (active) setLogs(typeof response.data === "string" && response.data
        ? response.data : "No log output available."); })
      .catch((e: unknown) => { if (active) setLogs(err(e)); });
    return () => { active = false; };
  }, [id]);
  return <Frame title={value(item,"name")} eyebrow="CONTAINER LOGS · LAST 80 LINES" onClose={onClose}>
    <pre>{logs}</pre>
    <p className="muted small">Application logs may contain sensitive data; restrict who can view them.</p>
  </Frame>;
}

function DraftDialog({ item, onClose }: ItemProps) {
  const [details, setDetails] = useState<ApiRow>({});
  const [message, setMessage] = useState("");
  const id = pathId(item);
  useEffect(() => {
    let active = true;
    api<Envelope<unknown>>("/api/deployments/drafts/" + id + "/review")
      .then(response => { if (active) setDetails(asObject(response.data)); })
      .catch((e: unknown) => { if (active) setMessage(err(e)); });
    return () => { active = false; };
  }, [id]);
  const manifest = asObject(details.manifest);
  return <Frame title={value(item,"name") + " / Static security review"}
    eyebrow="PRE-DEPLOYMENT / STATIC REVIEW ONLY" onClose={onClose}>
    <div className="project-config">
      <p className="small-note">This does not reserve resources, approve deployment,
        or contact any remote Docker host.</p>
      <DetailList lines={[
        "Project: " + value(details,"project") + " · Environment: " + value(details,"environment"),
        "Server: " + (details.server ? value(details,"server") : "Not assigned"),
        ...(details.manifest ? [
          "Pinned image: " + value(manifest,"image"),
          "Resources: " + value(manifest,"cpu_limit") + " CPU · " +
            value(manifest,"memory_mb") + " MB RAM · Internal port " +
            value(manifest,"container_port") + " · Read-only filesystem",
        ] : []),
      ]}/>
      <h3>Security and readiness checks</h3>
      <DetailList lines={[
        ...asRows(details.checks).map(check =>
          (check.passed ? "PASS" : "BLOCKED") + " · " + value(check,"explanation")),
        "EXECUTION DISABLED — this review does not deploy anything.",
      ]}/>
      {message && <p className="error" role="alert">{message}</p>}
    </div>
  </Frame>;
}

function JobDialog({ item, onClose }: ItemProps) {
  const [packet, setPacket] = useState<ApiRow>({});
  const [message, setMessage] = useState("");
  const id = pathId(item);
  useEffect(() => {
    let active = true;
    api<Envelope<unknown>>("/api/deployments/jobs/" + id + "/review-packet")
      .then(response => { if (active) setPacket(asObject(response.data)); })
      .catch((e: unknown) => { if (active) setMessage(err(e)); });
    return () => { active = false; };
  }, [id]);
  return <Frame title={"Job " + id.slice(0,12) + " · Review packet"}
    eyebrow="REVIEW EVIDENCE / READ ONLY" onClose={onClose}>
    <div className="project-config">
      <p className="small-note">Evidence is not host attestation. This view does not resolve
        a job, release a lock or start Docker.</p>
      <DetailList lines={[
        "State: " + value(packet,"state") +
          (packet.review_eligible ? " · Blocked pending review" : ""),
        "Packet SHA-256: " + value(packet,"packet_digest"),
        "Immutable manifest SHA-256: " + value(packet,"manifest_sha256"),
        "Execution attempts: " + value(packet,"attempt"),
        "Host lock released: NO · Safe to retry: NO",
        "Independent host attestation: NOT VERIFIED",
      ]}/>
      <h3>Recorded transition history</h3>
      <DetailList lines={asRows(packet.events).slice(-100).map(event =>
        formatTime(event.created_at) + " · " + value(event,"state") +
        " · " + value(event,"code"))}/>
      <h3>Operator references</h3>
      <DetailList lines={asRows(packet.evidence).map(reference =>
        value(reference,"reason_code") + " · Reference SHA-256 " +
        value(reference,"evidence_ref") + " · Untrusted operator-supplied reference")}/>
      {message && <p className="error" role="alert">{message}</p>}
    </div>
  </Frame>;
}

export function ModalHost({ modal, onClose, onChange }: {
  modal: Modal | null; onClose: () => void; onChange: () => void;
}) {
  if (!modal) return null;
  if (modal.kind === "resource") return <ResourceDialog
    resource={modal.resource} onClose={onClose} onChange={onChange}/>;
  if (modal.kind === "server") return <ServerDialog
    item={modal.item} onClose={onClose} onChange={onChange}/>;
  if (modal.kind === "project") return <ProjectDialog
    item={modal.item} onClose={onClose} onChange={onChange}/>;
  if (modal.kind === "logs") return <LogsDialog
    item={modal.item} onClose={onClose} onChange={onChange}/>;
  if (modal.kind === "draft") return <DraftDialog
    item={modal.item} onClose={onClose} onChange={onChange}/>;
  return <JobDialog item={modal.item} onClose={onClose} onChange={onChange}/>;
}
