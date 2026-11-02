'use strict';
const $ = (id) => document.getElementById(id);
const state = {view: 'overview', containers: [], overview: null, projectId: null};
const descriptions = {
  overview: ['Infrastructure overview', 'A real-time snapshot of your local Docker host.', 'Container inventory'],
  containers: ['Containers', 'Inspect running and stopped workloads.', 'All containers'],
  images: ['Container images', 'Available local Docker images.', 'Images'],
  networks: ['Networks', 'Docker network inventory.', 'Network inventory'],
  volumes: ['Volumes', 'Named persistent Docker volumes (mount paths hidden).', 'Volume inventory'],
  servers: ['Servers', 'Server identities are not connected until secure pairing is implemented.', 'Server registry'],
  projects: ['Projects', 'Configuration-only application workspaces.', 'Projects'],
  activity: ['Activity', 'Recent administrative sign-in and sign-out events.', 'Security audit log'],
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
      const items = (await api('/api/catalog/servers')).data;
      tableRows(['Name', 'Connection', 'Notes', 'Created'],
        items.map(x => plainRow([x.name, 'Not paired', x.notes || '—',
          new Date(x.created_at * 1000).toLocaleDateString()])));
      $('table-subtitle').textContent = 'Saved identities only; no SSH connection or host access.';
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
    if (view !== 'activity') {
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
async function init() {
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
