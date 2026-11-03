"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { api, asObject, asRows, formatBytes, formatTime, show, type ApiRow, type Envelope } from "@/lib/api";
import { useSession } from "@/components/session-gate";
import { ModalHost, type Modal } from "@/components/legacy-dialogs";
import { PAGE, SECTIONS, type Section } from "@/lib/sections";

const SOURCE: Record<Section, string[]> = {
  overview:["/api/server/overview","/api/server/containers"],
  containers:["/api/server/overview","/api/server/containers"],
  images:["/api/server/images"], networks:["/api/server/networks"],
  volumes:["/api/server/volumes"], servers:["/api/fleet/summary"],
  projects:["/api/catalog/projects"], activity:["/api/audit/events?limit=100"],
  monitoring:["/api/monitoring/overview","/api/monitoring/diagnostics"],
  deployments:["/api/deployments/readiness","/api/deployments/jobs?limit=50"],
  settings:["/api/settings/security"],
};
const str = (item: ApiRow, key: string) => show(item[key]);
const count = (value: unknown) => typeof value === "number" && Number.isFinite(value)
  ? value.toLocaleString() : "—";
const short = (value: unknown, n = 70) => show(value).slice(0,n);
const fields = (row: ApiRow, ...names: string[]) => names.map(name => str(row,name));
type Item = { id: string; cells: ReactNode[] };
type View = {title:string; subtitle:string; headers:string[]; items:Item[]};
type Stat = [string,string,string,string];

function action(label: string, onClick: () => void, disabled = false) {
  return <button type="button" className="link-button" onClick={onClick} disabled={disabled}>{label}</button>;
}
function Table({ view, empty = "No resources found." }: {view: View;empty?:string}) {
  return <div className="table-wrap"><table>
    <thead><tr>{view.headers.map(h => <th key={h}>{h}</th>)}</tr></thead>
    <tbody>{view.items.length ? view.items.map(item => <tr key={item.id}>
      {item.cells.map((cell,i) => <td key={i}>{cell}</td>)}
    </tr>) : <tr><td className="empty" colSpan={view.headers.length}>{empty}</td></tr>}</tbody>
  </table></div>;
}
function Stats({ values }: {values:Stat[]}) {
  return values.length ? <div className="stats">{values.map(([name,value,foot,icon]) =>
    <div className="stat" key={name}><span className="stat-icon">{icon}</span>
      <div className="stat-label">{name}</div><div className="stat-value">{value}</div>
      <div className="stat-footer">{foot}</div></div>)}</div> : null;
}
function Status({ status }: {status: string}) {
  return <span className={"pill "+(status === "running" ? "" : status === "exited" ? "off" : "other")}>
    {status}</span>;
}
function formatPorts(value: unknown) {
  return asRows(value).map(p => p.public ? str(p,"public")+":"+str(p,"private")
    : str(p,"private")).join(", ") || "—";
}
function warningText(value: unknown) {
  return asRows(value).map(w => str(w,"severity").toUpperCase()+": "+str(w,"message"))
    .join("; ") || "No warnings";
}
function entry(item: ApiRow, i: number, cells: ReactNode[]): Item {
  return {id:typeof item.id === "string" ? item.id : String(i),cells};
}

