const schema = [{"name": "left", "label": "第一个变量", "options": ["practice", "preparation", "feedback", "score"]}, {"name": "right", "label": "第二个变量", "options": ["practice", "preparation", "feedback", "score"]}];
const defaults = {"operation": "correlation", "left": "practice", "right": "score"};
const sources = ["observations", "variables", "knowledge"];
let study = null;
let summary = null;
let latestRequest = {...defaults};
let currentRun = null;

async function api(route, payload) {
  const options = payload === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
  };
  const response = await fetch(route, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || String(response.status));
  return result;
}

function display(target, value) {
  document.getElementById(target).textContent = JSON.stringify(value, null, 2);
}

function renderTable(source) {
  const holder = document.getElementById('records');
  holder.replaceChildren();
  const raw = study[source];
  const rows = Array.isArray(raw) ? raw : Object.entries(raw).map(([key, value]) => ({key, value}));
  if (!rows.length) { holder.textContent = '当前集合没有记录'; return; }
  const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
  const table = document.createElement('table');
  const head = table.createTHead().insertRow();
  for (const column of columns) {
    const cell = document.createElement('th'); cell.textContent = column; head.append(cell);
  }
  const body = table.createTBody();
  for (const row of rows) {
    const rendered = body.insertRow();
    for (const column of columns) {
      const value = row[column];
      rendered.insertCell().textContent = value === null ? '缺失' : typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
    }
  }
  holder.append(table);
  document.getElementById('record-count').textContent = String(rows.length) + ' 条记录';
}

function renderControls() {
  const form = document.getElementById('action-form');
  for (const control of schema) {
    const label = document.createElement('label'); label.textContent = control.label;
    let input;
    if (control.options) {
      input = document.createElement('select');
      input.multiple = Array.isArray(defaults[control.name]);
      for (const value of control.options) {
        const option = document.createElement('option'); option.value = value; option.textContent = value;
        option.selected = input.multiple ? defaults[control.name].includes(value) : defaults[control.name] === value;
        input.append(option);
      }
    } else {
      input = document.createElement('input'); input.type = 'number'; input.value = defaults[control.name];
    }
    input.name = control.name; label.append(input); form.append(label);
  }
  const button = document.createElement('button'); button.type = 'submit'; button.textContent = "查看成对相关";
  form.append(button);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    latestRequest = {operation: defaults.operation};
    for (const control of schema) {
      const field = form.elements.namedItem(control.name);
      latestRequest[control.name] = field.multiple ? [...field.selectedOptions].map(option => option.value)
        : control.options ? field.value : Number(field.value);
    }
    try { display('result', await api('/api/action', latestRequest)); }
    catch (error) { display('result', {error: error.message}); }
  });
}

async function refreshNotes() {
  const result = await api('/api/notes');
  const holder = document.getElementById('notes'); holder.replaceChildren();
  for (const note of result.notes) {
    const item = document.createElement('li'); item.textContent = note.text + ' · ' + note.created_at; holder.append(item);
  }
}

/* ---------- 结构候选探索台 ---------- */

function parsePairs(text) {
  const pairs = [];
  for (const line of text.split('\n')) {
    const parts = line.split(/→|->|,|，|\s+/).map(part => part.trim()).filter(Boolean);
    if (!parts.length) continue;
    if (parts.length !== 2) throw new Error('知识约束每行应为一对变量：' + line);
    pairs.push(parts);
  }
  return pairs;
}

function pairsText(pairs) {
  return (pairs || []).map(pair => pair[0] + '→' + pair[1]).join('\n');
}

function prefillKnowledge() {
  const timed = study.variables.filter(variable => variable.time !== null && variable.time !== undefined)
    .sort((a, b) => a.time - b.time).map(variable => variable.name);
  const temporal = [];
  for (let index = 0; index + 1 < timed.length; index++) temporal.push([timed[index], timed[index + 1]]);
  for (const pair of (study.knowledge.temporal_order || [])) {
    if (!temporal.some(entry => entry[0] === pair[0] && entry[1] === pair[1])) temporal.push(pair);
  }
  document.getElementById('k-temporal').value = pairsText(temporal);
  document.getElementById('k-required').value = pairsText(study.knowledge.required);
  document.getElementById('k-forbidden').value = pairsText(study.knowledge.forbidden);
}

