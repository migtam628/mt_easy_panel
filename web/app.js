'use strict';
const $ = (id) => document.getElementById(id);
const state = {view: 'overview', containers: [], overview: null, projectId: null, serverId: null};
const descriptions = {
  overview: ['Infrastructure overview', 'A real-time snapshot of your local Docker host.', 'Container inventory'],
  containers: ['Containers', 'Inspect running and stopped workloads.', 'All containers'],
  images: ['Container images', 'Available local Docker images.', 'Images'],
  networks: ['Networks', 'Docker network inventory.', 'Network inventory'],
  volumes: ['Volumes', 'Named persistent Docker volumes (mount paths hidden).', 'Volume inventory'],
  servers: ['Servers', 'Monitor verified agent identities and signed host health. Remote Docker access remains disabled.', 'Fleet health'],
  projects: ['Projects', 'Configuration-only application workspaces.', 'Projects'],
  activity: ['Activity', 'Recent administrative sign-in and sign-out events.', 'Security audit log'],
  monitoring: ['Monitoring', 'Read-only host capacity and signed fleet signals.', 'Host and identity health'],
  deployments: ['Deployments', 'Configuration drafts only. Execution is disabled.', 'Deployment preparation'],
  settings: ['Security settings', 'Review effective settings without exposing secrets.', 'Security posture'],
};
async function api(path, options = {}) {
  const resp = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options});
  let json = {};
  try { json = await resp.json(); } catch (_) { /* empty body */ }
  if (!resp.ok) {
    const err = new Error(typeof json.detail === 'string' ? json.detail : `Request failed (HTTP ${resp.status})`);
    err.status = resp.status;
    throw err;
  }
  return json;
}
const size = (num) => Number.isFinite(Number(num)) ? `${(Number(num) / (1024 ** 3)).toFixed(1)} GB` : '—';
const number = (val) => Number.isFinite(Number(val)) ? Number(val).toLocaleString() : '—';
function el(tag, content = '', className = '') {
  const node = document.createElement(tag);
  node.textContent = String(content == null ? '—' : content);
  if (className) node.className = className;
  return node;
}
function cell(tr, content, className = '') { tr.append(el('td', content, className)); }
function statusCell(tr, value) {
  const td = document.createElement('td');
  const isOn = value === 'running';
  const badge = el('span', value || 'unknown', `pill ${isOn ? '' : value === 'exited' ? 'off' : 'other'}`);
  td.append(badge); tr.append(td);
}
function setMessage(msg) { $('banner').textContent = msg; $('banner').classList.toggle('hidden', !msg); }
function showLogin() { $('login').classList.remove('hidden'); $('shell').classList.add('hidden'); }
function showShell(username) {
  $('login').classList.add('hidden'); $('shell').classList.remove('hidden');
  $('avatar').textContent = (username || 'A')[0].toUpperCase();
}
function metric(title, value, foot, icon) {
  const c = el('div', '', 'stat');
  c.append(el('span', icon, 'stat-icon'), el('div', title, 'stat-label'), el('div', value, 'stat-value'), el('div', foot, 'stat-footer'));
  return c;
}
function renderMetricCards(items) {
  const holder = $('stats'); holder.replaceChildren();
  holder.classList.toggle('hidden', !items.length);
  items.forEach(item => holder.append(metric(...item)));
}
function showGuide(message) {
  const holder = $('phase-guide');
  holder.textContent = message;
  holder.classList.toggle('hidden', !message);
}
function renderStats(data) {
  const holder = $('stats'); holder.replaceChildren();
  if (!data) { holder.classList.add('hidden'); return; }
  holder.classList.remove('hidden');
  const items = [
    ['Containers', number(data.containers_total), `${number(data.containers_running)} running`, '▤'],
    ['CPU cores', number(data.cpus), data.os || 'Host', '◉'],
    ['Memory', size(data.memory_bytes), 'Host RAM capacity', '▥'],
    ['Disk used', size(data.disk_used_bytes), `of ${size(data.disk_total_bytes)} total`, '◫'],
  ];
  items.forEach((item) => holder.append(metric(...item)));
}
function secondaryRows(headers, rows) {
  const head = $('secondary-head'); head.replaceChildren();
  const hr = document.createElement('tr');
  headers.forEach(h => hr.append(el('th', h)));
  head.append(hr);
  const body = $('secondary-body'); body.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = el('td', 'No local container results.', 'empty');
    td.colSpan = headers.length; tr.append(td); body.append(tr);
  } else rows.forEach(row => body.append(row));
  $('secondary-count').textContent = rows.length + ' shown';
}
async function showDraftReview(draft) {
  $('draft-review-title').textContent = draft.name + ' / Static security review';
  $('draft-review-details').replaceChildren();
  $('draft-review-checks').replaceChildren();
  $('draft-review-dialog').showModal();
  try {
    const data = (await api('/api/deployments/drafts/' +
      encodeURIComponent(draft.id) + '/review')).data;
    const details = $('draft-review-details');
    details.append(el('div', 'Project: ' + data.project +
      ' · Environment: ' + data.environment, 'config-item'));
    details.append(el('div', 'Server: ' + (data.server || 'Not assigned'), 'config-item'));
    if (data.manifest) {
      details.append(el('div', 'Pinned image: ' + data.manifest.image, 'config-item mono'));
      details.append(el('div', 'Resources: ' + data.manifest.cpu_limit +
        ' CPU · ' + data.manifest.memory_mb + ' MB RAM · Internal port ' +
        data.manifest.container_port + ' · Read-only filesystem', 'config-item'));
    }
    data.checks.forEach(check => $('draft-review-checks').append(el('div',
      (check.passed ? 'PASS' : 'BLOCKED') + ' · ' + check.explanation, 'config-item')));
    $('draft-review-checks').append(el('div',
      'EXECUTION DISABLED — this review does not deploy anything.', 'config-item'));
  } catch (error) {
    $('draft-review-details').append(el('div', error.message, 'error'));
  }
}
function tableRows(headers, rows) {
  const head = $('table-head'); head.replaceChildren();
  const hr = document.createElement('tr'); headers.forEach(h => hr.append(el('th', h))); head.append(hr);
  const body = $('table-body'); body.replaceChildren();
  if (!rows.length) { const tr = document.createElement('tr'), td = el('td', 'No resources found.', 'empty'); td.colSpan = headers.length; tr.append(td); body.append(tr); }
  else rows.forEach(row => body.append(row));
  $('row-count').textContent = `${rows.length} total`;
}
function containerRow(c) {
  const tr = document.createElement('tr');
  cell(tr, c.name || '—'); cell(tr, c.image || '—', 'mono'); statusCell(tr, c.state);
  cell(tr, c.status || '—');
  const ports = (c.ports || []).map(p => p.public ? `${p.public}:${p.private}` : `${p.private}`).join(', ');
  cell(tr, ports || '—', 'mono');
  const last = document.createElement('td'), button = el('button', 'View logs', 'link-button');
  button.type = 'button'; button.addEventListener('click', () => openLogs(c));
  last.append(button); tr.append(last); return tr;
}
function serverRow(x) {
  const heartbeat = {
    recent: 'Signed recently', stale: 'Stale', never_seen: 'Never received',
    revoked: 'Revoked', unpaired: 'Not paired'
  };
  const host = x.health
    ? x.health.hostname + ' · ' + x.health.disk_free_percent + '% disk free'
    : 'No signed report';
  const warnings = (x.warnings || []).map(w => w.severity.toUpperCase() + ': ' + w.message);
  const tr = plainRow([x.name, x.status,
    heartbeat[x.heartbeat_state] || 'Unknown',
    (x.report_state === 'recent' ? 'Recent · ' : x.report_state === 'stale' ? 'Stale · ' : '') + host,
    warnings.join('; ') || 'No warnings',
    x.last_report ? new Date(x.last_report * 1000).toLocaleString() : '—']);
  const td = document.createElement('td');
  const button = el('button', 'Identity / health', 'link-button');
  button.type = 'button';
  button.addEventListener('click', () => openServer(x));
  td.append(button); tr.append(td);
  return tr;
}
function projectRow(x) {
  const tr = plainRow([x.name, x.slug, x.server_id ? x.server_id.slice(0,12) : 'Unassigned', x.environment_count]);
  const td = document.createElement('td');
  const button = el('button', 'Manage', 'link-button');
  button.type = 'button';
  button.addEventListener('click', () => openProject(x));
  td.append(button);
  tr.append(td);
  return tr;
}
function plainRow(values) {
  const tr = document.createElement('tr');
  values.forEach((v,i) => cell(tr, v, i === 1 ? 'mono' : ''));
  return tr;
}
async function openLogs(c) {
  $('log-title').textContent = c.name;
  $('log-output').textContent = 'Loading logs…';
  $('log-dialog').showModal();
  try {
    const json = await api(`/api/server/containers/${encodeURIComponent(c.id)}/logs`);
    $('log-output').textContent = json.data || 'No log output available.';
  } catch (err) { $('log-output').textContent = err.message; }
}
async function refresh() {
  setMessage('');
  const view = state.view;
  $('refresh').disabled = true;
  try {
    const shouldOverview = view === 'overview' || view === 'containers';
    if (shouldOverview) {
      const [ov, ct] = await Promise.all([api('/api/server/overview'), api('/api/server/containers')]);
      state.overview = ov.data; state.containers = ct.data;
      renderStats(ov.data);
      tableRows(['Container', 'Image', 'State', 'Status', 'Ports', 'Actions'], ct.data.map(containerRow));
      $('agent-state').textContent = 'Connected';
      document.querySelector('.status-dot').classList.add('ok');
      $('demo-banner').classList.toggle('hidden', ov.data.source !== 'demo');
      $('table-subtitle').textContent = `${ov.data.hostname} · Docker ${ov.data.docker_version}`;
    } else if (view === 'servers') {
      renderStats(null);
      const fleet = (await api('/api/fleet/summary')).data;
      tableRows(['Server', 'Enrollment', 'Signed heartbeat', 'Signed host report',
        'Warnings', 'Last host report', 'Actions'], fleet.servers.map(serverRow));
      const c = fleet.counts;
      $('table-subtitle').textContent = c.paired + ' paired · ' +
        c.heartbeat_recent + ' recent signed heartbeats · ' + c.heartbeat_stale +
        ' stale · ' + c.warning_servers + ' with warnings · ' +
        c.critical_servers + ' critical · ' + c.revoked + ' revoked' +
        (fleet.truncated ? ' · Showing first 500 servers' : '') +
        ' · Identity telemetry only; remote Docker control disabled.';
    } else if (view === 'projects') {
      renderStats(null);
      const items = (await api('/api/catalog/projects')).data;
      tableRows(['Project', 'Slug', 'Server ID', 'Environments', 'Actions'],
        items.map(projectRow));
      $('table-subtitle').textContent = 'Saved application workspaces; no deployments have been created.';
    } else if (view === 'activity') {
      renderStats(null);
      const data = (await api('/api/audit/events?limit=100')).data;
      tableRows(['Time', 'Actor', 'Action', 'Result', 'Source'],
        data.map(x => plainRow([new Date(x.timestamp * 1000).toLocaleString(),
          x.actor, x.action, x.result, x.source_ip || '—'])));
      $('table-subtitle').textContent = 'Owner-visible, locally persisted security events.';
    } else if (view === 'monitoring') {
      const data = (await api('/api/monitoring/overview')).data;
      const count = data.fleet.counts;
      const local = data.local_host;
      renderMetricCards([
        ['Local containers', local ? number(local.containers_total) : '—',
          local ? number(local.containers_running) + ' running' : 'Local agent unavailable', '▤'],
        ['Registered servers', number(data.fleet.servers.length),
          data.fleet.truncated ? 'First 500 shown' : 'Saved owner records', '◇'],
        ['Signed heartbeats', number(count.heartbeat_recent),
          number(count.heartbeat_stale) + ' stale', '◉'],
        ['Warnings', number(count.warning_servers),
          number(count.critical_servers) + ' critical', '⚑'],
      ]);
      const rows = data.fleet.servers.map(x => plainRow([
        x.name, x.status, x.heartbeat_state, x.report_state,
        (x.warnings || []).map(w => w.severity.toUpperCase() + ': ' + w.message).join('; ') || 'No warnings',
        x.last_report ? new Date(x.last_report * 1000).toLocaleString() : '—'
      ]));
      tableRows(['Server', 'Identity', 'Signed heartbeat', 'Host report', 'Warnings',
        'Last report'], rows);
      $('table-subtitle').textContent = data.local_state === 'connected'
        ? 'Local host connected · Remote health is self-reported and signed'
        : 'Local agent ' + data.local_state + ' · Remote health is self-reported and signed';
      showGuide('Monitoring is on-demand only. No background polling, alerts, remote Docker access, or automatic interventions are active.');
      const localDiagnostics = (await api('/api/monitoring/diagnostics')).data;
      $('secondary-panel').classList.remove('hidden');
      if (localDiagnostics.state === 'unavailable') {
        secondaryRows(['Container', 'State', 'Docker status', 'Health indicator'], []);
        $('secondary-subtitle').textContent = 'Local Docker inventory unavailable. No health status inferred.';
      } else {
        const summary = localDiagnostics.diagnostics;
        const sample = summary.containers.slice(0, 100);
        secondaryRows(['Container', 'State', 'Docker status', 'Health indicator'],
          sample.map(c => plainRow([c.name, c.state, c.status,
            c.flags.length ? c.flags.join(', ') :
              c.health === 'reported_healthy' ? 'Reported healthy' :
                c.health === 'unhealthy' ? 'Reported unhealthy' : 'No health report'])));
        const warning = summary.warnings;
        const capacity = localDiagnostics.capacity;
        $('secondary-subtitle').textContent =
          (localDiagnostics.state === 'demo' ? 'DEMO DATA · ' : 'LOCAL DOCKER · ') +
          summary.sampled + ' containers observed · ' +
          warning.unhealthy + ' unhealthy · ' + warning.restarting + ' restarting · ' +
          warning.dead + ' dead · Disk free: ' +
          (capacity && capacity.disk_free_percent !== null
            ? capacity.disk_free_percent + '%' : 'not reported') +
          (summary.containers.length > 100 ? ' · Showing first 100; see Containers for full inventory' : '');
      }
    } else if (view === 'deployments') {
      renderStats(null);
      const result = (await api('/api/deployments/readiness')).data;
      tableRows(['Draft', 'Project', 'Environment', 'Server', 'Image (pinned)',
        'State / blockers', 'Review'], result.drafts.map(d => {
          const tr = plainRow([
            d.name, d.project, d.environment, d.server_name || 'Not assigned',
            d.image ? (d.image.length > 70 ? d.image.slice(0, 67) + '…' : d.image) : 'Unavailable',
            'Draft only · ' + d.blockers.join(', ')
          ]);
          const last = document.createElement('td');
          const button = el('button', 'Review policy', 'link-button');
          button.type = 'button';
          button.addEventListener('click', () => showDraftReview(d));
          last.append(button); tr.append(last);
          return tr;
        }));
      $('table-subtitle').textContent = result.total_returned + ' saved drafts' +
        (result.truncated ? ' (first 200)' : '') + ' · 0 executable deployments';
      showGuide('Read-only deployment readiness. Drafts are not running workloads. No deployment queue, builds, Compose up, or Docker writes are implemented. Create drafts under Projects.');
    } else if (view === 'settings') {
      renderStats(null);
      const p = (await api('/api/settings/security')).data;
      const values = [
        ['Version', p.app_version, 'Current running dashboard'],
        ['Administrator', p.owner, 'Authenticated owner (single-user pilot)'],
        ['HTTPS origin', p.public_origin, 'Browser origin only; no private keys'],
        ['Session cookies', p.secure_cookies ? 'Secure + HttpOnly + SameSite=Strict' : 'HttpOnly + SameSite=Strict', 'No cookie values exposed'],
        ['Host agent', p.agent_connection, 'Dedicated local agent only'],
        ['Docker inventory', p.local_docker_inventory, 'Read-only queries'],
        ['Remote Docker', p.remote_docker_access ? 'Enabled' : 'Disabled', 'No remote Docker operations'],
        ['Container writes', p.container_writes ? 'Enabled' : 'Disabled', 'No start/stop/restart'],
        ['Deployment execution', p.deployment_execution ? 'Enabled' : 'Disabled', 'Configuration only'],
        ['Multi-factor authentication', p.multi_factor_auth ? 'Enabled' : 'Not implemented', 'Required for a public production panel'],
        ['Multi-user roles', p.multi_user_roles ? 'Enabled' : 'Not implemented', 'Single-owner pilot'],
        ['Security audit', p.security_audit, 'Local persistent audit events'],
        ['Background alerts', p.background_alerts ? 'Enabled' : 'Disabled', 'Manual refresh only']
      ];
      tableRows(['Control', 'Current value', 'Notes'], values.map(v => plainRow(v)));
      $('table-subtitle').textContent = 'Read-only configuration disclosure · No credentials or secrets included';
      showGuide('This page displays effective security settings. Credential rotation, MFA setup, and role management require a separate security-reviewed implementation.');
    } else {
      renderStats(null);
      const data = (await api(`/api/server/${view}`)).data;
      const format = {
        images: {headers: ['Image ID', 'Tags', 'Size'], row: x => [x.id?.slice(0, 25), (x.tags || []).join(', ') || 'untagged', size(x.size_bytes)]},
        networks: {headers: ['Name', 'Driver', 'Scope', 'Network ID'], row: x => [x.name, x.driver, x.scope, x.id?.slice(0, 28)]},
        volumes: {headers: ['Volume name', 'Driver', 'Scope'], row: x => [x.name, x.driver, x.scope]},
      }[view];
      tableRows(format.headers, data.map(x => plainRow(format.row(x))));
      $('table-subtitle').textContent = 'Host-local Docker inventory.';
    }
    $('updated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    if (['overview','containers','images','networks','volumes'].includes(view)) {
      $('agent-state').textContent = 'Unavailable';
      document.querySelector('.status-dot').classList.remove('ok');
    }
    setMessage(err.status === 401 ? 'Session ended. Please sign in again.' : err.message);
    if (err.status === 401) showLogin();
  } finally { $('refresh').disabled = false; }
}
function switchView(view) {
  state.view = view;
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  const desc = descriptions[view];
  $('page-title').textContent = desc[0]; $('breadcrumb').textContent = desc[0];
  $('page-desc').textContent = desc[1]; $('table-title').textContent = desc[2];
  $('demo-banner').classList.add('hidden');
  showGuide('');
  $('secondary-panel').classList.add('hidden');
  $('create-resource').classList.toggle('hidden', !['servers','projects'].includes(view));
  $('create-resource').textContent = view === 'servers' ? '+ Add server' : '+ New project';
  refresh();
}
async function showResourceForm() {
  const project = state.view === 'projects';
  $('resource-title').textContent = project ? 'Create project' : 'Register server (configuration only)';
  $('resource-form').reset();
  $('resource-error').textContent = '';
  for (const name of ['slug','server']) {
    $(name + '-label').classList.toggle('hidden', !project);
    $('resource-' + name).classList.toggle('hidden', !project);
  }
  $('resource-slug').required = project;
  $('notes-label').classList.toggle('hidden', project);
  $('resource-notes').classList.toggle('hidden', project);
  if (project) {
    try {
      const select = $('resource-server');
      select.replaceChildren(new Option('Unassigned', ''));
      const servers = (await api('/api/catalog/servers')).data;
      servers.forEach(s => select.add(new Option(s.name + ' (not paired)', s.id)));
    } catch (error) { setMessage(error.message); return; }
  }
  $('resource-dialog').showModal();
}
async function submitResource(event) {
  event.preventDefault();
  const project = state.view === 'projects';
  const payload = project
    ? {name: $('resource-name').value, slug: $('resource-slug').value,
       server_id: $('resource-server').value || null}
    : {name: $('resource-name').value, notes: $('resource-notes').value};
  $('resource-error').textContent = '';
  try {
    await api('/api/catalog/' + (project ? 'projects' : 'servers'), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    $('resource-dialog').close();
    await refresh();
  } catch (error) { $('resource-error').textContent = error.message; }
}
function renderSignedHistory(samples) {
  const holder = $('server-host-history');
  holder.replaceChildren();
  if (!samples.length) {
    holder.append(el('div', 'No signed host reports recorded yet.', 'config-item'));
    return;
  }
  const first = samples[0], latest = samples[samples.length - 1];
  holder.append(el('div', samples.length + ' signed reports · latest: ' +
    new Date(latest.recorded_at * 1000).toLocaleString() +
    ' · ' + latest.disk_free_percent.toFixed(1) + '% disk free', 'config-item'));
  // Native SVG only; numbers come from schema-validated, signed telemetry.
  // The 0-100% vertical scale is fixed to avoid exaggerated trend changes.
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 640 132');
  svg.setAttribute('role', 'img');
  svg.setAttribute('class', 'health-chart');
  svg.setAttribute('aria-label', 'Disk free percentage across ' +
    samples.length + ' signed reports, oldest to newest');
  const grid = document.createElementNS(ns, 'line');
  grid.setAttribute('x1', '12'); grid.setAttribute('x2', '628');
  grid.setAttribute('y1', '64'); grid.setAttribute('y2', '64');
  grid.setAttribute('stroke', 'currentColor'); grid.setAttribute('opacity', '0.18');
  svg.append(grid);
  const points = samples.map((entry, i) => {
    const x = 12 + (samples.length === 1 ? 308 : i * 616 / (samples.length - 1));
    const pct = Math.max(0, Math.min(100, Number(entry.disk_free_percent)));
    return x.toFixed(1) + ',' + (116 - pct).toFixed(1);
  });
  const line = document.createElementNS(ns, 'polyline');
  line.setAttribute('points', points.join(' '));
  line.setAttribute('fill', 'none'); line.setAttribute('stroke', '#098a87');
  line.setAttribute('stroke-width', '3');
  line.setAttribute('stroke-linecap', 'round');
  line.setAttribute('stroke-linejoin', 'round');
  svg.append(line);
  const label = document.createElementNS(ns, 'title');
  label.textContent = 'Signed disk history: ' + first.disk_free_percent +
    '% to ' + latest.disk_free_percent + '% free';
  svg.prepend(label);
  holder.append(svg);
}
async function refreshServerIdentity() {
  if (!state.serverId) return;
  const details = (await api('/api/catalog/servers/' + encodeURIComponent(state.serverId) + '/identity')).data;
  const holder = $('server-identity');
  holder.replaceChildren();
  const identity = details.identity;
  holder.append(el('div', 'Server ID: ' + state.serverId, 'config-item mono'));
  holder.append(el('div', 'Identity: ' + details.status, 'config-item'));
  const signals = {not_enrolled:'Not enrolled', revoked:'Revoked',
    never_seen:'No heartbeat received yet', recent:'Signed heartbeat received recently',
    stale:'Last signed heartbeat is stale'};
  holder.append(el('div', 'Heartbeat: ' +
    (signals[details.heartbeat_state] || 'Unknown') + ' (not Docker connectivity)', 'config-item'));
  if (identity) {
    holder.append(el('div', 'Key fingerprint: ' + identity.fingerprint, 'config-item mono'));
    holder.append(el('div', 'Last signed heartbeat: ' +
      (identity.last_seen ? new Date(identity.last_seen * 1000).toLocaleString() : 'Not received'),
      'config-item'));
    holder.append(el('div', 'Last sequence: ' + identity.last_sequence, 'config-item mono'));
  }
  const reportHolder = $('server-host-report');
  reportHolder.replaceChildren();
  const report = (await api('/api/catalog/servers/' +
    encodeURIComponent(state.serverId) + '/host-report')).data;
  if (!report.snapshot) {
    reportHolder.append(el('div', 'No available signed host report (' + report.state + ')',
      'config-item'));
  } else {
    const snapshot = report.snapshot;
    reportHolder.append(el('div', 'Report: ' + report.state +
      ' · ' + new Date(report.received_at * 1000).toLocaleString(), 'config-item'));
    reportHolder.append(el('div', 'Host: ' + snapshot.hostname + ' · ' +
      snapshot.system, 'config-item'));
    reportHolder.append(el('div', 'CPU: ' + snapshot.cpu_count +
      ' · RAM: ' + size(snapshot.memory_total_bytes), 'config-item'));
    reportHolder.append(el('div', 'Disk available: ' + size(snapshot.disk_free_bytes) +
      ' / ' + size(snapshot.disk_total_bytes) +
      ' · Uptime: ' + Math.floor(snapshot.uptime_seconds / 3600) + ' h',
      'config-item'));
  }
  const signedHistory = (await api('/api/catalog/servers/' +
    encodeURIComponent(state.serverId) + '/host-history?limit=96')).data;
  renderSignedHistory(signedHistory.samples);
  $('server-invite').disabled = details.status === 'paired';
  $('server-revoke').disabled = details.status === 'revoked';
}
async function openServer(server) {
  state.serverId = server.id;
  const warningHolder = $('server-warnings');
  warningHolder.replaceChildren();
  (server.warnings || []).forEach(w => warningHolder.append(el('div',
    w.severity.toUpperCase() + ' · ' + w.message, 'config-item')));
  if (!(server.warnings || []).length) {
    warningHolder.append(el('div', 'No warnings based on the latest signed data.', 'config-item'));
  }
  $('server-dialog-title').textContent = server.name + ' / Agent identity';
  $('server-invite-code').value = '';
  $('server-code-area').classList.add('hidden');
  $('server-error').textContent = '';
  $('server-dialog').showModal();
  try { await refreshServerIdentity(); }
  catch (err) { $('server-error').textContent = err.message; }
}
async function createServerInvite() {
  if (!state.serverId) return;
  $('server-error').textContent = '';
  $('server-invite-code').value = '';
  $('server-code-area').classList.add('hidden');
  try {
    const result = (await api('/api/catalog/servers/' +
      encodeURIComponent(state.serverId) + '/invites', {method:'POST'})).data;
    $('server-invite-code').value = result.enrollment_code;
    $('server-code-area').classList.remove('hidden');
    await refreshServerIdentity();
  } catch (err) { $('server-error').textContent = err.message; }
}
async function revokeServerIdentity() {
  if (!state.serverId) return;
  if (!window.confirm('Revoke this server identity and invalidate its invitations? Existing signed heartbeats will be denied.')) return;
  $('server-error').textContent = '';
  try {
    await api('/api/catalog/servers/' +
      encodeURIComponent(state.serverId) + '/revoke', {method:'POST'});
    $('server-invite-code').value = '';
    $('server-code-area').classList.add('hidden');
    await refreshServerIdentity();
    await refresh();
  } catch (err) { $('server-error').textContent = err.message; }
}
async function openProject(project) {
  state.projectId = project.id;
  $('project-dialog-title').textContent = project.name + ' / Environments';
  $('project-error').textContent = '';
  $('project-dialog').showModal();
  await refreshProject();
}
async function refreshProject() {
  if (!state.projectId) return;
  try {
    const envs = (await api('/api/catalog/projects/' + encodeURIComponent(state.projectId) + '/environments')).data;
    const list = $('project-environments');
    list.replaceChildren();
    if (!envs.length) list.append(el('div', 'No environments yet.', 'muted'));
    else envs.forEach(e => list.append(el('div', e.name + ' (' + e.slug + ')', 'config-item')));
    const select = $('draft-environment');
    const previous = select.value;
    select.replaceChildren(new Option('Choose environment', ''));
    envs.forEach(e => select.add(new Option(e.name, e.id)));
    if (envs.some(e => e.id === previous)) select.value = previous;
    else if (envs.length) select.value = envs[0].id;
    await refreshDrafts();
  } catch (error) { $('project-error').textContent = error.message; }
}
async function refreshDrafts() {
  const id = $('draft-environment').value;
  const list = $('project-drafts');
  list.replaceChildren();
  if (!id) {
    list.append(el('div', 'Choose an environment to view drafts.', 'muted'));
    return;
  }
  try {
    const drafts = (await api('/api/catalog/environments/' + encodeURIComponent(id) + '/drafts')).data;
    if (!drafts.length) list.append(el('div', 'No drafts configured.', 'muted'));
    else drafts.forEach(d => list.append(el('div', d.name + ' — ' + d.manifest.image + ' (draft only)', 'config-item mono')));
  } catch (error) { $('project-error').textContent = error.message; }
}
async function createEnvironment(event) {
  event.preventDefault();
  $('project-error').textContent = '';
  try {
    await api('/api/catalog/projects/' + encodeURIComponent(state.projectId) + '/environments', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:$('environment-name').value,slug:$('environment-slug').value})
    });
    $('environment-form').reset();
    await refreshProject();
    await refresh();
  } catch (error) { $('project-error').textContent = error.message; }
}
async function createDraft(event) {
  event.preventDefault();
  const envId = $('draft-environment').value;
  if (!envId) { $('project-error').textContent = 'Create an environment first.'; return; }
  $('project-error').textContent = '';
  try {
    await api('/api/catalog/environments/' + encodeURIComponent(envId) + '/drafts', {
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:$('draft-name').value,slug:$('draft-slug').value,
        image:$('draft-image').value,container_port:Number($('draft-port').value)})
    });
    $('draft-form').reset();
    await refreshDrafts();
  } catch (error) { $('project-error').textContent = error.message; }
}
async function previewCompose(event) {
  event.preventDefault();
  const out = $('compose-result');
  out.textContent = 'Validating — no deployment will run…';
  try {
    const response = await api('/api/validate/compose', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({source:$('compose-source').value})
    });
    out.textContent = JSON.stringify(response.data, null, 2);
  } catch (error) {
    out.textContent = 'Rejected by safe-preview policy: ' + error.message;
  }
}
async function init() {
  $('close-server').addEventListener('click', () => {
    $('server-invite-code').value = '';
    $('server-code-area').classList.add('hidden');
    $('server-dialog').close();
  });
  $('server-dialog').addEventListener('close', () => {
    $('server-invite-code').value = '';
    $('server-code-area').classList.add('hidden');
  });
  $('server-invite').addEventListener('click', createServerInvite);
  $('server-revoke').addEventListener('click', revokeServerIdentity);
  $('compose-form').addEventListener('submit', previewCompose);
  $('close-project').addEventListener('click', () => $('project-dialog').close());
  $('environment-form').addEventListener('submit', createEnvironment);
  $('draft-environment').addEventListener('change', refreshDrafts);
  $('draft-form').addEventListener('submit', createDraft);
  $('create-resource').addEventListener('click', showResourceForm);
  $('close-resource').addEventListener('click', () => $('resource-dialog').close());
  $('resource-form').addEventListener('submit', submitResource);
  document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => switchView(button.dataset.view)));
  $('refresh').addEventListener('click', refresh);
  $('close-log').addEventListener('click', () => $('log-dialog').close());
  $('close-draft-review').addEventListener('click', () => $('draft-review-dialog').close());
  $('logout').addEventListener('click', async () => {
    try { await api('/api/auth/logout', {method:'POST'}); } finally { showLogin(); }
  });
  $('login-form').addEventListener('submit', async event => {
    event.preventDefault(); $('login-error').textContent = '';
    const submit = event.target.querySelector('button[type="submit"]'); submit.disabled = true;
    try {
      const user = await api('/api/auth/login', {method:'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({username:$('username').value, password:$('password').value})});
      $('password').value = '';
      showShell(user.username); switchView('overview');
    } catch (err) { $('login-error').textContent = err.message; }
    finally { submit.disabled = false; }
  });
  try {
    const user = await api('/api/auth/me'); showShell(user.username); switchView('overview');
  } catch (_) {
    showLogin();
    try { if ((await api('/api/setup')).needs_setup) $('login-error').textContent = 'Initial setup required: run python -m panel.cli create-admin on the server.'; } catch (_) { /* offline */ }
  }
}
document.addEventListener('DOMContentLoaded', init);