export function Dashboard({section}:{section:Section}) {
  const {user,logout} = useSession();
  const [payload,setPayload] = useState<unknown[]>([]);
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState("");
  const [updated,setUpdated] = useState("");
  const [tick,setTick] = useState(0);
  const [modal,setModal] = useState<Modal|null>(null);
  const [saving,setSaving] = useState("");
  const refresh = () => setTick(n=>n+1);

  useEffect(()=>{
    let active=true;
    setLoading(true);setError("");setPayload([]);
    Promise.all(SOURCE[section].map(p=>api<Envelope<unknown>>(p)))
      .then(res=>{if(active){setPayload(res.map(x=>x.data));setUpdated(new Date().toLocaleTimeString());}})
      .catch((e:unknown)=>{if(active)setError(e instanceof Error ? e.message : "Unable to load page");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[section,tick]);

  async function saveDryRun(draft: ApiRow) {
    if(saving) return;
    if(!window.confirm("Save a DRY-RUN job for "+str(draft,"name")+
      "? This records metadata only. No container will be created or changed.")) return;
    const id=str(draft,"id");setSaving(id);setError("");
    try {
      const result=await api<Envelope<ApiRow>>("/api/deployments/drafts/"+
        encodeURIComponent(id)+"/jobs",{method:"POST",body:JSON.stringify({
          idempotency_key:crypto.randomUUID().replaceAll("-",""),execute:false})});
      setError("Dry-run saved as "+str(result.data,"id").slice(0,12)+
        ". No Docker operations were requested.");
      refresh();
    } catch(e) {setError(e instanceof Error?e.message:"Unable to save dry-run");}
    finally{setSaving("");}
  }

  const p=asObject(payload[0]), list=asRows(payload[0]), all=asRows(payload[1]);
  const meta=PAGE[section];
  const emptyView:View={title:meta.table,subtitle:"",headers:[],items:[]};
  let primary:View=emptyView, secondary:View|null=null;
  let stats:Stat[]=[], guide="", secondaryFoot="";
  if(section==="overview"||section==="containers"){
    stats=[
      ["Containers",count(p.containers_total),count(p.containers_running)+" running","▤"],
      ["CPU cores",count(p.cpus),str(p,"os"),"◉"],
      ["Memory",formatBytes(p.memory_bytes),"Host RAM capacity","▥"],
      ["Disk used",formatBytes(p.disk_used_bytes),
        "of "+formatBytes(p.disk_total_bytes)+" total","◫"],
    ];
    primary={title:meta.table,subtitle:str(p,"hostname")+" · Docker "+str(p,"docker_version"),
      headers:["Container","Image","State","Status","Ports","Actions"],
      items:all.map((c,i)=>entry(c,i,[
        str(c,"name"),<span className="mono" key="image">{str(c,"image")}</span>,
        <Status key="status" status={str(c,"state")}/>,str(c,"status"),
        <span className="mono" key="ports">{formatPorts(c.ports)}</span>,
        action("View logs",()=>setModal({kind:"logs",item:c})),
      ]))};
  }else if(section==="servers"){
    const fleet=asRows(p.servers), c=asObject(p.counts);
    const heartbeat:Record<string,string>={recent:"Signed recently",stale:"Stale",
      never_seen:"Never received",revoked:"Revoked",unpaired:"Not paired"};
    primary={title:meta.table,subtitle:count(c.paired)+" paired · "+
      count(c.heartbeat_recent)+" recent signed heartbeats · "+
      count(c.heartbeat_stale)+" stale · "+count(c.warning_servers)+
      " with warnings · "+count(c.critical_servers)+" critical · "+
      count(c.revoked)+" revoked · Identity telemetry only; remote Docker control disabled.",
      headers:["Server","Enrollment","Signed heartbeat","Signed host report","Warnings","Last host report","Actions"],
      items:fleet.map((s,i)=>entry(s,i,[
        str(s,"name"),str(s,"status"),heartbeat[str(s,"heartbeat_state")]||"Unknown",
        s.health ? str(asObject(s.health),"hostname")+" · "+
          str(asObject(s.health),"disk_free_percent")+"% disk free" : "No signed report",
        warningText(s.warnings),formatTime(s.last_report),
        action("Identity / health",()=>setModal({kind:"server",item:s})),
      ]))};
  }else if(section==="projects"){
    primary={title:meta.table,subtitle:"Saved application workspaces; no deployments have been created.",
      headers:["Project","Slug","Server ID","Environments","Actions"],
      items:list.map((x,i)=>entry(x,i,[str(x,"name"),<span key="slug" className="mono">{str(x,"slug")}</span>,
        x.server_id ? str(x,"server_id").slice(0,12) : "Unassigned",
        str(x,"environment_count"),action("Manage",()=>setModal({kind:"project",item:x}))]))};
  }else if(section==="activity"){
    primary={title:meta.table,subtitle:"Owner-visible, locally persisted security events.",
      headers:["Time","Actor","Action","Result","Source"],
      items:list.map((x,i)=>entry(x,i,[formatTime(x.timestamp),...fields(x,"actor","action","result"),
        str(x,"source_ip")]))};
  }else if(section==="monitoring"){
    const fleet=asObject(p.fleet), c=asObject(fleet.counts),
      local=asObject(p.local_host), servers=asRows(fleet.servers),
      diagnostics=asObject(payload[1]), details=asObject(diagnostics.diagnostics),
      counts=asObject(details.warnings), capacity=asObject(diagnostics.capacity);
    stats=[
      ["Local containers",count(local.containers_total),
        local.containers_running===undefined?"Local agent unavailable":
          count(local.containers_running)+" running","▤"],
      ["Registered servers",count(servers.length),"Saved owner records","◇"],
      ["Signed heartbeats",count(c.heartbeat_recent),count(c.heartbeat_stale)+" stale","◉"],
      ["Warnings",count(c.warning_servers),count(c.critical_servers)+" critical","⚑"],
    ];
    primary={title:meta.table,subtitle:"Local agent "+str(p,"local_state")+
      " · Remote health is self-reported and signed",
      headers:["Server","Identity","Signed heartbeat","Host report","Warnings","Last report"],
      items:servers.map((s,i)=>entry(s,i,[...fields(s,"name","status","heartbeat_state","report_state"),
        warningText(s.warnings),formatTime(s.last_report)]))};
    secondary={title:"Local container diagnostics",
      subtitle:diagnostics.state==="unavailable"?"Local Docker inventory unavailable. No health status inferred.":
        str(details,"sampled")+" containers observed · "+str(counts,"unhealthy")+
        " unhealthy · "+str(counts,"restarting")+" restarting · "+
        str(counts,"dead")+" dead · Disk free: "+
        (capacity.disk_free_percent==null?"not reported":str(capacity,"disk_free_percent")+"%"),
      headers:["Container","State","Docker status","Health indicator"],
      items:asRows(details.containers).slice(0,100).map((c,i)=>entry(c,i,[
        ...fields(c,"name","state","status"), Array.isArray(c.flags)&&c.flags.length
          ? c.flags.map(String).join(", ") : c.health==="reported_healthy"
            ? "Reported healthy":c.health==="unhealthy"?"Reported unhealthy":"No health report",
      ]))};
    guide="Monitoring is on-demand only. No background polling, alerts, remote Docker access, or automatic interventions are active.";
    secondaryFoot="Docker state is on-demand observation, not continuous health monitoring. No restart or write actions.";
  }else if(section==="deployments"){
    primary={title:meta.table,subtitle:str(p,"total_returned")+" saved drafts · 0 production-ready deployments",
      headers:["Draft","Project","Environment","Server","Image (pinned)","State / blockers","Actions"],
      items:asRows(p.drafts).map((d,i)=>entry(d,i,[
        ...fields(d,"name","project","environment"),
        d.server_name ? str(d,"server_name"):"Not assigned",
        <span key="image" className="mono">{short(d.image)}</span>,
        "Draft only · "+(Array.isArray(d.blockers)?d.blockers.map(String).join(", "):"Review required"),
        <div key="actions" className="next-quick-actions">
          {action("Review policy",()=>setModal({kind:"draft",item:d}))}
          {action(saving===d.id?"Saving…":"Save dry-run",()=>void saveDryRun(d),!!saving)}
        </div>,
      ]))};
    secondary={title:"Recent local deployment jobs",subtitle:"Owner-scoped SQLite history · manual lab execution only",
      headers:["Job","Draft","State","Attempts","Last update","Review"],
      items:all.map((j,i)=>entry(j,i,[str(j,"id").slice(0,12),str(j,"draft_id").slice(0,12),
        str(j,"state"),str(j,"attempt"),formatTime(j.updated_at),
        action("Evidence packet",()=>setModal({kind:"job",item:j}))]))};
    guide="Deployment execution remains disabled on production hosts. Only isolated lab hosts may explicitly enable the signed local execution pilot; there are no UI execution buttons.";
    secondaryFoot="No automatic execution. Unknown outcomes require operator reconciliation. Docker writes are disabled by default.";
  }else if(section==="settings"){
    const triples=[
      ["Version",str(p,"app_version"),"Current running dashboard"],
      ["Administrator",str(p,"owner"),"Authenticated owner (single-user pilot)"],
      ["HTTPS origin",str(p,"public_origin"),"Browser origin only; no private keys"],
      ["Session cookies",p.secure_cookies?"Secure + HttpOnly + SameSite=Strict":"HttpOnly + SameSite=Strict","No cookie values exposed"],
      ["Host agent",str(p,"agent_connection"),"Dedicated local agent only"],
      ["Docker inventory",str(p,"local_docker_inventory"),"Read-only queries"],
      ["Remote Docker",p.remote_docker_access?"Enabled":"Disabled","No remote Docker operations"],
      ["Container writes",p.container_writes?"Enabled":"Disabled","No start/stop/restart"],
      ["Deployment execution",p.deployment_execution?"Enabled":"Disabled","Configuration only"],
      ["Multi-factor authentication",p.multi_factor_auth?"Enabled":"Not implemented","Required for a public production panel"],
      ["Multi-user roles",p.multi_user_roles?"Enabled":"Not implemented","Single-owner pilot"],
      ["Security audit",str(p,"security_audit"),"Local persistent audit events"],
      ["Background alerts",p.background_alerts?"Enabled":"Disabled","Manual refresh only"],
    ];
    primary={title:meta.table,subtitle:"Read-only configuration disclosure · No credentials or secrets included",
      headers:["Control","Current value","Notes"],
      items:triples.map((x,i)=>({id:String(i),cells:x}))};
    guide="This page displays effective security settings. Credential rotation, MFA setup, and role management require a separate security-reviewed implementation.";
  }else{
    const config={
      images:["Image ID","Tags","Size"],
      networks:["Name","Driver","Scope","Network ID"],
      volumes:["Volume name","Driver","Scope"],
    } as Record<string,string[]>;
    primary={title:meta.table,subtitle:"Host-local Docker inventory.",headers:config[section]||[],
      items:list.map((x,i)=>entry(x,i,section==="images"
        ? [str(x,"id").slice(0,25),Array.isArray(x.tags)&&x.tags.length
          ? x.tags.map(String).join(", "):"untagged",formatBytes(x.size_bytes)]
        : section==="networks" ? [str(x,"name"),str(x,"driver"),str(x,"scope"),str(x,"id").slice(0,28)]
        : [str(x,"name"),str(x,"driver"),str(x,"scope")]))};
  }

  const connected=!loading && !error && SOURCE[section].some(s=>s.startsWith("/api/server/"));
  return <div className="shell">
    <aside className="sidebar">
      <div className="logo"><span className="logo-mark">M</span><span>MT <strong>Panel</strong></span></div>
      <div className="nav-section">WORKSPACE</div>
      <nav aria-label="Main navigation">{SECTIONS.map(name=><Link key={name}
        href={name==="overview"?"/":"/"+name}
        className={"nav-item"+(name===section?" active":"")}
        aria-current={name===section?"page":undefined}>
        <span className="nav-icon">{PAGE[name].icon}</span>
        {name==="overview"?"Overview":name==="settings"?"Settings":
          name[0].toUpperCase()+name.slice(1)}</Link>)}</nav>
      <div className="nav-section lower">COMING IN PHASE 3</div>
      <div className="nav-disabled">⚙ &nbsp; Deploy/Restart <span>locked</span></div>
      <div className="nav-disabled">◷ &nbsp; Automatic alerts <span>planned</span></div>
      <div className="sidebar-bottom">
        <div className="server-pill">
          <span className={"status-dot"+(connected?" ok":"")}/>
          <span>Local host agent</span><span>{connected?"Connected":error?"Unavailable":"Checking"}</span>
        </div>
        <div className="sidebar-footer">MT Tech Services · v0.3.14-dev</div>
      </div>
    </aside>
    <main className="workspace">
      <header className="topbar">
        <div className="breadcrumbs">Infrastructure <span>/</span><strong>{meta.title}</strong></div>
        <div className="top-actions"><span className="readonly">◉ &nbsp;READ-ONLY MODE</span>
          <button className="button ghost" disabled={loading} onClick={refresh}>↻ &nbsp;Refresh</button>
          <span className="avatar">{user.username.charAt(0).toUpperCase()}</span>
          <button className="button text-button" onClick={()=>void logout()}>Sign out</button>
        </div>
      </header>
      <section className="content">
        <div className="page-heading">
          <div><div className="eyebrow">OPERATIONS CENTER / NEXT.JS PREVIEW</div>
            <h1>{meta.title}</h1><p className="muted">{meta.subtitle}</p></div>
          <div className="updated">{updated?"Updated "+updated:"Not yet refreshed"}</div>
        </div>
        {error && <div role="alert" className="banner">{error}</div>}
        {p.source==="demo"&&<div className="demo-banner">DEMO DATA — This is a sample inventory, not a connected server.</div>}
        {guide && <div className="phase-guide" role="note">{guide}</div>}
        {loading?<div className="panel next-loading">Loading MT Panel inventory…</div>:<>
          <Stats values={stats}/>
          <section className="panel">
            <div className="panel-heading"><div><h2>{primary.title}</h2>
              <p className="muted">{primary.subtitle}</p></div>
              <div className="heading-actions">
                {(section==="servers"||section==="projects")&&<button type="button"
                  className="button primary" onClick={()=>setModal({kind:"resource",resource:section})}>
                  {section==="servers"?"+ Add server":"+ New project"}</button>}
                <span className="row-count">{primary.items.length} total</span>
              </div>
            </div>
            <Table view={primary}/>
            <div className="panel-foot">Read-only management · No deployment or container modifications are enabled</div>
          </section>
          {secondary&&<section className="panel next-panel">
            <div className="panel-heading"><div><h2>{secondary.title}</h2>
              <p className="muted">{secondary.subtitle}</p></div>
              <span className="row-count">{secondary.items.length} shown</span>
            </div>
            <Table view={secondary} empty="No local container results."/>
            <div className="panel-foot">{secondaryFoot}</div>
          </section>}
        </>}
      </section>
    </main>
    <ModalHost modal={modal} onClose={()=>setModal(null)} onChange={refresh}/>
  </div>;
}