function renderExplorerControls() {
  const cohort = document.getElementById('cohort');
  cohort.replaceChildren();
  const all = document.createElement('option'); all.value = ''; all.textContent = '全部群体'; cohort.append(all);
  for (const name of summary.cohorts) {
    const option = document.createElement('option'); option.value = name; option.textContent = name; cohort.append(option);
  }
  const picker = document.getElementById('variable-picker');
  picker.replaceChildren();
  for (const variable of study.variables) {
    const label = document.createElement('label'); label.className = 'variable-option';
    const box = document.createElement('input'); box.type = 'checkbox'; box.value = variable.name; box.checked = true;
    label.append(box, document.createTextNode(variable.name)); picker.append(label);
  }
  document.getElementById('k-reset').addEventListener('click', prefillKnowledge);
  prefillKnowledge();
}

function collectDiscoveryRequest() {
  const variables = [...document.querySelectorAll('#variable-picker input:checked')].map(box => box.value);
  return {
    cohort: document.getElementById('cohort').value || null,
    variables,
    alpha: Number(document.getElementById('alpha').value),
    max_conditioning: Number(document.getElementById('max-cond').value),
    bootstrap: Number(document.getElementById('bootstrap').value),
    knowledge: {
      temporal_order: parsePairs(document.getElementById('k-temporal').value),
      required: parsePairs(document.getElementById('k-required').value),
      forbidden: parsePairs(document.getElementById('k-forbidden').value),
    },
  };
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function fmt(value, digits = 4) {
  return typeof value === 'number' ? Number(value.toFixed(digits)).toString() : '—';
}

function fmtP(value) {
  if (typeof value !== 'number') return '—';
  if (value === 0) return '<1e-300';
  return value < 1e-4 ? value.toExponential(2) : Number(value.toFixed(4)).toString();
}

function edgeKey(edge) { return [edge.left, edge.right].sort().join(' ↔ '); }

function stabilityFor(run, edge) {
  if (!run.stability) return null;
  const pairs = run.stability.pairs || {};
  return pairs[edge.left + ' ↔ ' + edge.right] || pairs[edge.right + ' ↔ ' + edge.left] || null;
}

function renderPopulation(run, container) {
  const banner = el('div', '', 'banner');
  banner.id = 'population-banner';
  const p = run.population;
  banner.append(
    el('strong', '观测集合：'),
    document.createTextNode(`群体 ${p.cohort === 'all' ? '全部' : p.cohort} · 变量 ${p.variables.join('、')} · ` +
      `完整记录 ${p.rows_used}/${p.rows_total} · 指纹 ${p.fingerprint}`),
    el('br'), el('span', p.rule, 'hint'));
  container.append(banner);
}

function renderTextList(container, title, items, className) {
  if (!items || !items.length) return;
  const box = el('div', '', className || 'note-list');
  box.append(el('h3', title));
  const list = document.createElement('ul');
  for (const item of items) list.append(el('li', typeof item === 'string' ? item : item.detail || JSON.stringify(item)));
  box.append(list);
  container.append(box);
}

const SVG_NS = 'http://www.w3.org/2000/svg';

function renderGraph(run, container) {
  const names = run.population.variables;
  const width = 680, height = 430, radius = 155, cx = width / 2, cy = height / 2 + 10;
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.id = 'structure-graph';
  const defs = document.createElementNS(SVG_NS, 'defs');
  const marker = document.createElementNS(SVG_NS, 'marker');
  marker.setAttribute('id', 'arrow');
  marker.setAttribute('viewBox', '0 0 10 10');
  marker.setAttribute('refX', '9'); marker.setAttribute('refY', '5');
  marker.setAttribute('markerWidth', '7'); marker.setAttribute('markerHeight', '7');
  marker.setAttribute('orient', 'auto-start-reverse');
  const tip = document.createElementNS(SVG_NS, 'path');
  tip.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
  marker.append(tip); defs.append(marker); svg.append(defs);
  const positions = {};
  names.forEach((name, index) => {
    const angle = -Math.PI / 2 + 2 * Math.PI * index / names.length;
    positions[name] = {x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle)};
  });
  const panel = el('div', '', 'edge-panel');
  panel.id = 'edge-evidence';
  panel.textContent = '点击图中的边，回看该关系的检验证据、定向依据与所需假设。';
  for (const edge of run.edges) {
    const a = positions[edge.left], b = positions[edge.right];
    const dx = b.x - a.x, dy = b.y - a.y;
    const length = Math.hypot(dx, dy) || 1;
    const shrink = 40;
    const x1 = a.x + dx * shrink / length, y1 = a.y + dy * shrink / length;
    const x2 = b.x - dx * shrink / length, y2 = b.y - dy * shrink / length;
    const group = document.createElementNS(SVG_NS, 'g');
    group.setAttribute('class', 'edge edge-' + edge.status + (edge.contested ? ' edge-contested' : ''));
    const line = document.createElementNS(SVG_NS, 'line');
    line.setAttribute('x1', x1); line.setAttribute('y1', y1);
    line.setAttribute('x2', x2); line.setAttribute('y2', y2);
    if (edge.status === 'directed' && edge.direction) {
      if (edge.direction[0] !== edge.left) {
        line.setAttribute('x1', x2); line.setAttribute('y1', y2);
        line.setAttribute('x2', x1); line.setAttribute('y2', y1);
      }
      line.setAttribute('marker-end', 'url(#arrow)');
    }
    const hit = document.createElementNS(SVG_NS, 'line');
    hit.setAttribute('x1', x1); hit.setAttribute('y1', y1);
    hit.setAttribute('x2', x2); hit.setAttribute('y2', y2);
    hit.setAttribute('class', 'edge-hit');
    const label = document.createElementNS(SVG_NS, 'text');
    label.setAttribute('x', (x1 + x2) / 2); label.setAttribute('y', (y1 + y2) / 2 - 6);
    label.setAttribute('class', 'edge-label');
    const stability = stabilityFor(run, edge);
    const parts = [];
    if (edge.status === 'undirected') parts.push('方向未定');
    if (edge.contested) parts.push('方向存争议');
    if (stability) parts.push(Math.round(stability.adjacency * 100) + '%');
    label.textContent = parts.join(' · ');
    group.append(line, hit, label);
    group.addEventListener('click', () => showEdgeEvidence(run, edge, panel));
    svg.append(group);
  }
  for (const name of names) {
    const group = document.createElementNS(SVG_NS, 'g');
    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', positions[name].x); circle.setAttribute('cy', positions[name].y);
    circle.setAttribute('r', 36); circle.setAttribute('class', 'node');
    const text = document.createElementNS(SVG_NS, 'text');
    text.setAttribute('x', positions[name].x); text.setAttribute('y', positions[name].y + 4);
    text.setAttribute('class', 'node-label'); text.textContent = name;
    group.append(circle, text); svg.append(group);
  }
  container.append(svg);
  const legend = el('p', '', 'legend');
  legend.append(
    el('span', '—— 有向（依据见边详情）', 'legend-directed'), document.createTextNode(' '),
    el('span', '—— 方向未定（仅确定相邻）', 'legend-undirected'), document.createTextNode(' '),
    el('span', '—— 冲突/存争议', 'legend-conflict'));
  container.append(legend, panel);
}

function reasonText(reason) {
  if (reason.kind === 'knowledge') return '提交知识 · ' + reason.detail;
  if (reason.kind === 'collider') return '统计证据 · ' + reason.detail;
  if (reason.kind === 'meek') return 'Meek 规则 R' + reason.rule + ' · ' + reason.detail;
  return JSON.stringify(reason);
}

function testsTable(tests) {
  const table = el('table', '', 'evidence-table');
  const head = table.createTHead().insertRow();
  for (const column of ['条件集', 'n', '偏相关 r', 'p', '判定', '备注']) head.append(el('th', column));
  const body = table.createTBody();
  for (const test of tests) {
    const row = body.insertRow();
    row.insertCell().textContent = test.conditioning.length ? test.conditioning.join('、') : '（无）';
    row.insertCell().textContent = test.n;
    row.insertCell().textContent = fmt(test.r);
    row.insertCell().textContent = fmtP(test.p);
    row.insertCell().textContent = {independent: '独立（删边）', dependent: '不独立', undefined: '无法检验'}[test.decision];
    row.insertCell().textContent = test.note || '';
  }
  return table;
}

function showEdgeEvidence(run, edge, panel) {
  panel.replaceChildren();
  const title = edge.status === 'directed'
    ? `${edge.direction[0]} → ${edge.direction[1]}（定向）`
    : `${edge.left} — ${edge.right}（方向未定，仅确定相邻）`;
  panel.append(el('h3', '关系详情：' + title));
  if (edge.contested) panel.append(el('p', '注意：不同碰撞点证据曾给出相反方向，该定向存争议。', 'conflict-text'));
  if (edge.oriented_by.length) {
    panel.append(el('h4', '定向依据'));
    const list = document.createElement('ul');
    for (const reason of edge.oriented_by) list.append(el('li', reasonText(reason)));
    panel.append(list);
  }
  if (edge.needs) {
    panel.append(el('h4', '定向所需的额外假设'));
    const list = document.createElement('ul');
    for (const need of edge.needs) list.append(el('li', need.assumption));
    panel.append(list);
  }
  const stability = stabilityFor(run, edge);
  if (stability) {
    panel.append(el('h4', '稳定程度（重抽样 ' + run.stability.replicates_used + ' 次）'));
    panel.append(el('p', `邻接出现 ${fmt(stability.adjacency, 2)} · ${edge.left}→${edge.right} ${fmt(stability.left_to_right, 2)} · ` +
      `${edge.right}→${edge.left} ${fmt(stability.right_to_left, 2)} · 方向未定 ${fmt(stability.undirected, 2)}`));
  }
  panel.append(el('h4', '检验证据（同一观测集合，n=' + run.population.rows_used + '）'));
  panel.append(testsTable(edge.evidence));
}

function renderRemoved(run, container) {
  if (!run.removed.length) return;
  container.append(el('h3', '被分离的关系（删边证据）'));
  const table = el('table', '', 'evidence-table');
  const head = table.createTHead().insertRow();
  for (const column of ['变量对', '分离集', '关键 p 值', '说明']) head.append(el('th', column));
  const body = table.createTBody();
  for (const removed of run.removed) {
    const separating = removed.evidence.find(test => test.decision === 'independent');
    const row = body.insertRow();
    row.insertCell().textContent = removed.left + ' — ' + removed.right;
    row.insertCell().textContent = removed.sepset.length ? removed.sepset.join('、') : '（空集）';
    row.insertCell().textContent = separating ? fmtP(separating.p) : '—';
    row.insertCell().textContent = separating ? '在该条件集下判定独立' : '见检验记录';
  }
  container.append(table);
}

function renderStability(run, container) {
  if (!run.stability) return;
  container.append(el('h3', '稳定程度（自助重抽样 ' + run.stability.replicates_used + '/' +
    run.stability.replicates_requested + ' 次成功）'));
  const table = el('table', '', 'evidence-table');
  const head = table.createTHead().insertRow();
  for (const column of ['变量对', '邻接频率', '正向频率', '反向频率', '方向未定频率']) head.append(el('th', column));
  const body = table.createTBody();
  for (const [pair, entry] of Object.entries(run.stability.pairs)) {
    const row = body.insertRow();
    row.insertCell().textContent = pair;
    row.insertCell().textContent = fmt(entry.adjacency, 2);
    row.insertCell().textContent = fmt(entry.left_to_right, 2);
    row.insertCell().textContent = fmt(entry.right_to_left, 2);
    row.insertCell().textContent = fmt(entry.undirected, 2);
  }
  container.append(table);
}

function renderCandidates(run, container) {
  container.append(el('h3', '与资料和知识相容的候选结构（' + run.candidates.list.length + ' 个）'));
  if (run.candidates.note) container.append(el('p', run.candidates.note, 'hint'));
  if (!run.candidates.list.length && !run.candidates.note) {
    container.append(el('p', '当前约束下没有完全一致的候选，请查看冲突列表。', 'conflict-text'));
    return;
  }
  const list = document.createElement('ol');
  for (const candidate of run.candidates.list) list.append(el('li', candidate.join('，')));
  container.append(list);
}

function renderRun(run, container, savedMeta) {
  container.replaceChildren();
  if (savedMeta) {
    container.append(el('p', '已保存快照 · ' + savedMeta.created_at + ' · ' + savedMeta.purpose, 'hint'));
  }
  renderPopulation(run, container);
  if (run.status !== 'ok') {
    renderTextList(container, '无法给出结构候选', run.notices, 'conflict-list');
    return;
  }
  renderTextList(container, '冲突（发布前需处理）',
    (run.conflicts || []).map(conflict => conflict.detail || conflict.kind), 'conflict-list');
  renderTextList(container, '提示', run.notices, 'note-list');
  renderTextList(container, '本次解释所依赖的假设', run.assumptions, 'note-list');
  renderGraph(run, container);
  renderCandidates(run, container);
  renderStability(run, container);
  renderRemoved(run, container);
  const details = el('details');
  details.append(el('summary', '全部检验记录（' + run.tests.length + ' 次，均来自同一观测集合）'));
  details.append(testsTable(run.tests));
  container.append(details);
  container.append(el('p', run.scope, 'hint'));
}

function renderSaveControls(container) {
  const box = el('div', '', 'save-box');
  const input = el('input');
  input.type = 'text'; input.id = 'graph-note'; input.maxLength = 2000;
  input.placeholder = '给这次快照留一句讨论备注（可选）';
  const button = el('button', '保存此图供实验设计讨论');
  button.id = 'save-graph';
  button.addEventListener('click', async () => {
    try {
      await api('/api/graphs', {run: currentRun, note: input.value || null});
      input.value = '';
      await refreshGraphs();
    } catch (error) {
      alert('保存失败：' + error.message);
    }
  });
  box.append(input, button, el('span', '保存的是图快照与其观测集合指纹，供后续实验设计讨论，不构成学生个人决策依据。', 'hint'));
  container.append(box);
}

async function runDiscovery() {
  const container = document.getElementById('discovery-result');
  let request;
  try { request = collectDiscoveryRequest(); }
  catch (error) { container.replaceChildren(el('p', error.message, 'conflict-text')); return; }
  container.replaceChildren(el('p', '检验中……'));
  try {
    currentRun = await api('/api/discovery', request);
  } catch (error) {
    currentRun = null;
    container.replaceChildren(el('p', '无法完成探索：' + error.message, 'conflict-text'));
    return;
  }
  renderRun(currentRun, container);
  if (currentRun.status === 'ok') renderSaveControls(container);
}

async function refreshGraphs() {
  const result = await api('/api/graphs');
  const holder = document.getElementById('graphs');
  holder.replaceChildren();
  for (const entry of result.graphs) {
    const item = document.createElement('li');
    const p = entry.population;
    item.append(el('span', `${entry.created_at} · 群体 ${p.cohort === 'all' ? '全部' : p.cohort} · ` +
      `完整记录 ${p.rows_used}/${p.rows_total} · 指纹 ${p.fingerprint} · 边 ${entry.summary.edges}` +
      `（定向 ${entry.summary.directed} / 未定 ${entry.summary.undirected}）· 冲突 ${entry.summary.conflicts}` +
      (entry.note ? ' · 备注：' + entry.note : '')));
    const view = el('button', '查看');
    view.addEventListener('click', () => {
      const target = document.getElementById('saved-view');
      renderRun(entry.run, target, entry);
      target.scrollIntoView({behavior: 'smooth'});
    });
    item.append(document.createTextNode(' '), view);
    holder.append(item);
  }
  if (!result.graphs.length) holder.append(el('li', '尚未保存任何图'));
}

async function start() {
  study = await api('/api/study');
  summary = await api('/api/summary');
  display('summary', summary);
  const selector = document.getElementById('source');
  for (const source of sources) {
    const option = document.createElement('option'); option.value = source; option.textContent = source; selector.append(option);
  }
  selector.addEventListener('change', () => renderTable(selector.value));
  renderTable(sources[0]); renderControls();
  renderExplorerControls();
  document.getElementById('run-discovery').addEventListener('click', runDiscovery);
  document.getElementById('note-form').addEventListener('submit', async event => {
    event.preventDefault();
    const field = document.getElementById('note');
    try { await api('/api/notes', {text: field.value, selection: latestRequest}); field.value = ''; await refreshNotes(); }
    catch (error) { display('result', {error: error.message}); }
  });
  await refreshNotes();
  await refreshGraphs();
}

start().catch(error => display('summary', {error: error.message}));
