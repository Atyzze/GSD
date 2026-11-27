

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const rejections = [];
process.on('unhandledRejection', (reason) => rejections.push(reason));
const uiDir = process.argv[2];
const LATTICE_WHO = JSON.parse(require('child_process').execFileSync(process.env.GSD_PYTHON || 'python3',
  ['-c', 'import json\nfrom graph_scale_dynamics.services.api.law_order import LATTICE_WHO\nprint(json.dumps(list(LATTICE_WHO)))'],
  { cwd: path.resolve(__dirname, '..', '..'), encoding: 'utf8' }));
const bootPath = process.argv[3] || '/';

function makeClassList() {
  const set = new Set();
  return { add: (c) => set.add(c), remove: (c) => set.delete(c),
           contains: (c) => set.has(c), toggle: (c) => set.has(c) ? set.delete(c) : set.add(c) };
}

function makeStyle() {
  const properties = new Map();
  return {
    setProperty: (name, value) => properties.set(name, String(value)),
    getPropertyValue: (name) => properties.get(name) || '',
    removeProperty: (name) => properties.delete(name),
    get customPropertyCount() { return properties.size; },
  };
}

function makeElement(id) {
  const listeners = {};
  const element = {
    id, dataset: {}, style: makeStyle(), classList: makeClassList(),
    innerHTML: '', textContent: '', children: [], clientWidth: 900, clientHeight: 400,
    width: 900, height: 400,
    get offsetHeight() { return element.getBoundingClientRect().height; },
    get offsetWidth() { return element.getBoundingClientRect().width; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener() {},
    dispatch(type, event) { (listeners[type] || []).forEach((fn) => fn(event || {})); },
    rectWidth: 900, rectHeight: 400,
    getBoundingClientRect: () => ({ width: element.rectWidth, height: element.rectHeight,
                                    left: 0, top: 0 }),
    querySelector: () => null, querySelectorAll: () => [],
    getContext: () => new Proxy({}, {
      get: (_, prop) => (prop === 'canvas' ? element
                        : prop === 'measureText' ? () => ({ width: 10 })
                        : () => undefined),
    }),
  };
  return withTree(element);
}

function serialize(node) {
  const tag = String(node.tagName || 'div').toLowerCase();
  const attrs = Object.entries(node.attributes).map(([k, v]) => ` ${k}="${v}"`).join('');
  const data = Object.entries(node.dataset || {}).map(([k, v]) => ` data-${k}="${v}"`).join('');
  return `<${tag}${attrs}${data}>${node.innerHTML}</${tag}>`;
}
function withTree(element) {
  let html = '';
  element.tagName = String(element.id || 'div').toUpperCase();
  element.attributes = {};
  element.childNodes = [];
  element.parentNode = null;
  element.classWrites = 0;
  Object.defineProperty(element, 'children', { get: () => element.childNodes });
  Object.defineProperty(element, 'innerHTML', {
    get: () => (element.childNodes.length ? element.childNodes.map(serialize).join('') : html),
    set: (value) => { element.childNodes.forEach((c) => { c.parentNode = null; });
                      element.childNodes = []; html = String(value); recordLayout(element, html); },
  });
  Object.defineProperty(element, 'className', {
    get: () => element.attributes.class || '',
    set: (value) => { element.classWrites += 1; element.attributes.class = String(value); },
  });
  Object.defineProperty(element, 'isConnected', { get: () => true });
  element.setAttribute = (k, v) => { element.attributes[k] = String(v); };
  element.getAttribute = (k) => (k in element.attributes ? element.attributes[k] : null);
  element.removeChild = (child) => {
    element.childNodes = element.childNodes.filter((c) => c !== child);
    child.parentNode = null;
    return child;
  };
  element.insertBefore = (child, ref) => {
    if (child.parentNode) child.parentNode.removeChild(child);
    const at = ref ? element.childNodes.indexOf(ref) : -1;
    if (at < 0) element.childNodes.push(child); else element.childNodes.splice(at, 0, child);
    child.parentNode = element;
    return child;
  };
  element.appendChild = (child) => element.insertBefore(child, null);
  element.append = (...kids) => kids.forEach((k) => { if (k && typeof k === 'object') element.appendChild(k); });
  element.remove = () => { if (element.parentNode) element.parentNode.removeChild(element); };
  return element;
}

const elements = new Map();
const layoutDump = process.env.GSD_LAYOUT_DUMP ? new Map() : null;
function recordLayout(element, html) {
  if (!layoutDump || elements.get(element.id) !== element || !html.includes('<table')) return;
  const kept = layoutDump.get(element.id) || [];
  if (kept.length < 6 && !kept.includes(html)) kept.push(html);
  layoutDump.set(element.id, kept);
}
function getElementById(id) {
  if (!elements.has(id)) elements.set(id, makeElement(id));
  return elements.get(id);
}

const documentStub = {
  getElementById,
  createElement: (tag) => makeElement(tag),
  createElementNS: (ns, tag) => makeElement(tag),
  addEventListener() {}, removeEventListener() {},
  documentElement: makeElement('html'),
  body: makeElement('body'),
  querySelector: () => null, querySelectorAll: () => [],
  title: '', readyState: 'complete',
  scripts: [{ src: 'http://127.0.0.1:8765/assets/system.js?v=209' }],
};

const windowListeners = {};
const resizeObservers = [];

const sandbox = {
  console,
  setTimeout: () => 0, clearTimeout: () => {},
  setInterval: () => 0, clearInterval: () => {},
  Math, Date, JSON, Number, String, Array, Object, Boolean, Error, RangeError,
  Set, Map, Intl, isNaN, isFinite, parseFloat, parseInt, encodeURIComponent,
  URLSearchParams, URL, TextEncoder, TextDecoder, structuredClone,
  decodeURIComponent, Promise, devicePixelRatio: 1,
  document: documentStub,
  location: { href: 'http://127.0.0.1:8765' + bootPath, pathname: bootPath, search: '', hash: '' },
  history: { pushState() {}, replaceState() {} },
  requestAnimationFrame: (fn) => { fn(0); return 1; },
  cancelAnimationFrame: () => {},
  fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}),
                                 text: () => Promise.resolve('') }),
  getComputedStyle: () => ({ getPropertyValue: () => '#123456' }),
  addEventListener(type, fn) { (windowListeners[type] = windowListeners[type] || []).push(fn); },
  removeEventListener(type, fn) {
    windowListeners[type] = (windowListeners[type] || []).filter((x) => x !== fn);
  },
  dispatchEvent(event) {
    (windowListeners[event && event.type] || []).forEach((fn) => fn(event));
    return true;
  },
  scrollTo() {}, scrollBy() {}, alert() {}, matchMedia: () => ({ matches: false,
    addEventListener() {}, removeEventListener() {} }),
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } },
  Event: class { constructor(type) { this.type = type; } },
  ResizeObserver: class {
    constructor(callback) { this.callback = callback; resizeObservers.push(this); }
    observe(element) { this.element = element; }
    unobserve() {} disconnect() {}
  },
  GSD_UI_CONFIG: { basePath: '', buildNumber: '209', runtimeFingerprint: 'test',
                    runtimeShort: 'test', homeHref: '/' },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

function load(name) {
  const source = fs.readFileSync(path.join(uiDir, name), 'utf8');
  vm.runInContext(source, sandbox, { filename: name });
}

function liveLaw(id) {
  const root = getElementById('live');
  const grid = root.children.find((c) => /live-grid/.test(c.className));
  const body = grid && grid.children.find((c) => /live-body/.test(c.className));
  return body ? body.children.find((c) => c.dataset.law === id) : undefined;
}
function liveLeases(id) {
  const law = liveLaw(id);
  return law && law.children.find((c) => /live-leases/.test(c.className));
}

const failures = [];
function check(label, fn) {
  try { fn(); } catch (error) { failures.push(`${label}: ${error && error.message}`); }
}

check('load system.js', () => load('system.js'));
check('load term_visual.js', () => load('term_visual.js'));
check('load map.js', () => load('map.js'));
check('load selection.js', () => load('selection.js'));
check('load app.js', () => load('app.js'));

if (bootPath !== '/') {
  setImmediate(() => setImmediate(() => {
    for (const error of rejections) {
      failures.push(`boot at ${bootPath}: unhandled rejection: ${error && error.message}`);
    }
    if (failures.length) {
      console.log('FAIL');
      failures.forEach((line) => console.log(line));
      process.exit(1);
    }
    console.log('OK');
    process.exit(0);
  }));
}

check('GSD_SYSTEM exported', () => {
  if (!sandbox.GSD_SYSTEM) throw new Error('window.GSD_SYSTEM is missing');
  for (const fn of ['registerLiveRegion', 'deferrableRedraw', 'setPinned',
                    'getPinned', 'localTime', 'localTimeHtml']) {
    if (typeof sandbox.GSD_SYSTEM[fn] !== 'function') throw new Error(`missing ${fn}`);
  }
});

check('deferrableRedraw does not invoke redraw inline', () => {
  const { deferrableRedraw } = sandbox.GSD_SYSTEM;
  const element = makeElement('probe');
  let invoked = 0;
  const deferred = deferrableRedraw(element, () => { invoked += 1; });
  if (deferred !== false) throw new Error('should not defer when not hovering');
  if (invoked !== 0) throw new Error('redraw was invoked on the inline path: recursion risk');
});

check('deferrableRedraw defers and replays while hovering', () => {
  const { registerLiveRegion, deferrableRedraw } = sandbox.GSD_SYSTEM;
  const element = makeElement('probe2');
  registerLiveRegion(element);
  element.dispatch('pointerenter');
  let invoked = 0;
  const deferred = deferrableRedraw(element, () => { invoked += 1; });
  if (deferred !== true) throw new Error('should defer while hovering');
  if (invoked !== 0) throw new Error('deferred redraw ran early');
  element.dispatch('pointerleave');
  if (invoked !== 1) throw new Error('deferred redraw was not replayed on exit');
});

check('a time is shown in the viewer zone with the UTC original behind it, and a naive one is UTC', () => {
  const { localTimeHtml, parseUtc } = sandbox.GSD_SYSTEM;
  const html = localTimeHtml('2026-11-03T12:11:51Z');
  if (!/class="local-time"/.test(html) || !html.includes('title="2026-11-03T12:11:51Z (UTC)"')) {
    throw new Error(`the local time does not keep its UTC original: ${html}`);
  }
  const naive = parseUtc('2026-11-03 12:11:51'), marked = parseUtc('2026-11-03T12:11:51Z');
  if (!naive || naive.getTime() !== marked.getTime()) throw new Error('a timestamp without a zone was read as local');
  if (localTimeHtml(null) !== '—') throw new Error('an absent time is not a dash');
});

check('a hovered live region keeps its tooltip while the pointer rests and is redrawn once it moves (2026-11-14)', () => {
  const { registerLiveRegion, deferrableRedraw } = sandbox.GSD_SYSTEM;
  const element = makeElement('probe3');
  registerLiveRegion(element);
  element.dispatch('pointerenter');
  let drawn = 0;
  if (deferrableRedraw(element, () => { drawn += 1; }) !== true) throw new Error('should defer while hovering');
  if (deferrableRedraw(element, () => { drawn += 10; }) !== true) throw new Error('a later poll should defer as well');
  if (drawn) throw new Error('a resting pointer let a poll redraw the region and close its tooltip');
  element.dispatch('pointermove');
  if (drawn !== 10) throw new Error(`the pointer moved and the newest poll was not drawn, once: ${drawn}`);
  element.dispatch('pointermove');
  if (drawn !== 10) throw new Error('a redraw was replayed twice');
});

function campaignsPayload(empty) {
  return {
    contract: 'gsd-campaign-manager-1', reporting_campaign_id: '1', fleet_paused: false,
    worker_pool: 32,
    reading: 'laws at a rung counts every law bought into it',
    terms: [
      {op: 'degree_square_sum', cost: 1, group: 'degree_sequence', defines_sparse_phase: true, reduces_to: []},
      {op: 'degree_anchor', cost: 1, group: 'degree_sequence', defines_sparse_phase: true,
       reduces_to: ['degree_square_sum', 'edge_count']},
      {op: 'triangle_count', cost: 2, group: 'topology', defines_sparse_phase: false, reduces_to: []},
    ],
    campaigns: empty ? [] : [{
      campaign_id: '2', name: 'engine_survey', status: 'active', state: 'paused',
      created_utc: '2026-09-20T09:00:00Z', mode: 'continuous', campaign_role: 'discovery',
      parent_campaign_id: '1', term_count: 3,
      terms: ['degree_square_sum', 'edge_count', 'triangle_count'],
      temperature: 'zero', mean_degree_window: {min: 0, max: 32}, complexity_budget: 7,
      grid: {magnitudes: {min: 0.05, max: 2, spacing: 'log'}, betas: {min: 0.1, max: 100, spacing: 'log'},
             scales: ['one', 'log_N'], signs: [-1, 1], term_counts: [1, 2, 3], zero_temperature: [true],
             localities: {min: 0, max: 0.99, spacing: 'linear'}, local_moves: ['toggle'],
             per_term: {edge_count: {magnitudes: {min: 0.5, max: 1.5}, signs: [-1]}}},
      laws_total: 41, held: 7, deepest_n: 262144, deepest_laws: 3,
      workers_target: 8, worker_share: 8, slots_held: 8, work_queued: 412,
      core_seconds: 90000, compute_hours: 25.0,
      stopped_by_rule: [{rule: 'empty', laws: 8, example: 'mean degree at most 0.05 at every rung through N=256'},
                        {rule: 'too_dense', laws: 6, example: 'mean degree 16.01 at N=256, at the cap of 16'},
                        {rule: 'disconnected', laws: 3, example: 'largest component 0.004 of the graph at N=1024'}],
      laws_stopped: 17,
      high_score: {score: 63.5, candidate_id: 'abc123', max: 100,
                   generated_utc: '2026-09-20T10:00:00Z'},
      rungs: [{n: 4096, laws: 41, measured: 40, ceiling: 30},
              {n: 65536, laws: 9, measured: 8, ceiling: 70},
              {n: 262144, laws: 3, measured: 2, ceiling: 90}],
      top_rungs: [{n: 262144, laws: 3, measured: 2, ceiling: 90},
                  {n: 65536, laws: 9, measured: 8, ceiling: 70},
                  {n: 4096, laws: 41, measured: 40, ceiling: 30}],
      laws_by_state: {STOPPED: 30, HELD: 7, EXTENDING: 4},
      science_contract_hash: 'abc123def4567890',
      controls: {pause: false, resume: true, reopen: false, reopen_problems: [], use: false,
                 clone: true, delete: false, archive: false, workers: true},
    }],
  };
}

check('the campaigns table shows the high score, the compute hours and each rung ceiling', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(campaignsPayload(false));
  const html = host.innerHTML;
  if (!html.includes('63.5')) throw new Error('the high score from the landscape is not on the row');
  if (!html.includes('25h')) throw new Error('the compute hours are not on the row');
  if (!html.includes('regime-zero_temperature')) throw new Error('the temperature is not on the row');
  if (!html.includes('0 to 32')) throw new Error('the mean-degree window is not on the row');
  if (html.includes('>deepest N<')) throw new Error('the deepest N column is still drawn');
  if (html.includes('N=262144')) throw new Error('the rung ladder is still in the table; it belongs in the panel');
});

check('the campaigns page says the work left and when it is done, per campaign and for the study', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  const payload = campaignsPayload(false);
  payload.campaigns[0].work_left = {graphs_queued: 412, queued_by_n: {'4096': 400, '65536': 12}, queued_core_hours: 5.2,
    laws_to_budget: 3169, core_hours_a_law: 0.0209, laws_core_hours: 66.2, analysis_ratio: 0.25, core_hours_left: 89.3,
    cores_last_hour: 6.2, hours_at_last_hours_pace: 14.4, share_cores: 8, hours_at_fair_share: 11.2,
    unpriced_rungs: [1048576], rungs_priced_at_a_floor: [], at_least: true, laws_climbing: 3};
  payload.work_left = {campaigns: 2, core_hours_left: 250.5, cores_last_hour: 20, hours_at_last_hours_pace: 12.5,
    hours_at_the_whole_pool: 7.8, pool: 32, at_least: true};
  sandbox.GSD_APP.renderCampaigns(payload);
  const html = String(host.innerHTML);
  if (!html.includes('<b>412</b> graphs queued')) throw new Error('the graphs queued are not drawn');
  if (!html.includes('3 laws still climbing') || !html.includes('so this count can rise again')) {
    throw new Error('the laws still climbing, and why the queue refills, are not said');
  }
  if (!/<td class="work"><div class="work-left"/.test(html)) throw new Error('the work left is not its own column');
  if (!html.includes('>work left</th>')) throw new Error('the work left column has no heading');
  if (!html.includes('&ge;89.3 core-h left') || !html.includes('&ge;14.4 h &middot; last hour')) throw new Error('the work left is not drawn');
  if (!html.includes('&ge;11.2 h &middot; a fair share')) throw new Error('the fair-share time is not drawn');
  if (!html.includes('3,169 laws to the budget') || !html.includes('N=1,048,576')) throw new Error('its reasons are not on hover');
  if (!html.includes('the study: &ge;250.5 core-hours left in 2 campaign(s)')) throw new Error('the study total is missing');
  if (/with the sizes to come/.test(html)) throw new Error('a payload with no expected work says nothing of the sizes to come');
  Object.assign(payload.campaigns[0].work_left, {core_hours_expected: 131.4, hours_expected_at_last_hours_pace: 21.2,
    sizes_to_come_core_hours: 42.1});
  Object.assign(payload.work_left, {core_hours_expected: 673.2, hours_expected_at_last_hours_pace: 33.7});
  sandbox.GSD_APP.renderCampaigns(payload);
  const withSizes = String(host.innerHTML);
  if (!withSizes.includes('&ge;89.3 core-h left') || !withSizes.includes('about 131.4 core-h with the sizes to come')) {
    throw new Error('839: the queued work keeps its line and the sizes the climbing laws are expected to buy stand under it');
  }
  if (!withSizes.includes('about 673.2 core-hours with the sizes to come, 33.7 h at the last hour')) {
    throw new Error(`839: the study line does not carry the expected work: ${withSizes.slice(withSizes.indexOf('the study:'), withSizes.indexOf('the study:') + 400)}`);
  }
  payload.campaigns[0].work_left = {graphs_queued: 0, laws_to_budget: 0};
  payload.work_left = {campaigns: 0};
  sandbox.GSD_APP.renderCampaigns(payload);
  if (!String(host.innerHTML).includes('nothing queued')) throw new Error('a campaign with nothing left does not say so');
  if (String(host.innerHTML).includes('the study:')) throw new Error('a study total with nothing at work is drawn');
});

check('every rule that stopped a law is shown (545, M)', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  const payload = campaignsPayload(false);
  payload.campaigns[0].stopped_by_rule = ['empty', 'too_dense', 'disconnected', 'no_reading', 'over_budget', 'failed',
    'no_finite_dimension'].map((rule, i) => ({ rule, laws: 5379 - i, example: rule }));
  sandbox.GSD_APP.renderCampaigns(payload);
  const html = String(host.innerHTML);
  for (const rule of ['empty', 'too dense', 'disconnected', 'no reading', 'over budget', 'failed', 'no finite dimension'])
    if (!html.includes(`>${rule} <b>`)) throw new Error(`the rule ${rule} is not shown`);
  if (!html.includes('<b>5,379</b>')) throw new Error('a count is not written with its thousands');
});

check('a campaign with no landscape shows no score rather than a zero', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  const payload = campaignsPayload(false);
  payload.campaigns[0].high_score = null;
  sandbox.GSD_APP.renderCampaigns(payload);
  if (host.innerHTML.includes('>0</b>')) throw new Error('an unscored campaign renders as a zero score');
});

check('a surveyed campaign says so instead of looking idle', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  const payload = campaignsPayload(false);
  payload.campaigns[0].state = 'surveyed';
  payload.campaigns[0].surveyed = {held: 23, pool_min: 32, reading: 'every law this term set can write is proposed'};
  sandbox.GSD_APP.renderCampaigns(payload);
  const html = host.innerHTML;
  if (!html.includes('surveyed')) throw new Error('the surveyed state is not rendered');
  if (!html.includes('all 23 laws proposed')) throw new Error('the surveyed row does not say how many laws it holds');
});

check('the campaigns row carries every term and merges its state with its control', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  const payload = campaignsPayload(false);
  payload.campaigns[0].terms = ['degree_square_sum','edge_count','triangle_count','square_count',
                                'wedge_count','degree_anchor','degree_cube_sum'];
  payload.campaigns[0].term_count = 7;
  sandbox.GSD_APP.renderCampaigns(payload);
  const html = String(host.innerHTML);
  const chips = (html.match(/class="term-chip"/g) || []).length;
  if (chips < 7) throw new Error('the term set is truncated; every term has to be shown');
  if (!/<td class="state">[\s\S]*?data-action="resume"/.test(html))
    throw new Error('the control is not inside the state cell');
});

check('the campaigns table shows the term set and what stopped the laws', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(campaignsPayload(false));
  const html = String(host.innerHTML);
  if (!html.includes('degree_square_sum') && !html.includes('\u03a3d\u00b2')) throw new Error('the term set is not shown');
  if (!html.includes('too dense')) throw new Error('what stopped the laws is not shown');
  if (!html.includes('empty')) throw new Error('the second stop rule is not shown');
  if (/data-action="pause"/.test(html)) throw new Error('pause drawn on a paused campaign');
  if (!/data-action="resume"/.test(html)) throw new Error('resume not offered on a paused campaign');
  if (/data-action="reopen"/.test(html)) throw new Error('reopen drawn on a campaign that is not closed');
  if (html.includes('data-action="delete"')) throw new Error('the page offers to delete a campaign');
  if (html.includes('data-action="archive"')) throw new Error('the page offers to archive a campaign');
  if (!html.includes('paused')) throw new Error('the paused state is not named');
});

check('a share of the fleet is editable and says what it is holding', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(campaignsPayload(false));
  const html = String(host.innerHTML);
  if (!html.includes('data-share="2"')) throw new Error('the share is not editable');
  if (!/value="8"/.test(html)) throw new Error('the share does not show its current value');
  if (!html.includes('8 held')) throw new Error('slots held against the share are not shown');
  if (!html.includes('412 queued')) throw new Error('queued work is not shown beside the share');
});

check('the fleet control lives on the page and says what it costs', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(campaignsPayload(false));
  const html = String(host.innerHTML);
  if (!html.includes('data-fleet="fleet_pause"')) throw new Error('no fleet control on the page');
  if (!html.includes('campaignFence')) throw new Error('the fast-pause choice is not offered');
  if (!html.includes('start again')) throw new Error('the cost of stopping the fleet is not stated');
});

check('a campaign still saving its chains reads as pausing, not as a hang', () => {
  const payload = campaignsPayload(false);
  payload.campaigns[0].state = 'pausing';
  payload.campaigns[0].slots_held = 12;
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(payload);
  const html = String(host.innerHTML);
  if (!html.includes('pausing')) throw new Error('the pausing state is not shown');
  if (!html.includes('12 chain(s) saving')) throw new Error('nothing says why it is taking time');
});

check('a pause waiting on analyses says so, not that chains are saving', () => {
  const payload = campaignsPayload(false);
  payload.campaigns[0].state = 'pausing';
  payload.campaigns[0].slots_held = 0;
  payload.campaigns[0].analyses_running = 8;
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(payload);
  const html = String(host.innerHTML);
  if (!html.includes('8 analyses finishing')) throw new Error('the analyses still running are not named');
  if (html.includes('0 chain(s) saving')) throw new Error('a pause with no chains left says chains are saving');
});

check('a campaign row counts its laws by meeting reading (513)', () => {
  const payload = campaignsPayload(false);
  payload.campaigns[0].meeting_readings = { agreeing: 40, frozen: 3, disagreeing_while_moving: 2 };
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(payload);
  const html = String(host.innerHTML);
  if (!/agree <b>40<\/b>/.test(html) || !/frozen <b>3<\/b>/.test(html) || !/disagreeing <b>2<\/b>/.test(html)) {
    throw new Error('the meeting readings are not counted on the row');
  }
});

check('every Campaigns heading has a cell under it', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(campaignsPayload(false));
  const html = String(host.innerHTML);
  const heads = (html.match(/<th[ >]/g) || []).length;
  const firstRow = html.split('<tbody>')[1].split('</tr>')[0];
  const cells = (firstRow.match(/<td[ >]/g) || []).length;
  if (heads !== cells) throw new Error(`${heads} headings over ${cells} cells`);
});

check('an empty folder says so rather than drawing an empty table', () => {
  const host = sandbox.document.getElementById('campaignsBody');
  sandbox.GSD_APP.renderCampaigns(campaignsPayload(true));
  const html = String(host.innerHTML);
  if (!html.includes('no campaign has been created')) throw new Error('empty state not stated');
  if (html.includes('<table')) throw new Error('an empty table was drawn as though it were a reading');
});

check('the author marks a term that is exactly other terms', () => {
  const payload = campaignsPayload(false);
  sandbox.GSD_APP.campaignsData = payload;
  sandbox.GSD_APP.renderCampaigns(payload);
  sandbox.GSD_APP.openCampaignAuthor(payload.campaigns[0].campaign_id);
  sandbox.GSD_APP.renderCampaignAuthor();
  const host = sandbox.document.getElementById('campaignAuthor');
  const html = String(host.innerHTML || '');
  if (!html.includes('degree_square_sum')) throw new Error('the term catalogue is not offered');
  if (!html.includes('= a + b')) throw new Error('a term that is exactly other terms is not marked');
});

check('the author renders the founder Hamiltonian term by term', () => {
  const payload = campaignsPayload(false);
  payload.campaigns[0].terms = ['edge_count', 'degree_square_sum'];
  payload.campaigns[0].grid = {scales: ['one'], magnitudes: [0.05, 0.1, 0.2], signs: [-1, 1], betas: [1, 10]};
  sandbox.GSD_APP.campaignsData = payload;
  sandbox.GSD_APP.renderCampaigns(payload);
  sandbox.GSD_APP.openCampaignAuthor(payload.campaigns[0].campaign_id);
  sandbox.GSD_APP.authorGrid = {betas: [100], per_term: {
    edge_count: {magnitudes: [1], signs: [-1], scales: ['one']},
    degree_square_sum: {magnitudes: {min: 0.015, max: 0.2, spacing: 'log'}, signs: [1]}}};
  sandbox.GSD_APP.renderCampaignAuthor();
  const html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('per-term-table')) throw new Error('the term rows are not drawn');
  if (html.indexOf('<h3>Terms</h3>') > html.indexOf('<h3>Temperature</h3>'))
    throw new Error('the term rows must come before the shared grid, not after it');
  if (!html.includes('data-rf-part="term:degree_square_sum|min"') || !html.includes('value="0.015"'))
    throw new Error('a term\'s own range is not shown as a min field');
  if (!html.includes('data-rf-part="term:degree_square_sum|max"') || !html.includes('value="0.2"'))
    throw new Error('a term\'s own range is not shown as a max field');
  if (!html.includes('data-rf-spacing="term:degree_square_sum|log"')) throw new Error('a term\'s range has no spacing choice');
  if (!html.includes('value="the shipped defaults') && !html.includes('<option value="defaults"'))
    throw new Error('the author does not offer the shipped defaults as a starting point');
  if (!html.includes('inverse temperature')) throw new Error('beta is not explained as a temperature');
  if (!html.includes('every selected term sets its own magnitude'))
    throw new Error('the unused defaults are not called unused');
  if (!html.includes('data-tc="min|') || !html.includes('data-tc="max|'))
    throw new Error('terms per law is not a min and a max');
  if (!html.includes('leave some of your selected terms out'))
    throw new Error('a founder campaign drawing one-term laws must say so');
});

check('the author sets a law\'s dynamics and says which regimes it will draw', () => {
  const payload = campaignsPayload(false);
  payload.campaigns[0].terms = ['edge_count', 'degree_square_sum'];
  payload.campaigns[0].grid = {scales: ['one'], magnitudes: [0.05, 0.1, 0.2], signs: [-1, 1], betas: [1, 10]};
  sandbox.GSD_APP.campaignsData = payload;
  sandbox.GSD_APP.renderCampaigns(payload);
  sandbox.GSD_APP.openCampaignAuthor(payload.campaigns[0].campaign_id);
  sandbox.GSD_APP.authorGrid = {};
  sandbox.GSD_APP.renderCampaignAuthor();
  let html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('<h3>Dynamics</h3>')) throw new Error('there is no dynamics section');
  if (!html.includes('every move is global')) throw new Error('locality off does not say what it means');
  if (html.includes('data-local-move=')) throw new Error('the local move is offered with no local moves');
  if (!html.includes('<b>equilibrium</b>')) throw new Error('the default is not called equilibrium');
  sandbox.GSD_APP.authorGrid = {localities: {min: 0, max: 0.99, spacing: 'linear'},
                                local_moves: ['toggle'], zero_temperature: [false, true]};
  sandbox.GSD_APP.renderCampaignAuthor();
  html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('data-rf-part="grid:localities|max"') || !html.includes('value="0.99"'))
    throw new Error('the locality range is not a min and a max');
  if (html.includes('data-local-move=')) throw new Error('a local move is offered, and the toggle is the only one');
  if (html.includes('add_only') || html.includes('driven')) throw new Error('the move taken out at 774 is offered');
  if (!html.includes('data-zero-t="true"')) throw new Error('zero temperature is not offered');
  if (!html.includes('<b>equilibrium, zero temperature</b>')) throw new Error('the regimes drawn are not named');
  if (!html.includes('data-rf-mode="grid:swap_shares|off"') || !html.includes('>fixed<'))
    throw new Error('the swap share has no mode that keeps the campaign\'s move mix');
  if (!html.includes('15% swaps')) throw new Error('the fixed swap share does not say what it is');
  if (!html.includes('data-grid-sign="positive"')) throw new Error('the default sign cannot be set');
  if (!html.includes('data-rf-mode="grid:power_exponents|range"')) throw new Error('the power exponent cannot be set');
  if (!html.includes('data-rf-mode="grid:anchor_k|range"')) throw new Error('anchor k cannot be set');
  sandbox.GSD_APP.authorGrid = {swap_shares: [0], zero_temperature: [true]};
  sandbox.GSD_APP.renderCampaignAuthor();
  html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('data-rf-part="grid:swap_shares|list"') || !html.includes('value="0"'))
    throw new Error('a swap share of 0 is not shown as a value');
  if (!html.includes('<b>zero temperature</b>')) throw new Error('a zero-temperature selection is not named');
});

check('the author sets the mean-degree window beside the temperature', () => {
  const payload = campaignsPayload(false);
  sandbox.GSD_APP.campaignsData = payload;
  sandbox.GSD_APP.renderCampaigns(payload);
  sandbox.GSD_APP.openCampaignAuthor(payload.campaigns[0].campaign_id);
  sandbox.GSD_APP.authorCheck = {status: 'PASS', grid: {}, mean_degree_window: {min: 0, max: 16, dense_cap: 16,
                                                                               armed_from_n: 256}};
  sandbox.GSD_APP.authorWindow = null;
  sandbox.GSD_APP.renderCampaignAuthor();
  let html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('<h3>Mean degree</h3>')) throw new Error('there is no mean-degree window on the form');
  if (!html.includes('data-window="min"') || !html.includes('data-window="max"') || !html.includes('value="16"'))
    throw new Error('the window is not two fields showing the starting point\'s');
  if (!html.includes('armed from N = 256')) throw new Error('the form does not say where the cap is armed');
  if (html.indexOf('<h3>Mean degree</h3>') < html.indexOf('<h3>Dynamics</h3>'))
    throw new Error('the window belongs beside the temperature and dynamics, after them');
  if (html.includes('data-window-reset')) throw new Error('nothing to go back from yet');
  sandbox.GSD_APP.authorWindow = {min: 1.5, max: 32};
  sandbox.GSD_APP.renderCampaignAuthor();
  html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('value="32"') || !html.includes('value="1.5"')) throw new Error('the window set is not shown');
  if (!html.includes('data-window-reset')) throw new Error('a set window cannot go back to the starting point\'s');
  if (/id="authorStart" disabled/.test(html)) throw new Error('a valid window blocked the start');
  sandbox.GSD_APP.authorWindow = {min: 8, max: 4};
  sandbox.GSD_APP.renderCampaignAuthor();
  html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('the window must end above where it starts')) throw new Error('an upside-down window is not refused');
  if (!/id="authorStart" disabled/.test(html)) throw new Error('an upside-down window can still be started');
  sandbox.GSD_APP.authorWindow = null;
});

check('a term with nothing set shows the default it will draw, dimmed', () => {
  const payload = campaignsPayload(false);
  payload.campaigns[0].terms = ['edge_count', 'degree_square_sum'];
  payload.campaigns[0].grid = {scales: ['one'], magnitudes: [0.05, 0.1, 0.2], signs: [-1, 1], betas: [1, 10]};
  sandbox.GSD_APP.campaignsData = payload;
  sandbox.GSD_APP.renderCampaigns(payload);
  sandbox.GSD_APP.openCampaignAuthor(payload.campaigns[0].campaign_id);
  sandbox.GSD_APP.authorGrid = {};
  sandbox.GSD_APP.renderCampaignAuthor();
  const html = String(sandbox.document.getElementById('campaignAuthor').innerHTML || '');
  if (!html.includes('rf-default')) throw new Error('an unset magnitude does not show its default');
  if (!html.includes('data-rf-mode="term:edge_count|default"')) throw new Error('a term cannot go back to the default');
  if (!html.includes('filter-pill inherit')) throw new Error('inherited signs and scales are not drawn');
  if (!html.includes('campaign defaults')) throw new Error('the row does not say it inherits');
});

check('the campaign panel is its definition, read-only, and folds what ran', () => {
  sandbox.GSD_APP.campaignsData = campaignsPayload(false);
  const before = JSON.stringify(sandbox.GSD_APP.authorGrid);
  sandbox.GSD_APP.renderCampaignPanel({
    available: true, campaign: campaignsPayload(false).campaigns[0],
    term_diff: {summary: 'added triangle_count'}, events: [
      {created_utc: '2026-09-20T09:00:00Z', event_type: 'campaign_created'},
      {created_utc: '2026-09-20T10:00:00Z', event_type: 'campaign_paused'}],
    definition: {quadrant: 'zero temperature, mean degree to 32', temperature: 'zero',
                 mean_degree_window: {min: 0, max: 32}, dense_cap: 32, dense_from_n: 256, empty_mean_degree: 0.05,
                 empty_from_n: 256, connectivity_floor: 0.5, connectivity_from_n: 1024, salt: 0.1,
                 ladder: [64, 256, 4194304], work_budgets: [[64, 375000000000, 60], [256, 375000000000, 60], [4194304, 540000000000000, 86400]],
                 law_budget: {law_budget: 5000, laws_held: 41}, search_seed: 8, complexity_budget: 7},
    frozen: [{field: 'limits', value: {mean_degree_window: {min: 0, max: 32}}, reading: 'stop rules',
              shipped_default: false}],
  });
  const html = String(sandbox.document.getElementById('campaignPanel').innerHTML);
  if (!html.includes('frozen')) throw new Error('the immutability of the definition is not stated');
  if (!html.includes('zero temperature, mean degree to 32')) throw new Error('the quadrant is not in the title');
  if (!html.includes('added triangle_count')) throw new Error('the term diff against the parent is missing');
  for (const section of ['<h3>Terms</h3>', '<h3>Temperature</h3>', '<h3>Dynamics</h3>', 'Limits and the ladder']) {
    if (!html.includes(section)) throw new Error(`the definition has no ${section}`);
  }
  if (!html.includes('0 to 32')) throw new Error('the mean-degree window is not in the definition');
  if (!html.includes('data-zero-t="true" title="accept exactly the moves that do not raise the energy"')
      || !/class="filter-pill active" data-zero-t="true"/.test(html.replace(/<button disabled /g, '<button '))) {
    throw new Error('the zero temperature the campaign draws is not drawn as chosen');
  }
  if (!html.includes('value="1.5"')) throw new Error("a term's own range is not drawn");
  if (/<button(?! disabled)[^>]*data-(zero-t|term-sign|rf-mode|scale)/.test(html)) {
    throw new Error('a control of the definition can be pressed');
  }
  if (!html.includes('<input readonly')) throw new Error('a field of the definition can be edited');
  if (!html.includes('<details class="campaign-run">') || !html.includes('campaign_paused')) {
    throw new Error('what ran is not folded under the definition');
  }
  if (!html.includes('1 differ from the shipped defaults')) throw new Error('the frozen fields are not listed');
  if (JSON.stringify(sandbox.GSD_APP.authorGrid) !== before) throw new Error("drawing the panel changed the author's state");
});

check("a campaign of a study from 554 on says each gate's own let-through", () => {
  const definition = {quadrant: 'zero temperature, mean degree to 16', temperature: 'zero', dense_cap: 16, salt: 0.1,
                      salt_shares: [['empty', 0.01, 0.1], ['no_finite_dimension', 0.5, 0.01]], ladder: [64],
                      work_budgets: [[64, 375000000000, 60]], law_budget: {}};
  sandbox.GSD_APP.renderCampaignPanel({available: true, campaign: campaignsPayload(false).campaigns[0], events: [],
                                       definition, frozen: []});
  const html = String(sandbox.document.getElementById('campaignPanel').innerHTML);
  if (!html.includes('per gate: 2 of 4 gate stops confirmed')) throw new Error('the confirmed gate stops are not counted');
  if (!html.includes('<td>the let-through</td>') || html.includes('<td>the salt</td>')) throw new Error('the share is not called the let-through');
  if (!html.includes('empty 1% / 10%') || !html.includes('no_finite_dimension 50% / 1%')) {
    throw new Error("a gate's own shares are not listed");
  }
  delete definition.salt_shares;
  sandbox.GSD_APP.renderCampaignPanel({available: true, campaign: campaignsPayload(false).campaigns[0], events: [],
                                       definition, frozen: []});
  if (!String(sandbox.document.getElementById('campaignPanel').innerHTML).includes('<b>10%</b>')) {
    throw new Error('a campaign from before 554 does not show its one let-through');
  }
});

check('drawLandscape renders without exploding', () => {
  const points = [];
  for (let i = 0; i < 40; i += 1) {
    points.push({
      candidate_id: `cand${i}`.padEnd(20, '0'),
      d_s_estimate: 1 + (i % 5) * 0.3, d_s_source: 'current',
      d_v_estimate: 2 + (i % 4) * 0.2, d_v_source: 'fit',
      d_b_estimate: i % 3 === 0 ? 1.8 : null, d_b_source: 'current',
      d_w_estimate: 2 + (i % 6) * 0.05, d_w_source: 'current',
      contracting_band: i % 7 === 0,
      interest_score: 4.2, terms: [],
    });
  }
  sandbox.GSD_APP.drawLandscape(points);
  sandbox.GSD_APP.drawLandscape(points);
});

check('drawLandscape handles an empty landscape', () => sandbox.GSD_APP.drawLandscape([]));

function bandOfLaw(law) {
  sandbox.GSD_APP.drawLandscape([law]);
  const hits = sandbox.GSD_APP.hitPoints;
  if (!hits.length) throw new Error('the law was not plotted at all');
  const bands = new Set(hits.map((h) => h.band));
  if (bands.size !== 1) throw new Error(`one law was split across bands: ${[...bands]}`);
  return hits[0].band;
}

const LAW = {
  candidate_id: 'g1396'.padEnd(64, '0'), ensemble_code: 'G-1396-1408', terms: [],
  d_s_estimate: 1.087, d_s_source: 'current', d_v_estimate: 1.4, d_v_source: 'current',
  d_b_estimate: 1.235, d_b_source: 'current', d_w_estimate: 2.1, d_w_source: 'current',
};

check('the band flag from the payload decides the band, not the evaluator fields', () => {
  const band = bandOfLaw({...LAW, d_v_estimate: null, d_w_estimate: null,
    contracting_band: true, landscape_band: 'tier2',
    stability_contracting_probes: ['d_s', 'd_B'], stability_contracting_tier: 2});
  if (band !== 'tier2') throw new Error(`a two-probe law was drawn in ${band}`);
});

check('a law with no settled probe stays in the flowing band', () => {
  const band = bandOfLaw({...LAW, contracting_band: false, landscape_band: 'flowing',
    stability_contracting_probes: [], stability_contracting_tier: 0});
  if (band !== 'flowing') throw new Error(`a law with nothing settled was drawn in ${band}`);
});

check('an old payload without the band name still renders in a band', () => {
  const legacy = {...LAW, d_v_estimate: null, d_b_estimate: null, d_w_estimate: null,
    contracting_band: true};
  if (bandOfLaw(legacy) !== 'contracting') {
    throw new Error('a one-probe law fell out of the contracting band on the fallback path');
  }
  const legacyPair = {...LAW, stability_contracting_probes: ['d_s', 'd_B']};
  if (bandOfLaw(legacyPair) !== 'tier2') {
    throw new Error('the fallback ladder did not reach tier2 from the probe list alone');
  }
});

check('the calibration page reads each probe by family, says where it never gets close, and ties the three probes on every family', () => {
  const rung = (n, mean, theory) => ({ n, measured: 10, refused: 0, mean, spread: 0.01, deviation: mean - theory });
  const fam = (theory, means, first, trend, top) => ({ theory, rungs: means.map(([n, m]) => rung(n, m, theory)), trend, at_the_top: top,
    approach: 'from_below', observed_range: [Math.min(...means.map(x => x[1])), Math.max(...means.map(x => x[1]))],
    first_n_with_error_below: { 0.5: 64, 0.25: 64, 0.1: first, 0.05: null, 0.02: null } });
  const atlas = { tolerances: [0.5, 0.25, 0.1, 0.05, 0.02], probes: {
    d_s: { families: { periodic_cubic_lattice: fam(3, [[4096, 3.05], [65536, 3.01]], 4096, 'improves with N', "within its seeds' spread") } },
    d_V: { families: { periodic_cubic_lattice: fam(3, [[4096, 2.98], [65536, 2.99]], 4096, 'steady', "within its seeds' spread") } },
    d_B: { families: { periodic_cubic_lattice: fam(3, [[4096, 2.80], [65536, 2.88]], null, 'improves with N', 'off by 0.116') } },
    d_w: { families: { periodic_cubic_lattice: fam(2, [[4096, 2.02], [65536, 2.0]], 8000, 'steady', "within its seeds' spread") } } },
    d_s_margins: { threshold: 2, cells_with_margins: 2, cells: 2, from_this_table: {
      1024: { plateau: { geometry: [15.8, 122.7], no_finite_dimension: [30.9, 60.5], separated: false },
              whole_range: { geometry: [10.5, 223.9], no_finite_dimension: [-15, 138], separated: false },
              null_families_reported: { hyperbolic_geometric_graph: [30.9, 60.5] } },
      4096: { plateau: { geometry: [27.1, 125.1] }, whole_range: { geometry: [58.9, 256.4], no_finite_dimension: [-29.4, 149.4], separated: false },
              null_families_reported: {} } } } };
  const root = getElementById('calibAtlas');
  sandbox.GSD_APP.renderProbeAtlas(root, atlas);
  const html = root.innerHTML;
  if ((html.match(/<details class=atlas-family open>/g) || []).length !== 4) throw new Error('the four per-family tables are not open by default');
  if (!/never on cubic lattice \(-0\.120 at N=65,536\)/.test(html)) throw new Error(`d_B's line does not name where it never gets within 0.1: ${html.slice(0, 600)}`);
  if (!/improves with N/.test(html) || !/off by 0\.116/.test(html)) throw new Error('the trend and the accuracy at the largest sizes are not shown');
  if (!/none reached/.test(html) || !/hyperbolic geometric graph \(60\.5\)/.test(html)) throw new Error('the guard table does not say its dashes and its offenders in words');
  if (/<details class=atlas-family open><summary><b>d_s’s guard/.test(html)) throw new Error('the guard table should be folded');
  const order = ['d_s', 'd_V', 'd_w', 'd_B'].map((p) => html.indexOf(`<li><b>${p}</b>`));
  if (order.some((at) => at < 0) || order.some((at, i) => i && at < order[i - 1])) {
    throw new Error(`the probes are not read d_s, d_V, d_w, d_B, d_B last: ${order}`);
  }
  if (!/approach<\/th><th[^>]*>theory<\/th><th[^>]*>observed range</.test(html)) {
    throw new Error('the theory is not right before the observed range');
  }
  if (!/>3\.000<\/td><td>2\.980 … 2\.990</.test(html)) throw new Error('the theory is not drawn to three decimals beside its range');
  const sorted = JSON.parse(JSON.stringify(atlas));
  sorted.probes.d_s.families.periodic_square_lattice = fam(2, [[4096, 2.3]], null, 'steady', 'off by 0.3');
  sorted.probes.d_s.families.periodic_tesseract_quotient = fam(4, [[4096, 4.001]], 4096, 'steady', "within its seeds' spread");
  sorted.probes.d_s.families.uniform_random_tree = fam(1.333, [], null, 'steady', null);
  sandbox.GSD_APP.renderProbeAtlas(root, sorted);
  const ds = String(root.innerHTML).split('<details class=atlas-family open>')[1];
  const rows = ['tesseract quotient', 'cubic lattice', 'square lattice', 'uniform random tree'].map((f) => ds.indexOf(`<tr><td>${f}<`));
  if (rows.some((at) => at < 0) || rows.some((at, i) => i && at < rows[i - 1])) {
    throw new Error(`d_s's families do not run from the most accurate to the least, one never read last: ${rows}`);
  }
  sandbox.GSD_APP.renderProbeAtlas(root, atlas);
  const einstein = sandbox.GSD_APP.atlasEinstein(atlas);
  if (!/cubic lattice/.test(einstein) || !/2 sizes, 4,096 to 65,536/.test(einstein)) throw new Error(`Einstein is not read on every family: ${einstein}`);
  if (!/-0\.000|\+0\.000|0\.0[0-9]{2}/.test(einstein)) throw new Error('the Einstein residual is not drawn');
});

check('a law that settles on all four probes is drawn in its own top band', () => {
  const perfect = {...LAW, landscape_band: 'tier4', stability_contracting_tier: 4,
    stability_contracting_probes: ['d_s', 'd_V', 'd_B', 'd_w']};
  const band = bandOfLaw(perfect);
  if (band !== 'tier4') {
    throw new Error(`a four-probe law was drawn in ${band}; it must be in the all-four band, not nowhere`);
  }
  const derived = {...LAW, stability_contracting_probes: ['d_s', 'd_V', 'd_B', 'd_w']};
  if (bandOfLaw(derived) !== 'tier4') {
    throw new Error('the client ladder dropped a four-probe law out of the all-four band');
  }
  const three = {...LAW, stability_contracting_probes: ['d_s', 'd_V', 'd_B']};
  if (bandOfLaw(three) !== 'tier3') {
    throw new Error('a three-probe law left the three-probe band');
  }
});

check('a chain whose four probes agree by the Einstein relation is drawn in the 5th band, above the four', () => {
  const four = ['d_s', 'd_V', 'd_B', 'd_w'];
  const agreeing = {...LAW, stability_contracting_probes: four, stability_contracting_tier: 4,
    einstein: { residual: 0.02, tau: 0.075, agree: true }};
  const apart = {...agreeing, einstein: { residual: 0.3, tau: 0.075, agree: false }};
  if (bandOfLaw(agreeing) !== 'einstein') throw new Error('four settled probes that agree by Einstein are not in the 5th band');
  if (bandOfLaw(apart) !== 'tier4') throw new Error('four settled probes that do not agree left the four-probe band');
  const points = [{...agreeing, candidate_id: 'e1', d_s_estimate: 2.0, landscape_band: 'einstein'}];
  sandbox.GSD_APP.drawLandscape(points);
  const layout = sandbox.GSD_APP.bandLayout;
  if (layout[0].id !== 'einstein' || layout[0].count !== 1) throw new Error(`the 5th band is not the top band holding its law: ${JSON.stringify(layout[0])}`);
});

check('the ladder never demotes a law for settling one more probe', () => {
  const order = ['tier4', 'tier3', 'tier2', 'contracting', 'flowing'];
  const probes = ['d_s', 'd_V', 'd_B', 'd_w'];
  let previous = order.length;
  for (let tier = 0; tier <= 4; tier += 1) {
    const rank = order.indexOf(bandOfLaw({...LAW,
      stability_contracting_probes: probes.slice(0, tier), stability_contracting_tier: tier}));
    if (rank < 0) throw new Error(`tier ${tier} landed outside the band ladder`);
    if (rank > previous) throw new Error(`tier ${tier} was drawn below tier ${tier - 1}`);
    previous = rank;
  }
});

check('empty tiers collapse without vanishing and without overflowing', () => {
  const points = [];
  for (let i = 0; i < 12; i += 1) {
    points.push({...LAW, candidate_id: `c${i}`, d_s_estimate: 1 + i * 0.2,
      landscape_band: 'flowing', stability_contracting_probes: [], stability_contracting_tier: 0});
  }
  sandbox.GSD_APP.drawLandscape(points);
  const layout = sandbox.GSD_APP.bandLayout;
  if (layout.length !== 6) throw new Error(`expected six bands, the 5th band by the Einstein relation above the four, got ${layout.length}`);
  for (const b of ['einstein', 'tier4', 'tier3', 'tier2']) {
    const found = layout.find((l) => l.id === b);
    if (!found) throw new Error(`${b} disappeared when it had no members`);
    if (found.height <= 0) throw new Error(`${b} collapsed to nothing rather than to its label`);
    if (found.count !== 0) throw new Error(`${b} reported members it does not have`);
  }
  const height = getElementById('land').getBoundingClientRect().height;
  for (const h of sandbox.GSD_APP.hitPoints) {
    if (h.y > height) throw new Error('a specimen was drawn below the canvas');
  }
});

check('fill state is per probe, not per law', () => {
  const one = {...LAW, candidate_id: 'a'.padEnd(64, '0'), landscape_band: 'contracting',
    d_s_estimate: 1.8, d_v_estimate: 2.4, d_b_estimate: 2.7, d_w_estimate: 2.1,
    stability_contracting_probes: ['d_s'], stability_contracting_tier: 1};
  sandbox.GSD_APP.drawLandscape([one]);
  const marks = new Map(sandbox.GSD_APP.hitPoints.map((h) => [h.metric, h]));
  if (marks.size !== 4) throw new Error(`expected four marks, got ${marks.size}`);
  if (!marks.get('d_s').settled) throw new Error('the probe that earned the band is not filled');
  for (const id of ['d_V', 'd_B', 'd_w']) {
    if (marks.get(id).settled) throw new Error(`${id} drawn as settled on a tier-1 law`);
  }
});

check('a tier-2 law says which two, not just how many', () => {
  const pair = {...LAW, candidate_id: 'b'.padEnd(64, '0'), landscape_band: 'tier2',
    d_s_estimate: 1.8, d_v_estimate: 2.4, d_b_estimate: 2.7, d_w_estimate: 2.1,
    stability_contracting_probes: ['d_s', 'd_B'], stability_contracting_tier: 2};
  sandbox.GSD_APP.drawLandscape([pair]);
  const filled = sandbox.GSD_APP.hitPoints.filter((h) => h.settled).map((h) => h.metric).sort();
  if (filled.join(',') !== 'd_B,d_s') throw new Error(`filled marks were ${filled.join(',')}`);
});

check('a law with no settled probe draws no filled mark', () => {
  const none = {...LAW, candidate_id: 'c'.padEnd(64, '0'), landscape_band: 'flowing',
    d_s_estimate: 1.8, d_w_estimate: 2.1,
    stability_contracting_probes: [], stability_contracting_tier: 0};
  sandbox.GSD_APP.drawLandscape([none]);
  if (sandbox.GSD_APP.hitPoints.some((h) => h.settled)) {
    throw new Error('a FLOWING law drew a settled mark');
  }
});

check('a settled law draws the values its other probes withheld, as withheld', () => {
  const law = {...LAW, candidate_id: 'w'.padEnd(64, '0'), landscape_band: 'contracting',
    d_s_estimate: 3.4, d_v_estimate: 2.6, d_b_estimate: null, d_w_estimate: null,
    stability_contracting_probes: ['d_s'], stability_contracting_tier: 1,
    withheld: {d_B: {value: 3.1, n: 4096, seeds: 3, reasons: {NOT_POWER_LAW: 3}},
               d_V: {value: 9.9, n: 4096, seeds: 3, reasons: {EXPONENTIAL_GROWTH: 3}}}};
  sandbox.GSD_APP.drawLandscape([law]);
  const marks = new Map(sandbox.GSD_APP.hitPoints.map((h) => [h.metric, h]));
  if (marks.size !== 3) throw new Error(`expected d_s, d_V and the withheld d_B, got ${[...marks.keys()]}`);
  if (!marks.get('d_B').withheld || marks.get('d_B').settled || marks.get('d_B').value !== 3.1) {
    throw new Error('the withheld d_B is not drawn as withheld');
  }
  if (marks.get('d_V').withheld || marks.get('d_V').value !== 2.6) throw new Error('a withheld value replaced a reading');
});

check('a small world is drawn faint and never settled', () => {
  const island = {...LAW, candidate_id: 's'.padEnd(64, '0'), landscape_band: 'flowing',
    d_s_estimate: 5.9, d_v_estimate: 5.6, d_b_estimate: 3.9, d_w_estimate: 2.5,
    stability_contracting_probes: ['d_B'], stability_contracting_tier: 1,
    small_world: {sizes: [1024, 4096, 16384, 65536], radius_growth: 1.6, volume_growth: 64}};
  sandbox.GSD_APP.drawLandscape([island]);
  const hits = sandbox.GSD_APP.hitPoints;
  if (hits.length !== 4) throw new Error(`expected four marks, got ${hits.length}`);
  if (hits.some((h) => h.settled)) throw new Error('a small world drew a settled mark');
  if (!hits.every((h) => h.smallWorld)) throw new Error('a small world mark is not flagged faint');
  if (hits.some((h) => h.band !== 'flowing')) throw new Error('a small world left the FLOWING band');
});

check('an occupied tier takes room back from the collapsed ones', () => {
  const flowing = {...LAW, candidate_id: 'f'.padEnd(64, '0'), landscape_band: 'flowing',
    stability_contracting_probes: [], stability_contracting_tier: 0};
  sandbox.GSD_APP.drawLandscape([flowing]);
  const before = sandbox.GSD_APP.bandLayout.find((l) => l.id === 'tier2').height;
  const pair = {...LAW, candidate_id: 'p'.padEnd(64, '0'), landscape_band: 'tier2',
    stability_contracting_probes: ['d_s', 'd_B'], stability_contracting_tier: 2};
  sandbox.GSD_APP.drawLandscape([flowing, pair]);
  const after = sandbox.GSD_APP.bandLayout.find((l) => l.id === 'tier2').height;
  if (!(after > before)) {
    throw new Error(`tier2 did not expand when it gained a member: ${before} -> ${after}`);
  }
});

check('specimen layout scales with canvas height', () => {
  const spans = [];
  for (const height of [370, 800]) {
    const element = getElementById('land');
    element.rectHeight = height;
    const points = [];
    for (let i = 0; i < 12; i += 1) {
      points.push({
        candidate_id: `c${i}`, d_s_estimate: 1 + i * 0.2, d_v_estimate: 2,
        d_b_estimate: 1.5, d_w_estimate: 2, terms: [], interest_score: 1,
        contracting_band: i % 2 === 0,
      });
    }
    sandbox.GSD_APP.drawLandscape(points);
    const ys = sandbox.GSD_APP.hitPoints.map((p) => p.y);
    if (!ys.length) throw new Error(`no specimens plotted at ${height}px`);
    const span = Math.max(...ys) - Math.min(...ys);
    if (Math.max(...ys) > height) throw new Error(`specimen drawn below the canvas at ${height}px`);
    spans.push(span);
  }
  if (spans[1] <= spans[0] * 1.5) {
    throw new Error(`layout did not grow with the canvas: ${spans[0]} -> ${spans[1]}`);
  }
  getElementById('land').rectHeight = 400;
});


const cssText = fs.readFileSync(path.join(uiDir, 'system.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

function parseRules(text, maxWidth) {
  const rules = [];
  let i = 0;
  while (i < text.length) {
    const at = text.indexOf('@media', i);
    const brace = text.indexOf('{', i);
    if (brace < 0) break;
    if (at >= 0 && at < brace) {
      const open = text.indexOf('{', at);
      let depth = 0, end = open;
      for (; end < text.length; end += 1) {
        if (text[end] === '{') depth += 1;
        else if (text[end] === '}' && (depth -= 1) === 0) break;
      }
      const condition = text.slice(at + 6, open);
      const limit = /max-width\s*:\s*(\d+)px/.exec(condition);
      rules.push(...parseRules(text.slice(open + 1, end), limit ? Number(limit[1]) : maxWidth));
      i = end + 1;
      continue;
    }
    const close = text.indexOf('}', brace);
    if (close < 0) break;
    const selectors = text.slice(i, brace).split(',').map((s) => s.replace(/\s+/g, '').trim());
    const declarations = {};
    for (const part of text.slice(brace + 1, close).split(';')) {
      const split = part.indexOf(':');
      if (split < 0) continue;
      declarations[part.slice(0, split).trim()] = part.slice(split + 1).trim();
    }
    rules.push({ selectors, declarations, maxWidth });
    i = close + 1;
  }
  return rules;
}

const cssRules = parseRules(cssText, null);

function winning(selector, property, viewport) {
  let value = null;
  for (const rule of cssRules) {
    if (rule.maxWidth != null && viewport > rule.maxWidth) continue;
    if (!rule.selectors.includes(selector)) continue;
    if (rule.declarations[property] != null) value = rule.declarations[property];
  }
  return value;
}

function splitTop(text) {
  const parts = [];
  let depth = 0, start = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === '(') depth += 1;
    else if (text[i] === ')') depth -= 1;
    else if (text[i] === ',' && depth === 0) { parts.push(text.slice(start, i)); start = i + 1; }
  }
  parts.push(text.slice(start));
  return parts.map((p) => p.trim());
}

function resolveLength(expression, variables, seen = new Set()) {
  const text = String(expression == null ? '' : expression).trim();
  if (!text) return NaN;
  const fn = /^([a-z-]*)\(([\s\S]*)\)$/.exec(text);
  if (fn && (fn[1] === 'var' || fn[1] === 'calc' || fn[1] === 'clamp' || fn[1] === 'min' || fn[1] === 'max')) {
    const args = splitTop(fn[2]);
    if (fn[1] === 'var') {
      const name = args[0];
      if (seen.has(name)) return NaN;
      const next = new Set(seen).add(name);
      if (variables[name] != null) return resolveLength(variables[name], variables, next);
      return args.length > 1 ? resolveLength(args.slice(1).join(','), variables, next) : NaN;
    }
    if (fn[1] === 'min') return Math.min(...args.map((a) => resolveLength(a, variables, seen)));
    if (fn[1] === 'max') return Math.max(...args.map((a) => resolveLength(a, variables, seen)));
    if (fn[1] === 'clamp') {
      const [low, value, high] = args.map((a) => resolveLength(a, variables, seen));
      return Math.min(Math.max(value, low), high);
    }
    const inner = fn[2].replace(/var\(\s*(--[\w-]+)\s*(?:,([^()]*))?\)/g, (_, name, fallback) => {
      const value = resolveLength(`var(${name}${fallback === undefined ? '' : ',' + fallback})`, variables, seen);
      return Number.isFinite(value) ? String(value) : 'NaN';
    });
    const tokens = inner.match(/[\d.]+(?:px)?|NaN|[+\-*/()]/g) || [];
    let position = 0;
    const peek = () => tokens[position];
    const sum = () => {
      let value = product();
      while (peek() === '+' || peek() === '-') {
        const operator = tokens[position++];
        const right = product();
        value = operator === '+' ? value + right : value - right;
      }
      return value;
    };
    const product = () => {
      let value = unary();
      while (peek() === '*' || peek() === '/') {
        const operator = tokens[position++];
        const right = unary();
        value = operator === '*' ? value * right : value / right;
      }
      return value;
    };
    const unary = () => {
      if (peek() === '(') {
        position += 1;
        const value = sum();
        position += 1;
        return value;
      }
      if (peek() === '-') { position += 1; return -unary(); }
      const token = tokens[position++];
      return token === 'NaN' ? NaN : resolveLength(token, variables, seen);
    };
    return sum();
  }
  const length = /^(-?[\d.]+)(px)?$/.exec(text);
  return length ? Number(length[1]) : NaN;
}

function rootVariables(viewport) {
  const variables = {};
  for (const rule of cssRules) {
    if (rule.maxWidth != null && viewport > rule.maxWidth) continue;
    if (!rule.selectors.includes(':root')) continue;
    for (const [name, value] of Object.entries(rule.declarations)) {
      if (name.startsWith('--')) variables[name] = value;
    }
  }
  return variables;
}

check('the header height reaches the stylesheet as a measurement', () => {
  const header = getElementById('gsdSystemHeader');
  header.getBoundingClientRect = () => ({ width: 1720, height: 118, left: 0, top: 0 });
  sandbox.GSD_SYSTEM.measureHeaderHeight();
  const published = documentStub.documentElement.style.getPropertyValue('--gsd-header-h');
  if (published !== '118px') {
    throw new Error(`--gsd-header-h is "${published || 'unset'}"; the hero is sized from a literal`);
  }
});

check('a zero measurement does not clobber the last good one', () => {
  const header = getElementById('gsdSystemHeader');
  header.getBoundingClientRect = () => ({ width: 1720, height: 0, left: 0, top: 0 });
  sandbox.GSD_SYSTEM.measureHeaderHeight();
  if (documentStub.documentElement.style.getPropertyValue('--gsd-header-h') !== '118px') {
    throw new Error('a hidden header collapsed the hero row');
  }
});

check('a resized header republishes through the observer', () => {
  if (!resizeObservers.length) throw new Error('the header height is measured once and never again');
  const header = getElementById('gsdSystemHeader');
  header.getBoundingClientRect = () => ({ width: 1000, height: 176, left: 0, top: 0 });
  resizeObservers.forEach((observer) => observer.callback([]));
  if (documentStub.documentElement.style.getPropertyValue('--gsd-header-h') !== '176px') {
    throw new Error('the header grew a row and the hero did not follow');
  }
});

check('the landscape is repainted when the hero row changes', () => {
  const listeners = windowListeners['rr:hero-metrics'] || [];
  if (!listeners.length) {
    throw new Error('nothing listens for rr:hero-metrics: the plot would keep its first size');
  }
  sandbox.dispatchEvent(new sandbox.CustomEvent('rr:hero-metrics', { detail: { headerHeight: 176 } }));
});

check('switching campaigns tells the rest of the page', () => {
  const before = sandbox.GSD_SYSTEM.campaign;
  let heard = null;
  const listener = (event) => { heard = event.detail && event.detail.campaign; };
  sandbox.addEventListener('rr:campaign', listener);
  sandbox.GSD_SYSTEM.switchCampaign('2');
  if (sandbox.GSD_SYSTEM.campaign !== '2') {
    throw new Error(`the switcher did not change the campaign: still ${sandbox.GSD_SYSTEM.campaign}`);
  }
  if (heard !== '2') throw new Error('rr:campaign did not carry the new campaign');
  if (sandbox.window.GSD_CAMPAIGN !== '2') {
    throw new Error('GSD_CAMPAIGN was not republished; app.js reads it on first paint');
  }
  sandbox.GSD_SYSTEM.switchCampaign(before);
});

check('switching to the campaign already shown is a no-op', () => {
  const current = sandbox.GSD_SYSTEM.campaign;
  let fired = 0;
  const listener = () => { fired += 1; };
  sandbox.addEventListener('rr:campaign', listener);
  sandbox.GSD_SYSTEM.switchCampaign(current);
  sandbox.GSD_SYSTEM.switchCampaign(null);
  if (fired) throw new Error('a redundant switch reset the landscape and refetched');
});

check('575: a card in The study now switches the campaign, and each panel that reads one names it', () => {
  const before = sandbox.GSD_SYSTEM.campaign;
  const rowsBefore = sandbox.GSD_SYSTEM.campaignRows;
  sandbox.GSD_SYSTEM.campaignRows = [{ campaign_id: '1' }, { campaign_id: '2' }, { campaign_id: '3' },
                                     { campaign_id: '4', status: 'archived' }];
  sandbox.GSD_SYSTEM.switchCampaign('1');
  if (getElementById('ladderScope').textContent !== 'C1') {
    throw new Error(`the ladder does not name the campaign it reads: ${JSON.stringify(getElementById('ladderScope').textContent)}`);
  }
  const target = (id) => ({ closest: (selector) => (selector === '[data-campaign]' ? { dataset: { campaign: id } } : null) });
  getElementById('studyNow').dispatch('click', { target: target('2') });
  if (sandbox.GSD_SYSTEM.campaign !== '2') {
    throw new Error(`a click on campaign 2's card did not switch: still ${sandbox.GSD_SYSTEM.campaign}`);
  }
  if (sandbox.GSD_APP.campaign !== '2') throw new Error('app.js did not hear the switch');
  for (const id of ['landScope', 'topScope', 'ladderScope', 'liveScope', 'reportScope', 'gateScope', 'workScope']) {
    const label = getElementById(id);
    if (label.textContent !== 'C2') throw new Error(`${id} names ${JSON.stringify(label.textContent)}, not C2`);
    if (!/campaign 2/.test(label.title)) throw new Error(`${id} does not say what it names: ${label.title}`);
  }
  if (getElementById('explorerScopeOne').textContent !== 'campaign 2') {
    throw new Error(`the Explorer's one-campaign scope does not name it: ${getElementById('explorerScopeOne').textContent}`);
  }
  const others = String(getElementById('explorerScopeOthers').innerHTML);
  if (/value="c:2"/.test(others)) throw new Error(`the Explorer lists the campaign it is on among the others: ${others}`);
  const otherIds = (sandbox.GSD_SYSTEM.campaignRows || []).filter((r) => r.status !== 'archived').map((r) => String(r.campaign_id))
    .filter((x) => x !== '2');
  if (!otherIds.length) throw new Error('the harness has no other campaign to offer');
  for (const other of otherIds) {
    if (!others.includes(`value="c:${other}"`)) throw new Error(`the Explorer cannot choose campaign ${other}: ${others}`);
  }
  if (others.includes('value="c:4"')) throw new Error('an archived campaign is offered');
  getElementById('studyNow').dispatch('click', { target: { closest: () => null } });
  if (sandbox.GSD_SYSTEM.campaign !== '2') throw new Error('a click between the cards switched the campaign');
  sandbox.GSD_SYSTEM.switchCampaign('1');
  if (getElementById('ladderScope').textContent !== 'C1') throw new Error('switching back left the old name');
  sandbox.GSD_SYSTEM.campaignRows = rowsBefore;
  if (before) sandbox.GSD_SYSTEM.switchCampaign(before);
});

check('575: the GRAPHS tile and the core-hours add up every campaign of the folder', () => {
  const campaigns = [
    { campaign_id: '1', runtime_counts: { graph_jobs_created: 17496, completed_graph_realizations: 14809,
      graphs_finished_last_hour: 653, compute: { core_seconds: 52 * 3600 } } },
    { campaign_id: '2', runtime_counts: { graph_jobs_created: 90, completed_graph_realizations: 90,
      graphs_finished_last_hour: 0, compute: { core_seconds: 3600 } } },
    { campaign_id: '3', runtime_counts: { graph_jobs_created: 75, completed_graph_realizations: 75,
      graphs_finished_last_hour: 2, compute: { core_seconds: 1800 } } },
    { campaign_id: '4', runtime_counts: { graph_jobs_created: 108, completed_graph_realizations: 108,
      graphs_finished_last_hour: 1, compute: { core_seconds: 1800 } } },
  ];
  sandbox.GSD_SYSTEM.updateHeader({ campaign_id: '1', campaigns, runtime_counts: campaigns[0].runtime_counts,
    system_resources: { memory_bandwidth: {} },
    compute_utilization: { simulation_busy: 16, analysis_busy: 0, total_slots: 16 } }, 29);
  const graphs = getElementById('gsdGraphs');
  if (graphs.textContent !== (17496 + 90 + 75 + 108).toLocaleString()) {
    throw new Error(`the tile is not every campaign's graphs: ${graphs.textContent}`);
  }
  if (getElementById('gsdGraphsDetail').textContent !== '656/h over the last hour') {
    throw new Error(`the rate is not every campaign's last hour: ${getElementById('gsdGraphsDetail').textContent}`);
  }
  for (const line of ['C1: 17,496 graphs from 17,496 simulations created, 14,809 finished, 653 in the last hour',
                      'C4: 108 graphs from 108 simulations created, 108 finished',
                      'the 4 campaigns of this folder']) {
    if (!graphs.title.includes(line)) throw new Error(`the tooltip does not say "${line}": ${graphs.title}`);
  }
  if (getElementById('gsdComputeDetail').textContent !== '54 core-h accumulated') {
    throw new Error(`the core-hours are not every campaign's: ${getElementById('gsdComputeDetail').textContent}`);
  }
  sandbox.GSD_SYSTEM.updateHeader({ campaigns: [{ campaign_id: '1', runtime_counts: { graph_jobs_created: 10,
    compute: { core_seconds: 3600 } } }], system_resources: { memory_bandwidth: {} },
    compute_utilization: { simulation_busy: 0, analysis_busy: 16, total_slots: 16 } }, 20);
  if (getElementById('gsdComputeDetail').textContent !== '16 analyses · 1.0 core-h accumulated') {
    throw new Error(`the COMPUTE subline does not say how many slots are analyses: `
      + getElementById('gsdComputeDetail').textContent);
  }
  sandbox.GSD_SYSTEM.updateHeader({ campaign_id: '1', runtime_counts: { graph_jobs_created: 5487,
    graphs_finished_last_hour: 126 }, system_resources: { memory_bandwidth: {} }, compute_utilization: {} }, 20);
  if (graphs.textContent !== '5,487') throw new Error(`a payload with no list lost its own count: ${graphs.textContent}`);
});

check('729: the GRAPHS tile counts the graphs grown, five a simulation of five chains, over every campaign', () => {
  const campaigns = [
    { campaign_id: '1', runtime_counts: { graph_jobs_created: 1000, graphs_grown: 5000, completed_graph_realizations: 900,
      graphs_finished_last_hour: 10, graphs_grown_last_hour: 50 } },
    { campaign_id: '6', runtime_counts: { graph_jobs_created: 40, graphs_grown: 80, completed_graph_realizations: 40,
      graphs_finished_last_hour: 2, graphs_grown_last_hour: 4 } },
  ];
  sandbox.GSD_SYSTEM.updateHeader({ campaign_id: '1', campaigns, runtime_counts: campaigns[0].runtime_counts,
    system_resources: { memory_bandwidth: {} }, compute_utilization: {} }, 20);
  const graphs = getElementById('gsdGraphs');
  if (graphs.textContent !== (5080).toLocaleString()) throw new Error(`the tile is not the graphs grown: ${graphs.textContent}`);
  if (getElementById('gsdGraphsDetail').textContent !== '54/h over the last hour') {
    throw new Error(`the rate is not graphs grown an hour: ${getElementById('gsdGraphsDetail').textContent}`);
  }
  for (const line of ['5,080 graphs grown in the 2 campaigns of this folder', '1,040 simulations created',
                      'C6: 80 graphs from 40 simulations created']) {
    if (!graphs.title.includes(line)) throw new Error(`the tooltip does not say "${line}": ${graphs.title}`);
  }
});

check('the CPU tile carries temperature and power', () => {
  const source = fs.readFileSync(path.join(uiDir, 'system.js'), 'utf8');
  const line = /setText\('gsdCpuDetail',([^;]*);/.exec(source);
  if (!line) throw new Error('the CPU detail line is gone entirely');
  if (!/temp\(/.test(line[1]) || !/watts\(/.test(line[1])) {
    throw new Error('the CPU tile should still carry temperature and power');
  }
});

check('the landscape is never shorter than the plot floor plus its chrome, the filters above the row (872)', () => {
  for (const viewport of [1720, 1100, 700]) {
    const variables = rootVariables(viewport);
    const selector = viewport > 1250 ? '.hero' : '.herocol>.land-panel';
    const declared = winning(selector, 'height', viewport);
    if (!declared || declared === 'auto') {
      throw new Error(`${selector} has no height at ${viewport}px: its size comes from its content`);
    }
    const floor = resolveLength(winning('.canvaswrap', 'min-height', viewport), variables);
    const chrome = Number.isFinite(resolveLength(variables['--gsd-hero-chrome'], variables))
      ? resolveLength(variables['--gsd-hero-chrome'], variables) : 78;
    if (!Number.isFinite(floor)) {
      throw new Error('the plot floor must resolve to a length');
    }
    for (const filterHeight of [96, 128, 190]) {
      for (const headerHeight of [104, 118, 176]) {
        const measured = { ...variables, '--gsd-header-h': `${headerHeight}px`, '--gsd-filter-h': `${filterHeight}px` };
        const resolved = resolveLength(declared, measured);
        if (!Number.isFinite(resolved) || resolved <= 0) {
          throw new Error(`${selector} height "${declared}" does not resolve to a length at ${viewport}px`);
        }
        const beside = 0;
        if (resolved - beside - chrome < floor) {
          throw new Error(
            `${selector} is ${resolved}px at a ${headerHeight}px header and ${filterHeight}px of filters, leaving `
            + `${resolved - beside - chrome}px for a plot with a ${floor}px floor: its bottom rows are cut off`,
          );
        }
        if ((resolved - beside) / headerHeight > 6) {
          throw new Error(`the landscape is ${resolved - beside}px against a ${headerHeight}px header; that is runaway`);
        }
      }
    }
  }
});

check('the filters lead above the row, so the landscape and the Top 100 beside it keep their height (872)', () => {
  const variables = rootVariables(1720);
  const row = winning('.hero', 'height', 1720);
  const short = resolveLength(row, { ...variables, '--gsd-filter-h': '100px' });
  const tall = resolveLength(row, { ...variables, '--gsd-filter-h': '160px' });
  if (tall !== short) throw new Error(`the row moved ${tall - short}px for 60px more of filters above it`);
  if (winning('.heroaside>.panel', 'height', 1720) !== '100%') throw new Error('the Top 100 does not fill the row');
  const panel = getElementById('filterPanel');
  panel.getBoundingClientRect = () => ({ width: 1300, height: 141, left: 0, top: 0 });
  sandbox.GSD_APP.measureFilterHeight(panel);
  const published = documentStub.documentElement.style.getPropertyValue('--gsd-filter-h');
  if (published !== '141px') throw new Error(`--gsd-filter-h is "${published || 'unset'}" after measuring 141px`);
  panel.getBoundingClientRect = () => ({ width: 1300, height: 0, left: 0, top: 0 });
  sandbox.GSD_APP.measureFilterHeight(panel);
  if (documentStub.documentElement.style.getPropertyValue('--gsd-filter-h') !== '141px') {
    throw new Error('a zero measurement clobbered the filters\' height');
  }
});

check('the hero row still follows the header when the header is the binding term', () => {
  for (const viewport of [1720, 1100, 700]) {
    const variables = rootVariables(viewport);
    const declared = winning(viewport > 1250 ? '.hero' : '.herocol>.land-panel', 'height', viewport);
    const small = resolveLength(declared, { ...variables, '--gsd-header-h': '176px' });
    const large = resolveLength(declared, { ...variables, '--gsd-header-h': '196px' });
    if (!(large > small)) {
      throw new Error(`the row did not grow with the header at ${viewport}px: ${small} -> ${large}`);
    }
  }
});

check('the plot floor has one source, not two literals that must agree', () => {
  const variables = rootVariables(1720);
  const wrapper = winning('.canvaswrap', 'min-height', 1720);
  if (!/var\(\s*--gsd-plot-min-h/.test(String(wrapper))) {
    throw new Error(`.canvaswrap min-height is "${wrapper}"; it must read --gsd-plot-min-h`);
  }
  if (!Number.isFinite(resolveLength(variables['--gsd-plot-min-h'], variables))) {
    throw new Error('--gsd-plot-min-h is not declared as a length on :root');
  }
});

check('neither hero column can be sized by what is inside it', () => {
  for (const viewport of [1720, 1100, 700]) {
    const display = winning('.heroaside', 'display', viewport);
    const rows = winning('.heroaside', 'grid-template-rows', viewport);
    if (display === 'grid' && /auto|min-content|max-content/.test(rows || 'auto')) {
      throw new Error(
        `.heroaside is a grid with content-sized rows ("${rows}") at ${viewport}px: `
        + 'the ranking will set the height of the plot',
      );
    }
    const panel = winning('.heroaside>.panel', 'height', viewport)
               || winning('.top100-panel', 'height', viewport);
    if (!panel || panel === 'auto') {
      throw new Error(`the Top 100 panel has no height at ${viewport}px; it will grow to 100 rows`);
    }
  }
  if (!/auto|scroll/.test(winning('.top100-scroll', 'overflow', 1720) || '')) {
    throw new Error('.top100-scroll does not scroll, so the list will push the row taller');
  }
});

check('the study bundles have their own panel on the reports page', () => {
  const page = fs.readFileSync(path.join(uiDir, 'index.html'), 'utf8');
  if (!/class="panel study-bundles-panel"><h2>Study bundles<\/h2><div id="studyBundles"/.test(page)) {
    throw new Error('the study bundles have no panel of their own');
  }
});

check('the cycle panel is the campaign\'s own last cycle', () => {
  sandbox.GSD_APP.renderReports({
    manifest: { cycle_state: 'COMPLETE',
      analysis_phase: { state: 'complete', diagnostics: { cycle: { total_seconds: 10.7, snapshot_seconds: 1.1,
                                                                   snapshot_compressed_bytes: 1468006 } } }, generation_finished_utc: '2026-09-30T09:33:24Z',
      reports: [{ number: 1, slug: 'integrity', seconds: 0.279, status: 'ready' }],
      cycle: { total_seconds: 103.563, snapshot_seconds: 43.228, snapshot_resident_bytes: 6700000000,
               snapshot_peak_bytes: 6900000000, report_pool: { workers: 7, why: '7 children' },
               snapshot_stages: [{ stage: 'measurements', seconds: 21.6 }, { stage: 'peer_landscape', seconds: 5.2 },
                                 { stage: 'types', seconds: 5.0 }],
               snapshot_parts: [{ campaign_id: '1', part: 'measurements', json_bytes: 1005000000 }] } },
    access: {},
  });
  const panel = getElementById('reportCycle').innerHTML;
  if (/10\.7s|compressed/.test(panel)) throw new Error(`the cycle panel still shows the slot's old cycle: ${panel}`);
  if (!/1m43/.test(panel) || !/report processes <b>7/.test(panel)) {
    throw new Error(`the cycle panel is not the manifest's: ${panel}`);
  }
  if (!/measurements 22s/.test(panel)) throw new Error(`the snapshot line does not say where its seconds went: ${panel}`);
});

const QUIET_STATUS = (extra) => Object.assign({
  manifest: { reports: {}, cycle: { total_seconds: 454.1 } },
  access: { local_admin: true },
  in_flight: { total: 0, by_campaign: {}, reading: 'nothing is in flight' },
  quiet_report: null,
  reporting_campaign_id: '1',
}, extra || {});

check('a busy fleet offers the study bundle, pausing first, and says what is in flight', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.renderReports(QUIET_STATUS({
    in_flight: { total: 3, by_campaign: { 2: { simulate: 3 } },
                 reading: '3 unit(s) of work in flight (campaign 2: 3 simulate)' },
  }));
  const btn = getElementById('reportsManual');
  if (btn.disabled) throw new Error('the study bundle is refused while work is in flight; it pauses first');
  if (!/pause everything and make the study bundle/.test(btn.textContent)) {
    throw new Error(`the button does not say it pauses first: ${btn.textContent}`);
  }
  const note = getElementById('reportQuiet').innerHTML;
  if (!/3 unit\(s\) of work in flight/.test(note)) throw new Error(`the panel does not say what is in flight: ${note}`);
});

check('a quiet fleet offers the study bundle with nothing to pause', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.renderReports(QUIET_STATUS());
  const btn = getElementById('reportsManual');
  if (btn.disabled) throw new Error('a quiet fleet refused a report');
  if (btn.textContent !== 'make the study bundle') throw new Error(`unexpected button text: ${btn.textContent}`);
});

check('a study bundle in progress shows which campaign of how many, and holds the button', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.renderReports(QUIET_STATUS({
    in_flight: { total: 0, by_campaign: {}, reading: 'nothing is in flight' },
    quiet_report: { stage: 'reporting', campaign_id: '2', index: 1, campaigns: ['1', '2', '3', '4'] },
  }));
  const note = getElementById('reportQuiet').innerHTML;
  if (!/reporting/.test(note) || !/campaign <b>2<\/b> \(2 of 4\)/.test(note)) {
    throw new Error(`the stage is not shown: ${note}`);
  }
  if (!getElementById('reportsManual').disabled) throw new Error('a second report can be started while one runs');
  sandbox.GSD_APP.renderReports(QUIET_STATUS({ quiet_report: { stage: 'bundling', campaigns: ['1', '2'] } }));
  if (!getElementById('reportsManual').disabled) throw new Error('the button is free while the bundle is written');
  sandbox.GSD_APP.renderReports(QUIET_STATUS({ quiet_report: {
    stage: 'done', resumed: ['1'], campaigns: ['1', '2'],
    study_bundle: { filename: 'study_GSD533_x.tar.zst', campaigns: [{ campaign_id: '1' }, { campaign_id: '2' }],
                    missing: [] } } }));
  const done = getElementById('reportQuiet').innerHTML;
  if (!/study_GSD533_x\.tar\.zst<\/b>, 2 campaigns/.test(done)) throw new Error(`the finished bundle is not named: ${done}`);
});


check('the calibration page renders a full calibration table', () => {
  if (typeof sandbox.GSD_APP.renderCalibration !== 'function') {
    throw new Error('renderCalibration is not exported on GSD_APP');
  }
  const table = {
    available: true, contract: 'gsd-calibration-table-1', suite_version: 1, build_number: 244,
    authoritative: true, written_utc: '2026-09-01T10:00:00Z', science_fingerprint: 'abcd', suite_fingerprint: 'efgh',
    estimator_fingerprint: 'ijkl', path: '/repo/calibration/probe_calibration.json', source: 'durable',
    profile: { name: 'full', seeds: 10, max_nodes: null },
    plan: { total_cells: 590, current: 590, stale: 0, missing: 0, failed: 0, complete: true },
    origin: { computed_on: 'hostA', adopted: false },
    runs: [{ elapsed_seconds: 7200 }],
    atlas: { tolerances: [0.5, 0.1], probes: { d_B: { families: { sierpinski_gasket: {
      theory: 1.585, trend: 'improves with N', at_the_top: "within its seeds' spread", rungs: [], first_n_with_error_below: {} } } } } },
    pipeline_trial: {
      generated_utc: '2026-09-01T09:00:00Z', host: 'hostA', seeds: 2, seconds: 3.1,
      pipeline_passed: true, stage_failures: [],
      rows: [
        { anchor: 'sierpinski_gasket_level_7', channel: 'd_s', measured: 1.3904,
          theory: 1.3652, drift: 0.0252, tolerance: 0.25, status: 'PASS' },
        { anchor: 'sierpinski_gasket_level_7', channel: 'd_B', measured: null,
          theory: 1.585, drift: null, tolerance: 0.35, status: 'REFUSED' },
      ],
      einstein: [{
        anchor: 'sierpinski_gasket_level_7', d_s_measured: 1.3904, d_w_measured: 2.4313,
        closures: [
          { d_f_source: 'theory d_f', d_f: 1.585, d_s_from_relation: 1.3038, residual: 0.0866 },
          { d_f_source: 'measured d_B', d_f: 1.31, d_s_from_relation: 1.0776, residual: 0.3128 },
        ],
      }],
    },
    deviation: {
      verdict: 'FAIL', failing_families: ['random_4_regular'], incomplete_families: [], seeds: 10,
      summary_line: 'FAIL: random_4_regular out of declared tolerance or lost a refusal; investigate before collecting data',
      families: {
        sierpinski_gasket: {
          expectation: 'MEASURE', why: 'exact fractal', theory: { d_B: 1.585 }, verdict: 'PASS', complete: true,
          graph_varies_per_seed: false, dispersion_meaning: 'estimator dispersion: every seed measures the same graph',
          trends: { d_B: 'IMPROVING_WITH_N' },
          convergence: { d_B: { verdict: 'IMPROVES_WITH_N', late_median_drift: 0.043, late_median_spread: 0.05, n_range: [366, 1095], asymptote: 1.571 } },
          finite_size_flow: { d_B: { d_star: 1.571, omega: 0.55, asymptote_gap: -0.014, residual_rms: 0.02, points: 6, omega_unresolved: false } },
          false_confidence_readings: 0,
          rows: [
            { n: 366, parameter: 5, seeds_planned: 10, seeds_present: 10, complete: true, channels: { d_B: { measured: 1.479, theory: 1.585, drift: 0.106, tolerance: 0.45, status: 'WITHIN_TOLERANCE', seed_std: 0.111, seed_refusals: 0, refusal_gates: {} } } },
            { n: 1095, parameter: 6, seeds_planned: 10, seeds_present: 10, complete: true, channels: { d_B: { measured: 1.628, theory: 1.585, drift: 0.043, tolerance: 0.45, status: 'WITHIN_TOLERANCE', seed_std: 0.05, seed_refusals: 1, refusal_gates: { 'not power-law': 1 } } } },
          ],
        },
        random_4_regular: {
          expectation: 'REFUSE', why: 'expander; no finite dimension', theory: {}, verdict: 'FAIL', complete: true,
          graph_varies_per_seed: true, dispersion_meaning: 'ensemble dispersion: each seed measures a different graph draw',
          trends: { d_s: null, d_w: null }, convergence: {}, finite_size_flow: {},
          false_confidence_readings: 1,
          rows: [
            { n: 256, parameter: 256, seeds_planned: 10, seeds_present: 10, complete: true, channels: {
              d_s: { measured: null, theory: null, drift: null, status: 'REFUSED_OK', per_seed: [null], seed_refusals: 10, refusal_gates: { 'model selection (AICc)': 10 } },
              d_w: { measured: 2.712, theory: null, drift: null, status: 'FALSE_CONFIDENCE', seed_std: 0.2, seed_refusals: 0, refusal_gates: {} } } },
          ],
        },
      },
      refusals: [
        { family: 'random_4_regular', n: 256, channel: 'd_s', gate: 'model selection (AICc)', count: 10, status: 'REFUSED_OK' },
        { family: 'sierpinski_gasket', n: 1095, channel: 'd_B', gate: 'not power-law', count: 1, status: 'WITHIN_TOLERANCE' },
      ],
      where_more_nodes_help: [{ family: 'sierpinski_gasket', channel: 'd_B', verdict: 'IMPROVES_WITH_N', n_range: [366, 1095], asymptote: 1.571 }],
      where_more_nodes_do_not_help: [], already_accurate: [], needs_more_seeds_not_more_nodes: [],
      reading_rule: [{ class: 'fractal', channel: 'd_B', n: 1024, median_bias: -0.05, families: 1 }],
      waivers_applied: [], waivers_expired: [],
    },
    sweep_scan: {
      generated_utc: '2026-08-30T15:05:00Z', build_number: 229,
      references: {
        candidate_sparse_anchor: {
          reference: 'candidate_sparse_anchor', seeds: 4, floor: 8,
          ess_recording_ceiling: 600, ramp: [30, 480],
          by_n: [{ n: 64, required_sweeps: 480, crossing_band: [30, 480], cells: [
            { sweeps: 30, median_ess: 12.5, ess_min: 6.1, ess_max: 14.2, resolved: false, meets_floor: false },
            { sweeps: 480, median_ess: 43.6, ess_min: 39.0, ess_max: 51.2, resolved: true, meets_floor: true },
          ] }],
          law: { status: 'fitted', best: 'linear(N)', fits: [{ law: 'linear(N)', log_rms: 0.02 }] },
        },
        candidate_founder_positive_control: {
          reference: 'candidate_founder_positive_control', seeds: 4, floor: 8,
          ess_recording_ceiling: 600, ramp: [30, 480],
          by_n: [{ n: 64, required_sweeps: null, crossing_band: [null, null], cells: [
            { sweeps: 480, median_ess: 4.2, ess_min: 2.0, ess_max: 6.3, resolved: true, meets_floor: false },
          ] }],
          law: { status: 'insufficient', detail: '0 rung(s) crossed the floor' },
        },
      },
    },
  };
  sandbox.GSD_APP.renderCalibration(table);
  const statusHtml = getElementById('calibStatus').innerHTML;
  if (!statusHtml.includes('calibration FAIL') || !statusHtml.includes('random_4_regular')) {
    throw new Error('the verdict line must be loud and name the failing family');
  }
  if (!statusHtml.includes('investigate before collecting data')) throw new Error('the summary line is not rendered');
  if (statusHtml.includes('NOT AUTHORITATIVE')) throw new Error('an authoritative table must not be marked non-authoritative');
  const probes = getElementById('calibProbes').innerHTML;
  if (!/of \d+ readings carried right/.test(probes) || !/checks the plumbing, not the probes/.test(probes)) {
    throw new Error(`the pipeline trial is not one line saying what it checks: ${probes.slice(0, 300)}`);
  }
  if (!probes.includes('theory')) throw new Error('probe table lacks the theory column');
  if (!probes.includes('1.3652')) throw new Error('theory value not rendered');
  if (!probes.includes('REFUSED')) throw new Error('a refused probe must be visible, not hidden');
  if (!probes.includes('calib-band')) throw new Error('the tolerance band must be drawn, not stated');
  const einstein = getElementById('calibEinstein').innerHTML;
  if (!einstein.includes('no d_s, d_V and d_w to tie together')) {
    throw new Error(`a table without an atlas does not say the Einstein relation has nothing to read: ${einstein}`);
  }
  const laddersHtml = getElementById('calibLadders').innerHTML;
  if (!laddersHtml.includes('sierpinski_gasket')) throw new Error('measure family missing');
  if (!laddersHtml.includes('calib-false-confidence')) {
    throw new Error('a false-confidence reading on the refusal anchor is not marked');
  }
  if (!laddersHtml.includes('refused \u2713')) {
    throw new Error('a correct refusal on the refusal anchor must be shown as correct');
  }
  if (!laddersHtml.includes('1 false-confidence')) throw new Error('the false-confidence count is not rendered');
  if (!laddersHtml.includes('0.111')) throw new Error('per-seed spread not rendered');
  if (!laddersHtml.includes('d*=1.571')) throw new Error('finite-size flow asymptote not rendered');
  if (!laddersHtml.includes('=0.55')) throw new Error('flow exponent not rendered');
  if (!laddersHtml.includes('calib-band-mark')) throw new Error('the tolerance band is not drawn on ladder cells');
  if (!laddersHtml.includes('graph varies per seed')) throw new Error('a family whose graph varies per seed must say so');
  if (!laddersHtml.includes('ensemble dispersion') || !laddersHtml.includes('estimator dispersion')) {
    throw new Error('the two meanings of seed spread must be stated, never presented as one number');
  }
  if (!laddersHtml.includes('d_B</b>: improves with N, within its seeds&#39; spread')) {
    throw new Error(`a family's convergence is not worded as the atlas words it: ${laddersHtml.slice(laddersHtml.indexOf('does more N'), laddersHtml.indexOf('does more N') + 200)}`);
  }
  const refusals = getElementById('calibRefusals').innerHTML;
  if (!refusals.includes('model selection (AICc)') || !refusals.includes('not power-law')) {
    throw new Error('refusals must be shown by the gate that refused them');
  }
  const sweeps = getElementById('calibSweeps').innerHTML;
  if (!sweeps.includes('calib-floor-met')) throw new Error('floor crossing is not marked');
  if (!sweeps.includes('calib-unresolved')) throw new Error('unresolved-tau cells are not marked');
  if (!sweeps.includes('480')) throw new Error('required sweeps not rendered');
  if (!sweeps.includes('candidate_sparse_anchor')) throw new Error('first reference missing');
  if (!sweeps.includes('candidate_founder_positive_control')) throw new Error('second reference missing');
  if (!sweeps.includes('39')) throw new Error('seed band not rendered');
  if (!sweeps.includes('&gt; 480')) throw new Error('a never-crossing rung must show > max(ramp)');
  if (!sweeps.includes('initial_sweeps_multiplier')) {
    throw new Error('the page must name the campaign-spec knob the evidence feeds');
  }
  if (!sweeps.includes('not the decision')) {
    throw new Error('the scan must present itself as evidence for the S0 decision, not the decision');
  }
  const prov = getElementById('calibProvenance').innerHTML;
  if (!prov.includes('Authoritative table') || !prov.includes('590 of 590') || !prov.includes('10 seed')) {
    throw new Error('provenance must say in plain language how many cells, how many seeds and whether authoritative');
  }
  if (!prov.includes('computed on hostA')) throw new Error('provenance must say where the table was computed');
  if (!prov.includes('2.0 h')) throw new Error('provenance must say how long the measurement took');
  if (!prov.includes('provenance only')) throw new Error('the build number must be labelled provenance, not a staleness key');

  const reduced = JSON.parse(JSON.stringify(table));
  reduced.authoritative = false;
  reduced.profile = { name: 'reduced', seeds: 2, max_nodes: 1100 };
  reduced.plan = { total_cells: 590, current: 300, stale: 0, missing: 290, failed: 0, complete: false };
  reduced.origin = { computed_on: 'hostB', adopted: true, adopted_from: 'host hostB', adopted_utc: '2026-09-01T11:00:00Z' };
  reduced.deviation.verdict = 'INCOMPLETE';
  reduced.deviation.summary_line = 'INCOMPLETE: 300 of 590 cells present';
  sandbox.GSD_APP.renderCalibration(reduced);
  const reducedStatus = getElementById('calibStatus').innerHTML;
  if (!reducedStatus.includes('NOT AUTHORITATIVE')) throw new Error('a non-authoritative table must be marked as such');
  if (reducedStatus.indexOf('NOT AUTHORITATIVE') > reducedStatus.indexOf('calibration INCOMPLETE')) {
    throw new Error('the non-authoritative warning must come before the verdict');
  }
  if (!reducedStatus.includes('2 seed') || !reducedStatus.includes('1100')) {
    throw new Error('a non-authoritative table must state its actual seed count and truncation');
  }
  if (!reducedStatus.includes('adopted from')) throw new Error('an adopted table must say so on the status strip');
  if (!getElementById('calibLadders').innerHTML.includes('table incomplete')) {
    throw new Error('an incomplete plan must be visible on the ladders');
  }
  if (!getElementById('calibProvenance').innerHTML.includes('NOT an authoritative table')) {
    throw new Error('provenance must repeat that the table is not authoritative');
  }
});

check('the calibration page charts the structure census and the rungs beyond the gate (524)', () => {
  const structure = (gap, diameter, extra) => Object.assign({ seeds: 1, gap, gap_method: 'shift_invert', diameter_lower: diameter,
    diameter_upper: diameter, giant_fraction: 1, degeneracy: 2, largest_clique: 2, largest_clique_exact: true, triangles_per_node: 0 }, extra || {});
  const row = (n, s, extra) => Object.assign({ n, parameter: n, seeds_planned: 10, seeds_present: 10, complete: true,
    channels: { d_s: { measured: 1.0, theory: 1.0, drift: 0.0, tolerance: 0.2, status: 'WITHIN_TOLERANCE', seed_refusals: 0, refusal_gates: {} } },
    structure: s }, extra || {});
  const table = {
    available: true, authoritative: true, profile: { name: 'full', seeds: 10 }, origin: {},
    plan: { total_cells: 20, current: 20, complete: true },
    deviation: { verdict: 'PASS', seeds: 10, families: { periodic_ring: {
      expectation: 'MEASURE', theory: { d_s: 1.0 }, verdict: 'PASS', trends: {}, convergence: {}, finite_size_flow: {},
      rows: [row(1024, structure(1.88e-5, 512)), row(4096, structure(1.18e-6, 2048, { gap_slope: -2.0, implied_d_s: 1.0, diameter_slope: 1.0, implied_d_f: 1.0 })),
             row(16384, null)],
      extension_rows: [row(4194304, structure(null, 2097152, { gap_reason: 'not computed above N=1048576', diameter_slope: 1.0, implied_d_f: 1.0 }),
                           { extension: true, seeds_planned: 3, seeds_present: 3 })],
    } } },
    atlas: { structure_readings: { periodic_ring: { finite_dimension: true, implied_spectral_dimension: 1.0,
                                                    implied_fractal_dimension: 1.0, why: 'gap exponent -2.000 <= -0.3752' } },
             structure_limits: { gap_max_n: 1048576, clique_max_n: 262144, square_max_n: 262144 } },
  };
  table.deviation.families.periodic_ring.extension_rows[0].structure.largest_clique = null;
  sandbox.GSD_APP.renderCalibration(table);
  const html = getElementById('calibLadders').innerHTML;
  const intro = fs.readFileSync(path.join(uiDir, 'index.html'), 'utf8');
  if ((intro.match(/gate nothing/g) || []).length !== 1) throw new Error('the page does not say once that those rows gate nothing');
  for (const needle of ['d_s from gap', 'd_f from diameter', '1.180e-6',
                        'no census yet', 'finite dimension', 'the gap implies d_s', '4194304']) {
    if (!html.includes(needle)) throw new Error(`calibration ladders lack ${needle}`);
  }
  const top = html.split('4194304')[1].split('</tr>')[0];
  if ((top.match(/<small>not measured<\/small>/g) || []).length !== 3) throw new Error(`the 4 M row does not say what is not measured: ${top}`);
  if (!top.includes('N=1,048,576') || !top.includes('N=262,144')) throw new Error(`the limits are not stated: ${top}`);
  const first = html.split('<b>1024</b>')[1].split('</tr>')[0];
  if (!first.includes('first rung')) throw new Error(`the first rung does not say why it has no slope: ${first}`);
  const middle = html.split('<b>4096</b>')[1].split('</tr>')[0];
  if (/not measured|first rung/.test(middle)) throw new Error(`a measured rung carries a reason it does not have: ${middle}`);
  table.atlas.structure_limits = { gap_max_n: 4194304, clique_max_n: 4194304, square_max_n: 4194304,
                                   before_531: { gap_max_n: 1048576, clique_max_n: 262144, square_max_n: 262144 } };
  sandbox.GSD_APP.renderCalibration(table);
  const now = getElementById('calibLadders').innerHTML.split('4194304')[1].split('</tr>')[0];
  if ((now.match(/<small>not measured yet<\/small>/g) || []).length !== 3) throw new Error(`the 4 M row does not say it waits for --structure: ${now}`);
  if (!now.includes('--structure')) throw new Error(`the way to measure it is not named: ${now}`);
});

check('every column header stays on one line: no rule lets a th break or wrap', () => {
  if (winning('th', 'white-space', 1700) !== 'nowrap') throw new Error('th is not nowrap');
  if (winning('th', 'overflow-wrap', 1700) !== 'normal') throw new Error('th still breaks anywhere');
  const flat = cssText.replace(/@media[^{]*\{/g, '');
  for (const block of flat.split('}')) {
    const brace = block.indexOf('{');
    if (brace < 0) continue;
    const selectors = block.slice(0, brace).split(',').map((s) => s.trim()).filter(Boolean);
    if (selectors.join(',') === 'th,td') continue;
    const heads = selectors.filter((s) => /^th([.:[]|$)/.test(s.split(/[\s>+~]+/).pop()));
    if (!heads.length) continue;
    const body = block.slice(brace + 1);
    const value = (name) => ((new RegExp(`(^|;)\\s*${name}\\s*:\\s*([^;]+)`)).exec(body) || [])[2];
    const wrap = value('overflow-wrap'), space = value('white-space'), breakWord = value('word-break');
    if ((wrap && wrap.trim() !== 'normal') || (space && !/nowrap/.test(space))
        || (breakWord && !/^(normal|keep-all)$/.test(breakWord.trim()))) {
      throw new Error(`${heads.join(', ')} lets a header wrap: ${body.trim().slice(0, 200)}`);
    }
  }
});

check('the calibration page explains itself when no table exists', () => {
  sandbox.GSD_APP.renderCalibration({ available: false,
    hint: 'no calibration table in force; main.py run computes it in the foreground before starting',
    expected_path: '/repo/calibration/probe_calibration.json' });
  const status = getElementById('calibStatus').innerHTML;
  if (!status.includes('probe_calibration.json') || !status.includes('foreground')) {
    throw new Error('the empty state does not tell the operator how the table gets populated');
  }
  const sweeps = getElementById('calibSweeps').innerHTML;
  if (!sweeps.includes('sweep-scan')) {
    throw new Error('the sweep panel does not name its producing command');
  }
});

function lawScore(score, by, chain, toN, points) {
  if (!score) return { score: 0, by: null, chain: null, to_n: null, top_n: 65536, points: 0, einstein: false };
  return { score, by: by || 'kept', chain: chain || (by === 'empty' ? 'empty' : by === 'random' ? 'random' : 'honeycomb'),
           to_n: toN || 65536, top_n: 65536, points: points || 15, points_of: 15, einstein: (points || 15) >= 14 };
}

function landscapeRow(overrides) {
  return Object.assign({
    candidate_id: '1522428b0a0aa94dfebe0909909cf5cd0b98ba7d7526dd68d3e7b639d889016d',
    ensemble_code: 'G-361-373', state: 'PARKED', law: 'Σd⁴ + neighbor Δd²',
    terms: [], mean_degree: 2.87, limit_hits: [],
    law_score: lawScore(0),
    stability_valid_rungs: { d_s: 0, d_V: 0, d_B: 0, d_w: 0 },
  }, overrides || {});
}

check('the top-100 renders with real landscape rows', () => {
  sandbox.GSD_APP.landscapePayload = { top_candidates: [
    landscapeRow({ law_score: lawScore(57, 'empty') }),
    landscapeRow({ candidate_id: 'c579643a'.padEnd(64, '0'), ensemble_code: 'G-1141-1153' }),
    landscapeRow({ candidate_id: 'd579643a'.padEnd(64, '0'), ensemble_code: 'G-1142-1154', law_score: null }),
  ] };
  sandbox.GSD_APP.renderTop();
  const html = getElementById('best').innerHTML;
  if (!html.includes('G-361-373')) throw new Error('top-100 rendered no rows');
  if (!html.includes('the chain from empty: 15 of 15 at N=65,536, all four agreeing by Einstein')) throw new Error(`the card does not say who built it: ${html}`);
  if (!html.includes('<span class=score>57</span>')) throw new Error('the score is not on the card');
  if (!html.includes('no probe settles on any start')) throw new Error('a law that scored 0 is not distinguished');
  if (!html.includes('not scored yet')) throw new Error('a law the board has not read is not distinguished');
  const unread = html.split('<a class="top-candidate').find((card) => card.includes('G-1142-1154')) || '';
  if (!unread.includes('\u2026') || unread.includes('<span class=score>0</span>')) {
    throw new Error(`a law not scored yet reads as 0: ${unread}`);
  }
});

check('the board shows the score read from every start', () => {
  sandbox.GSD_APP.landscapePayload = { top_candidates: [
    landscapeRow({ stability_score: 100.0, stability_display_score: 100, stability_approach_score: 100.0 })] };
  sandbox.GSD_APP.renderTop();
  const html = getElementById('best').innerHTML;
  if (!html.includes('<span class=score>0</span>')) throw new Error(`the score read from every start is not: ${html}`);
});

check('the leader panel names no leader while every law scores zero', () => {
  sandbox.GSD_APP.overviewPayload = { active: [] };
  sandbox.GSD_APP.landscapePayload = { top_candidates: [landscapeRow({}), landscapeRow({})] };
  sandbox.GSD_APP.leaderRow();
  const html = getElementById('leader').innerHTML;
  if (html.includes('G-361-373')) throw new Error('a zero-scoring law is presented as the leader');
  if (!html.includes('scored above zero')) throw new Error('the panel does not say what it is waiting for');
});

check('the leader panel names no leader the board has not read', () => {
  sandbox.GSD_APP.overviewPayload = { active: [] };
  sandbox.GSD_APP.landscapePayload = { top_candidates: [landscapeRow({ law_score: null })] };
  sandbox.GSD_APP.leaderRow();
  const html = getElementById('leader').innerHTML;
  if (html.includes('G-361-373')) throw new Error('a law not scored yet is presented as the leader');
  if (!html.includes('not scored yet')) throw new Error(`the panel does not say the first law is not scored yet: ${html}`);
});

check('a law that scored is named, with who built its geometry', () => {
  sandbox.GSD_APP.overviewPayload = { active: [] };
  sandbox.GSD_APP.landscapePayload = { top_candidates: [landscapeRow({ law_score: lawScore(17) })], lattice_who: LATTICE_WHO };
  sandbox.GSD_APP.leaderRow();
  const html = getElementById('leader').innerHTML;
  if (!html.includes('G-361-373')) throw new Error('a qualifying law is not named');
  if (!html.includes('>17<')) throw new Error('the leader lost its score');
  if (!html.includes('a lattice start, kept (honeycomb): 15 of 15 at N=65,536')) throw new Error(`the leader does not say who built it: ${html}`);
});

check('base-block work of another law is attributed to it', () => {
  sandbox.GSD_APP.overviewPayload = { active: [
    { candidate_id: 'other'.padEnd(64, '0'), ensemble_code: 'G-2581-2593',
      state: 'BASE_BLOCK_RUNNING', running: [{ n: 16384, started_utc: '2026-09-04T17:54:00Z' }] },
  ] };
  sandbox.GSD_APP.landscapePayload = { extension: { clears_floor: false, floor: 0.0 },
    top_candidates: [landscapeRow({ law_score: lawScore(17) })] };
  sandbox.GSD_APP.leaderRow();
  const html = getElementById('leader').innerHTML;
  if (!html.includes('a different law')) {
    throw new Error('the deep rung is not attributed to another law');
  }
});

check('the panel says what the best law is doing, not only what others are', () => {
  sandbox.GSD_APP.overviewPayload = { active: [
    { candidate_id: 'other'.padEnd(64, '0'), ensemble_code: 'G-30424',
      state: 'BASE_BLOCK_RUNNING', running: [{ n: 65536, started_utc: '2026-09-12T22:00:00Z' }] },
  ] };
  sandbox.GSD_APP.landscapePayload = {
    extension: { clears_floor: true, automatic: true, ready_at_floor: 664, floor: 0.0 },
    top_candidates: [landscapeRow({ law_score: lawScore(34, 'random'),
                                    state: 'PARKED' })] };
  sandbox.GSD_APP.leaderRow();
  const html = getElementById('leader').innerHTML;
  if (!/nothing is running for this law/.test(html)) {
    throw new Error(`the panel does not say the best law itself is idle: ${html}`);
  }
  if (!/a different law/.test(html)) {
    throw new Error('the deep rung is not marked as belonging to another law');
  }
  if (!/(C\d+-G30424|G-30424)\b/.test(html)) throw new Error('the deepest live work vanished');
  if (!/65536/.test(html)) throw new Error('the deepest rung vanished');
});


check('an unrecognised stage is not asserted to be a base rung', () => {
  sandbox.GSD_APP.overviewPayload = { active: [
    { candidate_id: 'other'.padEnd(64, '0'), ensemble_code: 'G-30424',
      state: 'BASE_BLOCK_RUNNING',
      running: [{ n: 65536, stage: 'continuation_x2', started_utc: '2026-09-13T11:00:00Z' }] },
  ] };
  sandbox.GSD_APP.landscapePayload = { extension: { clears_floor: true, automatic: true,
    ready_at_floor: 2511, ready_at_tier: 0, min_tier: 2, floor: 0.0 },
    top_candidates: [landscapeRow({ law_score: lawScore(34, 'random'),
                                    state: 'PARKED' })] };
  sandbox.GSD_APP.leaderRow();
  const html = getElementById('leader').innerHTML;
  const facts = (html.match(/<span class="deepest-run-facts">([\s\S]*?)<\/span><\/span>/) || [])[1] || '';
  if (!facts) throw new Error('the deepest-run facts did not render');
  if (/base rung/.test(facts)) {
    throw new Error(`a stage that never said "base" is reported as a base rung: ${facts}`);
  }
  if (!/does not say whether/.test(facts)) {
    throw new Error(`the unknown stage is not flagged as unknown: ${facts}`);
  }
});

check('the leader row says what the engine last decided for an idle best law, and nothing about an extender', () => {
  sandbox.GSD_APP.overviewPayload = { active: [] };
  sandbox.GSD_APP.landscapePayload = {
    top_candidates: [landscapeRow({ law_score: lawScore(34, 'random'), state: 'BASE_BLOCK_RUNNING',
      engine_decision: { action: 'hold', rule: 'unsettled', at_n: 4096, next_n: 16384 } })] };
  sandbox.GSD_APP.leaderRow();
  let html = getElementById('leader').innerHTML;
  if (!/engine: held at N=4096 \u00b7 unsettled/.test(html)) throw new Error(`the engine's decision is not stated: ${html}`);
  sandbox.GSD_APP.landscapePayload.top_candidates[0].engine_decision = null;
  sandbox.GSD_APP.leaderRow();
  html = getElementById('leader').innerHTML;
  if (/engine:/.test(html)) throw new Error(`an engine line is printed for a law the engine has not decided: ${html}`);
});

check('the leader row names a running rung\'s lane from the rung, not from its stage', () => {
  sandbox.GSD_APP.landscapePayload = { top_candidates: [landscapeRow({ law_score: lawScore(34, 'random') })] };
  const best = sandbox.GSD_APP.landscapePayload.top_candidates[0];
  sandbox.GSD_APP.overviewPayload = { active: [{ candidate_id: best.candidate_id, state: 'BASE_BLOCK_RUNNING',
    running: [{ n: 16384, lane: 'extension', stage: 'rung_n16384', started_utc: '2026-09-16T00:00:00Z' }] }] };
  sandbox.GSD_APP.leaderRow();
  const html = getElementById('leader').innerHTML;
  if (!/running a rung above its base block at N=16384/.test(html)) throw new Error(`the lane is not read from the rung: ${html}`);
  if (/running its base block at N=16384/.test(html)) throw new Error('a bought rung is called the base block');
});



check('the active count and the split are on two different surfaces, and neither elides', () => {
  sandbox.GSD_SYSTEM.updateHeader({
    compute_utilization: { simulation_busy: 1, analysis_busy: 16,
                           exposed_slots: 32, active_slots: 17, total_slots: 32 },
    system_resources: {}, runtime_counts: { compute: { core_seconds: 1119600 } },
    operational_bottleneck: { state: 'CPU_LIMITED' },
  }, 7);
  const head = String(getElementById('gsdCompute').textContent || '');
  const sub = String(getElementById('gsdComputeDetail').textContent || '');
  if (!/core-h/.test(sub)) throw new Error(`compute spent is not the subline: ${sub}`);
  const title = String(getElementById('gsdCompute').title || '');
  if (!/1 running a chain/.test(title) || !/16 running probes/.test(title)) {
    throw new Error(`the split is not on the tooltip either, so it was lost: ${title}`);
  }
  if (!/17 active/.test(head)) throw new Error('the headline lost its active count');
});

check('every ladder header fits on one line and carries one short, fixed explanation', () => {
  sandbox.GSD_APP.landscapePayload = { selection: { mechanisms: [
    { name: 'budget in work', rule: 'budget', from_n: null }, { name: 'too dense', rule: 'too_dense', from_n: 256 },
    { name: 'empty', rule: 'empty', from_n: 256 }, { name: 'disconnected', rule: 'disconnected', from_n: 1024 }] } };
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [{ n: 4096, running: 3, queued: 0, measured: 313,
    graphs: 939, stopped: 1, stopped_by_rule: { disconnected: 1 } }] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  const widths = [...html.matchAll(/<col style="width:(\d+)px">/g)].map((m) => +m[1]);
  const heads = [...html.match(/<thead>[\s\S]*?<\/thead>/)[0].matchAll(/<tr>([\s\S]*?)<\/tr>/g)].pop()[1];
  const names = [...heads.matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1].replace(/&amp;/g, '&'));
  if (widths.length !== names.length) throw new Error(`${widths.length} widths for ${names.length} headers`);
  names.forEach((name, i) => {
    if (name && widths[i] < name.length * 7 + 13) throw new Error(`"${name}" is wider than its ${widths[i]}px column`);
  });
  const titles = [...heads.matchAll(/<th([^>]*)>([^<]*)<\/th>/g)].map((m) => [m[2], ((m[1].match(/title="([^"]*)"/) || [])[1]) || '']);
  for (const [name, title] of titles) {
    const sentences = title.split(/[.;:]\s/).length;
    if (!title || title.length > 160 || sentences > 3 || /\d{3,}|applies (from|at)/.test(title)) {
      throw new Error(`787: every header has one short, fixed explanation: ${name} | ${title}`);
    }
  }
  const body = html.replace(/<thead>[\s\S]*?<\/thead>/, '');
  if (/title=/.test(body)) throw new Error(`787: no cell, foot or label of the ladder has a mouse-over: ${body}`);
});

check('the whole ladder fits the operator\u2019s screen, and no cell is wider than its column', () => {
  const rung = (n, extra) => Object.assign({ n, laws: 1021, attempts: 3063, interrupted: 17, graphs: 3063, running: 6,
    queued: 67, analysing: 1, queued_analyses: 22, simulation_seconds_total: 136800, probe_seconds_total: 17640,
    rung_seconds_total: 154440, compute_share: 0.291, stopped_by_rule: { empty: 201, too_dense: 183, disconnected: 280,
    over_budget: 8, no_finite_dimension: 1311, no_giant_component: 97 }, d_s_median_seconds: 250.1, d_V_median_seconds: 68.2, d_B_median_seconds: 49.8,
    d_w_median_seconds: 71.2, d_s_seconds_total: 34309, d_V_seconds_total: 17057, d_B_seconds_total: 17633,
    d_w_seconds_total: 25644, peak_bytes_p05: 4.3 * 2 ** 30, peak_bytes_median: 4.4 * 2 ** 30,
    peak_bytes_p95: 4.5 * 2 ** 30, reserved_over_observed: 13.98, p05_seconds: 605, median_seconds: 981,
    p95_seconds: 1704 }, extra || {});
  sandbox.GSD_APP.landscapePayload = null;
  const lawsAt = [30320, 30320, 22184, 9960, 1021, 708, 309, 60];
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576]
    .map((n, i) => { const still = i > 3 ? 12 : 0, left = lawsAt[i] - (lawsAt[i + 1] || 0) - still;
      return rung(n, { laws: lawsAt[i], left, still_here: still, left_by_rule: { starts_alike: left },
                       parked_by_rule: { starts_alike: Math.round(left / 2), starts_apart_twice: 7 } }); }) };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  if (!/>budget</.test(html) || !/>total</.test(html) || /does not close|still here|>gated</.test(html)) {
    throw new Error('the fleet\u2019s work measured for its width has the budget and the total, and no law column (872)');
  }
  const widths = [...html.matchAll(/<col style="width:(\d+)px">/g)].map((m) => +m[1]);
  const total = widths.reduce((a, b) => a + b, 0);
  if (total > 1650) throw new Error(`the ladder's columns add to ${total} px, wider than the 1,672 px a laptop screen gives it`);
  const rows = [...html.matchAll(/<tr( class=ladder-total)?>([\s\S]*?)<\/tr>/g)].map((m) => m[2]).filter((r) => /<td/.test(r));
  for (const row of rows) {
    [...row.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].forEach((m, i) => {
      const text = m[1].split(/<small|<span class="run-bar/)[0].replace(/<[^>]*>/g, '');
      if (text.length * 7 + 13 > widths[i]) throw new Error(`"${text}" does not fit its ${widths[i]} px column`);
    });
  }
  if (!/<code>N=1048576<\/code>/.test(html)) throw new Error('the deepest rung is not written out');
});

check('the System page states the memory floor admission reads', () => {
  const gib = (v) => `${(Number(v) / 2 ** 30).toFixed(2)} GiB`;
  const html = sandbox.GSD_APP.memoryAdmissionRow({ budget_bytes: 60 * 2 ** 30, admission: {
    floor_bytes: 10 * 2 ** 30, available_bytes: 38.9 * 2 ** 30, unrealised_bytes: 12.3 * 2 ** 30,
    headroom_bytes: 16.6 * 2 ** 30, shed_below_bytes: 8 * 2 ** 30 } }, gib);
  for (const needle of [/>floor</, /10\.00 GiB/, /38\.90 GiB available/, /12\.30 GiB still to be taken by running children/,
                        /16\.60 GiB headroom/, /simulations stop under 8\.00 GiB/]) {
    if (!needle.test(html)) throw new Error(`the floor row lacks ${needle}: ${html}`);
  }
  const none = sandbox.GSD_APP.memoryAdmissionRow({ budget_bytes: 2 ** 30, note: 'old ledger' }, gib);
  if (!/>budget</.test(none)) throw new Error('a ledger without the admission block lost its budget row');
});

check('a ladder with no rungs and only analysis says which', () => {
  sandbox.GSD_APP.overviewPayload = { active: [], analysis_backlog: 12,
    compute_utilization: { analysis_busy: 16 },
    rung_distribution: [{ n: 16384, running: 0, queued: 0, measured: 3709 }] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  if (!/working the analysis backlog/.test(html)) {
    throw new Error(`an all-analysis frame does not say so: ${html}`);
  }
});

check('a click on a box’s title folds it, the fold survives a poll and a reload, and a second click opens it', () => {
  const store = new Map();
  const priorStorage = sandbox.localStorage, priorDispatch = sandbox.dispatchEvent;
  sandbox.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
                           removeItem: (k) => store.delete(k) };
  const dispatched = [];
  sandbox.dispatchEvent = (event) => { dispatched.push(event && event.type); return true; };
  const page = (title) => {
    const h2 = makeElement('h2');
    h2.childNodes.push({ nodeType: 3, textContent: `${title} `, tagName: '#text', attributes: {}, dataset: {}, innerHTML: '' });
    const section = makeElement('section');
    section.querySelector = (sel) => (sel === ':scope>h2' ? h2 : null);
    const main = makeElement('main');
    main.dataset.page = 'home';
    main.querySelectorAll = (sel) => (sel === 'section.panel' ? [section] : []);
    const root = { querySelectorAll: (sel) => (sel === 'main.gsd-app-page' ? [main] : []) };
    return { h2, section, root };
  };
  try {
    const one = page('Fleet ladder');
    sandbox.GSD_APP.setUpFolds(one.root);
    sandbox.GSD_APP.setUpFolds(one.root);
    if (one.h2.dataset.fold !== 'home:Fleet ladder' || !one.h2.classList.contains('fold-title')) {
      throw new Error(`the title is not made foldable under its page and name: ${one.h2.dataset.fold}`);
    }
    if (one.section.classList.contains('folded') || one.h2.getAttribute('aria-expanded') !== 'true') {
      throw new Error('a box starts open where nothing was folded before');
    }
    one.h2.dispatch('click', { target: one.h2 });
    if (!one.section.classList.contains('folded') || one.h2.getAttribute('aria-expanded') !== 'false') {
      throw new Error('one click on the title does not fold the box once (a second setUpFolds must not bind it twice)');
    }
    if (JSON.parse(store.get('gsd-folded-panels') || '[]').join() !== 'home:Fleet ladder') {
      throw new Error(`the fold is not kept for the next visit: ${store.get('gsd-folded-panels')}`);
    }
    sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [{ n: 64, laws: 3, graphs: 9, stopped: 0, stopped_by_rule: {} }] };
    sandbox.GSD_APP.rungLadderRow();
    if (!one.section.classList.contains('folded')) throw new Error('a poll opened the folded box');
    const reload = page('Fleet ladder');
    sandbox.GSD_APP.setUpFolds(reload.root);
    if (!reload.section.classList.contains('folded')) throw new Error('a reload forgot the folded box');
    const inner = { closest: (sel) => (/button/.test(sel) ? {} : null) };
    reload.h2.dispatch('click', { target: inner });
    if (!reload.section.classList.contains('folded')) throw new Error('a click on a control inside the title folded or opened the box');
    reload.h2.dispatch('keydown', { key: 'Enter', preventDefault() {} });
    if (reload.section.classList.contains('folded') || store.get('gsd-folded-panels') !== '[]') {
      throw new Error('Enter on the title does not open the box and forget its fold');
    }
    if (dispatched.filter((t) => t === 'resize').length !== 2) throw new Error(`a fold and an open each ask the landscape to draw again at its new size: ${dispatched}`);
  } finally {
    sandbox.localStorage = priorStorage;
    sandbox.dispatchEvent = priorDispatch;
  }
  const css = fs.readFileSync(path.join(uiDir, 'system.css'), 'utf8');
  for (const rule of ['.panel.folded>:not(h2):not(.panel-title-row)', '.hero>.panel.folded{height:auto', '.panel.folded h2.fold-title::before']) {
    if (!css.includes(rule)) throw new Error(`system.css lacks ${rule}`);
  }
  const index = fs.readFileSync(path.join(uiDir, 'index.html'), 'utf8');
  const sections = index.split('<section class="panel').slice(1).map((s) => s.slice(0, s.indexOf('</section>')));
  const untitled = sections.filter((s) => !/<h2[ >]/.test(s));
  if (sections.length < 20 || untitled.length) throw new Error(`every box on the pages has a title to fold it by: ${untitled.length} without`);
});

check('a rung whose runs are all under way shows their live values: the graphs being grown and the memory held so far, marked + (893, 10:42)', () => {
  const G = 2 ** 30;
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [
    { n: 65536, running: 0, queued: 0, graphs: 3, chains: 24, chains_per_seed: 8, completed: 3, peak_bytes_min: 1.0 * G,
      peak_bytes_median: 1.0 * G, peak_bytes_p95: 1.1 * G, peak_bytes_max: 1.1 * G, median_seconds: 1500, max_seconds: 1800,
      simulation_seconds_total: 4500, rung_seconds_total: 4500 },
    { n: 262144, running: 3, running_laws: 1, queued: 0, graphs: 0, chains_per_seed: 8, running_graphs: 24,
      running_peak_bytes: 3.4 * G, running_memory_bytes: 9.9 * G, max_seconds: 4800, max_unfinished: true,
      longest_unfinished_seconds: 4800, running_seconds: 14400, simulation_seconds_total: 0, rung_seconds_total: 0 }] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  const row = (html.split('N=262144</code>')[1] || '').split('</tr>')[0];
  for (const want of ['>24+<', '>–/–/–/3.4 G+<', '>–/–/–/1h20m+<']) {
    if (!row.includes(want)) throw new Error(`the rung under way lacks "${want}": ${row}`);
  }
  const done = (html.split('N=65536</code>')[1] || '').split('</tr>')[0];
  if (!done.includes('>24<') || !done.includes('>1.0/1.0/1.1/1.1 G<')) throw new Error(`a finished rung reads as before: ${done}`);
});

check('a size whose seeds are bought and not grown shows none grown, of those bought, and those under way (898)', () => {
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [
    { n: 262144, running: 0, queued: 0, graphs: 22, completed: 22, chains: 176, chains_per_seed: 8 },
    { n: 1048576, running: 3, running_laws: 1, queued: 5, graphs: 8, completed: 0, chains: 64, chains_per_seed: 8,
      running_graphs: 24, max_unfinished: true, longest_unfinished_seconds: 12780 }] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  const row = (html.split('N=1048576</code>')[1] || '').split('</tr>')[0];
  if (!row.includes('>0<small class=ladder-share>of 64</small><small class=ladder-share>+24 now</small>')) {
    throw new Error(`178 read 64 graphs at 1,048,576 with none grown: ${row}`);
  }
  const below = (html.split('N=262144</code>')[1] || '').split('</tr>')[0];
  if (!below.includes('>176<') || below.includes('of 176')) throw new Error(`a size grown whole reads as before: ${below}`);
  const foot = (html.split('<b>all</b>')[1] || '');
  if (!foot.includes('<b>176</b><small class=ladder-share>of 240</small>')) throw new Error(`the total counts the grown: ${foot.slice(0, 600)}`);
});

check('the ladder panel answers how many graphs are in each bracket', () => {
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [
    { n: 64, running: 0, queued: 0, measured: 7600, attempts: 22761,
      median_seconds: 2.4, p90_seconds: 5.1, max_seconds: 61.0,
      graphs: 10, completed: 10, stopped: 0,
      d_s_seconds_total: 100.0, d_V_seconds_total: 50.0,
      d_B_seconds_total: 60.0, d_w_seconds_total: 58.0, probe_seconds_total: 268.0,
      simulation_seconds_total: 2000.0, rung_seconds_total: 2268.0, compute_share: 0.0316 },
    { n: 16384, running: 21, queued: 480, running_laws: 20, queued_laws: 170, measured: 7418, attempts: 11205,
      median_seconds: 39.7, p90_seconds: 180.0, max_seconds: 4200.0, max_unfinished: true,
      peak_bytes_min: 2.1 * 2 ** 30, peak_bytes_median: 2.3 * 2 ** 30, peak_bytes_p95: 2.6 * 2 ** 30,
      peak_bytes_max: 2.9 * 2 ** 30,
      graphs: 12, completed: 6, abandoned: 0, stopped: 6, stopped_by_rule: { over_budget: 4, disconnected: 2 },
      interrupted: 3, interrupted_seconds: 5400.0,
      d_s_seconds_total: 2000.0, d_V_seconds_total: 500.0,
      d_B_seconds_total: 1500.0, d_w_seconds_total: 1000.0, probe_seconds_total: 5000.0,
      simulation_seconds_total: 20000.0, rung_seconds_total: 25000.0, compute_share: 0.3484 },
    { n: 65536, running: 11, queued: 2603, running_laws: 12, queued_laws: 870, measured: 93, attempts: 915,
      median_seconds: 42.2, p90_seconds: 220.0, max_seconds: 980.0,
      graphs: 8, completed: 4, stopped: 0,
      d_s_median_seconds: 1.75, d_V_median_seconds: 0.58,
      d_B_median_seconds: 1.79, d_w_median_seconds: 1.76,
      kappa_median_seconds: 7.3,
      d_s_seconds_total: 2520.0, d_V_seconds_total: 840.0,
      d_B_seconds_total: 1260.0, d_w_seconds_total: 1260.0,
      probe_seconds_total: 5880.0,
      peak_bytes_median: 878795776, peak_bytes_p90: 1430720512,
      peak_bytes_p05: 31457280, peak_bytes_p95: 1468006400, peak_bytes_min: 31457280, peak_bytes_max: 1610612736,
      p05_seconds: 12.0, p95_seconds: 280.0, min_seconds: 3.0,
      reserved_bytes_median: 2113929216, reserved_over_observed: 2.41,
      memory_timed_attempts: 915,
      simulation_seconds_total: 38610.0, rung_seconds_total: 44490.0, running_seconds: 9000.0,
      compute_share: 0.62 },
    { n: 262144, running: 0, queued: 0, measured: 0, chains_per_seed: 8, seeds_per_law: 3 },
  ] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  for (const n of ['N=64', 'N=16384', 'N=65536', 'N=262144']) {
    if (!html.includes(n)) throw new Error(`${n} is missing from the ladder panel`);
  }
  if (!/7\.3s?[\/<]/.test(html)) throw new Error(`the curvature probe's median did not render: ${html}`);
  for (const h of ['>d_s<', '>d_V<', '>d_B<', '>d_w<', '>curv<', '>etime<', '>ptime<', '>running<',
                   '>queue<', '>total<', '>time per seed<', '>budget<', '>cut<', '>sum<',
                   '>evolving laws \u00b7 a law at a size = 3 seeds \u00d7 8 starts = 24 graphs<', '>probing laws \u00b7 a law at a size = 3 seeds \u00d7 8 starts = 24 graphs<',
                   '>graphs<', '>memory<', '>ratio<',
                   '>evolving laws \u00b7 a law at a size = 3 seeds \u00d7 8 starts = 24 graphs<', '>probing laws \u00b7 a law at a size = 3 seeds \u00d7 8 starts = 24 graphs<', '>totals<']) {
    if (!html.includes(h)) throw new Error(`ladder is missing the ${h} column: ${html}`);
  }
  if (html.includes('>res/obs<')) throw new Error('the res/obs header was renamed to reserved/used');
  if (!/30M\/838M\/1\.4G\/1\.5G</.test(html)) {
    throw new Error(`the memory band rendered no value: ${html}`);
  }
  if (!/<b>66%<\/b>/.test(html)) throw new Error(`the compute share, the seeds evolving now counted, did not render: ${html}`);
  if (!/\/1\.5G</.test(html)) {
    throw new Error(`the heaviest run did not render after the median and the heaviest 5%: ${html}`);
  }
  if (!/<b>2\.41x<\/b>/.test(html)) {
    throw new Error('a res/obs ratio at 2.41 must be marked: above ~1.5 the '
      + 'reservation model is withholding memory the children do not use');
  }
  for (const v of ['1.8s', '580ms', '1.8s']) {
    if (!html.includes(v)) throw new Error(`a probe column rendered no value: ${html}`);
  }
  const totalRow = (html.match(/<tr class=ladder-total>[\s\S]*?<\/tr>/) || [''])[0];
  const bodyOnlyRows = html.slice(html.indexOf('<tbody>'), html.indexOf('</tbody>'));
  if (!totalRow) throw new Error(`the ladder has no totals row: ${html}`);
  if (!/<b>100%<\/b>/.test(totalRow)) {
    throw new Error(`the totals row must read 100% share: ${totalRow}`);
  }
  if (!/<b>32<\/b>/.test(totalRow)) {
    throw new Error(`the running total is wrong or absent: ${totalRow}`);
  }
  if (!/<b>1040<\/b>/.test(totalRow)) throw new Error('the queued total, in laws, is wrong or absent');
  const headerCells = (html.match(/<thead>[\s\S]*?<\/thead>/) || [''])[0]
    .split('</tr>')[1].match(/<th[^>]*>(.*?)<\/th>/g) || [];
  const columnAt = {};
  headerCells.forEach((cell, index) => {
    const name = cell.replace(/<[^>]*>/g, '').trim();
    const group = (cell.match(/g-(cand|evolve|probe|total)/) || [])[1] || '';
    if (name && !(name in columnAt)) columnAt[name] = index;
    if (name) columnAt[`${group}:${name}`] = index;
  });
  const footCells = totalRow.match(/<td[^>]*>.*?<\/td>/g) || [];
  if (footCells.length !== headerCells.length) {
    throw new Error(`the foot row has ${footCells.length} cells against ${headerCells.length} headers`);
  }
  for (const name of ['evolve:etime', 'd_s', 'd_V', 'd_B', 'd_w', 'probe:ptime', 'total']) {
    const cell = footCells[columnAt[name]];
    if (cell === undefined) throw new Error(`no ${name} column in the ladder header`);
    if (!/<b>/.test(cell)) throw new Error(`the foot row has no ${name} total: ${cell}`);
  }
  for (const name of ['memory', 'ratio', 'time per seed']) {
    const cell = footCells[columnAt[name]];
    if (/<b>/.test(cell)) throw new Error(`${name} was summed in the foot row: ${cell}`);
  }
  const shareOf = name => {
    const cell = footCells[columnAt[name]];
    const m = cell && cell.match(/<small class=ladder-share>([0-9.]+)%<\/small>/);
    if (!m) throw new Error(`the ${name} foot cell carries no share: ${cell}`);
    return Number(m[1]);
  };
  const evolveShare = shareOf('evolve:etime'), probesShare = shareOf('probe:ptime');
  const probeShares = ['d_s', 'd_V', 'd_B', 'd_w'].map(shareOf);
  if (Math.abs(evolveShare + probesShare - 100) > 0.15) {
    throw new Error(`evolving ${evolveShare}% + probing ${probesShare}% is not 100%`);
  }
  const fourProbes = probeShares.reduce((a, b) => a + b, 0);
  if (Math.abs(fourProbes - probesShare) > 0.25) {
    throw new Error(`the four probe shares add to ${fourProbes}%, the probes column says ${probesShare}%`);
  }
  if (evolveShare !== 86.2 || probesShare !== 13.8) {
    throw new Error(`foot shares read ${evolveShare}% / ${probesShare}%, expected 86.2% / 13.8%, the seeds evolving now in the whole of both`);
  }
  const bodyRows = bodyOnlyRows.split('</tr>').filter(row => /<td/.test(row));
  for (const row of bodyRows) {
    const cells = row.match(/<td[^>]*>[\s\S]*?<\/td>/g) || [];
    const share = cell => { const m = cell && cell.match(/<small class=ladder-share>([0-9.]+)%<\/small>/); return m ? Number(m[1]) : null; };
    const e = share(cells[columnAt['evolve:etime']]), q = share(cells[columnAt['probe:ptime']]);
    if (e !== null && q !== null && Math.abs(e + q - 100) > 0.15) {
      throw new Error(`a rung's etime ${e}% and ptime ${q}% add to ${e + q}%, not 100%: ${row}`);
    }
  }
  const deep = bodyRows.find(row => row.includes('N=65536')) || '';
  const deepCells = deep.match(/<td[^>]*>[\s\S]*?<\/td>/g) || [];
  if (!/89\.0%/.test(deepCells[columnAt['evolve:etime']] || '') || !/11\.0%/.test(deepCells[columnAt['probe:ptime']] || '')) {
    throw new Error(`with seeds evolving at 65,536, etime and ptime are shares of one whole, 89.0% and 11.0%: ${deep}`);
  }
  if (!/<b>19h20m<\/b>/.test(footCells[columnAt['evolve:etime']])) {
    throw new Error(`the evolve total is not the sum of the rungs: ${footCells[columnAt['evolve:etime']]}`);
  }
  if (!/13h14m<small class=ladder-share>89\.0%<\/small>/.test(html)) {
    throw new Error(`the per-rung all-runs cell did not render its sum and share: ${html}`);
  }
  if (columnAt['discon'] !== undefined || columnAt['empty'] !== undefined) {
    throw new Error('the stops by rule are the selection\u2019s ladder now, not the fleet\u2019s work (872)');
  }
  if (/halted/.test(html) || /run before the interruption/.test(html)) {
    throw new Error(`the graphs cell carries no halted note since 791, nor a cell seconds in a hover: ${html}`);
  }
  if (!/<small class=ladder-share><b>100%<\/b><\/small>/.test(footCells[columnAt['total']]) || columnAt['share'] !== undefined) {
    throw new Error('the rung\u2019s share is a line under its total, 100% in the foot row, not a column of its own (2026-11-14)');
  }
  if (!/1h38m<small class=ladder-share>11\.0%<\/small>/.test(html)) {
    throw new Error(`the per-rung all-probes cell did not render its sum and share: ${html}`);
  }
  const colgroup = (html.match(/<colgroup>[\s\S]*?<\/colgroup>/) || [''])[0];
  const cols = (colgroup.match(/<col[ >]/g) || []).length;
  if (cols !== headerCells.length) {
    throw new Error(`the colgroup has ${cols} columns against ${headerCells.length} headers`);
  }
  const peakHead = headerCells[columnAt['memory']];
  if (!/nowrap/.test(peakHead)) throw new Error(`the memory column is not nowrap: ${peakHead}`);
  const peakCol = (colgroup.match(/<col[^>]*>/g) || [])[columnAt['memory']] || '';
  if (!/width:\d+px/.test(peakCol)) throw new Error(`the memory column has no width: ${peakCol}`);
  if (!/>2\.1\/2\.3\/2\.6\/2\.9 G</.test(html)) {
    throw new Error(`a memory band in one unit does not carry it once: ${html}`);
  }
  if (!/>3\.0s\/42s\/4m40s\/16m</.test(html)) {
    throw new Error(`the time band did not render min/median/p95/max: ${html}`);
  }
  if (!/>\u2013\/40s\/\u2013\/1h10m\+</.test(html)) {
    throw new Error(`a max from a seed still running is not marked +: ${html}`);
  }
  if (!/>30M\/838M\/1\.4G\/1\.5G</.test(html)) {
    throw new Error(`the memory band did not render min/median/p95/max, each in its own unit: ${html}`);
  }
  for (const name of ['total']) {
    if (!/g-total/.test(headerCells[columnAt[name]])) {
      throw new Error(`${name} is not in the totals group: ${headerCells[columnAt[name]]}`);
    }
  }
  for (const name of ['time per seed', 'memory', 'ratio', 'evolve:etime']) {
    if (!/g-evolve/.test(headerCells[columnAt[name]])) {
      throw new Error(`${name} is not under evolving the graph: ${headerCells[columnAt[name]]}`);
    }
  }
  if (columnAt['evolve:etime'] + 1 !== columnAt['probe:running'] || columnAt['probe:ptime'] + 1 !== columnAt['total']) {
    throw new Error('each phase does not end on its own sum');
  }
  if (columnAt['graphs'] + 1 !== columnAt['evolve:running']) {
    throw new Error('with no selection read, the evolving work follows the graphs (872)');
  }
  if (!/<th class="g-total" colspan=1>totals<\/th>/.test(html) || !/<th class="g-cand" colspan=5>candidates<\/th>/.test(html)) {
    throw new Error(`the group headers do not span their columns: ${html}`);
  }
  const firstBodyRow = (bodyOnlyRows.match(/<tr>[\s\S]*?<\/tr>/) || [''])[0];
  const bodyCells = firstBodyRow.match(/<td[^>]*>.*?<\/td>/g) || [];
  if (bodyCells.length !== headerCells.length) {
    throw new Error(`a body row has ${bodyCells.length} cells against ${headerCells.length} headers`);
  }
  for (let i = 0; i < headerCells.length; i += 1) {
    const headGroup = (headerCells[i].match(/g-(cand|stop|evolve|probe|total)/) || [])[1] || '';
    const cellGroup = (bodyCells[i].match(/g-(cand|stop|evolve|probe|total)/) || [])[1] || '';
    if (headGroup !== cellGroup) {
      throw new Error(`column ${i} is "${headerCells[i]}" but its cell is "${bodyCells[i]}": `
        + 'a cell landed under the wrong header, which is build 425\'s defect');
    }
  }
  if (html.includes('7418')) throw new Error('the laws reached are the selection\u2019s ladder now (872)');
  if (!/<td class="num g-cand">6<small class=ladder-share>of 12<\/small><\/td>/.test(html) || html.includes('11205')) {
    throw new Error('the ladder does not show graphs where it showed attempts, those grown of those bought (898)');
  }
  for (const header of ['evolving laws \u00b7 a law at a size = 3 seeds \u00d7 8 starts = 24 graphs', 'probing laws \u00b7 a law at a size = 3 seeds \u00d7 8 starts = 24 graphs', 'totals', 'memory', 'ratio']) {
    if (!html.includes(`>${header}<`)) throw new Error(`the ${header} column is missing`);
  }
  const bodyOnly = html.slice(html.indexOf('<tbody>'), html.indexOf('</tbody>'));
  const last = bodyOnly.slice(bodyOnly.lastIndexOf('N=262144'));
  if (/>0(\.0)?s</.test(last)) {
    throw new Error('an unmeasured rung reports a duration of zero');
  }
});

check('the ladder closes: stopped total, done on the laws number, the budget and the four probes summed (2026-11-14)', () => {
  if (!getElementById('rungLadder')) throw new Error('no ladder element');
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [
    { n: 16384, laws: 155, graphs: 465, completed: 465, chains_per_seed: 8, seeds_per_law: 3, left: 97, stopped: 97,
      stopped_by_rule: { empty: 18, too_dense: 10, disconnected: 9, over_budget: 8, starts_alike: 52 },
      parked_by_rule: { starts_alike: 52 }, done: 0, done_by_rule: {}, still_here: 0,
      median_seconds: 115.0, p05_seconds: 5.0, p95_seconds: 1200.0, max_seconds: 4804.0, work_budget: 7500000000000,
      budget_seconds: 1200.0,
      d_s_median_seconds: 14.0, d_V_median_seconds: 1.7, d_B_median_seconds: 0.7, d_w_median_seconds: 6.3,
      kappa_median_seconds: 0.3,
      d_s_seconds_total: 1000.0, d_V_seconds_total: 100.0, d_B_seconds_total: 50.0, d_w_seconds_total: 400.0,
      probe_seconds_total: 1560.0, simulation_seconds_total: 118000.0, rung_seconds_total: 119560.0,
      reserved_bytes_median: 1289093530, fallback_reservation_bytes: 1289093530, peak_bytes_median: 83886080,
      reserved_over_observed: 15.37, compute_share: 0.45 },
    { n: 65536, laws: 58, graphs: 174, completed: 174, chains_per_seed: 8, left: 58, stopped: 18,
      stopped_by_rule: { empty: 13, disconnected: 5 }, done: 40, done_by_rule: { ladder_complete: 40 },
      still_here: 0, work_budget: 90000000000000, budget_seconds: 14400.0, max_seconds: 7686.0,
      probe_seconds_total: 13740.0, simulation_seconds_total: 146833.0, rung_seconds_total: 160573.0,
      compute_share: 0.55 },
  ] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  const headerCells = (html.match(/<thead>[\s\S]*?<\/thead>/) || [''])[0]
    .split('</tr>')[1].match(/<th[^>]*>(.*?)<\/th>/g) || [];
  const at = {};
  headerCells.forEach((cell, index) => {
    const name = cell.replace(/<[^>]*>/g, '').trim();
    const group = (cell.match(/g-(cand|stop|evolve|probe|total)/) || [])[1] || '';
    at[`${group}:${name}`] = index;
  });
  const bodyRows = (html.slice(html.indexOf('<tbody>'), html.indexOf('</tbody>')).match(/<tr>[\s\S]*?<\/tr>/g) || [])
    .map(row => row.match(/<td[^>]*>.*?<\/td>/g) || []);
  const foot = (html.match(/<tr class=ladder-total>[\s\S]*?<\/tr>/) || [''])[0].match(/<td[^>]*>.*?<\/td>/g) || [];
  const last = bodyRows[1];
  if (at['stop:total'] !== undefined || at['cand:laws'] === undefined) throw new Error('893: the candidates read the selection, its stops only once it is read');
  if (at['evolve:budget'] !== at['evolve:time per seed'] + 1) throw new Error('the budget does not stand beside the per-seed band');
  const first = bodyRows[0][at['evolve:budget']], top = last[at['evolve:budget']];
  if (!/>7\.5 T<\/td>/.test(first) || !/>90 T<\/td>/.test(top) || /title=|units|\u2248/.test(first + top)) {
    throw new Error(`the rung's budget is its work alone, no word "units", no sandbox time and no mouse-over: ${first} / ${top}`);
  }
  if (at['probe:sum'] + 1 !== at['probe:ptime']) throw new Error('the four probes\u2019 sum does not stand right before ptime');
  if (!/>23s<\/td>/.test(bodyRows[0][at['probe:sum']])) {
    throw new Error(`the four medians 14 + 1.7 + 0.7 + 6.3 do not add to 23s: ${bodyRows[0][at['probe:sum']]}`);
  }
  if (!/<b>25m50s<\/b>/.test(foot[at['probe:sum']])) throw new Error(`the foot's sum is not the four probes' totals: ${foot[at['probe:sum']]}`);
  if (/>0\.0s\/0\.0s\/0\.0s</.test(last[at['evolve:time per seed']])) {
    throw new Error('a rung with no timed run shows a band of zeros instead of a dash');
  }
  if (!/>\u2013\/\u2013\/\u2013\/2h08m<\/td>/.test(last[at['evolve:time per seed']])) {
    throw new Error(`a rung whose only time is its longest does not show it: ${last[at['evolve:time per seed']]}`);
  }
  if (/title=/.test(html.replace(/<thead>[\s\S]*?<\/thead>/, ''))) throw new Error('787: only the headers carry a mouse-over');
});

check('a probe cell is the median over the seeds the probe ran on, milliseconds under a second, the share it ran on beneath when not all (839)', () => {
  const probes = (values) => Object.assign({}, ...Object.entries(values).map(([p, [all, ran, timed, own]]) => ({
    [`${p}_median_seconds`]: all, [`${p}_ran`]: ran, [`${p}_timed`]: timed, [`${p}_ran_median_seconds`]: own })));
  sandbox.GSD_APP.landscapePayload = null;
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [
    Object.assign({ n: 64, laws: 2500, graphs: 60000, chains_per_seed: 8, seeds_per_law: 3, probe_timed_measurements: 2643 },
      probes({ d_s: [0.677, 2643, 2643, 0.677], d_V: [0.022, 2643, 2643, 0.022], d_B: [0, 0, 2643, null],
               d_w: [0.219, 2643, 2643, 0.22] })),
    Object.assign({ n: 256, laws: 2500, graphs: 60000, chains_per_seed: 8, seeds_per_law: 3, probe_timed_measurements: 2475 },
      probes({ d_s: [1.007, 2475, 2475, 1.007], d_V: [0.115, 2450, 2475, 0.116], d_B: [0, 3, 2475, 0.0004],
               d_w: [0.441, 2376, 2475, 0.444] })),
    Object.assign({ n: 65536, laws: 66, graphs: 1584, chains_per_seed: 8, seeds_per_law: 3, probe_timed_measurements: 180 },
      probes({ d_s: [77.953, 180, 180, 77.953], d_V: [13.489, 180, 180, 13.489], d_B: [0, 87, 180, 10.946],
               d_w: [28.978, 180, 180, 28.978] }))] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  const heads = (html.match(/<thead>[\s\S]*?<\/thead>/) || [''])[0].split('</tr>')[1].match(/<th[^>]*>(.*?)<\/th>/g) || [];
  const at = {};
  heads.forEach((cell, index) => { at[cell.replace(/<[^>]*>/g, '').trim()] = index; });
  const rows = (html.slice(html.indexOf('<tbody>'), html.indexOf('</tbody>')).match(/<tr>[\s\S]*?<\/tr>/g) || [])
    .map((row) => (row.match(/<td[^>]*>.*?<\/td>/g) || []).map((cell) => cell.replace(/^<td[^>]*>|<\/td>$/g, '')));
  const want = [
    { d_s: '677ms', d_V: '22ms', d_B: /^<span class=muted>[^<]<\/span><small class=ladder-share>0%<\/small>$/, d_w: '220ms', sum: '919ms' },
    { d_s: '1.0s', d_V: '116ms', d_B: '1ms<small class=ladder-share>&lt;1%</small>', d_w: '444ms', sum: '1.6s' },
    { d_s: '1m18s', d_V: '13s', d_B: '11s<small class=ladder-share>48%</small>', d_w: '29s', sum: '2m11s' }];
  want.forEach((cells, i) => {
    for (const [name, text] of Object.entries(cells)) {
      const cell = rows[i][at[name]];
      if (text instanceof RegExp ? !text.test(cell) : cell !== text) throw new Error(`row ${i}, ${name}: ${cell} is not ${text}`);
    }
  });
  if (/0\.0s/.test(rows.map((r) => [at.d_s, at.d_V, at.d_B, at.d_w].map((i) => r[i]).join(' ')).join(' '))) {
    throw new Error('a probe that refused at once on every seed still reads 0.0s');
  }
  if (/ladder-share/.test(rows[1][at.d_V] + rows[1][at.d_w])) {
    throw new Error('a probe that refused at once on 1 or 4 seeds in 100, which leaves its median where it was, carries no share');
  }
  if (/title=/.test(html.replace(/<thead>[\s\S]*?<\/thead>/, ''))) throw new Error('787: only the headers carry a mouse-over');
  const head = (html.match(/<th[^>]*title="([^"]*)"[^>]*>d_B<\/th>/) || [])[1] || '';
  if (!/over the seeds it ran on/.test(head) || !/under it their share/.test(head)) {
    throw new Error(`the header says what the cell and the share under it are: ${head}`);
  }
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [
    { n: 4096, laws: 9, graphs: 216, d_s_median_seconds: 14.0, d_V_median_seconds: 1.7, d_B_median_seconds: 0.7,
      d_w_median_seconds: 6.3 }] };
  sandbox.GSD_APP.rungLadderRow();
  const older = getElementById('rungLadder').innerHTML;
  if (!/>700ms<\/td>/.test(older) || !/>23s<\/td>/.test(older) || /ladder-share>\d+%/.test(older.slice(older.indexOf('<tbody>'), older.indexOf('</tbody>')).split('g-probe').slice(3, 7).join(''))) {
    throw new Error('a ladder recorded before the counts shows its medians as they were, no share beneath');
  }
});

check('no page calls d_V a Hausdorff dimension: each mention says it is not one', () => {
  for (const file of ['app.js', 'candidate.html', 'system.js', 'terms.js', 'index.html']) {
    const full = path.join(uiDir, file);
    if (!fs.existsSync(full)) continue;
    const text = fs.readFileSync(full, 'utf8');
    for (const m of text.matchAll(/Hausdorff/g)) {
      const around = text.slice(Math.max(0, m.index - 12), m.index + 40);
      if (!/[Nn]ot a Hausdorff|has Hausdorff dimension exactly zero/.test(around)) {
        throw new Error(`${file} names a Hausdorff dimension without saying d_V is not one: ${text.slice(Math.max(0, m.index - 80), m.index + 60)}`);
      }
    }
  }
});

check('the explorer caps rendered rows and debounces the search box', () => {
  const app = fs.readFileSync(path.join(uiDir, 'app.js'), 'utf8');
  if (!/EXPLORER_ROW_CAP\s*=\s*1000/.test(app)) throw new Error('the row cap is not 1000');
  if (!/EXPLORER_TYPING_DELAY_MS\s*=\s*500/.test(app)) throw new Error('no typing delay');
  if (!/id==='explorerQ'\?drawExplorerSoon:drawExplorer/.test(app)) {
    throw new Error('the debounce is not scoped to the search box');
  }
});

check('a law of every batch together is never named Cstudy (674), and a law of a study is named Sn-Cn-Gn (871, dashed at 882)', () => {
  const app = sandbox.GSD_APP, sys = sandbox.GSD_SYSTEM, rows = sys.campaignRows;
  try {
    sys.campaignRows = [{ campaign_id: '3', study: '176' }, { campaign_id: '4' }];
    if (app.lawCode({ ensemble_code: 'G-33430' }, 'study') !== 'G-33430') throw new Error('the study scope named a law\'s campaign');
    if (app.lawCode({ ensemble_code: 'G-33430', campaign_id: '3' }) !== 'S176-C3-G33430') throw new Error(app.lawCode({ ensemble_code: 'G-33430', campaign_id: '3' }));
    if (app.lawCode({ ensemble_code: 'G-79', campaign_id: '4' }) !== 'C4-G79') throw new Error('a campaign of no study lost its code');
    if (sys.lawCode('3', null, 'ab12cd34ef') !== 'S176-C3-ab12cd34') throw new Error(sys.lawCode('3', null, 'ab12cd34ef'));
    const read = (q) => JSON.stringify(app.lawCodeQuery(q));
    for (const [q, want] of [['S176C11G79', { study: '176', campaign: '11', ordinal: 79 }], ['s176-c11-g79', { study: '176', campaign: '11', ordinal: 79 }],
                             ['C11-G79', { study: null, campaign: '11', ordinal: 79 }], ['g79', { study: null, campaign: null, ordinal: 79 }]]) {
      if (read(q) !== JSON.stringify(want)) throw new Error(`${q} reads ${read(q)}`);
    }
    if (app.lawCodeQuery('ring') !== null || app.lawCodeQuery('S176') !== null) throw new Error('a word reads as a code');
  } finally {
    sys.campaignRows = rows;
  }
});

check('the fleet ladder\u2019s header says a law\u2019s graphs in whole numbers, a range where the merged campaigns differ (871)', () => {
  const app = sandbox.GSD_APP;
  const one = app.ladderPerLaw([{ n: 64, chains_per_seed: 8, seeds_per_law: 3 }]);
  if (one !== ' \u00b7 a law at a size = 3 seeds \u00d7 8 starts = 24 graphs') throw new Error(one);
  const merged = app.ladderPerLaw([{ n: 64, chains_per_seed: 8, seeds_per_law: 3.0049875311720697, seeds_per_law_most: 9 },
                                   { n: 4096, chains_per_seed: 8, chains_per_seed_most: 8, seeds_per_law: 3, seeds_per_law_most: 3 }]);
  if (merged !== ' \u00b7 a law at a size = 3 to 9 seeds \u00d7 8 starts = 24 to 72 graphs') throw new Error(merged);
  if (/\.\d/.test(merged)) throw new Error('a mean was shown unrounded');
  if (app.ladderPerLaw([{ n: 64 }]) !== '') throw new Error('a ladder without seeds says a law\u2019s graphs');
});

check('a ladder with a queue and no running work says so', () => {
  sandbox.GSD_APP.overviewPayload = { active: [], rung_distribution: [
    { n: 65536, running: 0, queued: 2603, measured: 93 },
  ] };
  sandbox.GSD_APP.rungLadderRow();
  const html = getElementById('rungLadder').innerHTML;
  if (!/nothing is running/.test(html)) {
    throw new Error(`a fully stalled ladder does not say so: ${html}`);
  }
});

check('the ladder panel renders before any rung exists', () => {
  sandbox.GSD_APP.overviewPayload = { active: [] };
  sandbox.GSD_APP.rungLadderRow();
  if (!/no rung has been declared/.test(getElementById('rungLadder').innerHTML)) {
    throw new Error('an empty ladder renders blank instead of saying why');
  }
});

check('a Top 100 card says who built its geometry and the largest size it held at', () => {
  sandbox.GSD_APP.landscapePayload = { top_candidates: [
    landscapeRow({ law_score: lawScore(29, 'empty', 'empty', 16384, 4) }),
    landscapeRow({ law_score: lawScore(34, 'random') })] };
  sandbox.GSD_APP.renderTop();
  const html = getElementById('best').innerHTML;
  if (!html.includes('the chain from empty: 4 of 15 at N=16,384')) throw new Error(`the chain from empty is not named: ${html}`);
  if (!html.includes('the random start: 15 of 15 at N=65,536, all four agreeing by Einstein')) throw new Error(`the random start is not named: ${html}`);
  if (/d_s\+d_B|no probe settled/.test(html)) throw new Error('the stability score\'s settled probes are on the card');
});

check('a zero-temperature law says so beside its name in the Top 100', () => {
  sandbox.GSD_APP.landscapePayload = { top_candidates: [
    landscapeRow({ law_score: lawScore(17), regime: 'zero_temperature' }),
    landscapeRow({ law_score: lawScore(9, 'lattice', 'cubic', 4096), regime: 'equilibrium' })] };
  sandbox.GSD_APP.renderTop();
  const html = getElementById('best').innerHTML;
  if (!html.includes('regime-chip regime-zero_temperature') || !html.includes('>zero temperature</span>'))
    throw new Error('a zero-temperature law is not marked');
  if ((html.match(/regime-chip/g) || []).length !== 1) throw new Error('an equilibrium law is marked too');
});

check('band geometry scales with the canvas height', () => {
  const land = getElementById('land');
  const measure = (height) => {
    land.rectHeight = height;
    const points = [];
    for (let i = 0; i < 12; i += 1) {
      points.push({...LAW, candidate_id: `h${i}`, d_s_estimate: 1 + i * 0.2,
        landscape_band: 'flowing', stability_contracting_probes: [], stability_contracting_tier: 0});
    }
    sandbox.GSD_APP.drawLandscape(points);
    return sandbox.GSD_APP.bandLayout.map((b) => ({...b}));
  };

  const at = { 300: measure(300), 400: measure(400), 800: measure(800) };
  land.rectHeight = 400;

  const total = (rows) => rows.reduce((sum, b) => sum + b.height, 0);
  if (!(total(at[800]) > total(at[400]) && total(at[400]) > total(at[300]))) {
    throw new Error(`bands did not follow the canvas: ${total(at[300])}, ${total(at[400])}, ${total(at[800])}`);
  }

  const occupied = (rows) => rows.find((b) => b.count > 0);
  const small = occupied(at[300]), large = occupied(at[400]);
  if (!small || !large) throw new Error('no band reported the laws it was given');
  if (!(large.rowGap > small.rowGap)) {
    throw new Error(`row spacing is not derived from the band: ${small.rowGap} -> ${large.rowGap}`);
  }

  for (const [height, rows] of Object.entries(at)) {
    for (const b of rows) {
      if (!(b.rowGap >= 6 && b.rowGap <= 46)) {
        throw new Error(`${b.id} row spacing ${b.rowGap} is outside its declared clamp at ${height}px`);
      }
      if (b.count > 0 && b.head + 3 * b.rowGap > b.height) {
        throw new Error(`${b.id} draws its last channel row past its own floor at ${height}px`);
      }
    }
  }
});

check('legend labels carry each channel count exactly once', () => {
  const counts = { d_s: 260, d_V: 230, d_B: 119, d_w: 310 };
  sandbox.GSD_APP.channelCounts = counts;
  sandbox.GSD_APP.drawLandscape([{...LAW, candidate_id: 'legend'.padEnd(64, '0')}]);
  const labels = sandbox.GSD_APP.labelHits.filter((l) => l.channel);
  if (labels.length !== 4) throw new Error(`expected four channel labels, got ${labels.length}`);
  for (const [channel, count] of Object.entries(counts)) {
    const hit = labels.find((l) => l.channel === channel);
    if (!hit) throw new Error(`${channel} has no legend entry`);
    const occurrences = hit.label.split(String(count)).length - 1;
    if (occurrences !== 1) {
      throw new Error(`${channel}: count printed ${occurrences} times in "${hit.label}"`);
    }
    if (!hit.label.startsWith(channel)) throw new Error(`${channel}: label is "${hit.label}"`);
    if (!(hit.w > 0)) throw new Error(`${channel}: legend entry has no hit region`);
  }

  sandbox.GSD_APP.channelCounts = {};
  sandbox.GSD_APP.drawLandscape([{...LAW, candidate_id: 'bare'.padEnd(64, '0')}]);
  for (const hit of sandbox.GSD_APP.labelHits.filter((l) => l.channel)) {
    if (hit.label !== hit.channel) {
      throw new Error(`an absent count printed itself: "${hit.label}"`);
    }
  }
});


const EXPLORER_ROWS = [
  { candidate_id: 'a'.padEnd(64, '0'), ensemble_code: 'G-31', law: '+1.0*edge_count', terms: [],
    state: 'PARKED', status_group: 'past', coupling_stratum: 'weak',
    scaling_profile: 'scaled', coefficient_scales: ['one'], term_operators: ['edge_count'],
    largest_n: 16384, created_utc: '2026-09-09T01:00:00Z', probes_valid: 1, rungs: [{ n: 64 }] },
  { candidate_id: 'b'.padEnd(64, '0'), ensemble_code: 'G-4', law: '+2.0*wedge_count', terms: [],
    state: 'ACTIVE', status_group: 'active', coupling_stratum: 'strong',
    scaling_profile: 'mixed', coefficient_scales: ['one'], term_operators: ['wedge_count'],
    largest_n: 262144, created_utc: '2026-09-10T01:00:00Z', probes_valid: 1, rungs: [{ n: 64 }] },
  { candidate_id: 'c'.padEnd(64, '0'), ensemble_code: 'G-208', law: '+3.0*square_count', terms: [],
    state: 'BASE_INCONCLUSIVE', status_group: 'active', coupling_stratum: 'moderate',
    scaling_profile: 'unscaled', coefficient_scales: ['one'], term_operators: ['square_count'],
    largest_n: 4096, created_utc: '2026-09-11T01:00:00Z', probes_valid: 0, rungs: [{ n: 64 }] },
];

function mountExplorer() {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.explorerRows = EXPLORER_ROWS;
  sandbox.GSD_APP.landscape = {
    campaign_id: '1', revision: 'rev-1', lattice_who: LATTICE_WHO,
    dimension_points: [
      { candidate_id: EXPLORER_ROWS[0].candidate_id, law_score: lawScore(17),
        stability_contracting_probes: ['d_s'] },
      { candidate_id: EXPLORER_ROWS[1].candidate_id, law_score: lawScore(34, 'random'),
        stability_contracting_probes: ['d_s', 'd_V'] },
    ],
  };
  sandbox.GSD_APP.explorerSort = { key: 'created', dir: -1 };
  sandbox.GSD_APP.drawExplorer();
  return getElementById('explorerBody').innerHTML;
}

function bodyRowOrder(html) {
  return EXPLORER_ROWS.map((r) => r.candidate_id)
    .map((id) => ({ id, at: html.indexOf(id) }))
    .filter((e) => e.at >= 0).sort((a, b) => a.at - b.at).map((e) => e.id[0]);
}

check('the Explorer paints a score column from the landscape join', () => {
  const html = mountExplorer();
  if (!/data-sort="score"/.test(html)) throw new Error('no score column header');
  if (!/>17</.test(html)) throw new Error('law a scored 17 and the cell does not say so');
  if (!/>34</.test(html)) throw new Error('law b scored 34 and the cell does not say so');
  if (!/a lattice start, kept \(honeycomb\): 15 of 15 at N=65,536/.test(html)) throw new Error('the cell does not say who built it');
  const cRow = html.slice(html.indexOf(EXPLORER_ROWS[2].candidate_id));
  if (/>0</.test(cRow.slice(0, cRow.indexOf('</tr>')))) {
    throw new Error('a law the landscape has never scored rendered as a zero');
  }
});

check('every Explorer column header is sortable and sorts both ways', () => {
  const html = mountExplorer();
  const keys = [...html.matchAll(/data-sort="([a-z_]+)"/g)].map((m) => m[1]);
  if (keys.length < 8) throw new Error(`only ${keys.length} sortable headers`);
  for (const key of keys) {
    sandbox.GSD_APP.explorerSortBy(key);
    const first = bodyRowOrder(getElementById('explorerBody').innerHTML);
    sandbox.GSD_APP.explorerSortBy(key);
    const second = bodyRowOrder(getElementById('explorerBody').innerHTML);
    if (first.length !== EXPLORER_ROWS.length) throw new Error(`${key}: rows went missing`);
    if (first.join('') === second.join('') && new Set(first).size > 1) {
      throw new Error(`${key}: clicking twice did not reverse the order`);
    }
  }
});

check('a column whose values are all equal does not reorder the table', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.explorerRows = EXPLORER_ROWS.map((r) => ({ ...r, coupling_stratum: 'weak' }));
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.explorerSort = { key: 'created', dir: -1 };
  sandbox.GSD_APP.drawExplorer();
  sandbox.GSD_APP.explorerSortBy('coupling');
  const first = bodyRowOrder(getElementById('explorerBody').innerHTML);
  sandbox.GSD_APP.explorerSortBy('coupling');
  const second = bodyRowOrder(getElementById('explorerBody').innerHTML);
  if (first.join('') !== second.join('')) {
    throw new Error(`a tied column shuffled rows between clicks: ${first} / ${second}`);
  }
});

check('sorting by score puts the unscored law last in both directions', () => {
  mountExplorer();
  sandbox.GSD_APP.explorerSortBy('score');
  const down = bodyRowOrder(getElementById('explorerBody').innerHTML);
  sandbox.GSD_APP.explorerSortBy('score');
  const up = bodyRowOrder(getElementById('explorerBody').innerHTML);
  if (down[0] !== 'b') throw new Error(`descending should lead with the 34: got ${down}`);
  if (up[0] !== 'a') throw new Error(`ascending should lead with the 17: got ${up}`);
  if (down[down.length - 1] !== 'c' || up[up.length - 1] !== 'c') {
    throw new Error(`the unscored law must sort last both ways: ${down} / ${up}`);
  }
});

check('the Explorer renders before the landscape has arrived', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.explorerRows = EXPLORER_ROWS;
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.drawExplorer();
  const html = getElementById('explorerBody').innerHTML;
  if (!/data-sort="score"/.test(html)) throw new Error('the column vanished with the landscape');
  if (/>17</.test(html)) throw new Error('a score appeared with no landscape to read it from');
});

check('every render entry point is exported and callable', () => {
  const required = ['drawLandscape', 'drawExplorer', 'explorerSortBy', 'renderHome',
                    'renderSystem', 'renderReports', 'renderCalibration',
                    'renderGate', 'renderProbeAtlas', 'renderCampaigns',
                  'renderCampaignPanel', 'renderCampaignAuthor',
                    'renderTop', 'leaderRow', 'rungLadderRow'];
  const missing = required.filter((name) => typeof sandbox.GSD_APP[name] !== 'function');
  if (missing.length) throw new Error(`not callable on GSD_APP: ${missing.join(', ')}`);
  if (!Array.isArray(sandbox.GSD_APP.hitPoints)) {
    throw new Error('hitPoints is not readable as an array');
  }
});


const GROWS = ['G-1', 'G-2', 'G-9', 'G-10', 'G-100', 'G-10000', 'G-100000'].map((code, i) => ({
  candidate_id: String(i).padEnd(64, 'f'), ensemble_code: code,
  law: '+1.0*edge_count', terms: [], state: 'PARKED', status_group: 'past',
  coupling_stratum: 'weak', scaling_profile: 'unscaled', coefficient_scales: ['one'],
  term_operators: ['edge_count'], largest_n: i === 0 ? null : 1024,
  created_utc: `2026-09-09T0${i}:00:00Z`, probes_valid: 1, rungs: [{ n: 64 }],
}));

function codeOrder() {
  const html = getElementById('explorerBody').innerHTML;
  const shown = (code) => `>C${sandbox.GSD_APP.campaign}-${String(code).replace(/^G-/, 'G')}<`;
  return GROWS.map((r) => ({ code: r.ensemble_code, at: html.indexOf(shown(r.ensemble_code)) }))
    .filter((e) => e.at >= 0).sort((a, b) => a.at - b.at).map((e) => e.code);
}

check('the candidate column sorts G-codes as numbers, not as text', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.explorerRows = GROWS;
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.explorerSort = { key: 'created', dir: -1 };
  sandbox.GSD_APP.drawExplorer();
  sandbox.GSD_APP.explorerSortBy('candidate');
  const up = codeOrder();
  const want = ['G-1', 'G-2', 'G-9', 'G-10', 'G-100', 'G-10000', 'G-100000'];
  if (up.join(',') !== want.join(',')) {
    throw new Error(`ascending gave ${up.join(',')}; wanted ${want.join(',')}`);
  }
  sandbox.GSD_APP.explorerSortBy('candidate');
  const down = codeOrder();
  if (down.join(',') !== want.slice().reverse().join(',')) {
    throw new Error(`descending gave ${down.join(',')}`);
  }
});

check('a law with no measured rung sorts last by largest N, not as a zero', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.explorerRows = GROWS;
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.explorerSort = { key: 'created', dir: -1 };
  sandbox.GSD_APP.drawExplorer();
  sandbox.GSD_APP.explorerSortBy('largest_n');
  if (codeOrder().pop() !== 'G-1') throw new Error('descending: the unmeasured law is not last');
  sandbox.GSD_APP.explorerSortBy('largest_n');
  if (codeOrder().pop() !== 'G-1') {
    throw new Error('ascending: an absent rung sorted as 0 instead of last');
  }
});

check('ties break on the candidate code rather than on load order', () => {
  const shuffled = [...GROWS].reverse();
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.explorerRows = GROWS;
  sandbox.GSD_APP.explorerSort = { key: 'coupling', dir: 1 };
  sandbox.GSD_APP.drawExplorer();
  const first = codeOrder();
  sandbox.GSD_APP.explorerRows = shuffled;
  sandbox.GSD_APP.drawExplorer();
  const second = codeOrder();
  if (first.join(',') !== second.join(',')) {
    throw new Error(`the API's row order leaked into the table: ${first} vs ${second}`);
  }
  if (first[0] !== 'G-1') throw new Error(`tie-break is not the code: ${first.join(',')}`);
});


check('an empty research panel says whether analysis is still running', () => {
  sandbox.GSD_APP.renderHome({
    active: [], campaigns: [], runtime_counts: {},
    compute_utilization: { simulation_busy: 0, analysis_busy: 12, total_slots: 32 },
    analysis_backlog: 40,
  });
  const html = getElementById('live').innerHTML;
  if (!/analysis job\(s\) in flight/.test(html)) {
    throw new Error(`an idle simulation pool with 12 analyses said: ${html}`);
  }
  if (!/12/.test(html)) throw new Error('the count of running analyses is not shown');
  if (!/40/.test(html)) throw new Error('the queued backlog is not shown');
});

check('a genuinely idle fleet is not described as analysis finishing', () => {
  sandbox.GSD_APP.renderHome({
    active: [], campaigns: [], runtime_counts: {},
    compute_utilization: { simulation_busy: 0, analysis_busy: 0, total_slots: 32 },
    analysis_backlog: 0,
  });
  const html = getElementById('live').innerHTML;
  if (/in flight/.test(html)) throw new Error('claimed analysis was running when none was');
  if (!/capacity verdict/.test(html)) {
    throw new Error('an idle fleet must point at where the reason lives');
  }
});

check('now researching shows only laws with something running', () => {
  const id = n => String(n).padEnd(64, '0');
  sandbox.GSD_APP.renderHome({
    active: [
      { candidate_id: id(1), ensemble_code: 'G-RUN', state: 'BASE_BLOCK_RUNNING',
        law: '+1*edge_count', terms: [], rungs: [{ n: 64, elapsed_s: 10 }],
        running: [{ n: 256, seed: 0, since_s: 30, lane: 'base', budget_seconds: 1200,
                    eta: { identifiable: true, median_seconds: 100, attempts: 40,
                           candidate_scale: { factor: 2.0, rungs: [64],
                                              reason: 'this law ran 2.00x the population median' },
                           progress: { elapsed_seconds: 30, remaining_seconds: 170,
                                       median_seconds: 200, scaled_by: 2.0, overdue: false } } }],
        queued: [], ladder: [{ n: 64, standing: 'measured' }, { n: 256, standing: 'running' }],
        largest_n: 256 },
      { candidate_id: id(2), ensemble_code: 'G-QUEUED', state: 'BASE_BLOCK_RUNNING',
        law: '+1*edge_count', terms: [], rungs: [], running: [], queued: [{ n: 64 }],
        ladder: [{ n: 64, standing: 'queued' }], largest_n: 64 },
      { candidate_id: id(3), ensemble_code: 'G-PROBE', state: 'PARKED',
        law: '+1*edge_count', terms: [], rungs: [{ n: 64, elapsed_s: 8 }], running: [],
        probing: [{ n: 65536, lane: 'extension', since_s: 12 }],
        queued: [], ladder: [{ n: 65536, standing: 'analyzing' }], largest_n: 65536 },
    ],
    campaigns: [], runtime_counts: {},
    compute_utilization: { simulation_busy: 1, analysis_busy: 1, total_slots: 32 },
  });
  const html = getElementById('live').innerHTML;
  if (!/G-RUN/.test(html)) throw new Error('a law with a leased chain is missing');
  if (!/G-PROBE/.test(html)) throw new Error('a law with a leased probe is missing');
  if (/G-QUEUED/.test(html)) {
    throw new Error(`a law with only queued rungs is still listed: ${html}`);
  }
  if (!/lease-icon graph/.test(html)) throw new Error(`the graph lease has no icon: ${html}`);
  if (!/lease-icon probe/.test(html)) throw new Error(`the probe lease has no icon: ${html}`);
  if (!/<code>N=256<\/code>/.test(html)) throw new Error(`the rung is not a column: ${html}`);
  if (!/lease-bar/.test(html)) throw new Error(`no progress bar drawn: ${html}`);
  if (!/class="lease-typical num"><span[^>]*>1m40\.0s</.test(html)) {
    throw new Error(`typical is not the rung's one number (784): ${html}`);
  }
  if (!/own estimate 3m20\.0s \(the rung\u2019s typical \u00d7 2\), about 2m50\.0s left/.test(html)) {
    throw new Error(`the law's own estimate is not in the mouse-over: ${html}`);
  }
  if (!/2\.00x the population median/.test(html)) {
    throw new Error(`the per-law factor is not explained: ${html}`);
  }
});

check('a probe says what its rung typically costs, and says so when nothing is timed', () => {
  const id = 'p'.padEnd(64, '0');
  const probeLaw = (rungs) => ({
    active: [{ candidate_id: id, ensemble_code: 'G-PR', state: 'PARKED',
               law: '+1*edge_count', terms: [], rungs: [{ n: 64, elapsed_s: 9 }],
               running: [], probing: [{ n: 262144, lane: 'extension', state: 'running', since_s: 40 }],
               queued: [], ladder: [{ n: 262144, standing: 'analyzing' }], largest_n: 262144 }],
    campaigns: [], runtime_counts: {}, rung_distribution: rungs,
    compute_utilization: { simulation_busy: 0, analysis_busy: 1, total_slots: 32 } });
  sandbox.GSD_APP.renderHome(probeLaw([]));
  let html = serialize(liveLaw(id));
  if (/first rung/.test(html)) throw new Error(`a probe at N=262144 was called a first rung: ${html}`);
  if (!/none at N=262144 yet/.test(html)) {
    throw new Error(`a probe with no timings does not say so: ${html}`);
  }
  sandbox.GSD_APP.renderHome(probeLaw([{ n: 262144, d_s_median_seconds: 20, d_V_median_seconds: 5,
                                          d_B_median_seconds: 10, d_w_median_seconds: 5 }]));
  html = serialize(liveLaw(id));
  if (!/<span[^>]*>40\.0s<\/span>/.test(html)) throw new Error(`the typical probe time is missing: ${html}`);
  if (/>typical /.test(html)) throw new Error(`the cell repeats the column heading: ${html}`);
  if (!/probe-split/.test(html) || (html.match(/<b style="width:/g) || []).length !== 4) {
    throw new Error(`the probe bar is not split into the four probes: ${html}`);
  }
});

check('a row is one element for as long as its lease lives, and a single missing frame is not a departure', () => {
  const id = 'q'.padEnd(64, '0');
  const frame = (running) => ({
    active: [{ candidate_id: id, ensemble_code: 'G-FR', state: 'BASE_BLOCK_RUNNING',
               law: '+1*edge_count', terms: [], rungs: [], probing: [], running,
               queued: [], ladder: [{ n: 64, standing: 'running' }], largest_n: 64 }],
    campaigns: [], runtime_counts: {}, compute_utilization: { simulation_busy: 1, analysis_busy: 0, total_slots: 32 } });
  const lease = { n: 64, seed: 0, lane: 'base', since_s: 2 };
  sandbox.GSD_APP.renderHome(frame([lease]));
  const first = liveLeases(id).children[0];
  const writes = first.classWrites;
  for (let poll = 0; poll < 10; poll += 1) {
    sandbox.GSD_APP.renderHome(frame([Object.assign({}, lease, { since_s: 3 + poll })]));
    const now = liveLeases(id).children[0];
    if (now !== first) throw new Error(`poll ${poll} replaced the row element: its animation would restart`);
  }
  if (first.classWrites !== writes) {
    throw new Error(`the row's class was rewritten ${first.classWrites - writes} time(s) with nothing changing`);
  }
  sandbox.GSD_APP.renderHome(frame([]));
  const stillThere = liveLeases(id) && liveLeases(id).children[0];
  if (stillThere !== first || /leaving/.test(first.className)) {
    throw new Error(`one missing frame ended the row: ${first.className}`);
  }
  sandbox.GSD_APP.renderHome(frame([]));
  if (!/leaving/.test(first.className)) throw new Error(`two missing frames did not end the row: ${first.className}`);
});

check('switching campaign draws the new rows without arriving and drops the old ones without leaving', () => {
  const a = 'm'.padEnd(64, '1'), b = 'n'.padEnd(64, '2');
  const frame = (id) => ({
    active: [{ candidate_id: id, ensemble_code: 'G-SW', state: 'BASE_BLOCK_RUNNING', law: '+1*edge_count', terms: [],
               rungs: [], probing: [], running: [{ n: 256, seed: 0, lane: 'base', since_s: 5 }], queued: [],
               ladder: [{ n: 256, standing: 'running' }], largest_n: 256 }],
    campaigns: [], runtime_counts: {}, compute_utilization: { simulation_busy: 1, analysis_busy: 0, total_slots: 32 } });
  const before = sandbox.GSD_APP.campaign;
  sandbox.GSD_APP.renderHome(frame(a));
  sandbox.GSD_APP.renderHome(frame(a));
  sandbox.GSD_APP.campaign = 'switch-test';
  sandbox.GSD_APP.homeLoading = { campaign: 'switch-test', overview: false };
  sandbox.GSD_APP.renderLive(frame(a));
  if (liveLaw(a) && /leaving/.test(liveLaw(a).className)) throw new Error('the old row started leaving on the click');
  sandbox.GSD_APP.homeLoading = { campaign: 'switch-test', overview: true };
  sandbox.GSD_APP.renderLive(frame(b));
  if (liveLaw(a)) throw new Error('the old campaign\'s row stayed, to fold away');
  const row = liveLaw(b);
  if (!row) throw new Error('the new campaign\'s row is missing');
  if (/entering/.test(row.className) || /entering/.test(liveLeases(b).children[0].className)) {
    throw new Error(`the new campaign's row arrived with motion: ${row.className}`);
  }
  sandbox.GSD_APP.homeLoading = null;
  sandbox.GSD_APP.campaign = before;
});

check('a law whose last lease ends folds its whole row, not only the lease', () => {
  const id = 'f'.padEnd(64, '0');
  const frame = (running) => ({
    active: [{ candidate_id: id, ensemble_code: 'G-FOLD', state: 'BASE_BLOCK_RUNNING', law: '+1*edge_count', terms: [],
               rungs: [], probing: [], running, queued: [], ladder: [{ n: 1024, standing: 'measured' }], largest_n: 1024 }],
    campaigns: [], runtime_counts: {}, compute_utilization: { simulation_busy: 1, analysis_busy: 0, total_slots: 32 } });
  sandbox.GSD_APP.renderHome(frame([{ n: 1024, seed: 0, lane: 'base', since_s: 3 }]));
  const law = liveLaw(id);
  sandbox.GSD_APP.renderHome(frame([]));
  if (/leaving/.test(law.className)) throw new Error('one missing frame folded the law');
  sandbox.GSD_APP.renderHome(frame([]));
  if (!/live-law leaving/.test(law.className)) throw new Error(`the law row did not start folding: ${law.className}`);
  if (law.style.maxHeight !== '0px') throw new Error(`the law row's height was not released: ${law.style.maxHeight}`);
  if (liveLaw(id) !== law) throw new Error('the folding row was replaced');
});

check('a rung waiting for a probe slot is not a row: waiting is a queue, not research', () => {
  const id = 'w'.padEnd(64, '0');
  sandbox.GSD_APP.renderHome({
    active: [{ candidate_id: id, ensemble_code: 'G-WAIT', state: 'PARKED', law: '+1*edge_count', terms: [],
               rungs: [{ n: 16384, elapsed_s: 90 }], running: [], queued: [],
               probing: [{ n: 65536, lane: 'extension', state: 'waiting', seeds: 3, since_s: 130 }],
               ladder: [{ n: 65536, standing: 'analyzing' }], largest_n: 65536 }],
    campaigns: [], runtime_counts: {}, compute_utilization: { simulation_busy: 0, analysis_busy: 8, total_slots: 32 } });
  if (liveLaw(id)) throw new Error(`a law with only queued probes has a row: ${serialize(liveLaw(id))}`);
});

check('the score column reads every scored law, not only the top hundred', () => {
  const id = 's'.padEnd(64, '0');
  sandbox.GSD_APP.landscapePayload = { top_candidates: [],
    dimension_points: [{ candidate_id: id, law_score: lawScore(29, 'empty', 'empty', 4096) },
                       { candidate_id: 't'.padEnd(64, '0'), law_score: { score: 0, by: null, chain: null, to_n: null, top_n: 256 } }],
    selection: { base_sizes: [64, 256, 1024, 4096, 16384] } };
  sandbox.GSD_APP.renderHome({
    active: [{ candidate_id: id, ensemble_code: 'G-SCORED', state: 'PARKED', law: '+1*edge_count', terms: [],
               rungs: [], queued: [], probing: [], running: [{ n: 65536, seed: 1, lane: 'extension', since_s: 5 }],
               ladder: [{ n: 65536, standing: 'running' }], largest_n: 65536 },
             { candidate_id: 't'.padEnd(64, '0'), ensemble_code: 'G-NEW', state: 'BASE_BLOCK_RUNNING', law: '+1*edge_count',
               terms: [], rungs: [], queued: [], probing: [], running: [{ n: 256, seed: 0, lane: 'base', since_s: 1 }],
               ladder: [{ n: 256, standing: 'running' }], largest_n: 256 }],
    campaigns: [], runtime_counts: {}, compute_utilization: { simulation_busy: 2, analysis_busy: 0, total_slots: 32 } });
  const scored = serialize(liveLaw(id));
  if (!/class=live-score>29</.test(scored)) throw new Error(`a law below the top hundred shows no score: ${scored}`);
  const unscored = serialize(liveLaw('t'.padEnd(64, '0')));
  if (!/scored from N=1,024 nodes/.test(unscored) || /class=live-score>0</.test(unscored)) {
    throw new Error(`a law below N=1,024 does not say when it is scored: ${unscored}`);
  }
  sandbox.GSD_APP.landscapePayload = null;
});

check('an overdue rung fills its bar and says how far past typical it is', () => {
  sandbox.GSD_APP.renderHome({
    active: [{ candidate_id: 'y'.padEnd(64, '0'), ensemble_code: 'G-LATE',
               state: 'BASE_BLOCK_RUNNING', law: '+1*edge_count', terms: [],
               rungs: [], running: [{ n: 4096, seed: 1, since_s: 900, lane: 'base', budget_seconds: 1200,
                 budget_units: 7500000000000,
                 eta: { identifiable: true, median_seconds: 300, attempts: 30,
                        progress: { elapsed_seconds: 900, remaining_seconds: null,
                                    overdue: true, overdue_by_seconds: 500 } } }],
               queued: [], ladder: [{ n: 4096, standing: 'running' }], largest_n: 4096 }],
    campaigns: [], runtime_counts: {},
    compute_utilization: { simulation_busy: 1, analysis_busy: 0, total_slots: 32 },
  });
  const html = serialize(liveLaw('y'.padEnd(64, '0')));
  if (!/lease-bar overdue/.test(html)) throw new Error(`an overdue lease is not marked: ${html}`);
  if (!/typical 5m00\.0s/.test(html) || !/class="lease-mult"[^>]*>\u00d73\.0</.test(html)) {
    throw new Error(`the multiple of typical is not stated: ${html}`);
  }
  const budgetCell = liveLeases('y'.padEnd(64, '0')).children[0].children[6];
  if (!/>7\.5 T</.test(serialize(budgetCell)) || !/about 20m /.test(serialize(budgetCell))) {
    throw new Error(`the budget in work and its hours are not stated in their own cell: ${serialize(budgetCell)}`);
  }
  const estimateCell = liveLeases('y'.padEnd(64, '0')).children[0].children[5];
});

check('the landscape has one filter, whether lattice starts count, and labels its bands by the probes settled (784)', () => {
  const law = (id, d_s, band, extra) => ({ ...LAW, candidate_id: id.padEnd(64, '0'), d_s_estimate: d_s, landscape_band: band,
    stability_contracting_probes: [], stability_contracting_tier: 0, ...(extra || {}) });
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscapePayload = { campaign_id: '1', revision: 'r2', top_candidates: [], exposure: {}, limits: {}, lattice_who: LATTICE_WHO,
    dimension_points: [law('a', 1.2, 'flowing', { landscape_band_with_lattices: 'flowing' }),
                       law('b', 2.0, 'flowing', { landscape_band_with_lattices: 'tier2' })],
    counts: { measured_candidates: 2, refused_candidates: 4, band_candidates: { flowing: 2 } },
    every_chain: { contract: 'landscape-every-chain-1', names: ['empty', 'random', 'cubic'],
      points: { random: [law('a', 1.3, 'flowing')],
                cubic: [law('b', 2.9, 'flowing', { landscape_band_with_lattices: 'tier2', law_score: { score: 9, by: 'kept', chain: 'cubic' } })] },
      counts: {} } };
  const overview = { active: [], campaigns: [], runtime_counts: {}, compute_utilization: {}, rung_distribution: [] };
  sandbox.GSD_APP.renderHome(overview);
  let caption = getElementById('landMeta').innerHTML;
  if (!/id=landLattices>/.test(caption) || !/include lattice starts/.test(caption)) throw new Error(`no lattice toggle: ${caption}`);
  if (!/0 at 1 probe · 0 at 2 · 0 at 3 · 0 at 4/.test(caption)) throw new Error(`the bands are not counted as labelled: ${caption}`);
  if (sandbox.GSD_APP.landChainPoints().some((p) => p.landscape_band !== 'flowing')) throw new Error('off, a lattice band is drawn');
  sandbox.GSD_APP.chooseLandLattices(true);
  caption = getElementById('landMeta').innerHTML;
  if (!/id=landLattices checked>/.test(caption)) throw new Error(`the toggle does not stay on: ${caption}`);
  if (!/1 at 2/.test(caption)) throw new Error(`on, the lattice start's band is not counted: ${caption}`);
  const drawn = sandbox.GSD_APP.landChainPoints();
  const b = drawn.find((p) => p.candidate_id.startsWith('b'));
  if (drawn.length !== 2 || b.d_s_estimate !== 2.9 || b.landscape_band !== 'tier2') throw new Error('on, the law is not drawn at its scoring lattice start');
  sandbox.GSD_APP.drawLandscape(drawn);
  if (sandbox.GSD_APP.bandLayout.find((x) => x.id === 'tier2').count !== 1) throw new Error('the band is not the one drawn');
  sandbox.GSD_APP.chooseLandLattices(false);
});

check('a resize, which a phone fires as its address bar hides on a scroll, redraws the landscape as the toggle left it', () => {
  if (bootPath !== '/') return;
  const law = (id, d_s, band, extra) => ({ ...LAW, candidate_id: id.padEnd(64, '0'), d_s_estimate: d_s, landscape_band: band,
    stability_contracting_probes: [], stability_contracting_tier: 0, ...(extra || {}) });
  sandbox.GSD_APP.campaign = '1';
  const points = [law('a', 1.2, 'flowing', { landscape_band_with_lattices: 'flowing' }),
                  law('b', 2.0, 'flowing', { landscape_band_with_lattices: 'tier2' })];
  sandbox.GSD_APP.landscapePayload = { campaign_id: '1', revision: 'r839', top_candidates: [], exposure: {}, limits: {}, lattice_who: LATTICE_WHO,
    dimension_points: points,
    counts: { measured_candidates: 2, refused_candidates: 4, band_candidates: { flowing: 2 } },
    every_chain: { contract: 'landscape-every-chain-1', names: ['empty', 'random', 'cubic'],
      points: { random: [law('a', 1.3, 'flowing')],
                cubic: [law('b', 2.9, 'flowing', { landscape_band_with_lattices: 'tier2', law_score: { score: 9, by: 'kept', chain: 'cubic' } })] },
      counts: {} } };
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {}, rung_distribution: [] });
  const inTier2 = () => ((sandbox.GSD_APP.bandLayout.find((x) => x.id === 'tier2') || {}).count) || 0;
  try {
    sandbox.GSD_APP.chooseLandLattices(true);
    sandbox.GSD_APP.drawLandscape(points);
    if (inTier2() !== 0) throw new Error('the plain points put a law in a lattice band');
    for (const type of ['resize', 'rr:hero-metrics']) {
      sandbox.GSD_APP.drawLandscape(points);
      sandbox.dispatchEvent(type === 'resize' ? { type } : new sandbox.CustomEvent(type, { detail: { headerHeight: 176 } }));
      if (inTier2() !== 1) throw new Error(`${type} drew the landscape without the lattice starts while the toggle stayed on`);
    }
    sandbox.GSD_APP.chooseLandLattices(false);
    sandbox.dispatchEvent({ type: 'resize' });
    if (inTier2() !== 0) throw new Error('off, a resize draws a lattice start');
  } finally {
    sandbox.GSD_APP.chooseLandLattices(false);
  }
});

check('every batch together: the toggle brings in each law at its best lattice start, filled by the score (787)', () => {
  const law = (id, cid, d_s, extra) => ({ ...LAW, candidate_id: id.padEnd(64, '0'), campaign_id: cid, d_s_estimate: d_s,
    landscape_band: 'flowing', settled_probes: [], stability_contracting_probes: ['d_s'], ...(extra || {}) });
  const kept = { landscape_band_with_lattices: 'einstein', settled_probes_with_lattices: ['d_s', 'd_V', 'd_B', 'd_w'],
                 law_score: { score: 17, by: 'kept', chain: 'triangular' } };
  sandbox.GSD_APP.campaign = 'study';
  sandbox.GSD_APP.landscapePayload = { campaign_id: 'study', revision: 's1', top_candidates: [], exposure: {}, limits: {}, lattice_who: LATTICE_WHO,
    dimension_points: [law('a', '1', 1.0, kept)],
    counts: { measured_candidates: 1, band_candidates: { flowing: 1 } },
    every_chain: { contract: 'landscape-every-chain-1', names: ['empty', 'random', 'triangular'],
      points: { triangular: [law('a', '1', 2.0, kept), law('a', '2', 2.1, kept), law('b', '2', 2.0, kept)] }, counts: {} } };
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {}, rung_distribution: [] });
  const off = sandbox.GSD_APP.landChainPoints();
  if (off.length !== 1 || off[0].settled_probes.length !== 0) throw new Error('off, the twins\u2019 point is drawn, filled by the twins\u2019 score');
  sandbox.GSD_APP.chooseLandLattices(true);
  const on = sandbox.GSD_APP.landChainPoints();
  if (on.length !== 3) throw new Error(`a law whose twin starts have no reading, or the same law in two batches, is missing: ${on.length}`);
  if (on.some((p) => p.d_s_estimate < 2 || p.landscape_band !== 'einstein' || p.settled_probes.length !== 4)) {
    throw new Error('on, a law is not drawn at its lattice start, in its band, every probe the score settled filled');
  }
  if (!/3 by Einstein/.test(getElementById('landMeta').innerHTML)) throw new Error(`on, the 5th band is not counted: ${getElementById('landMeta').innerHTML}`);
  sandbox.GSD_APP.chooseLandLattices(false);
});

check('the gates box under the ladder says when it has no counters', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscapePayload = { campaign_id: '1', revision: 'r1', dimension_points: [], top_candidates: [],
    counts: {}, exposure: {}, limits: {},
    selection: { headline: 'window', mechanisms: [{ name: 'stage gate', active: true, applies_from: 'N\u22654096', does: 'x' }],
                 every_rung: [], stages: [{ sizes: [64], lane: 'base', limit_seconds: 60, limit: '1 min', changes: [] }], base_sizes: [64] } };
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {}, rung_distribution: [] });
  const caption = getElementById('landMeta').innerHTML;
  const box = getElementById('gatesBox').innerHTML;
  if (!/no gate counters/.test(box)) throw new Error(`a campaign without counters is not said so: ${box}`);
  sandbox.GSD_APP.landscapePayload = null;
});

check('the gates box under the fleet ladder lists every gate by kind, with what it reads and its counters at each size (789)', () => {
  sandbox.GSD_APP.campaign = '1';
  const ledger = { contract: 'gsd-let-through-ledger-1', from_n: 256, confirm_after: 100, known_result_after: 100, known_result_from: 4096,
    ab_share: 0.5, testing_share: 0.1, confirmed_share: 0.01, signatures_total: 3, decisions_read: 41,
    about: { empty: { kind: 'fact', reads: 'mean degree at most the empty line', order: 0 },
             starts_alike: { kind: 'judgment', reads: 'every start ends alike', order: 3 },
             kept_shape: { kind: 'class', reads: 'only lattice starts that kept their shape', order: 9 },
             no_plateau: { kind: 'depth', reads: 'd_s did not settle before a deep rung', order: 14, let_through: true },
             failed: { kind: 'operational', reads: 'a seed failed for good', order: 20, let_through: false } },
    signatures: [{ signature: 'empty:k2 d1', n: 4096, kept: 120, read_one_size_up: 130, known: true }],
    gates: { kept_shape: { 16384: { held: 6, let_through: 5, clean: 2, same_gate: 2, missed: 1, open: 2, clean_since_last_miss: 0, share: 0.5, label: 'A/B' } },
             empty: { 64: { held: 0, let_through: 900, clean: 880, same_gate: 870, missed: 3, open: 17, clean_since_last_miss: 412, share: 1.0, label: 'records only' },
                      256: { held: 70, let_through: 72, clean: 71, same_gate: 70, missed: 0, open: 1, clean_since_last_miss: 71, share: 0.5, label: 'A/B' } },
             starts_alike: { 4096: { held: 11, let_through: 12, clean: 7, same_gate: 7, missed: 1, open: 4, clean_since_last_miss: 2, share: 0.5, label: 'A/B' } } } };
  sandbox.GSD_APP.landscapePayload = { campaign_id: '1', revision: 'r9', dimension_points: [], top_candidates: [],
    counts: {}, exposure: {}, limits: {}, gates_ledger: ledger, selection: {} };
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {}, rung_distribution: [] });
  const box = getElementById('gatesBox').innerHTML;
  for (const needle of [/<b>empty<\/b>/, /mean degree at most the empty line/, />fact</, />judgment</, />class</,
                        /<code>N=256<\/code>/, /A\/B 50%/, /records only all/, />70</, /held back/, /held again/, /passed/,
                        /each law\u2019s arm drawn once for the gate/, /repeats_a_known_result reads from N=4,096/, /1 signature\(s\) of 3/]) {
    if (!needle.test(box)) throw new Error(`the gates box lacks ${needle}: ${box}`);
  }
  const order = ['<b>empty</b>', '<b>starts_alike</b>', '<b>kept_shape</b>'].map((x) => box.indexOf(x));
  if (!(order[0] < order[1] && order[1] < order[2])) throw new Error(`the gates are not in their kinds' order: ${order}`);
  if ((box.match(/<b>empty<\/b>/g) || []).length !== 1) throw new Error('a gate is named on every size');
  if (!/<b>no_plateau<\/b>[\s\S]*not fired yet in this study/.test(box)) throw new Error(`a gate that has not fired is not listed: ${box}`);
  if (/<b>failed<\/b>/.test(box)) throw new Error('a gate that lets nothing through is listed');
  if (/>scored</.test(box)) throw new Error('a ledger without scores draws a scored column');
  sandbox.GSD_APP.landscapePayload = null;
});

check('the gates box counts what each gate let through that scored, over every batch or in one (790)', () => {
  sandbox.GSD_APP.campaign = '1';
  const ledger = { from_n: 256, ab_share: 0.5, decisions_read: 77, scored_from: ['1', '2'], scored_at_least: false,
    about: { starts_alike: { kind: 'judgment', reads: 'every start ends alike', order: 3, let_through: true } },
    gates: { starts_alike: { 65536: { held: 4, let_through: 4, clean: 1, same_gate: 1, missed: 1, open: 2, share: 0.5,
                                      label: 'A/B', scored: 2, best_score: 71, best_law: ['2', '213f65'] },
                             4096: { held: 9, let_through: 8, clean: 8, same_gate: 8, missed: 0, open: 0, share: 0.5,
                                     label: 'A/B', scored: 0, best_score: null, best_law: null } } } };
  sandbox.GSD_APP.landscapePayload = { campaign_id: '1', revision: 'r-s1', dimension_points: [], top_candidates: [],
    counts: {}, exposure: {}, limits: {}, gates_ledger: ledger, selection: {} };
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {}, rung_distribution: [] });
  let box = getElementById('gatesBox').innerHTML;
  if (!/>scored</.test(box) || !/<b>2<\/b> <small class=muted>best 71<\/small>/.test(box)) throw new Error(`no scored count: ${box}`);
  if (/batch 1/.test(box)) throw new Error('scores read over every batch are named as one batch\u2019s');
  sandbox.GSD_APP.landscapePayload = { ...sandbox.GSD_APP.landscapePayload, revision: 'r-s2',
    gates_ledger: { ...ledger, decisions_read: 78, scored_from: ['1'], scored_at_least: true } };
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {}, rung_distribution: [] });
  box = getElementById('gatesBox').innerHTML;
  if (!/scored <small class=muted>batch 1<\/small>/.test(box) || !/<b>\u22652<\/b>/.test(box)) throw new Error(`one batch's scores not named so: ${box}`);
  sandbox.GSD_APP.landscapePayload = null;
});

check('the fleet ladder counts chains that are still running', () => {
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {},
    rung_distribution: [{ n: 1048576, running: 3, running_laws: 2, laws: 2, running_seconds: 5400, measured: 0, attempts: 0,
                          simulation_seconds_total: 0, rung_seconds_total: 0 }] });
  const html = getElementById('rungLadder').innerHTML;
  if (!/<b>2<\/b>/.test(html)) throw new Error(`a rung with only running laws shows none running: ${html}`);
  if (!/1h30m</.test(html)) throw new Error(`running time is not counted: ${html}`);
});

check('held laws are counted beside the stranded ones, and holds alone are not a warning', () => {
  const el = getElementById('strandedAlert');
  sandbox.GSD_APP.renderStranded({ operational_alerts: [{ code: 'STRANDED_SCIENTIFIC_WORK', severity: 'info',
    headline: 'no stranded laws · 203 held by the engine, waiting by design', stranded: 0, held: 203, by_state: {},
    candidates: [], explanation: '203 held law(s) own no work by design' }] });
  let html = el.innerHTML;
  if (/alert-box warn/.test(html)) throw new Error(`holds alone render as a warning: ${html}`);
  if (/<table/.test(html)) throw new Error('an empty stranded table is drawn for holds');
  if (!/203 held/.test(html)) throw new Error(`the held count is not shown: ${html}`);
  sandbox.GSD_APP.renderStranded({ operational_alerts: [{ code: 'STRANDED_SCIENTIFIC_WORK', severity: 'warning',
    headline: '1 STRANDED · running with no queued or leased work · 203 held by the engine, waiting by design',
    stranded: 1, held: 203, by_state: { BASE_BLOCK_RUNNING: 1 },
    candidates: [{ candidate_id: 's'.padEnd(64, '0'), state: 'BASE_BLOCK_RUNNING', candidate_state_age_seconds: 42 }] }] });
  html = el.innerHTML;
  if (!/alert-box warn/.test(html) || !/<table/.test(html)) throw new Error(`a stranded law is not a warning with its row: ${html}`);
  if (!/1 STRANDED/.test(html) || !/203 held/.test(html)) throw new Error(`the counts are not both shown: ${html}`);
});

check('a paused fleet empties NOW RESEARCHING at once, pointer or no pointer', () => {
  const root = getElementById('live');
  sandbox.GSD_APP.renderLive({ paused: false, active: [{ candidate_id: 'a'.repeat(64), ensemble_code: 'G-1',
    rungs: [], running: [{ n: 4096, seed: 0, sealed: false, owner: 'executor-1', stage: 'rung_n4096',
    started_utc: '2026-09-17T21:00:00Z', since_s: 120 }], probing: [] }], compute_utilization: {} });
  if (!/N=4096/.test(root.innerHTML)) throw new Error(`the running row was not drawn: ${root.innerHTML}`);
  root.dataset.hovering = '1';
  sandbox.GSD_APP.renderLive({ paused: true, active: [], compute_utilization: {} });
  if (/N=4096/.test(root.innerHTML)) throw new Error('a paused fleet still shows work in flight');
  delete root.dataset.hovering;
});

check('laws the controller has not decided for ten minutes are a warning above the stranded box', () => {
  const el = getElementById('strandedAlert');
  sandbox.GSD_APP.renderStranded({ operational_alerts: [
    { code: 'DECISIONS_BEHIND', severity: 'warning', headline: '134 law(s) await a decision, the oldest for 412 min',
      explanation: 'Laws still waiting after ten minutes are laws it is not reaching' },
    { code: 'STRANDED_SCIENTIFIC_WORK', severity: 'warning', headline: '134 STRANDED', stranded: 134, held: 538,
      by_state: {}, candidates: [] }] });
  const html = el.innerHTML;
  if (!/134 law\(s\) await a decision, the oldest for 412 min/.test(html)) throw new Error(`the backlog is not shown: ${html}`);
  if (html.indexOf('await a decision') > html.indexOf('134 STRANDED')) throw new Error('the backlog is not above the stranded box');
  sandbox.GSD_APP.renderStranded({ operational_alerts: [{ code: 'DECISIONS_BEHIND', severity: 'warning',
    headline: '3 law(s) await a decision, the oldest for 11 min', explanation: '' }] });
  if (!/3 law\(s\) await a decision/.test(el.innerHTML)) throw new Error('the backlog alone is not shown');
});

check('the RAM scratch alerts are a banner on the System page', () => {
  const el = getElementById('strandedAlert');
  sandbox.GSD_APP.renderStranded({ operational_alerts: [
    { alert_key: 'scratch:full', source: 'scratch', severity: 'error', message: 'the scratch is full: writes stop',
      first_seen_utc: '2026-09-28T02:00:00Z', occurrences: 4 },
    { code: 'STRANDED_SCIENTIFIC_WORK', severity: 'warning', headline: '2 STRANDED', stranded: 2, held: 0,
      by_state: {}, candidates: [] }] });
  const html = el.innerHTML;
  if (!/the RAM scratch: the scratch is full: writes stop/.test(html)) throw new Error(`the scratch alert is not drawn: ${html}`);
  if (!/alert-box bad scratch-alert/.test(html)) throw new Error('a full scratch is not drawn as an error');
  if (!html.includes('tools/scratch_holders.py')) throw new Error('the banner does not name the tool that says what fills it');
  sandbox.GSD_APP.renderStranded({ operational_alerts: [] });
  if (el.innerHTML.includes('scratch-alert')) throw new Error('a resolved alert is still drawn');
});

const STUDY_RUNNING = { stage: 'reporting', campaigns: ['1', '2', '6'], index: 1, campaign_id: '2',
  study_process: { started_utc: '2026-09-30T00:18:18Z' },
  study_layout: { at_once: 1, report_workers_each: 32, why: '1 campaign(s) at once of 3: 32 cores, 32 report children each, 1 17.4 GiB, 2 18.0 GiB, 6 3.0 GiB (3 measured) in 28.0 GiB (70% of 40.0 available)' },
  study_progress: { '1': { state: 'complete', seconds: 231.1 },
                    '2': { state: 'running', stage: 'report 16 \u00b7 9 of 25 \u00b7 Scientific Compute Efficiency', started_utc: '2026-09-30T00:22:10Z' },
                    '6': { state: 'queued' } } };
check('the quiet panel points at the table while the study reports', () => {
  const html = sandbox.GSD_APP.reportQuietHtml({ quiet_report: STUDY_RUNNING, reporting_campaign_id: '1' });
  if (!html.includes('1 campaign at a time') || !html.includes('first row of the table below')) throw new Error(`not said: ${html}`);
});
check('an admin can cancel a study bundle while it holds the fleet, and nobody else sees the button', () => {
  sandbox.GSD_APP.reportAdmin = true;
  const held = sandbox.GSD_APP.reportQuietHtml({ quiet_report: Object.assign({}, STUDY_RUNNING, { runner_error: 'OperationalError: gone' }) });
  if (!held.includes('id=reportQuietCancel') || !held.includes('OperationalError: gone')) throw new Error(`no cancel: ${held}`);
  const resuming = sandbox.GSD_APP.reportQuietHtml({ quiet_report: Object.assign({}, STUDY_RUNNING, { stage: 'resuming' }) });
  if (resuming.includes('reportQuietCancel')) throw new Error('a bundle that is resuming offers a cancel');
  sandbox.GSD_APP.reportAdmin = false;
  if (sandbox.GSD_APP.reportQuietHtml({ quiet_report: STUDY_RUNNING }).includes('reportQuietCancel')) {
    throw new Error('a viewer without the token sees the cancel');
  }
});
check('the study bundle being made is the first row, each campaign in number order with a bar', () => {
  sandbox.GSD_APP.reportStatusForTest = { quiet_report: STUDY_RUNNING };
  sandbox.GSD_APP.studyBundles = { download_prefix: '/reports/study/bundles/', bundles: [{
    filename: 'study_252_old.tar.zst', built_utc: '2026-09-26T23:19:00Z', bytes: 3100000, missing: [],
    campaigns: [{ campaign_id: '1' }, { campaign_id: '2' }, { campaign_id: '3' }, { campaign_id: '4' }] }] };
  sandbox.GSD_APP.renderStudyBundles();
  const html = getElementById('studyBundles').innerHTML;
  const live = html.split('<tr class="bundle-live study-live">')[1];
  if (!live) throw new Error('the study bundle in flight is not a row of the table');
  const first = live.split('</tr>')[0];
  const order = [...first.matchAll(/study-live-camp"><b>([^<]+)<\/b>/g)].map((m) => m[1]);
  if (order.join(',') !== '1,2,6') throw new Error(`the campaigns are not in number order: ${order}`);
  if (!/study-bar complete[^>]*><i style="width:100%"/.test(first)) throw new Error('a finished campaign is not a full bar');
  if (!/report 9 of 25: Scientific Compute Efficiency/.test(first)) throw new Error(`the running report is not said: ${first}`);
  if (!/width:59%/.test(first)) throw new Error('the bar does not stand at report 9 of 25: eight done');
  const whyRow = (html.split('study-why-row">')[1] || '').split('</tr>')[0];
  if (!/queued: one campaign at a time/.test(first) || !/28\.0 GiB \(70% of 40\.0 available\)/.test(whyRow)) {
    throw new Error('why the campaigns wait is not said');
  }
  if (!/<td colspan=5 class="study-camps study-live-camps">/.test(first)) {
    throw new Error(`the campaigns of the bundle being made do not take the empty columns: ${first}`);
  }
  if ((first.match(/<td/g) || []).length !== 3) throw new Error(`the row being made has cells with nothing in them: ${first}`);
  if (!/making it<br>reporting/.test(first)) throw new Error('the stage is not said under "making it"');
  if (html.indexOf('study-live') > html.indexOf('study_252_old')) throw new Error('the running row is not first');
  if (!/campaigns <b>1, 2, 3, 4<\/b>/.test(html)) throw new Error('an old bundle without detail does not keep its campaigns on one line');
  if (!/data-study-delete="study_252_old.tar.zst"/.test(html)) throw new Error('an old bundle cannot be deleted from its row');
  sandbox.GSD_APP.reportStatusForTest = {};
});

check('a study bundle row links its gate trees and its Classify maps', () => {
  sandbox.GSD_APP.reportStatusForTest = {};
  sandbox.GSD_APP.studyBundles = { download_prefix: '/reports/study/bundles/', bundles: [{
    filename: 'study_252_new.tar.zst', svg: 'study_252_new.gate_trees.svg', maps: 'study_252_new.classify_maps.svg',
    built_utc: '2026-10-01T00:20:17Z', bytes: 65679825, missing: [], campaigns: [{ campaign_id: '1', laws: 10000 }] },
    { filename: 'study_252_old.tar.zst', svg: 'study_252_old.gate_trees.svg', built_utc: '2026-09-26T23:19:00Z',
      bytes: 3100000, missing: [], campaigns: [{ campaign_id: '1' }] }] };
  sandbox.GSD_APP.renderStudyBundles();
  const html = getElementById('studyBundles').innerHTML;
  const [, newRow, oldRow] = html.split('<tr class=study-row><td>');
  if (!/href="[^"]*study_252_new\.gate_trees\.svg"[^>]*>gate trees</.test(newRow || '')) throw new Error(`no gate trees link: ${newRow}`);
  if (!/href="[^"]*study_252_new\.classify_maps\.svg"[^>]*>maps</.test(newRow || '')) throw new Error(`no maps link: ${newRow}`);
  if (/>maps</.test(oldRow || '')) throw new Error('a bundle made before 559 has no maps, and none is linked');
  if (!/>pages</.test(html)) throw new Error('the column is not called pages');
});

check('577: a study bundle row links its front page first', () => {
  sandbox.GSD_APP.reportStatusForTest = {};
  sandbox.GSD_APP.studyBundles = { download_prefix: '/reports/study/bundles/', bundles: [{
    filename: 'study_253_new.tar.zst', svg: 'study_253_new.gate_trees.svg', maps: 'study_253_new.classify_maps.svg',
    explorer: 'study_253_new.explorer.html', front: 'study_253_new.index.html', advice: 'study_253_new.advice.json',
    built_utc: '2026-10-03T20:20:17Z', bytes: 65679825, missing: [], campaigns: [{ campaign_id: '1', laws: 984 }] },
    { filename: 'study_253_old.tar.zst', svg: 'study_253_old.gate_trees.svg', explorer: 'study_253_old.explorer.html',
      built_utc: '2026-10-03T07:32:15Z', bytes: 3100000, missing: [], campaigns: [{ campaign_id: '1' }] }] };
  sandbox.GSD_APP.renderStudyBundles();
  const html = getElementById('studyBundles').innerHTML;
  const [, newRow, oldRow] = html.split('<tr class=study-row><td>');
  const front = /href="[^"]*study_253_new\.index\.html"[^>]*>front page</.exec(newRow || '');
  if (!front) throw new Error(`no front page link: ${newRow}`);
  if (front.index > (newRow || '').indexOf('>gate trees<')) throw new Error('the front page is not the first page of the row');
  if (/front page</.test(oldRow || '')) throw new Error('a bundle made before 577 has no front page, and none is linked');
});

check('577, 862 and 889: the nav reads Home, Map, Top, Campaigns, Explorer, Reports, Calibration, System', () => {
  const html = String(getElementById('gsdSystemHeader').innerHTML);
  const order = [...html.matchAll(/class="gsd-nav-link" data-gsd-page="([a-z]+)"/g)].map((m) => m[1]);
  if (order.join(',') !== 'home,map,top,campaigns,explorer,reports,calibration,system') {
    throw new Error(`the nav reads ${order.join(', ')}`);
  }
});

check("a page's address lands on that page, any other on home", () => {
  for (const [asked, page] of [['campaigns', 'campaigns'], ['explorer', 'explorer'], ['map', 'map'], ['nowhere', 'home']]) {
    const lands = sandbox.GSD_APP.landingPage(asked);
    if (lands !== page) throw new Error(`${asked} lands on ${lands}, not ${page}`);
  }
});

check('572: a study bundle row links its explorer', () => {
  sandbox.GSD_APP.reportStatusForTest = {};
  sandbox.GSD_APP.studyBundles = { download_prefix: '/reports/study/bundles/', bundles: [{
    filename: 'study_253_new.tar.zst', svg: 'study_253_new.gate_trees.svg', maps: 'study_253_new.classify_maps.svg',
    explorer: 'study_253_new.explorer.html', built_utc: '2026-10-03T00:20:17Z', bytes: 65679825, missing: [],
    campaigns: [{ campaign_id: '1', laws: 1000 }] },
    { filename: 'study_252_old.tar.zst', svg: 'study_252_old.gate_trees.svg', maps: 'study_252_old.classify_maps.svg',
      built_utc: '2026-10-02T14:03:00Z', bytes: 3100000, missing: [], campaigns: [{ campaign_id: '1' }] }] };
  sandbox.GSD_APP.renderStudyBundles();
  const html = getElementById('studyBundles').innerHTML;
  const [, newRow, oldRow] = html.split('<tr class=study-row><td>');
  if (!/href="[^"]*study_253_new\.explorer\.html"[^>]*>study explorer</.test(newRow || '')) throw new Error(`no explorer link: ${newRow}`);
  if (/explorer</.test(oldRow || '')) throw new Error('a bundle made before 572 has no explorer, and none is linked');
});

check("578: a study bundle row links the gate trees' page, and no maps beside an explorer", () => {
  sandbox.GSD_APP.reportStatusForTest = {};
  sandbox.GSD_APP.studyBundles = { download_prefix: '/reports/study/bundles/', bundles: [{
    filename: 'study_252_new.tar.zst', gates: 'study_252_new.gate_trees.html', explorer: 'study_252_new.explorer.html',
    front: 'study_252_new.index.html', advice: 'study_252_new.advice.json', built_utc: '2026-10-03T12:40:00Z',
    bytes: 66700000, missing: [], campaigns: [{ campaign_id: '1', laws: 10000 }] },
    { filename: 'study_252_old.tar.zst', svg: 'study_252_old.gate_trees.svg', maps: 'study_252_old.classify_maps.svg',
      explorer: 'study_252_old.explorer.html', front: 'study_252_old.index.html', built_utc: '2026-10-03T10:12:00Z',
      bytes: 65700000, missing: [], campaigns: [{ campaign_id: '1' }] }] };
  sandbox.GSD_APP.renderStudyBundles();
  const html = getElementById('studyBundles').innerHTML;
  const [, newRow, oldRow] = html.split('<tr class=study-row><td>');
  const page = /<a class=chip href="([^"]*)"[^>]*title="([^"]*)">gate trees</.exec(newRow || '');
  if (!page || !/study_252_new\.gate_trees\.html$/.test(page[1])) throw new Error(`no gate trees page link: ${newRow}`);
  if (!/explorer/.test(page[2]) || /picture|\b5\d\d\b/.test(page[2])) throw new Error(`the gate trees' page is titled as a picture or by a build: ${page[2]}`);
  if (/\.svg"/.test(newRow || '') || />maps</.test(newRow || '')) throw new Error(`a bundle since 578 links a picture: ${newRow}`);
  const order = ['>front page<', '>gate trees<', '>study explorer<'].map((s) => (newRow || '').indexOf(s));
  if (order.some((i) => i < 0) || order.join() !== [...order].sort((a, b) => a - b).join()) throw new Error(`the pages are not front page, gate trees, explorer: ${newRow}`);
  const picture = /<a class=chip href="([^"]*)"[^>]*title="([^"]*)">gate trees</.exec(oldRow || '');
  if (!picture || !/study_252_old\.gate_trees\.svg$/.test(picture[1]) || !/picture/.test(picture[2])) throw new Error(`an older bundle lost its gate trees' picture: ${oldRow}`);
  if (/>maps</.test(oldRow || '')) throw new Error('a bundle with an explorer links its Classify maps as well');
});

check('a budget is written without zero units', () => {
  const t = sandbox.GSD_APP.budgetText;
  if (typeof t !== 'function') throw new Error('budgetText is not reachable');
  const cases = [[3600, '1h'], [14400, '4h'], [921600, '256h'], [900, '15m'], [5400, '1h30m'], [60, '1m'], [45, '45s'], [3690, '1h1m30s']];
  for (const [seconds, text] of cases) {
    if (t(seconds) !== text) throw new Error(`budgetText(${seconds}) = ${t(seconds)}, expected ${text}`);
  }
});

check('a Top 100 card says how deep its law is and what the engine last decided', () => {
  const id = 'k'.padEnd(64, '0');
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscapePayload = { campaign_id: '1', revision: 'r2', dimension_points: [],
    top_candidates: [{ candidate_id: id, ensemble_code: 'G-10630', state: 'PARKED', law_score: lawScore(17),
                       stability_top_rung: 65536, terms: [], mean_degree: 3.93,
                       engine_decision: { action: 'run_next', rule: 'settled', priority: 1, at_n: 65536, next_n: 262144 } }],
    counts: {}, exposure: {}, limits: {}, selection: {} };
  sandbox.GSD_APP.renderHome({ active: [], campaigns: [], runtime_counts: {}, compute_utilization: {} });
  const html = getElementById('best').innerHTML;
  if (!/to N=65536/.test(html) || !/next N=262144/.test(html) || !/settled/.test(html)) {
    throw new Error(`the card lacks its depth or its engine decision: ${html}`);
  }
  sandbox.GSD_APP.landscapePayload = null;
});

check('a rung whose population cannot be estimated draws no guess', () => {
  sandbox.GSD_APP.renderHome({
    active: [{ candidate_id: 'z'.padEnd(64, '0'), ensemble_code: 'G-NEW',
               state: 'BASE_BLOCK_RUNNING', law: '+1*edge_count', terms: [],
               rungs: [], running: [{ n: 65536, seed: 0, since_s: 60, lane: 'extension',
                 eta: { identifiable: false, median_seconds: null,
                        candidate_scale: { factor: null, reason: '0 comparable lower rung(s)' },
                        extrapolation: { seconds: null, basis: null,
                                         reason: 'the first rung of this law: nothing below it to extrapolate from' },
                        progress: { elapsed_seconds: 60, remaining_seconds: null, overdue: false } } }],
               queued: [], ladder: [{ n: 65536, standing: 'running' }], largest_n: 65536 }],
    campaigns: [], runtime_counts: {},
    compute_utilization: { simulation_busy: 1, analysis_busy: 0, total_slots: 32 },
  });
  const html = getElementById('live').innerHTML;
  if (!/lease-bar unknown/.test(html)) throw new Error(`an unidentifiable lease guessed: ${html}`);
  if (!/no estimate: first rung/.test(html)) {
    throw new Error(`the refusal does not say why: ${html}`);
  }
  if (!/first rung of this law/.test(html)) throw new Error(`the reason is not on hover: ${html}`);
});

check('a running campaign still lists its candidates', () => {
  sandbox.GSD_APP.renderHome({
    active: [{ candidate_id: 'x'.padEnd(64, '0'), ensemble_code: 'G-7', state: 'BASE_BLOCK_RUNNING',
               law: '+1*edge_count', terms: [], rungs: [{ n: 64 }], running: [{ n: 256 }],
               queued: [], upcoming_rungs: [1024], largest_n: 256 }],
    campaigns: [], runtime_counts: {},
    compute_utilization: { simulation_busy: 1, analysis_busy: 0, total_slots: 32 },
  });
  const html = getElementById('live').innerHTML;
  if (/no active candidates/.test(html) || /in flight/.test(html)) {
    throw new Error('a live candidate rendered the empty state');
  }
  if (!/(C\d+-G7|G-7)\b/.test(html)) throw new Error('the candidate is missing from the table');
});

check('the Reports page lists study bundles only, each campaign on its line with its time', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.studyBundles = { download_prefix: '/reports/study/bundles/', bundles: [{
    filename: 'study_252_x.tar.zst', built_utc: '2026-09-29T17:57:56Z', bytes: 73400000, reporting_seconds: 512,
    missing: [], campaigns: [
      { campaign_id: '1', label: 'T0/16', laws: 10000, graphs: 78691, seconds: 447.5 },
      { campaign_id: '6', label: 'controls', laws: 5, graphs: 93, seconds: 10.7 }] }] };
  sandbox.GSD_APP.renderStudyBundles();
  const html = getElementById('studyBundles').innerHTML;
  if (!/reports took/.test(html)) throw new Error('the study table must say how long the reports took');
  if (!/8m32/.test(html)) throw new Error('the report phase time is missing');
  if ((html.match(/class=study-camp /g) || []).length !== 2) throw new Error('each campaign its own entry');
  if (!/<tr class=study-camps-row><td colspan=7 class=study-camps[^>]*><div class=study-camps-list><div class=study-camp /.test(html)) {
    throw new Error('the campaigns are not laid out side by side on the line under their bundle');
  }
  if (!/7m27/.test(html) || !/10,000 laws/.test(html)) throw new Error("a campaign's laws and time are missing");
});

check('Home says which campaign it is loading and stops saying so when it has landed', () => {
  sandbox.GSD_APP.campaign = '3';
  sandbox.GSD_APP.landscape = { campaign_id: '1', dimension_points: [] };
  sandbox.GSD_APP.homeLoading = { campaign: '3', overview: false };
  sandbox.GSD_APP.markHomeLoading();
  const note = getElementById('homeLoadingNote');
  if (!note || !/loading campaign 3/.test(note.innerHTML)) throw new Error('no loading line for campaign 3');
  sandbox.GSD_APP.homeLoading = { campaign: '3', overview: true };
  sandbox.GSD_APP.markHomeLoading();
  if (!/its landscape is on its way/.test(getElementById('homeLoadingNote').innerHTML)) {
    throw new Error('the line must say what is still on its way');
  }
  sandbox.GSD_APP.landWaiting = { campaign: '3', read: 7, of: 10 };
  sandbox.GSD_APP.markHomeLoading();
  if (!/its landscape is on its way \(7 of 10 batches read\)/.test(getElementById('homeLoadingNote').innerHTML)) {
    throw new Error('a study says how many of its batches have their landscape');
  }
  sandbox.GSD_APP.landWaiting = null;
  sandbox.GSD_APP.landscape = { campaign_id: '3', dimension_points: [] };
  sandbox.GSD_APP.markHomeLoading();
  if (sandbox.GSD_APP.homeLoading !== null) throw new Error('loaded: the loading state must end');
});

check('ten batch chips stay on one row', () => {
  const css = fs.readFileSync(path.join(uiDir, 'system.css'), 'utf8');
  const row = (css.match(/\.study-card \.draw-batches\{([^}]*)\}/) || [])[1] || '';
  const chip = (css.match(/\.draw-batch\{([^}]*)\}/) || [])[1] || '';
  if (!/flex-wrap:nowrap/.test(row) || !/min-width:16px/.test(chip)) throw new Error(`the batch row wraps: ${row} ${chip}`);
});



check('the explorer candidate column is the G-code', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.explorerRows = [
    { ...EXPLORER_ROWS[0], ensemble_code: 'G-917', candidate_number: 12 },
    { ...EXPLORER_ROWS[1], ensemble_code: null, candidate_number: 1739,
      state: 'PROPOSED', status_group: 'active' },
    { ...EXPLORER_ROWS[2], ensemble_code: null, candidate_number: null,
      state: 'PROPOSED', status_group: 'active' },
  ];
  sandbox.GSD_APP.explorerSort = { key: 'candidate', dir: 1 };
  sandbox.GSD_APP.drawExplorer();
  const html = getElementById('explorerBody').innerHTML;
  if (!/C1-G917/.test(html)) throw new Error('a law with a G-code does not show it as C1-G917');
  if (!/law [0-9a-f]{10}/.test(html)) throw new Error("the law's hash is not beneath its code");
  if (!/not run yet/.test(html)) {
    throw new Error('a law with no graph does not say it has not run');
  }
  const labels = [...html.matchAll(/<code[^>]*>([^<]+)<\/code>/g)].map((m) => m[1]);
  if (labels.length !== 1 || labels[0] !== 'C1-G917') {
    throw new Error(`the only code in the column should be C1-G917, got ${labels.join(', ')}`);
  }
});

check('the identity column never contradicts the score beside it', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.explorerRows = [
    { ...EXPLORER_ROWS[0], candidate_id: 'a'.padEnd(64, '0'), ensemble_code: null,
      candidate_number: 7, state: 'PROPOSED', status_group: 'active' },
  ];
  sandbox.GSD_APP.landscapePayload = { campaign_id: '1', revision: 'r2',
    dimension_points: [{ candidate_id: 'a'.padEnd(64, '0'), law_score: lawScore(9, 'lattice', 'cubic', 4096) }],
    top_candidates: [] };
  sandbox.GSD_APP.drawExplorer();
  const html = getElementById('explorerBody').innerHTML;
  if (/not run yet/.test(html)) {
    throw new Error('the column says a scored law has never run');
  }
  if (!/index is behind/.test(html)) {
    throw new Error('the column does not say why it has no code for a measured law');
  }
  sandbox.GSD_APP.explorerRows = [
    { ...EXPLORER_ROWS[0], candidate_id: 'z'.padEnd(64, '0'), ensemble_code: null,
      candidate_number: 9, state: 'PROPOSED', status_group: 'active' },
  ];
  sandbox.GSD_APP.drawExplorer();
  if (!/not run yet/.test(getElementById('explorerBody').innerHTML)) {
    throw new Error('an unmeasured law no longer says it has not run');
  }
});

check('a searched code finds its one law: C1-G917, G-917 and G917 alike', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.explorerRows = [
    { ...EXPLORER_ROWS[0], candidate_id: 'a'.padEnd(64, '0'), ensemble_code: 'G-917' },
    { ...EXPLORER_ROWS[1], candidate_id: 'b'.padEnd(64, '0'), ensemble_code: 'G-9170' },
    { ...EXPLORER_ROWS[2], candidate_id: 'c'.padEnd(64, '0'), ensemble_code: 'G-1917' },
  ];
  const query = getElementById('explorerQ');
  for (const q of ['C1-G917', 'G-917', 'g917']) {
    query.value = q;
    sandbox.GSD_APP.drawExplorer();
    const codes = [...getElementById('explorerBody').innerHTML.matchAll(/<code[^>]*>(C1-G\d+)<\/code>/g)].map((m) => m[1]);
    if (codes.join(',') !== 'C1-G917') throw new Error(`"${q}" found ${codes.join(', ') || 'nothing'}`);
  }
  for (const q of ['C1', 'c1', 'B855-C1-G917']) {
    query.value = q;
    sandbox.GSD_APP.drawExplorer();
    const codes = [...getElementById('explorerBody').innerHTML.matchAll(/<code[^>]*>(C1-G\d+)<\/code>/g)].map((m) => m[1]);
    const wanted = q.endsWith('G917') ? 'C1-G917' : 'C1-G917,C1-G9170,C1-G1917';
    if (codes.slice().sort().join(',') !== wanted.split(',').sort().join(',')) throw new Error(`"${q}" found ${codes.join(', ') || 'nothing'}`);
  }
  query.value = 'C2';
  sandbox.GSD_APP.drawExplorer();
  if (!/C2 holds the laws of campaign 2/.test(String(getElementById('explorerFilterSummary').textContent || ''))) {
    throw new Error('a campaign code of another campaign does not say whose laws they are');
  }
  query.value = 'C2-G917';
  sandbox.GSD_APP.drawExplorer();
  if (/<code[^>]*>C1-G/.test(getElementById('explorerBody').innerHTML)) throw new Error("another campaign's code matched here");
  if (!/is a law of campaign 2/.test(String(getElementById('explorerFilterSummary').textContent || ''))) {
    throw new Error('a code of another campaign does not say whose it is');
  }
  query.value = '';
});
check('the Explorer across the study finds a code in its own campaign and links it there', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscape = null;
  getElementById('explorerScope').value = 'study';
  sandbox.GSD_APP.explorerRows = [
    { ...EXPLORER_ROWS[0], candidate_id: 'a'.padEnd(64, '0'), ensemble_code: 'G-917', campaign_id: '1' },
    { ...EXPLORER_ROWS[1], candidate_id: 'b'.padEnd(64, '0'), ensemble_code: 'G-917', campaign_id: '2' },
    { ...EXPLORER_ROWS[2], candidate_id: 'c'.padEnd(64, '0'), ensemble_code: 'G-12', campaign_id: '2' },
  ];
  const query = getElementById('explorerQ');
  try {
    for (const [q, want] of [['C2-G917', 'C2-G917'], ['C1-G917', 'C1-G917']]) {
      query.value = q;
      sandbox.GSD_APP.drawExplorer();
      const html = getElementById('explorerBody').innerHTML;
      const codes = [...html.matchAll(/<code[^>]*>(C\d+-G\d+)<\/code>/g)].map((m) => m[1]);
      if (codes.join(',') !== want) throw new Error(`"${q}" found ${codes.join(', ') || 'nothing'} across the study`);
      if (!html.includes(`campaign=${want[1]}`)) throw new Error(`${want} does not link into campaign ${want[1]}`);
    }
    query.value = '';
    sandbox.GSD_APP.drawExplorer();
    const summary = String(getElementById('explorerFilterSummary').textContent || '');
    if (!/of 2 campaigns/.test(summary)) throw new Error(`the status does not say how many campaigns it shows: ${summary}`);
    if (/is a law of campaign/.test(summary)) throw new Error('across the study, a code is not sent to the header');
    const merged = sandbox.GSD_APP.mergeFilterOptions([{ filter_options: { rungs: [256, 64], states: ['A'] } },
                                                         { filter_options: { rungs: [4096, 64], states: ['B'] } }]);
    if (merged.rungs.join(',') !== '64,256,4096' || merged.states.join(',') !== 'A,B') {
      throw new Error(`the filters are not what any campaign holds: ${JSON.stringify(merged)}`);
    }
  } finally {
    query.value = '';
    getElementById('explorerScope').value = '';
  }
});

check('the study now is one bar: the laws drawn blind against the laws the map chose, the controls a tick', () => {
  sandbox.GSD_APP.campaign = 'study';
  const row = (id, extra) => ({ campaign_id: id, quadrant: `quadrant ${id}`, state: 'active', slots_held: 0,
    analyses_running: 0, work_queued: 0, graphs_total: 100, graphs_created: 100, laws_total: 10, law_budget: null,
    chains_per_seed: 1, ...extra });
  const batch = (id, extra) => row(id, { design_kind: 'blind', group: 'A', study_batch: true,
    law_budget: { law_budget: 1000, laws_held: 600 }, high_score: { score: 19, scoring: 2 }, ...extra });
  sandbox.GSD_APP.renderStudyNow({ campaigns: [
    batch('1', { slots_held: 3, work_queued: 12, graphs_created: 1012, graphs_total: 1000,
                 work_left: { core_hours_left: 21.5, hours_at_last_hours_pace: 1.4 } }),
    batch('2', { deepest_n: 65536 }),
    row('11', { name: 'campaign-standing-controls', control_verdict: { overall: 'pass' }, laws_total: 5 }),
    row('12', { design_kind: 'seed', group: 'N', laws_total: 59, high_score: { scoring: 7 } }),
    row('13', { design_kind: 'focus', group: 'N', laws_total: 44, slots_held: 2 }),
    row('14', { design_kind: 'focus', group: 'D', laws_total: 6 }),
    row('5', { archived: true, design_kind: 'blind', laws_total: 999 }),
  ] });
  const html = getElementById('studyNow').innerHTML;
  if ((html.match(/<button/g) || []).length !== 1 || !html.includes('data-campaign="study"')) throw new Error(`not one bar: ${html}`);
  if (/study-card|draw-batch/.test(html)) throw new Error('a batch or a campaign still has a card of its own');
  const blind = html.split('study-side blind')[1].split('study-side zoned')[0], zoned = html.split('study-side zoned')[1];
  for (const want of ['1,200 laws of 2,000', '92%', '1,112 graphs, 1,100 done', '4 score', 'running 3', 'queued 12',
                      'deepest N=65,536', 'at least 21.5 core-h left, 1.4 h at the last hour', '2 campaigns']) {
    if (!blind.includes(want)) throw new Error(`the blind side lacks "${want}": ${blind}`);
  }
  for (const want of ['109 laws', '8%', '7 score', 'running 2', '3 campaigns']) {
    if (!zoned.includes(want)) throw new Error(`the zoned side lacks "${want}": ${zoned}`);
  }
  if (!/study-split-blind style="width:91\.7%/.test(html)) throw new Error('the bar is not split by the laws on each side');
  if (!html.includes('known answers: pass') || html.includes('999')) throw new Error('the controls are not a tick, or an archived batch counts');
  if (!/class="study-split current"/.test(html)) throw new Error('the bar is not marked while the panels read every batch');
  sandbox.GSD_APP.paintCampaignScope();
  if (getElementById('landScope').textContent !== '') throw new Error('893: no box title says "all batches"');
  sandbox.GSD_APP.renderStudyNow({ campaigns: [row('11', { name: 'campaign-standing-controls', work_queued: 8,
    work_left: { core_hours_left: 0, graphs_queued: 8, unpriced_rungs: [256] } })] });
  const alone = getElementById('studyNow').innerHTML;
  if (!alone.includes('known answers: not read yet') || !alone.includes('0 laws')) throw new Error(`a folder with only its controls: ${alone}`);
  sandbox.GSD_APP.renderStudyNow({ campaigns: [batch('1', { work_queued: 8, high_score: null,
    work_left: { core_hours_left: 0, graphs_queued: 8, unpriced_rungs: [256] } })] });
  const unpriced = getElementById('studyNow').innerHTML;
  if (!unpriced.includes('queued 8 · time left not known yet (no seed at N=256 has ended here)') || unpriced.includes('nothing left to run · 1 campaign')) {
    throw new Error(`a queue with no price reads as nothing: ${unpriced}`);
  }
});

check('the study now is drawn the first time even under the pointer, and a failed ask says so and asks again soon', () => {
  const root = getElementById('studyNow');
  root.innerHTML = '<div class="empty">every campaign of the study, loading…</div>';
  root.dataset.hovering = '1';
  sandbox.GSD_APP.renderStudyNow({ campaigns: [{ campaign_id: '1', design_kind: 'blind', group: 'A', study_batch: true,
    state: 'active', laws_total: 3, graphs_total: 3, graphs_created: 3, slots_held: 0, work_queued: 0 }] });
  delete root.dataset.hovering;
  if (!root.innerHTML.includes('data-campaign="study"')) throw new Error(`the first drawing waited for the pointer to move: ${root.innerHTML}`);
  if (typeof sandbox.GSD_APP.studyNowRetryMs !== 'number' || sandbox.GSD_APP.studyNowRetryMs > 5000) {
    throw new Error('a study now not yet read is not asked for again within a few seconds');
  }
});

check('the candidate column sorts by G-code, smallest first', () => {
  sandbox.GSD_APP.campaign = '1';
  sandbox.GSD_APP.landscape = null;
  sandbox.GSD_APP.explorerRows = [
    { ...EXPLORER_ROWS[0], candidate_id: 'a'.padEnd(64, '0'), ensemble_code: 'G-9170' },
    { ...EXPLORER_ROWS[1], candidate_id: 'b'.padEnd(64, '0'), ensemble_code: null,
      candidate_number: 5, state: 'PROPOSED', status_group: 'active' },
    { ...EXPLORER_ROWS[2], candidate_id: 'c'.padEnd(64, '0'), ensemble_code: 'G-1' },
  ];
  sandbox.GSD_APP.explorerSort = { key: 'candidate', dir: 1 };
  sandbox.GSD_APP.drawExplorer();
  const html = getElementById('explorerBody').innerHTML;
  const order = [...html.matchAll(/<code[^>]*>C1-(G\d+)<\/code>/g)].map((m) => m[1]);
  if (order[0] !== 'G1') {
    throw new Error(`ascending did not put the earliest law first: ${order.join(', ')}`);
  }
  if (order.join(',') !== 'G1,G9170') {
    throw new Error(`G-codes are not in numeric order: ${order.join(', ')}`);
  }
  const identities = (html.split('<tbody>')[1] || '').split('<tr>').slice(1)
    .map((row) => (row.split('</td>')[0] || '').replace(/<[^>]*>/g, '').trim());
  if (identities.length !== 3) {
    throw new Error(`expected three rows, read ${identities.length}`);
  }
  if (!/^C1-G\d+law [0-9a-f]{10}/.test(identities[0])) {
    throw new Error('ascending opens on a law that has never run rather than on '
      + `the earliest G-code: ${identities.join(' | ')}`);
  }
  const notRun = html.indexOf('not run yet');
  if (notRun === -1) throw new Error('the un-run law vanished from the table');
  if (notRun < html.lastIndexOf('G-9170')) {
    throw new Error('a law that has never run sorted above laws that have; '
      + 'ascending should open on the earliest G-code');
  }
  sandbox.GSD_APP.explorerSortBy('candidate');
  const down = getElementById('explorerBody').innerHTML;
  const downOrder = [...down.matchAll(/<code[^>]*>C1-(G\d+)<\/code>/g)].map((m) => m[1]);
  if (downOrder.join(',') !== 'G9170,G1') {
    throw new Error(`descending did not reverse the G-codes: ${downOrder.join(', ')}`);
  }
  if (!/identity-pending/.test(html)) {
    throw new Error('a law with no G-code is not marked as not having one');
  }
});


check('575: a score and its badge never split a word', () => {
  const id = 'e'.repeat(64);
  const kept = sandbox.GSD_APP.landscape;
  const lease = () => ({ paused: false, compute_utilization: {}, rung_distribution: [],
    active: [{ candidate_id: id, ensemble_code: 'G-511', compute_seconds: 341.5, rungs: [], terms: [],
      running: [{ n: 65536, seed: 0, sealed: false, owner: 'executor-1', stage: 'rung_n65536',
                  started_utc: '2026-10-02T21:50:00Z', since_s: 341 }], probing: [] }] });
  try {
    sandbox.GSD_APP.landscape = { campaign_id: sandbox.GSD_APP.campaign, dimension_points: [] };
    sandbox.GSD_APP.renderLive(lease());
    sandbox.GSD_APP.landscape = { campaign_id: sandbox.GSD_APP.campaign,
      dimension_points: [{ candidate_id: id, law_score: lawScore(57, 'empty') }] };
    sandbox.GSD_APP.renderLive(lease());
    const law = liveLaw(id);
    if (!law) throw new Error(`no row was drawn: ${getElementById('live').innerHTML.slice(0, 300)}`);
    const cell = law.children[2].innerHTML;
    if (!/<span class=live-score>57<\/span><wbr><span class="score-move up">first<\/span>/.test(cell)) {
      throw new Error(`the badge has no break opportunity before it: ${cell}`);
    }
    const css = fs.readFileSync(path.join(uiDir, 'system.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    const rule = /\.score-move\s*\{([^}]*)\}/.exec(css);
    if (!rule || !/white-space:\s*nowrap/.test(rule[1]) || !/display:\s*inline-block/.test(rule[1])) {
      throw new Error(`the badge can still be split: .score-move {${rule && rule[1]}}`);
    }
    if (layoutDump) layoutDump.set('live', [getElementById('live').innerHTML]);
  } finally {
    sandbox.GSD_APP.landscape = kept;
  }
});

check('483: NOW RESEARCHING draws one column per thing, and the three grids line up', () => {
  const root = getElementById('live');
  sandbox.GSD_APP.renderLive({ paused: false, compute_utilization: {},
    rung_distribution: [{ n: 65536, d_s_median_seconds: 30, d_V_median_seconds: 10,
                          d_B_median_seconds: 12, d_w_median_seconds: 8 }],
    active: [{ candidate_id: 'b'.repeat(64), ensemble_code: 'G-7', compute_seconds: 214.2, rungs: [],
      running: [{ n: 4096, seed: 2, sealed: false, owner: 'executor-1', stage: 'rung_n4096',
                  started_utc: '2026-09-18T23:00:00Z', since_s: 45, budget_seconds: 60, budget_units: 375000000000,
                  eta: { progress: { median_seconds: 3.5 }, extrapolation: {} } }],
      probing: [{ n: 65536, seed: 1 }, { n: 65536, seed: 2 }] }] });
  const law = liveLaw('b'.repeat(64));
  if (!law) throw new Error(`no law row was drawn: ${root.innerHTML}`);
  if (law.children.length !== 5) {
    throw new Error(`a law row draws ${law.children.length} cells, expected 4 plus the leases`);
  }
  const compute = law.children[3];
  if (!/3m34/.test(compute.innerHTML)) throw new Error(`compute is not its own cell: ${compute.innerHTML}`);

  const leases = liveLeases('b'.repeat(64)).children;
  if (leases.length !== 3) throw new Error(`expected a chain and two probe rows, got ${leases.length}`);
  for (const lease of leases) {
    if (lease.children.length !== 7) {
      throw new Error(`a lease draws ${lease.children.length} cells, expected rung, phase, seed, elapsed, bar, typical, budget`);
    }
  }
  const [probe, probeTwo, chain] = leases;
  if (!/N=65536/.test(probe.children[0].innerHTML)) throw new Error(`the deepest rung is not first: ${probe.innerHTML}`);
  if (!/probing/.test(probe.children[1].innerHTML)) throw new Error(`the phase cell has no verb: ${probe.children[1].innerHTML}`);
  if (!/evolving/.test(chain.children[1].innerHTML)) throw new Error(`the chain's phase cell has no verb: ${chain.children[1].innerHTML}`);
  if (!/>1</.test(serialize(probe.children[2]))) throw new Error(`the probe has no seed: ${serialize(probe.children[2])}`);
  if (!/>2</.test(serialize(probeTwo.children[2]))) throw new Error(`the second probe has no seed: ${serialize(probeTwo.children[2])}`);
  if (!/>2</.test(serialize(chain.children[2]))) throw new Error(`the chain has no seed cell: ${serialize(chain.children[2])}`);
  if (!/live-clock/.test(chain.children[3].innerHTML)) throw new Error(`elapsed is not a live clock: ${chain.children[3].innerHTML}`);
  if (!/lease-bar/.test(chain.children[4].innerHTML)) throw new Error(`the bar is not in its own cell: ${chain.children[4].innerHTML}`);
  const drawnText = (cell) => cell.innerHTML.replace(/<[^>]*>/g, '');
  if (/typical/i.test(drawnText(chain.children[5]))) throw new Error(`the typical cell repeats its own heading: ${drawnText(chain.children[5])}`);
  if (!/>375 G</.test(serialize(chain.children[6]))) throw new Error(`the budget is not its own cell: ${serialize(chain.children[6])}`);

  const css = fs.readFileSync(path.join(uiDir, 'system.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const tracks = (selector) => {
    const rule = new RegExp(`${selector}\\s*\\{[^}]*grid-template-columns:([^;]+);`).exec(css);
    if (!rule) throw new Error(`${selector} declares no grid-template-columns`);
    return rule[1].trim().split(/\s+(?![^(]*\))/);
  };
  const head = tracks('\\.live-head'), lawCols = tracks('\\.live-law'), leaseCols = tracks('\\.lease');
  if (head.length !== 11) throw new Error(`the header declares ${head.length} columns, expected 11`);
  if (lawCols.length !== 5) throw new Error(`the law row declares ${lawCols.length} columns, expected 5`);
  if (leaseCols.length !== 7) throw new Error(`a lease declares ${leaseCols.length} columns, expected 7`);
  for (let i = 0; i < 4; i += 1) {
    if (lawCols[i] !== head[i]) throw new Error(`law column ${i + 1} is ${lawCols[i]} and the header's is ${head[i]}`);
  }
  for (let i = 0; i < 7; i += 1) {
    if (leaseCols[i] !== head[i + 4]) throw new Error(`lease column ${i + 1} is ${leaseCols[i]} and the header's is ${head[i + 4]}`);
  }
  for (const cls of ['lease-rung', 'lease-phase', 'lease-seed', 'lease-elapsed', 'lease-bar-cell',
                     'lease-typical', 'lease-budget', 'law-compute']) {
    if (!new RegExp(`\\.${cls}\\b`).test(css)) throw new Error(`the panel draws .${cls} and the stylesheet has no rule for it`);
  }
});

check('482: the header tiles say active workers and compute spent', () => {
  const payload = (extra) => ({ campaign_id: '1',
    runtime_counts: { graph_jobs_created: 5487, graphs_finished_last_hour: 126,
                      compute: { core_seconds: 10800 } },
    system_resources: { memory_bandwidth: {} },
    compute_utilization: Object.assign({ simulation_busy: 14, analysis_busy: 18, total_slots: 32 }, extra) });
  sandbox.GSD_SYSTEM.updateHeader(payload({}), 20);
  let detail = getElementById('gsdComputeDetail').textContent;
  if (!/core-h/.test(detail)) throw new Error(`compute spend is not the subline: ${detail}`);
  if (!/32 active/.test(getElementById('gsdCompute').textContent)) throw new Error('the headline lost the active count');
  const steady = detail;
  sandbox.GSD_SYSTEM.updateHeader(payload({ scheduler_snapshot_inconsistent: true }), 20);
  detail = getElementById('gsdComputeDetail').textContent;
  if (detail !== steady) throw new Error(`an inconsistent snapshot changed the subline: ${steady} -> ${detail}`);
  const graphs = getElementById('gsdGraphsDetail').textContent;
  if (!/126\/h/.test(graphs)) throw new Error(`the graphs rate is not drawn: ${graphs}`);
});

check('571: a missed CPU reading keeps the last good one, drawn stale, never a 0', () => {
  const busy = { simulation_busy: 14, analysis_busy: 2, total_slots: 32 };
  const header = (cpu, util) => sandbox.GSD_SYSTEM.updateHeader({ campaign_id: '1',
    runtime_counts: { compute: { core_seconds: 10800 } },
    system_resources: { cpu_percent: cpu, memory_bandwidth: {} }, compute_utilization: util }, 20);
  const tile = getElementById('gsdCpu');
  header(37.2, busy);
  if (tile.textContent !== '37%' || tile.classList.contains('stale-reading')) {
    throw new Error(`a good reading is drawn as it is: ${tile.textContent}`);
  }
  for (const missed of [null, 0]) {
    header(missed, busy);
    if (tile.textContent !== '37%' || !tile.classList.contains('stale-reading')) {
      throw new Error(`a missed reading (${missed}) replaced the last good one: ${tile.textContent}`);
    }
    if (!/last good reading/.test(String(tile.title || ''))) throw new Error('the stale reading does not say its age');
  }
  header(52, busy);
  if (tile.textContent !== '52%' || tile.classList.contains('stale-reading')) throw new Error('a new reading is not drawn');
  header(0, { simulation_busy: 0, analysis_busy: 0, total_slots: 32 });
  if (tile.textContent !== '0%' || tile.classList.contains('stale-reading')) {
    throw new Error('0% on an idle fleet is a reading, not a missed one');
  }
  const css = fs.readFileSync(path.join(uiDir, 'system.css'), 'utf8');
  if (!/\.gsd-stat>strong\.stale-reading\{color:var\(--muted\)/.test(css)) throw new Error('no stale colour');
});

check('672: the MEM BW tile says what it reads, and what a run of zeros usually means', () => {
  const header = bw => sandbox.GSD_SYSTEM.updateHeader({ campaign_id: '1', runtime_counts: { compute: {} },
    system_resources: { cpu_percent: 50, memory_bandwidth: bw }, compute_utilization: {} }, 20);
  const tile = getElementById('gsdMembwTile');
  header({ available: true, bandwidth_gbps: 0, utilization_percent: 0, history_gbps: [0, 0, 0, 0],
           source: 'file:/run/membw/latest.json', sample_age_seconds: 0.4, cap_gbps: 96, cap_source: 'umc_mem_clk' });
  const zeros = String(tile.title || '');
  if (!/file:\/run\/membw\/latest\.json/.test(zeros) || !/reads 0/.test(zeros) || !/umc_mem_bandwidth/.test(zeros)) {
    throw new Error(`a run of zeros is not explained: ${zeros}`);
  }
  header({ available: true, bandwidth_gbps: 47.2, utilization_percent: 49, history_gbps: [9.9, 28.5, 47.2],
           source: 'file:/run/membw/latest.json' });
  if (/reads 0/.test(String(tile.title || ''))) throw new Error('a live reading is called zeros');
  header({ available: false, status: 'perf not found in PATH', history_gbps: [] });
  if (!/No memory-bandwidth reading: perf not found in PATH/.test(String(tile.title || ''))) {
    throw new Error(`a missing reading does not say why: ${tile.title}`);
  }
});

const asyncChecks = [];
function checkAsync(label, fn) { if (bootPath === '/') asyncChecks.push([label, fn]); }

checkAsync('the Explorer draws every batch when the home view is All batches (it stopped silently before 779)', async () => {
  const app = sandbox.GSD_APP, sys = sandbox.GSD_SYSTEM, originalGet = sys.getJson;
  const node = (id, c) => ({ candidate_id: id.padEnd(64, '0'), campaign_id: c, state: 'STOPPED', law: 'H = 1.0 * edges',
    terms: [], created_utc: '2026-11-14T10:00:00Z', rungs: [64] });
  const maps = { 1: [node('a', '1'), node('b', '1')], 2: [node('c', '2')] };
  const before = sys.campaignRows;
  try {
    sys.campaignRows = [{ campaign_id: '1', status: 'active' }, { campaign_id: '2', status: 'active' }];
    sys.getJson = (path) => {
      const m = /\/api\/overview\/([^?]+)\?exploration=1/.exec(path);
      if (/\/api\/campaigns$/.test(path)) return Promise.resolve(sys.campaignRows);
      if (/\/api\/landscape\/study\?meta=1/.test(path)) return Promise.resolve({ batches: ['1', '2'] });
      if (!m) return Promise.resolve({});
      return Promise.resolve({ dashboard_response: {}, exploration_map: { nodes: maps[m[1]] || [], filter_options: {} } });
    };
    const settle = async () => { for (let i = 0; i < 60; i += 1) await new Promise((r) => setImmediate(r)); };
    await settle();
    sys.switchCampaign('study');
    await settle();
    if (app.campaign !== 'study') throw new Error(`the harness left the home view on campaign ${app.campaign}`);
    sys.campaignRows = [{ campaign_id: '1', status: 'active' }, { campaign_id: '2', status: 'active' }];
    app.paintCampaignScope();
    for (const id of ['explorerState', 'explorerCoupling', 'explorerScaling', 'explorerCoeffScale', 'explorerMinN']) {
      const select = getElementById(id);
      if (!select.options) select.options = [];
    }
    if (!/all batches/.test(getElementById('explorerScopeOne').textContent)) {
      throw new Error(`the scope reads "${getElementById('explorerScopeOne').textContent}" where every batch is shown`);
    }
    await app.loadExplorer(true);
    if (app.explorerRows.length !== 3) throw new Error(`${app.explorerRows.length} rows loaded from two batches of 2 and 1; status: ${getElementById('explorerStatus').textContent}`);
    if (!/3 candidates loaded/.test(getElementById('explorerStatus').textContent)) {
      throw new Error(`the explorer did not finish: ${getElementById('explorerStatus').textContent}`);
    }
  } finally {
    sys.getJson = originalGet;
    sys.campaignRows = before;
  }
});

checkAsync('the System page sets the worker count and hands it back to the ramp', async () => {
  const app = sandbox.GSD_APP, sys = sandbox.GSD_SYSTEM, originalPost = sys.postJson;
  const sent = [];
  try {
    app.renderWorkerCount({ fleet_workers: { target: null, most: 16, active_slots: 6, reading: '6 executor slot(s) running; the ramp chooses how many, up to 16' } });
    const drawn = getElementById('workerCount').innerHTML;
    if (!/id=workerCountInput[^>]*max="16"[^>]*value="6"/.test(drawn)) throw new Error(`the count box does not show 6 of 16: ${drawn}`);
    if (!/id=workerCountAuto disabled/.test(drawn)) throw new Error('the ramp button is live while the ramp already decides');
    sys.postJson = (path, body) => { sent.push([path, body]); return Promise.resolve(body.workers == null
      ? { ok: true, target: null, most: 16, active_slots: 4, reading: 'the ramp chooses' }
      : { ok: true, target: body.workers, most: 16, active_slots: body.workers, reading: `${body.workers} asked for` }); };
    await app.setWorkerCount(4);
    if (JSON.stringify(sent[0]) !== JSON.stringify(['/api/campaigns/manage', { action: 'fleet_workers', workers: 4 }])) {
      throw new Error(`the page sent ${JSON.stringify(sent[0])}`);
    }
    const asked = getElementById('workerCount').innerHTML;
    if (!/value="4"/.test(asked) || !/you asked for 4/.test(asked) || /id=workerCountAuto disabled/.test(asked)) {
      throw new Error(`after asking for 4 the panel reads: ${asked}`);
    }
    await app.setWorkerCount(null);
    if (sent[1][1].workers !== null) throw new Error(`the ramp button sent ${JSON.stringify(sent[1][1])}`);
    if (!/the ramp decides again/.test(getElementById('workerCount').innerHTML)) throw new Error('handing back to the ramp is not said');
    sys.postJson = () => Promise.reject(new Error('POST /api/campaigns/manage → HTTP 400: choose between 1 and 16 workers'));
    await app.setWorkerCount(40);
    if (!/choose between 1 and 16 workers/.test(getElementById('workerCount').innerHTML)) throw new Error('a refused count is not said');
  } finally {
    sys.postJson = originalPost;
  }
});

checkAsync('the reports page says late, not offline, while the API is busy, and offline once it stays silent', async () => {
  const app = sandbox.GSD_APP, original = sandbox.fetch;
  let status = 200;
  const answer = (code, body) => Promise.resolve({ ok: code === 200, status: code, json: () => Promise.resolve(body),
                                                   text: () => Promise.resolve(JSON.stringify(body)) });
  sandbox.fetch = (url) => (/\/api\/reports\/status\//.test(String(url)) && status !== 200
    ? answer(status, status === 503 ? { error: 'api temporarily unavailable', detail: 'TimeoutError' } : { error: 'boom' })
    : answer(200, /\/api\/reports\/status\//.test(String(url)) ? QUIET_STATUS() : {}));
  const badge = () => getElementById('reportsBadge').textContent;
  const failure = () => getElementById('reportFailure').innerHTML;
  try {
    app.campaign = '1';
    await app.refreshReports(true);
    if (!(app.reportsAnsweredAt > 0)) throw new Error('an answered status is not remembered');
    status = 503;
    await app.refreshReports(true);
    if (badge() !== 'reports late') throw new Error(`a busy API reads "${badge()}"`);
    if (/report-error-box/.test(failure()) || !/report-late-line/.test(failure())) {
      throw new Error(`a busy API shows: ${failure()}`);
    }
    app.reportsAnsweredAt = Date.now() - 61000;
    await app.refreshReports(true);
    if (badge() !== 'reports offline' || !/report-error-box/.test(failure())) {
      throw new Error(`a minute of silence reads "${badge()}": ${failure()}`);
    }
    status = 200;
    await app.refreshReports(true);
    status = 500;
    await app.refreshReports(true);
    if (badge() !== 'reports offline') throw new Error(`a failing status (HTTP 500) reads "${badge()}"`);
  } finally {
    sandbox.fetch = original;
    app.reportsAnsweredAt = 0;
  }
});

const FOCUS_PAGE = {
  contract: 'gsd-map-page-1', studies: [{ study: '174', campaigns: 11 }],
  workload: { shares: { A: 0.5, N: 0.25, D: 0.25 }, split: 'A=2,D=1,N=1' },
  focus: {
    study: '174', stopped: false, campaigns: { N: '12', S: '13', D: '14' },
    doing: 'in focus: S174C1G6940, halving its boundaries; the N-push on S174C1G100',
    settings: { radii: [[1e-9, 4], [0.001, 4], [0.1, 8], [0.2, 8]], confirm_radius: 0.1, confirm_share: 0.667,
                contenders: 5, outward_most: 0.8, inside_share: 0.5 },
    next_settings: null,
    current: { law: 'b4d17dcdb3'.padEnd(64, '0'), label: 'C1-G6940', score: 19, kind: 'ring', stage: 'boundaries',
               radii: { '1e-09': { laws: 4, alike: 1, other: 3, waiting: 0 }, '0.1': { laws: 8, alike: 7, other: 1, waiting: 0 },
                        '0.2': { laws: 8, alike: 5, other: 2, waiting: 1 } },
               seeds: { own: { 0: 'ring', 1: 'ring', 2: 'ring' }, more: { 3: 'ring', 4: 'ring', 5: 'ring' }, reproduced: true, other: [], of: 6,
                        compared_at: { 0: 16384, 1: 16384, 2: 4096 } },
               needs: [{ what: 'its kind', done: true, said: 'ring at N=16,384, read in its seeds\u2019 campaign' },
                       { what: 'its depth', done: false, said: 'the depth worker has read it to N=4,096; it must reach N=16,384' }],
               sensitivity: { on: 'its exact parameters', words: 'its 6 seeds, each read alone, agree, and 3 of 4 moves of 0.001 or less read another kind' },
               alike_to: 0.1, depth: { deepest: 65536, holds_to: 65536, invalidated_at: null },
               boundaries: { ['ab'.repeat(32)]: { between: [0.25, 0.3125], kinds: ['ring', 'full'], why: null } } },
    contenders: { ['b4'.repeat(32)]: { label: 'C1-G6940', deepest: 262144, holds_to: 262144, invalidated_at: null, kinds: { 16384: 'ring', 262144: 'ring' } } },
    regions: [{ number: 1, name: 'GG#1', kind: 'ring', labels: ['C2-G64'], members: 41, alike_to: 0.4, boundaries: [],
                ranges: { 'coupling degree_cube_sum': [1.1, 1.3], beta: [0.18, 0.2], 'zero temperature': [0, 0] } }],
    touching: [],
    queue: [{ law: 'b4d17dcdb3'.padEnd(64, '0'), label: 'C1-G6940', score: 19, status: 'in focus' },
            { law: 'cd'.repeat(32), label: 'C2-G64', score: 19, status: 'mapped', region: 'GG#1' },
            { law: 'ef'.repeat(32), label: 'C6-G1015', score: 19, status: 'waiting' },
            { law: '12'.repeat(32), label: 'C8-G33', score: 19, status: 'skipped' }],
    done: [{ law: 'cd'.repeat(32), label: 'C2-G64', stage: 'mapped', region: 'GG#1', why: 'every neighbour to radius 0.4 reads its kind', sensitivity: { on: 'robust' } }],
    lists: { focus: [{ law: 'ef'.repeat(32), label: 'C6-G1015', score: 19, type: 'grown ring', identified_from: 64 },
                     { law: '56'.repeat(32), campaign: '15', label: 'S176C15G3', score: 38, type: null, identified_from: null, standing: 'bundle',
                       origin: { code: 'S174C2G3187', score: 38, study: '174', bundle: 'study_174_2026-11-25T13-04-19Z' } },
                     { law: '34'.repeat(32), label: 'C8-G2983', score: 27, type: 'moved', identified_from: null, placed: true }],
             depth: [{ law: 'b4'.repeat(32), label: 'C1-G6940', score: 19, type: 'grown ring', in_depth: true }] },
  },
  work: { N: { campaign: '12', running: 2, queued: 9, done: 40, deepest: 1024 }, S: { campaign: '13', running: 0, queued: 3, done: 6, deepest: 256 },
          P: { campaign: '14', running: 1, queued: 0, done: 12, deepest: 65536 } },
};

check('the Map page shows the law in focus, its rings, seeds, depth, regions, queue and ended laws', () => {
  const map = sandbox.GSD_MAP;
  map.render(FOCUS_PAGE);
  const html = (id) => getElementById(id).innerHTML;
  for (const [id, wants] of [
    ['mapControls', ['in focus: S174C1G6940, halving its boundaries', 'the N-push on S174C1G100', 'study <b>174</b>', 'the fleet\u2019s order within its mode: 1 the zone of the law in focus',
                     'zone worker, neighbours (C12): running 2, queued 9, 40 done, deepest N=1,024', 'the N-push (C14): running 1',
                     'value="1e-9:4, 0.001:4, 0.1:8, 0.2:8"']],
    ['mapFocusList', ['C6-G1015', 'grown ring', 'N=64', 'C8-G2983', 'placed by hand', 'data-map-move=up', 'the suggested order',
                      'S176C15G3</a>', 'from S174C2G3187, 38 there', "38 <span class=muted", "in study 174's bundle", 'candidate=' + '56'.repeat(32) + '&amp;campaign=15']],
    ['mapDepthList', ['C1-G6940', 'in the depth campaign', 'data-map-list="depth"']],
    ['mapCurrent', ['C1-G6940', 'halving its boundaries', 'its exact parameters', 'its own seeds reproduced', 'between 0.25 and 0.3125']],
    ['mapRegions', ['GG#1', 'coupling degree_cube_sum', '1.100 to 1.300', '41 laws read its kind']],
    ['mapDepth', ['262,144', 'C1-G6940']],
    ['mapQueue', ['C6-G1015', 'skip', 'put back', 'mapped \u00b7 GG#1']],
    ['mapDone', ['C2-G64', 'mapped as GG#1', 'sensitive to robust']]]) {
    for (const want of wants) {
      const text = want.replace('\\u00b7', '\u00b7');
      if (!html(id).includes(text)) throw new Error(`${id} lacks "${text}": ${html(id).slice(0, 400)}`);
    }
  }
  if (/focus now|stop the focus|mapSplit|type=range|mapLean/.test(html('mapQueue') + html('mapControls'))) throw new Error('the fleet\u2019s order replaces the slider, focus now, stop and the split');
  if (/depth 1 worker/.test(html('mapControls'))) throw new Error('the depth seeker is always one worker: the slider does not say so');
  for (const id of ['mapCurrent', 'mapDepth', 'mapQueue', 'mapDone', 'mapFocusList', 'mapDepthList']) {
    if (!/<a class="candidate-link map-law" href="[^"]*candidate=/.test(html(id))) throw new Error(`${id}'s laws do not link to their law page: ${html(id).slice(0, 300)}`);
  }
  if (!/disabled/.test(html('mapFocusList').split('data-map-move=up')[1] || '')) throw new Error('the first law of a list cannot move up');
  for (const want of ['to map it, 1 of 2 still to come:', 'its kind: ring at N=16,384', 'its depth: the depth worker has read it to N=4,096',
                      'its own seeds reproduced at N=16,384', '<th title="neighbours with a reading at 16,384">read</th>']) {
    if (!html('mapCurrent').includes(want)) throw new Error(`the law in focus does not say what it waits for: "${want}"`);
  }
  map.render({ studies: [{ study: '174', campaigns: 11 }], workload: {}, focus: null });
  if (!/start the focus/.test(html('mapControls')) || !/no focus in this folder/.test(html('mapCurrent'))) {
    throw new Error(`a folder with no focus offers no start: ${html('mapControls')}`);
  }
});

const ZONE_NOW = {
  contract: 'gsd-zone-now-1', at: '2026-11-26T16:30:00Z',
  running: [{ role: 'zone', part: 'ring 0.1', campaign: '12', law: '9a'.repeat(32), label: 'S174-C12-G40', n: 4096, seed: 1,
              started_utc: '2026-11-26T16:28:55Z', seconds: 65, typical: 16 },
            { role: 'depth', part: "the depth worker's law", campaign: '14', law: 'b4'.repeat(32), label: 'S174-C14-G1', n: 16384, seed: 0,
              started_utc: '2026-11-26T16:29:00Z', seconds: 60, typical: 87 },
            { role: 'Dex laws', part: 'a Dex law, read again here', campaign: '15', law: '56'.repeat(32), label: 'S174-C15-G3', n: 64, seed: 2,
              started_utc: '2026-11-26T16:29:58Z', seconds: 2, typical: null }],
  workers: { zone: 9, 'zone seeds': 0, depth: 1, 'Dex laws': 5, blind: 1, other: 0 }, analyses: { running: 3, queued: 12 },
  order: { ordered: true, tier: 0, name: 'the zone of the law in focus', names: ['the zone of the law in focus', 'the depth worker', 'the Dex laws read again', 'the blind draw', "earlier laws' leftovers"],
           queued: { 'the zone of the law in focus': 6, 'the blind draw': 1091 } },
  typical: { hours: 6 }, zone_first: { N: { waiting: 37 }, S: { waiting: 0 } },
  zone: { campaign: '12', seeds: 3, ladder: [64, 256, 1024, 4096, 16384], left_seconds: 13680, left_unknown: false, eta_seconds: 1520,
          judged: 'a neighbour is alike when it reads the law\u2019s own kind at N=16,384', needs_at: { 'its kind': '2026-11-26T16:02:00Z' },
          pace: { on_it_seconds: 1680, began_utc: '2026-11-26T16:02:00Z', read: 2, of: 44, read_last_hour: 2, last_read_seconds: 240 },
          rings: { '0.1': { laws: 8, read: 1, running: 3, queued: 2, 'being read': 1, 'waiting for the decider': 0, 'its next size due': 0,
                            held: 1, failed: 0, decided: 0, 'not started': 0, alike_so_far: 4, other_so_far: 1 } },
          points: [{ law: '9a'.repeat(32), label: 'S174-C12-G40', part: 'neighbour', radius: 0.1, reached: 1024, verdict: null, alike: null,
                     where: { stage: 'running', n: 4096, done: 1, running: 1, queued: 1, seeds: 3, since: '2026-11-26T16:28:55Z', seconds: 65 },
                     so_far: { n: 1024, kind: 'moved', law_reads: 'moved', alike: true } },
                   { law: '9b'.repeat(32), label: 'S174-C12-G41', part: 'neighbour', radius: 0.1, reached: 64, verdict: null, alike: null,
                     where: { stage: 'held', n: 64, rule: 'budget_hold', since: '2026-11-26T16:27:00Z', seconds: 180 } },
                   { law: '9c'.repeat(32), label: 'S174-C12-G42', part: 'term off', term: 'square_count', reached: 16384, verdict: 'stopped: starts_alike at 4,096',
                     alike: false, where: { stage: 'read', n: 16384, since: '2026-11-26T16:26:00Z', seconds: 240 } }] },
};

check('the Map page says how the zone is going: its workers, every law where it stands, and timers (2026-11-26 17:22)', () => {
  const map = sandbox.GSD_MAP;
  map.render(Object.assign({}, FOCUS_PAGE, { zone_now: ZONE_NOW }));
  const current = getElementById('mapCurrent').innerHTML, working = getElementById('mapWorking').innerHTML;
  for (const want of ['on it for <b><span class=map-since data-map-since="2026-11-26T16:02:00Z">28:00</span></b>', '(since 16:02 UTC)',
                      '<b>2 of 44</b> of its laws read', 'about <b>25 min</b> of work left at its 9 zone workers now',
                      'zone <b>9</b>', 'Dex laws <b>5</b>', "earlier laws' zones: 0 running, 37 queued behind this law's", 'probes 3 running, 12 queued',
                      'its kind: ring at N=16,384', '(since 16:02 UTC)', 'alike when it reads', '<summary>every law of the zone, where it stands now (3)</summary>',
                      'running at N=4,096: 1 of 3 seeds done, 1 running, 1 queued', '<b class=warn>held at N=64</b> (budget_hold)', 'square_count off',
                      '1,024: moved', 'stopped: starts_alike at 4,096 <b class=warn>other</b>', '4 of 5']) {
    if (!current.includes(want)) throw new Error(`the law in focus lacks "${want}": ${current.slice(0, 600)}`);
  }
  const controls = getElementById('mapControls').innerHTML;
  for (const want of ['1 <b>the zone of the law in focus</b> <span class=muted>(6 queued)</span>', '4 the blind draw <span class=muted>(1,091 queued)</span>',
                      'now on: <b>the zone of the law in focus</b>']) {
    if (!controls.includes(want)) throw new Error(`the fleet\u2019s order lacks "${want}": ${controls.slice(0, 600)}`);
  }
  for (const want of ['<td>zone</td>', 'S174-C12-G40', 'ring 0.1', '4,096', '1:05', '<td>16 s</td>', 'map-run-bar', 'not timed yet', '<td>depth</td>']) {
    if (!working.includes(want)) throw new Error(`Working now lacks "${want}": ${working.slice(0, 600)}`);
  }
  if (map.forText(3725) !== '1 h 02 min' || map.longText(5400) !== '1 h 30 min' || map.longText(1520) !== '25 min') throw new Error('the clock words');
  const done = JSON.parse(JSON.stringify(ZONE_NOW));
  done.zone.eta_seconds = null; done.zone.left_seconds = 0; done.zone.probes_waiting = 93;
  map.render(Object.assign({}, FOCUS_PAGE, { zone_now: done }));
  if (!getElementById('mapCurrent').innerHTML.includes('its runs are done: <b>93</b> probe readings to come')) throw new Error('a zone waiting on its probes does not say so');
  const smaller = JSON.parse(JSON.stringify(FOCUS_PAGE));
  smaller.focus.current.confirmed_at = 0.01; smaller.focus.current.alike_to = null;
  map.render(smaller);
  if (!getElementById('mapCurrent').innerHTML.includes('its zone stands at ring 0.01')) throw new Error('a smaller zone is not said');
  const lucky = JSON.parse(JSON.stringify(FOCUS_PAGE));
  lucky.focus.done = [{ law: 'ab'.repeat(32), label: 'S177-C11-G37', stage: 'unconfirmed', why: '2 of 8 neighbours at radius 0.1 read its kind' }];
  lucky.focus.queue = [{ law: 'ab'.repeat(32), label: 'S177-C11-G37', score: 27, status: 'unconfirmed' }];
  map.render(lucky);
  if (!getElementById('mapDone').innerHTML.includes('a lucky hit: no zone found around it') || !getElementById('mapQueue').innerHTML.includes('a lucky hit')) {
    throw new Error('a law with no zone around it is not called a lucky hit');
  }
  map.render(Object.assign({}, FOCUS_PAGE, { zone_now: { contract: 'gsd-zone-now-1', error: 'OperationalError: gone' } }));
  if (!getElementById('mapWorking').innerHTML.includes('the live reading failed: OperationalError: gone')) throw new Error('a failed live reading is not said');
  map.render(FOCUS_PAGE);
});

check('the Map page lists the import folder\u2019s bundles to tick, and folds the focus\u2019s settings away (15:11, 15:13)', () => {
  const map = sandbox.GSD_MAP;
  const page = Object.assign({}, FOCUS_PAGE, { imports: { contract: 'gsd-imports-1', folder: '/data/projects/GSD/176/main/import', exists: true, bundles: [
    { name: 'study_174_2026-11-25T13-04-19Z.tar.zst', kind: 'archive', bytes: 180621331, readable: true, bundle: 'study_174_2026-11-25T13-04-19Z',
      study: '174', build: 865, built_utc: '2026-11-25T13:04:19Z', laws: 10058, scoring: 69, regions: 0, science_same: true, science_differ: [], in_folder: true,
      seeded: { at: '2026-11-25T14:14:02Z', selected: true, laws_recorded: true, laws_standing: 72, regions: ['GG#3'] } },
    { name: 'study_174_copy.tar.zst', kind: 'archive', bytes: 180621331, readable: true, bundle: 'study_174_copy', study: '174', build: 865,
      built_utc: '2026-11-25T13:04:19Z', laws: 10058, scoring: 69, regions: 0, science_same: true, science_differ: [], in_folder: true,
      seeded: null, identical_to: 'study_174_2026-11-25T13-04-19Z' },
    { name: 'study_175_b', bundle: 'study_175_b', readable: true, in_folder: false, kind: 'read', study: '175', scoring: 12, science_same: true,
      seeded: { at: '2026-11-25T15:00:00Z', selected: false, let_go_utc: '2026-11-25T16:40:00Z', laws_recorded: true, laws_standing: 12, regions: [] } },
    { name: 'study_170_old.tar.zst', kind: 'archive', bytes: 1000, readable: true, bundle: 'study_170_old', study: '170', build: 790,
      built_utc: '2026-10-01T00:00:00Z', laws: 10, scoring: 1, regions: 0, science_same: false, science_differ: ['probes'], seeded: null },
    { name: 'copying.tar.zst', kind: 'archive', bytes: 10, readable: false, why: 'ValueError: truncated' }] } });
  map.render(page);
  const seedHtml = getElementById('mapSeed').innerHTML;
  for (const want of ['/data/projects/GSD/176/main/import', 'data-map-do=open_import', 'open the folder', 'copy the path',
                      'study_174_2026-11-25T13-04-19Z.tar.zst', 'build 865', '172 MiB', '69 scoring laws of 10,058', 'data-map-do=synchronize',
                      'another science: laws only', 'not readable yet', 'still being copied?', 'in the map since 2026-11-25 14:14', '72 laws, zones GG#3',
                      'identical to study_174_2026-11-25T13-04-19Z: refused', 'let go 2026-11-25 16:40; its readings kept', '(not in the folder)',
                      "merged with this folder's own laws into the dex it writes every hour", 'write the dex now',
                      'no dex written yet']) {
    if (!seedHtml.includes(want)) throw new Error(`the Seeds panel lacks "${want}": ${seedHtml.slice(0, 300)}`);
  }
  if (/mapBundle|path\/to\//.test(seedHtml)) throw new Error('the Seeds panel still asks for a path');
  const ticks = seedHtml.split('map-import-tick').length - 1;
  if (ticks !== 4 || /data-import-name="study_170_old" disabled/.test(seedHtml)) throw new Error('a bundle of another science cannot be ticked for its laws alone');
  const dexButton = { getAttribute: (k) => ({ 'data-map-do': 'dex' })[k] || null };
  if (JSON.stringify(map.bodyFor(dexButton)) !== JSON.stringify({ do: 'dex' })) throw new Error('the dex button sends nothing');
  if (!/data-import-name="study_174_2026-11-25T13-04-19Z" checked/.test(seedHtml)) throw new Error('a bundle in the map is not ticked');
  if (!/data-import-name="study_174_copy" disabled/.test(seedHtml)) throw new Error('a bundle identical to one in the map can be ticked');
  if (/data-import-name="study_175_b" checked/.test(seedHtml) || /data-import-name="study_175_b" disabled/.test(seedHtml)) throw new Error('a bundle let go is not offered again');
  if (/seeded so far/.test(seedHtml)) throw new Error('a bundle is one row, not a row and a line of what was seeded');
  const controls = getElementById('mapControls').innerHTML;
  if (!/<details class=map-settings/.test(controls) || / open>/.test(controls.split('<summary>')[0])) throw new Error('the focus\u2019s settings are not folded away');
  for (const want of ['how far from the law its neighbours are drawn', 'a law goes deeper only on the Top page', 'counts as inside it']) {
    if (!controls.includes(want)) throw new Error(`the settings do not say "${want}"`);
  }
  const open = { getAttribute: (k) => ({ 'data-map-do': 'open_import' })[k] || null };
  if (JSON.stringify(map.bodyFor(open)) !== JSON.stringify({ do: 'open_import' })) throw new Error('opening the folder sends nothing');
  const sync = { getAttribute: (k) => ({ 'data-map-do': 'synchronize' })[k] || null };
  if (JSON.stringify(map.bodyFor(sync)) !== JSON.stringify({ do: 'synchronize', ticked: [] })) throw new Error(JSON.stringify(map.bodyFor(sync)));
  const said = map.doneNote({ do: 'synchronize' }, { read_in: [{ bundle: 'study_174_b', laws_added: 3, laws_standing: 40 }], let_go: [{ bundle: 'study_175_b' }],
                                                  refused: [{ name: 'study_174_c', why: 'bundle study_174_c was read already' }] });
  for (const want of ['read in study_174_b: 3 laws new, 40 standing on its scores', 'let go of study_175_b', 'refused study_174_c: bundle study_174_c was read already']) {
    if (!said.includes(want)) throw new Error(`the note after synchronize lacks "${want}": ${said}`);
  }
});

check('a running law says whether the blind draw or the focus drew it (15:18)', () => {
  const app = sandbox.GSD_APP;
  const rows = [{ campaign_id: '3', design_kind: 'blind', group: 'A', study_batch: true }, { campaign_id: '12', design_kind: 'focus', group: 'N', focus_part: 'N' },
                { campaign_id: '13', design_kind: 'focus', group: 'N', focus_part: 'S' }, { campaign_id: '14', design_kind: 'focus', group: 'D', focus_part: 'D' },
                { campaign_id: '15', design_kind: 'seed', group: 'N' }, { campaign_id: '11', name: 'campaign-standing-controls' },
                { campaign_id: '16', design_kind: 'focus', group: 'N', focus_part: 'E' }, { campaign_id: '17', design_kind: 'focus', group: 'D', focus_part: 'P' }];
  const got = ['3', '12', '13', '14', '15', '16', '17', '11', '99'].map((cid) => app.lawGroupOf(rows, cid)[1]).join(',');
  if (got !== 'blind,zone,zone seeds,depth,seeded,zone edges,pushed,control,other') throw new Error(`the groups read ${got}`);
  app.paintLiveMode({ mode: 'push', why: 'S178-C15-G2302 is first on the push list' });
  if (!getElementById('liveMode').innerHTML.includes('<b>the N-push</b>')) throw new Error('Now researching does not say the mode (893)');
  app.paintLiveGroups({ A: 6, N: 3, P: 1 });
  const said = getElementById('liveGroups').innerHTML;
  if (!/blind<\/span> 6/.test(said) || !/zone<\/span> 3/.test(said) || !/pushed<\/span> 1/.test(said)) throw new Error(`the heading counts ${said}`);
});

check('the Top page lists the pushed laws, the law being pushed with its ladder ahead, and the laws by N (893)', () => {
  const top = sandbox.GSD_TOP;
  if (!top) throw new Error('no GSD_TOP');
  const law = 'c8'.repeat(32), other = 'a1'.repeat(32);
  const G = 1073741824;
  top.render({ contract: 'gsd-push-1', focus: true, laws_read: 412,
    mode: { mode: 'push', why: 'S178-C15-G133 is first on the push list', since: '2026-11-27T10:00:00Z', campaigns: ['17'], laws: [law] },
    pushed: [{ law, of: '15', label: 'S178-C15-G133', since: '2026-11-27T01:30:00Z', deepest: 65536 }],
    now: { law, label: 'S178-C15-G133', campaign: '17', since: '2026-11-27T10:00:00Z' },
    top: [{ law, campaign: '15', label: 'S178-C15-G133', deepest: 65536, runs: 21, pushed: true, running: true },
          { law: other, campaign: '4', label: 'S178-C4-G7', deepest: 4096, runs: 12, pushed: false, running: false }],
    law: { law, campaign: '15', label: 'S178-C15-G133', running: true, pushed: true, deepest: 65536,
           ladder: { contract: 'gsd-push-ladder-1', workers: 16, reach_bytes: 46 * G, now_utc: '2026-11-27T10:30:00Z',
             rungs: [{ n: 64, state: 'done', seeds: 16, done: 16, failed: 0, peak_bytes: 0.05 * G, seconds: 2 },
                     { n: 16384, state: 'running', seeds: 16, left: 9, at_once: 16, passes: 1, needs_bytes: 0.6 * G, seconds: 600, hours: 0.17, starts_utc: '2026-11-27T10:30:00Z', ends_utc: '2026-11-27T10:40:00Z' },
                     { n: 65536, state: 'ahead', seeds: 16, left: 16, at_once: 16, passes: 1, needs_bytes: 2.4 * G, seconds: 2400, hours: 0.67, starts_utc: '2026-11-27T10:40:00Z', ends_utc: '2026-11-27T11:20:00Z' },
                     { n: 262144, state: 'ahead', seeds: 4, left: 4, at_once: 4, passes: 1, needs_bytes: 9.6 * G, seconds: 9600, hours: 2.67, starts_utc: '2026-11-27T11:20:00Z', ends_utc: '2026-11-27T14:00:00Z' },
                     { n: 1048576, state: 'ahead', seeds: 3, left: 3, at_once: 1, passes: 3, needs_bytes: 38.4 * G, seconds: 38400, hours: 32, starts_utc: '2026-11-27T14:00:00Z', ends_utc: '2026-11-28T22:00:00Z' }],
             limit: { n: 4194304, needs_bytes: 153.6 * G, reach_bytes: 46 * G },
             marks: { fewer: { n: 262144, at_utc: '2026-11-27T11:20:00Z', at_once: 4, seeds: 4 },
                      two_passes: { n: 1048576, at_utc: '2026-11-27T14:00:00Z', at_once: 1, seeds: 3 },
                      one_worker: { n: 1048576, at_utc: '2026-11-27T14:00:00Z', at_once: 1, seeds: 3 } },
             end: { n: 1048576, ends_utc: '2026-11-28T22:00:00Z', hours: 35.5 } } },
    slot: { campaign: '17', running: Array.from({ length: 7 }, (_, i) => ({ law, label: 'S178-C15-G133', n: 16384, seed: i + 9, since: '2026-11-27T10:28:00Z', memory_now: 0.5 * G, memory_peak: 0.55 * G, elapsed: 120 })),
            order: [{ law, label: 'S178-C15-G133', queued: 2 }], waiting: [] } });
  const pushed = getElementById('topPushed').innerHTML, one = getElementById('topLaw').innerHTML, list = getElementById('topList').innerHTML;
  if (/two passes<\/text>|one worker \u00b7 N=1,048,576<\/text>[\s\S]*two passes \u00b7/.test(getElementById('topLaw').innerHTML)) throw new Error('894: two marks at one size are one label');
  for (const want of ['the fleet is in <b>the N-push</b>', 'S178-C15-G133 is first on the push list', 'the N-push runs 7 seeds of', 'holding 3.5 GiB between them',
                      'top-runs', '0.50 GiB', 'being pushed now', '65,536', 'data-top-do=unpush', 'stop pushing', 'from N=64, in a campaign of its own']) {
    if (!pushed.includes(want)) throw new Error(`the push list lacks "${want}": ${pushed.slice(0, 700)}`);
  }
  for (const want of ['its ladder again from N=64, 16 workers', '46.0 GiB', 'N=4,194,304 would need 153.6 GiB', 'ends near 22:00 UTC', '35 h 30 min from now',
                      'fewer than the 16 workers at once from N=262,144 (4 at once, 4 seeds)', 'two passes from N=1,048,576', 'one worker from N=1,048,576',
                      'top-timeline', 'top-rung-all', 'top-rung-fewer', 'top-rung-one', 'top-rung-now', 'top-mark', 'all 16 workers at once', 'one worker</span>',
                      'two passes, one worker \u00b7 N=1,048,576</text>',
                      '<b>under way</b>', '16 of 16', '16, 9 left', '9.6 GiB priced', '10:30 UTC to 10:40 UTC', 'top-chart', 'top-reach', "the host's reach"]) {
    if (!one.includes(want)) throw new Error(`the pushed law lacks "${want}": ${one.slice(0, 900)}`);
  }
  for (const want of ['412 laws have read at least one size', 'S178-C4-G7', '4,096', 'data-top-do=push', 'push to the N limit', 'top-running']) {
    if (!list.includes(want)) throw new Error(`Top 100 by N lacks "${want}": ${list.slice(0, 500)}`);
  }
  top.render({ contract: 'gsd-push-1', focus: false, pushed: [], top: [], law: null });
  if (!getElementById('topPushed').innerHTML.includes('no focus in this folder')) throw new Error('a folder with no focus is not said');
});

check('the Top page says how many seeds run now and why, what the admission asks, and where the N-push stops a law (897)', () => {
  const top = sandbox.GSD_TOP;
  const law = 'd7'.repeat(32), G = 1073741824;
  const rung = { n: 1048576, state: 'running', seeds: 8, left: 8, at_once: 4, passes: 2, needs_bytes: 10.06 * G, asked_bytes: 10.06 * G,
                 grown_bytes: 6.56 * G, hold_bytes: 14.1 * G, live_bytes: 9.4 * G, cut_bytes: 6.8 * G, running: 4, held_bytes: 47.08 * G,
                 seconds: 32040, hours: 17.8, starts_utc: '2026-11-27T14:30:00Z', ends_utc: '2026-11-28T08:18:00Z' };
  const ladder = { contract: 'gsd-push-ladder-2', workers: 11, reach_bytes: 54 * G, now_utc: '2026-11-27T14:30:00Z',
    rungs: [{ n: 262144, state: 'done', seeds: 16, done: 16, failed: 0, peak_bytes: 3.19 * G, typical_bytes: 1.49 * G, seconds: 5736 }, rung],
    limit: null, marks: { fewer: { n: 1048576, at_utc: '2026-11-27T14:30:00Z', at_once: 4, seeds: 8 } },
    end: { n: 1048576, ends_utc: '2026-11-28T08:18:00Z', hours: 17.8 },
    under_way: { n: 1048576, running: 4, held_bytes: 47.08 * G, live_bytes: 9.4 * G, asked_bytes: 10.06 * G, headroom_bytes: 6.29 * G, more: 0 },
    ceiling: { n: 1048576, next: 4194304, next_bytes: 30.1 * G, next_fits: true, next_at_once: 1, next_seconds: 195540 } };
  const entry = { law, of: '15', label: 'S178-C15-G73', since: '2026-11-27T07:32:00Z', deepest: 262144, ceiling: 1048576 };
  top.render({ contract: 'gsd-push-1', focus: true, laws_read: 3, top: [], mode: { mode: 'push', why: 'S178-C15-G73 is first on the push list' },
    pushed: [entry], now: { law, label: 'S178-C15-G73', campaign: '15' },
    law: { law, campaign: '15', label: 'S178-C15-G73', running: true, pushed: true, deepest: 262144, ceiling: 1048576, ladder },
    slot: { campaign: '17', running: [], order: [], waiting: [] },
    done: [{ law: 'e1'.repeat(32), of: '15', label: 'S178-C15-G5', at_n: 1048576, rule: 'ceiling' }] });
  const one = getElementById('topLaw').innerHTML, list = getElementById('topPushed').innerHTML;
  for (const want of ['N=1,048,576 under way: 4 seeds run at once, the admission holding 47.1 GiB for them (the largest at 9.4 GiB so far)',
                      'the next asks 10.1 GiB and 6.3 GiB is free above the host', 'so it waits for one to finish',
                      'the N-push stops this law at N=1,048,576, its ceiling; pushed past it, N=4,194,304 would ask 30.1 GiB a seed, 1 at once',
                      'the admission asks 10.1 GiB to start a seed', 'a running seed held at about 14.1 GiB', 'its runs under way at 9.4 GiB so far',
                      'a typical run 1.5 GiB, the largest 3.2 GiB', '10.1 GiB priced']) {
    if (!one.includes(want)) throw new Error(`the pushed law lacks "${want}": ${one.slice(0, 1200)}`);
  }
  for (const want of ['data-top-do=push_past', 'past N=1,048,576', 'it stops at N=1,048,576 unless pushed past it', 'S178-C15-G5', '(ceiling)']) {
    if (!list.includes(want)) throw new Error(`the push list lacks "${want}": ${list.slice(0, 900)}`);
  }
  if ((list.match(/data-top-do=push_past/g) || []).length !== 2) throw new Error('a law that ended at its ceiling is offered "past" too');
  top.render({ contract: 'gsd-push-1', focus: true, laws_read: 3, top: [], pushed: [entry], now: null, slot: { running: [], order: [], waiting: [] },
    law: { law, campaign: '15', label: 'S178-C15-G73', running: false, pushed: true, ladder: Object.assign({}, ladder, { under_way: null, ceiling: null,
      rungs: [Object.assign({}, rung, { state: 'ahead', running: 0, needs_bytes: 60 * G, waits: true })] }) } });
  const waits = getElementById('topLaw').innerHTML;
  if (!waits.includes('N=1,048,576: the admission asks 60.0 GiB to start one seed, more than the 54.0 GiB the host admits')) {
    throw new Error(`a rung whose ask passes the host's reach is not said: ${waits.slice(0, 900)}`);
  }
  if (waits.includes('under way:') || waits.includes('its ceiling')) throw new Error('a line was said with nothing behind it');
});

check('the Top page shows the push list in its order with who put each law there, the laws waiting and those done, and the mode when nothing is pushed', () => {
  const top = sandbox.GSD_TOP;
  const a = 'b1'.repeat(32), b = 'b2'.repeat(32), c = 'b3'.repeat(32), w = 'b4'.repeat(32), d = 'b5'.repeat(32);
  top.render({ contract: 'gsd-push-1', focus: true, laws_read: 3, top: [], law: null,
    mode: { mode: 'push', why: 'S178-C15-G73 is first on the push list' },
    pushed: [{ law: a, of: '15', label: 'S178-C15-G73', since: '2026-11-27T07:32:00Z', deepest: 65536 },
             { law: b, of: '15', label: 'S178-C15-G133', since: '2026-11-27T07:33:00Z', deepest: 65536 },
             { law: c, of: '11', label: 'S178-C11-G900', since: '2026-11-27T09:00:00Z', deepest: null, by: 'zone S178-C15-G2302' }],
    now: { law: a, label: 'S178-C15-G73', campaign: '17', since: '2026-11-27T07:35:00Z' },
    slot: { campaign: '17', running: [], order: [{ law: a, label: 'S178-C15-G73', queued: 2 }], waiting: [{ law: w, label: 'S178-C15-G2302' }] },
    done: [{ law: d, of: '15', label: 'S178-C15-G5', at_n: 1048576, rule: 'memory' }] });
  const pushed = getElementById('topPushed').innerHTML;
  for (const want of ['the N-push holds', 'between rungs', '>you</td>', 'zone S178-C15-G2302', 'data-top-do=push_move', 'data-top-to="0"', 'data-top-to="1"',
                      '>first</button>', '>up</button>', 'waiting, their runs kept', 'S178-C15-G2302', 'pushed to their limit', 'to N=1,048,576 (memory)',
                      'joins the end of this list', 'its runs stop at once, saved']) {
    if (!pushed.includes(want)) throw new Error(`the push list lacks "${want}": ${pushed.slice(0, 1200)}`);
  }
  const firstRow = pushed.split('<tr>')[2] || '';
  if (firstRow.includes('data-top-do=push_move')) throw new Error('the first law offers to move up');
  top.render({ contract: 'gsd-push-1', focus: true, laws_read: 0, top: [], law: null, pushed: [], slot: { running: [] },
    mode: { mode: 'zone', why: 'S178-C15-G2302 is in focus' } });
  const zone = getElementById('topPushed').innerHTML;
  if (!zone.includes('the fleet is in <b>the zone search</b>') || !zone.includes('S178-C15-G2302 is in focus')) throw new Error(`the mode is not said: ${zone.slice(0, 400)}`);
});

check('the Map page shows the work law by law, each with its progress, and why a dex was written', () => {
  const map = sandbox.GSD_MAP;
  const laws = [{ role: 'Dex laws', part: 'a Dex law, read again here', campaign: '15', law: '56'.repeat(32), label: 'S178-C15-G3',
                  sizes: [64, 256, 1024, 4096], seeds: 3, planned: 12, done: 3, running: 2, queued: 1,
                  now: [{ n: 256, seeds: [0, 1] }], seconds: 40, started_utc: '2026-11-27T00:29:20Z', progress: 0.3 }];
  map.render(Object.assign({}, FOCUS_PAGE, { zone_now: Object.assign({}, ZONE_NOW, { laws }) }));
  const working = getElementById('mapWorking').innerHTML;
  for (const want of ['map-working-laws', '>its runs</th>', 'S178-C15-G3', '3 of 12', '(1 queued)', 'N=256, seeds 0, 1', 'map-law-bar',
                      'width:25.0%', 'width:5.0%', '30%', 'each run under way (3)', 'map-run-bar']) {
    if (!working.includes(want)) throw new Error(`Working now by law lacks "${want}": ${working.slice(0, 700)}`);
  }
  const verifying = Object.assign({}, FOCUS_PAGE.focus, { current: null, dex_check: { laws: [], counts: { held: 193 }, zone: null, verify_to: 4096 } });
  map.render(Object.assign({}, FOCUS_PAGE, { focus: verifying, imports: { contract: 'gsd-imports-2', folder: '/x/178/main/import', exists: true, bundles: [] }, dex: { path: '/x/export/dex_178_2026-11-27T00-20-51Z.tar.zst', utc: '2026-11-27T00:20:51Z',
                                                                      counts: { laws: 5 }, why: '3 laws of the dex verified here since the last dex' } }));
  if (!getElementById('mapCurrent').innerHTML.includes('no law is in focus while the dex is verified')) throw new Error('the focus panel does not say it waits for the dex');
  const seed = getElementById('mapSeed').innerHTML;
  for (const want of ['0 of 193 laws read again, each to N=4,096', 'title="laws of the dex read again and judged"', '(3 laws of the dex verified here since the last dex)', 'at most every 10 minutes']) {
    if (!seed.includes(want)) throw new Error(`the Seeds panel lacks "${want}": ${seed.slice(0, 700)}`);
  }
});

check('the Map page lists a dex read in as it is verified, then the first zone and why it was chosen', () => {
  const map = sandbox.GSD_MAP;
  const rows = [{ law: 'aa'.repeat(32), code: 'S176-C12-G4', score: 1, verdict: 'denied', agree: 7, differ: 1, other_length: 0, sizes: [64, 256],
                  first_differ: { n: 256, accepted_moves: [400, 401] } },
                { law: 'bb'.repeat(32), code: 'S177-C12-G565', score: 27, verdict: 'unmatched', agree: 0, differ: 0, other_length: 8, sizes: [] },
                { law: 'cc'.repeat(32), code: 'S176-C12-G2', score: 1, verdict: 'confirmed', agree: 8, differ: 0, other_length: 0, sizes: [64, 256] }];
  const verifying = { contract: 'gsd-dex-check-1', campaign: '15', bundles: ['dex_177_2026-11-26T19-33-48Z'], laws: rows, zone: null,
                      counts: { confirmed: 1, denied: 1, unmatched: 1, controls: 0, laws: 3, owed: 190, held: 193 } };
  const page = (check) => Object.assign({}, FOCUS_PAGE, { focus: Object.assign({}, FOCUS_PAGE.focus, { dex_check: check }) });
  map.render(page(verifying));
  let seedHtml = getElementById('mapSeed').innerHTML;
  for (const want of ['verifying the dex first', '3 of 193 laws read again', 'no law is taken into focus before every law has read',
                      '1 confirmed', '1 denied', '1 unmatched', 'the dex campaign C15', 'the dex’s laws as they read again (3)',
                      'S177-C12-G565', '8 of another length', '1 differ', 'candidate=' + 'cc'.repeat(32) + '&amp;campaign=15']) {
    if (!seedHtml.includes(want)) throw new Error(`the dex check lacks "${want}": ${seedHtml.slice(0, 400)}`);
  }
  const zone = { contract: 'gsd-zone-choice-1', radius: 0.1, campaign: '15', centre: 'cc'.repeat(32), code: 'S176-C12-G2',
                 why: 'the most verified laws of one term set nearest one centre: 29 verified laws within 0.1 of S176-C12-G100',
                 chosen: { centre: 'cc'.repeat(32), code: 'S176-C12-G2', near: 29, laws: 45 },
                 groups: [{ centre: 'cc'.repeat(32), code: 'S176-C12-G2', near: 29, laws: 45, terms: ['degree_anchor k=7', 'induced_square_count'],
                            dynamics: 'zero temperature', mean: 0.09 },
                          { centre: 'dd'.repeat(32), code: 'S177-C12-G1015', near: 28, laws: 34, terms: ['degree_cube_sum'], dynamics: 'zero temperature', mean: 0.09 }],
                 taken_utc: '2026-11-27T08:00:00Z' };
  map.render(page(Object.assign({}, verifying, { zone, done_utc: '2026-11-27T07:59:00Z' })));
  seedHtml = getElementById('mapSeed').innerHTML;
  for (const want of ['the first zone:', 'S176-C12-G2', 'taken into focus 2026-11-27 08:00', '29 verified laws within 0.1 of S176-C12-G100',
                      '29 within 0.1', 'S177-C12-G1015', '28 within 0.1', 'degree_anchor k=7, induced_square_count, zero temperature', '0.090']) {
    if (!seedHtml.includes(want)) throw new Error(`the zone chosen lacks "${want}": ${seedHtml.slice(0, 400)}`);
  }
  map.render(page(Object.assign({}, verifying, { zone: { radius: 0.1, chosen: null, why: 'no two verified laws of one term set lie within 0.1 of each other' } })));
  if (!getElementById('mapSeed').innerHTML.includes('no zone chosen')) throw new Error('a dex with no zone in it is not said');
  map.render(FOCUS_PAGE);
  if (getElementById('mapSeed').innerHTML.includes('verifying the dex')) throw new Error('a folder with no dex first shows a dex check');
});

check('the Map page lists the zones searched, how each ended and its central law, then the next zone (891)', () => {
  const map = sandbox.GSD_MAP;
  const zones = [{ centre: 'cc'.repeat(32), of: '15', label: 'S178-C15-G2', stage: 'mapped', region: 'Z1', kind: 'made', held_to: 16384,
                   central: { law: 'ee'.repeat(32), of: '11', label: 'S178-C11-G40' }, members: 27, edges: 11 },
                 { centre: 'dd'.repeat(32), of: '15', label: 'S178-C15-G9', stage: 'unconfirmed', region: null, kind: 'moved', held_to: null,
                   central: null, members: 3, edges: 0 }];
  const next = { radius: 0.1, campaign: '15', centre: 'ff'.repeat(32), code: 'S178-C15-G31', chosen: { centre: 'ff'.repeat(32) },
                 why: 'the most verified laws of one term set nearest one centre', passed_over: 31, groups: [] };
  const check = { contract: 'gsd-dex-check-1', campaign: '15', laws: [], counts: { confirmed: 193, held: 193 }, zone: next, zones };
  map.render(Object.assign({}, FOCUS_PAGE, { focus: Object.assign({}, FOCUS_PAGE.focus, { dex_check: check }) }));
  const html = getElementById('mapSeed').innerHTML;
  for (const want of ['the next zone:', 'S178-C15-G31', '31 laws passed over, inside or at the centre of a zone already searched',
                      '<td>Z1</td>', 'S178-C15-G2', 'mapped <span class=muted>(made)</span>', 'held to N=16,384', 'S178-C11-G40',
                      'S178-C15-G9', 'a lucky hit: no zone found around it, kept to revisit']) {
    if (!html.includes(want)) throw new Error(`the zones searched lack "${want}": ${html.slice(0, 900)}`);
  }
  map.render(Object.assign({}, FOCUS_PAGE, { focus: Object.assign({}, FOCUS_PAGE.focus, { dex_check: Object.assign({}, check, { zone: { radius: 0.1, chosen: null, why: 'none left' } }) }) }));
  if (!getElementById('mapSeed').innerHTML.includes('no zone left to choose')) throw new Error('the zones run out unsaid');
});

check('the Map page reads its rings and settings and refuses what is not radius:laws', () => {
  const map = sandbox.GSD_MAP;
  const rings = map.parseRings('1e-9:4, 0.1:8 ,0.4:8');
  if (JSON.stringify(rings) !== JSON.stringify([[1e-9, 4], [0.1, 8], [0.4, 8]])) throw new Error(JSON.stringify(rings));
  let refused = '';
  try { map.parseRings('0.1-8'); } catch (e) { refused = e.message; }
  if (!/radius:laws/.test(refused)) throw new Error(`a bad ring was taken: ${refused}`);
  if (map.ringsText([[1e-9, 4], [0.001, 4], [0.1, 8]]) !== '1e-9:4, 0.001:4, 0.1:8') throw new Error(map.ringsText([[1e-9, 4], [0.001, 4], [0.1, 8]]));
});

check('the Map page shows the zone’s search: each line stepped out and halved, its edges read again, its central law and its cost (890)', () => {
  const map = sandbox.GSD_MAP;
  const search = { stage: 'confirming', judge_n: 4096, confirm_n: 16384, radius: 0.1, centre: { kind: 'made', curves: ['d_s', 'mean_degree'] },
                   members: { a: { near: true, verdict: 'alike' }, b: { near: true, verdict: 'alike' }, c: { near: false, verdict: 'other' } },
                   off: { square_edge_overlap: { verdict: 'other' } },
                   lines: { 'beta +': { param: 'beta', sign: 1, lo: 0.55, hi: 0.6, done: true,
                                        steps: { '0.1': { at: 0.1, verdict: 'alike' }, '0.8': { at: 0.8, verdict: 'other', why: 'reads moved, not made' } } },
                            'swap +': { param: 'swap', sign: 1, lo: 0, hi: null, done: true, why: 'a share cannot leave 0 to 1', steps: {} },
                            'beta -': { param: 'beta', sign: -1, lo: 0.1, hi: null, done: false, steps: { '0.1': { at: 0.1, verdict: 'alike' } } } },
                   edges: { 'beta +': { held: true }, 'beta -': { held: null } },
                   central: { law: 'cd'.repeat(32), of: '11', label: 'S178-C11-G9' },
                   benchmark: { total: { runs: 412, core_hours: 3.1, hours: 2.4 }, ring_method: { words: 'the ring method read 29 neighbours of this zone on 3 seeds at 5 sizes to N=16,384: about 435 runs' },
                                calls: { held: 1, edges: 2 } } };
  const page = JSON.parse(JSON.stringify(FOCUS_PAGE));
  page.focus.current.search = search;
  map.render(page);
  const current = getElementById('mapCurrent').innerHTML;
  for (const want of ["the zone's search", 'confirming; judged at N=4,096, its edges read again at N=16,384', 'its laws: 2 of 3 alike, 2 of the 2 within 0.1',
                      'its curves locked in at 4,096: d_s, mean_degree', 'each term off: square_edge_overlap: other',
                      'between 55% and 60%', '<span class=warn title="reads moved, not made">80%</span>', 'a share cannot leave 0 to 1', 'stepping out',
                      '<span class=good>held</span>', '<span class=muted>reading</span>', 'S178-C11-G9', 'pushed to the N limit',
                      'the search cost 412 runs, 3.1 core-hours over 2.4 h', 'about 435 runs', '1 of 2 edges held at the larger size']) {
    if (!current.includes(want)) throw new Error(`the zone's search lacks "${want}": ${current.slice(0, 900)}`);
  }
  delete page.focus.current.search;
  map.render(page);
  if (getElementById('mapCurrent').innerHTML.includes('map-search')) throw new Error('a law in focus with no search draws one');
});

checkAsync('a Map page button sends its action to the focus and draws the answer', async () => {
  const map = sandbox.GSD_MAP, sys = sandbox.GSD_SYSTEM, original = sys.postJson, sent = [];
  try {
    map.render(FOCUS_PAGE);
    sys.postJson = (path, body) => { sent.push([path, body]); return Promise.resolve(Object.assign({}, FOCUS_PAGE, { ok: true })); };
    const skip = { getAttribute: (k) => ({ 'data-map-do': 'skip', 'data-map-law': 'ef'.repeat(32) })[k] || null };
    await map.act(map.bodyFor(skip));
    if (JSON.stringify(sent[0]) !== JSON.stringify(['/api/focus', { do: 'skip', law: 'ef'.repeat(32) }])) throw new Error(JSON.stringify(sent[0]));
    if (map.note !== 'done: skip') throw new Error(`the page says "${map.note}"`);
    sys.postJson = () => Promise.reject(new Error('POST /api/focus \u2192 HTTP 403: admin capability required'));
    await map.act({ do: 'stop' });
    if (!/HTTP 403/.test(map.note) || !/HTTP 403/.test(getElementById('mapControls').innerHTML)) throw new Error(`a refusal is not said: ${map.note}`);
  } finally {
    sys.postJson = original;
  }
});

check('a reading one seed of three gave is drawn faint and says what the larger sizes said', () => {
  const lone = { n: 256, seeds: 1, of: 3, refused_above: [[1024, 'NO_SCALING_WINDOW'], [4096, 'EXPONENTIAL_GROWTH']] };
  const app = sandbox.GSD_APP;
  if (!app.oneSeedReading(lone)) throw new Error('one seed of three is not a lone reading');
  if (app.oneSeedReading(Object.assign({}, lone, { seeds: 2 }))) throw new Error('two seeds of three read as lone');
  if (app.oneSeedReading({ n: 64, seeds: 1, of: 1 })) throw new Error('a law run on one seed reads as lone');
  const line = app.readingFromLine(lone);
  for (const want of ['read on 1 of 3 seeds at N=256', 'drawn faint', '1,024 (no scaling window)', '4,096 (exponential growth)']) {
    if (!line.includes(want)) throw new Error(`the tooltip line lacks "${want}": ${line}`);
  }
  const point = { candidate_id: 'f1307c3a2c'.padEnd(64, '0'), landscape_band: 'flowing', d_w_estimate: 8.588,
                  readings_from: { d_w: lone }, law_score: { score: 0, to_n: null, top_n: 4096 } };
  sandbox.GSD_APP.drawLandscape([point]);
});

check('one set of filters picks the laws of the landscape and the Top 100 by kind, map region, group, batch and settling', () => {
  const app = sandbox.GSD_APP;
  const point = (id, kind, group, batch, score, region, settled) => ({
    candidate_id: id.padEnd(64, '0'), campaign_id: batch, kind, group, batch, region,
    settled_probes: settled ? ['d_s'] : [], law_score: { score, to_n: 16384, top_n: 16384 } });
  const points = [
    point('a', 'still', 'A', '1', 1, null, true), point('b', 'made', 'A', '1', 19, null, true),
    point('c', 'small_world', 'B', '11', 21, { of: 'c'.padEnd(64, '0'), state: 'mapping', kind: null }, true),
    point('d', 'ring', 'B', '11', 9, { of: 'x'.padEnd(64, '0'), state: 'known', kind: 'ring' }, false),
    point('e', null, 'A', '2', 0, null, false)];
  app.clearFilters();
  app.renderFilters(points);
  const drawn = getElementById('homeFilters').innerHTML;
  if (layoutDump) layoutDump.set('homeFilters', [drawn]);
  for (const want of ['still lattice 1', 'small world 1', 'not read yet 1', 'B, map', 'C11', '<b>5</b> of 5 laws: every law of the study']) {
    if (!drawn.includes(want)) throw new Error(`the panel does not show "${want}": ${drawn}`);
  }
  const keep = () => points.filter((p) => app.homeFilterPasses(p)).map((p) => p.candidate_id[0]).join('');
  app.chooseFilter({ target: { dataset: { filterKind: 'still' }, checked: false } });
  if (keep() !== 'bcde') throw new Error(`hiding still kept ${keep()}`);
  app.chooseFilter({ target: { id: 'filterGroup', value: 'B', dataset: {} } });
  if (keep() !== 'cd') throw new Error(`group B kept ${keep()}`);
  app.chooseFilter({ target: { id: 'filterRegion', value: 'known', dataset: {} } });
  if (keep() !== 'd') throw new Error(`a known region kept ${keep()}`);
  app.clearFilters();
  app.chooseFilter({ target: { id: 'filterKind', value: 'small_world', dataset: {} } });
  if (keep() !== 'c') throw new Error(`one kind kept ${keep()}`);
  app.clearFilters();
  app.chooseFilter({ target: { id: 'filterSettled', value: 'unsettled', dataset: {} } });
  app.chooseFilter({ target: { id: 'filterBatch', value: '2', dataset: {} } });
  if (keep() !== 'e') throw new Error(`batch 2, not settled, kept ${keep()}`);
  app.renderFilters(points);
  if (!getElementById('homeFilters').innerHTML.includes('<b>1</b> of 5 laws: batch C2, not settled')) throw new Error('the line does not say what is chosen');
  app.clearFilters();
  if (app.homeFilter.off.size || app.homeFilter.kind) throw new Error('clear left a filter on');
});

check('with a filter on, the selection\u2019s ladder counts the laws the filters keep and the fleet\u2019s work stays whole (872)', () => {
  const app = sandbox.GSD_APP;
  const id = (c) => c.padEnd(64, '0');
  const row = (c, kind, top) => ({ candidate_id: id(c), campaign_id: '1', kind, law_score: { score: 3, to_n: top, top_n: top }, settled_probes: [] });
  app.campaign = '1';
  app.landscape = { campaign_id: '1', top_candidates: [],
                    dimension_points: [row('a', 'still', 16384), row('b', 'made', 65536), row('c', 'made', 16384)] };
  app.overviewPayload = { active: [], rung_distribution: [{ n: 4096, running: 3, queued: 0, measured: 313, graphs: 939 }] };
  app.selectionData = { campaign: '1', facts: [
    ['1', id('a'), [64, 4096, 16384], 'settled', 'starts_alike', 16384, null, 3, 16384],
    ['1', id('b'), [64, 4096, 16384, 65536], 'waiting', null, 65536, null, 3, 65536],
    ['1', id('c'), [64, 4096, 16384], 'under way', null, 4096, 65536, 3, 16384],
    ['1', id('d'), [64], 'settled', 'empty', 64, null, 0, null]] };
  app.clearFilters();
  app.renderSelection();
  let html = getElementById('rungLadder').innerHTML;
  for (const want of ['>alike<', '>empty<', '>waiting<', '>scoring<', '>laws stopped by rule<', '>candidates<', 'N=65536', 'N=4096']) {
    if (!html.includes(want)) throw new Error(`the fleet ladder lacks ${want}: ${html.slice(0, 900)}`);
  }
  const reached = (h, n) => (h.match(new RegExp(`N=${n}</code></td><td class="num g-cand">(?:<b>)?(\\d+)`)) || [])[1];
  if (reached(html, '64') !== '4' || reached(html, '16384') !== '3') throw new Error(`every law reached 64 and three 16,384: ${html}`);
  if (!/N=4096<\/code>[\s\S]*?>939</.test(html)) throw new Error(`the fleet\u2019s graphs at 4,096 are not in the box: ${html.slice(0, 900)}`);
  app.chooseFilter({ target: { id: 'filterKind', value: 'made', dataset: {} } });
  app.renderSelection();
  html = getElementById('rungLadder').innerHTML;
  if (reached(html, '64') !== '2' || />alike</.test(html)) throw new Error(`the made laws alone: ${html}`);
  if (!/ladder-table/.test(html) || !/N=4096/.test(html)) throw new Error('the fleet\u2019s work left the box');
  app.chooseFilter({ target: { id: 'filterScoring', checked: true, dataset: {} } });
  app.chooseFilter({ target: { id: 'filterDeepest', value: '65536', dataset: {} } });
  app.renderSelection();
  html = getElementById('rungLadder').innerHTML;
  if (reached(html, '64') !== '1') throw new Error(`scoring, made and read to 65,536: one law: ${html}`);
  app.clearFilters();
  app.landscape = null;
  app.selectionData = null;
});

check('the study bar counts core-hours and memory held in four parts, whole numbers (872)', () => {
  const sel = sandbox.GSD_SELECTION;
  const html = sel.hours({ core_hours: { A: 1234.4, N: 300.6, D: 80.2, system: 40.9 }, memory_gib_hours: { A: 900, N: 120, D: 500, system: 64 },
                           host_read: true, host_cores: 32, since: '2026-11-25T15:00:00Z', names: {} });
  for (const want of ['<b>blind</b> 1,234 core-h', '<b>focus</b> 301 core-h', '<b>depth</b> 80 core-h', '<b>system</b> 41 core-h',
                      '1,656 core-h in all', '<b>depth</b> 500 GiB-h', 'hours-system']) {
    if (!html.includes(want)) throw new Error(`the bars lack ${want}: ${html}`);
  }
  if (/\d\.\d/.test(html.replace(/style="[^"]*"/g, '').replace(/title="[^"]*"/g, ''))) throw new Error('a decimal on the bars');
});

check('with a filter on, the Top 100 is the best laws the filters keep, from every point of the landscape', () => {
  const app = sandbox.GSD_APP;
  const row = (id, kind, score) => ({ candidate_id: id.padEnd(64, '0'), campaign_id: '1', kind,
    law_score: { score, to_n: 16384 }, settled_probes: [] });
  app.campaign = '1';
  app.landscape = { campaign_id: '1', top_candidates: [row('t', 'still', 30)],
                    dimension_points: [row('t', 'still', 30), row('u', 'ring', 7), row('v', 'made', 12)] };
  app.clearFilters();
  if (app.filteredTop().map((r) => r.candidate_id[0]).join('') !== 't') throw new Error('no filter changed the Top 100');
  app.chooseFilter({ target: { dataset: { filterKind: 'still' }, checked: false } });
  const kept = app.filteredTop().map((r) => r.candidate_id[0]).join('');
  if (kept !== 'vu') throw new Error(`with still hidden the Top 100 reads ${kept}`);
  app.clearFilters();
  app.landscape = null;
});

check('with lattice starts ticked, a frozen or still lattice that scores is drawn at its start, as a changed or kept one', () => {
  const app = sandbox.GSD_APP;
  if (!LATTICE_WHO.includes('frozen') || !LATTICE_WHO.includes('still')) throw new Error(`the server's lattice set: ${LATTICE_WHO}`);
  const law = (id, d_s, by, chain) => ({ candidate_id: id.padEnd(64, '0'), campaign_id: '1', d_s_estimate: d_s,
    landscape_band: 'flowing', landscape_band_with_lattices: 'einstein', settled_probes: [],
    law_score: { score: 1, by, chain, to_n: 65536 } });
  app.campaign = '1';
  app.landscapePayload = { campaign_id: '1', revision: 'rf', top_candidates: [], exposure: {}, limits: {}, lattice_who: LATTICE_WHO,
    dimension_points: [law('f', null, 'frozen', 'square'), law('s', null, 'still', 'cubic'), law('k', null, 'kept', 'bcc')],
    counts: { measured_candidates: 3, band_candidates: { flowing: 3 } },
    every_chain: { contract: 'landscape-every-chain-1', names: ['empty', 'random', 'square', 'cubic', 'bcc'],
      points: { square: [law('f', 2.0, 'frozen', 'square')], cubic: [law('s', 3.0, 'still', 'cubic')],
                bcc: [law('k', 3.0, 'kept', 'bcc')] }, counts: {} } };
  app.chooseLandLattices(true);
  const drawn = app.landChainPoints().filter((p) => p.landscape_band === 'einstein').map((p) => p.d_s_estimate).sort();
  app.chooseLandLattices(false);
  if (drawn.join(',') !== '2,3,3') throw new Error(`the frozen, still and kept lattices drawn at: ${drawn}`);
  app.landscape = null;
});

check('equal scores in the Top 100 keep one order, campaign then graph number, with or without a filter', () => {
  const app = sandbox.GSD_APP;
  const row = (cid, g, hash, score) => ({ candidate_id: hash.padEnd(64, '0'), campaign_id: cid, ensemble_code: `G-${g}`,
    kind: 'ring', law_score: { score, to_n: 65536, top_n: 65536 }, settled_probes: [] });
  const rows = [row('6', 1015, '3a', 19), row('1', 6940, 'b4', 19), row('2', 64, '99', 19), row('10', 5, '01', 19),
                row('3', 7363, '00', 7)];
  app.campaign = 'study';
  app.landscape = { campaign_id: 'study', top_candidates: rows.slice(), dimension_points: rows.slice(), lattice_who: LATTICE_WHO };
  app.clearFilters();
  const name = (r) => `C${r.campaign_id}-${r.ensemble_code}`;
  const plain = app.filteredTop().map(name).join(' ');
  app.chooseFilter({ target: { dataset: { filterKind: 'still' }, checked: false } });
  const filtered = app.filteredTop().map(name).join(' ');
  app.clearFilters();
  app.landscape = null;
  const want = 'C1-G-6940 C2-G-64 C6-G-1015 C10-G-5 C3-G-7363';
  if (plain !== want || filtered !== want) throw new Error(`plain: ${plain}; filtered: ${filtered}`);
});

checkAsync('the System page shows the groups and the system CPUs and sets them behind the admin link', async () => {
  const app = sandbox.GSD_APP, sys = sandbox.GSD_SYSTEM, originalPost = sys.postJson;
  const sent = [];
  try {
    const before = { shares: { A: 0.5, B: 0.5 }, split: 'A=0.5,B=0.5', system_cpus: [], work_cpus: [0, 1, 2, 3], cpus: 4,
                     shares_a_core: {} };
    app.renderWorkload({ workload: before });
    const drawn = getElementById('workload').innerHTML;
    if (!/A 50%/.test(drawn) || !/B 50%/.test(drawn) || !/system CPUs: none/.test(drawn)) throw new Error(`the panel reads: ${drawn}`);
    if (!/id=workloadSplit data-admin-write/.test(drawn) || !/data-admin-write id=workloadSet/.test(drawn)) {
      throw new Error('the workload control is not behind the admin link');
    }
    sys.postJson = (path, body) => { sent.push([path, body]); return Promise.resolve({ ok: true, ...before,
      system_cpus: [0, 2], work_cpus: [1, 3], shares_a_core: { 0: [1] } }); };
    await app.setWorkload('A=1,B=1', '0,2');
    if (JSON.stringify(sent[0]) !== JSON.stringify(['/api/campaigns/manage', { action: 'workload', split: 'A=1,B=1', system_cpus: '0,2' }])) {
      throw new Error(`the page sent ${JSON.stringify(sent[0])}`);
    }
    const after = getElementById('workload').innerHTML;
    if (!/system CPUs: 0,2/.test(after) || !/simulations on 2 of 4 CPUs/.test(after) || !/CPU 0 shares its core with 1/.test(after)) {
      throw new Error(`after keeping two CPUs the panel reads: ${after}`);
    }
    sys.postJson = () => Promise.reject(new Error('POST /api/campaigns/manage → HTTP 400: the system cannot keep every CPU'));
    await app.setWorkload('', '0-3');
    if (!/the system cannot keep every CPU/.test(getElementById('workload').innerHTML)) throw new Error('a refusal is not said');
    app.renderWorkload({});
    if (!/arrives with the next poll/.test(getElementById('workload').innerHTML)) throw new Error('no workload is not said');
  } finally {
    sys.postJson = originalPost;
  }
});

checkAsync('a failed Campaigns refresh keeps the last table, says why, and retries', async () => {
  const app = sandbox.GSD_APP;
  if (typeof app.refreshCampaigns !== 'function') throw new Error('refreshCampaigns is not exported');
  const originalFetch = sandbox.fetch, originalTimeout = sandbox.setTimeout;
  const good = () => Promise.resolve({ ok: true, status: 200,
    json: () => Promise.resolve(campaignsPayload(false)), text: () => Promise.resolve('') });
  let scheduled = 0;
  try {
    sandbox.fetch = good;
    await app.refreshCampaigns(true);
    const table = getElementById('campaignsBody').innerHTML;
    if (!table || /unavailable/.test(table)) throw new Error('the fixture did not render a table');
    sandbox.setTimeout = () => { scheduled += 1; return 0; };
    sandbox.fetch = () => Promise.resolve({ ok: false, status: 503,
      json: () => Promise.resolve({ error: 'api temporarily unavailable', detail: 'TimeoutError', retryable: true }) });
    await app.refreshCampaigns(true);
    if (getElementById('campaignsBody').innerHTML !== table) throw new Error('a failed refresh replaced the table');
    const stale = getElementById('campaignsStale');
    if (stale.hidden || !/out of date/.test(stale.innerHTML) || !/TimeoutError/.test(stale.innerHTML)) {
      throw new Error(`the marker does not say the table is stale and why: ${stale.innerHTML}`);
    }
    if (!scheduled) throw new Error('no retry was scheduled after a failed refresh');
    sandbox.fetch = good;
    await app.refreshCampaigns(true);
    if (!stale.hidden) throw new Error('the marker stayed after a good refresh');
  } finally {
    sandbox.fetch = originalFetch;
    sandbox.setTimeout = originalTimeout;
  }
});

checkAsync('a landing pause is polled and then says saving done', async () => {
  const app = sandbox.GSD_APP;
  const originalFetch = sandbox.fetch, originalTimeout = sandbox.setTimeout;
  const serve = (state) => () => {
    const payload = campaignsPayload(false);
    payload.campaigns[0].state = state;
    payload.campaigns[0].slots_held = state === 'pausing' ? 10 : 0;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload),
      text: () => Promise.resolve('') });
  };
  const delays = [];
  try {
    sandbox.setTimeout = (fn, ms) => { delays.push(ms); return 0; };
    sandbox.fetch = serve('pausing');
    await app.refreshCampaigns(true);
    if (!getElementById('campaignsBody').innerHTML.includes('10 chain(s) saving')) {
      throw new Error('the pausing row is not drawn');
    }
    if (!delays.includes(4000)) throw new Error(`no poll one tick later while a pause lands: ${delays}`);
    delays.length = 0;
    sandbox.fetch = serve('paused');
    await app.refreshCampaigns(true);
    const html = getElementById('campaignsBody').innerHTML;
    if (!/class="saving-done"[^>]*>saving done</.test(html)) throw new Error(`the landed pause does not say so: ${html.slice(0, 400)}`);
    if (delays.includes(4000)) throw new Error('the page kept polling after the pause landed');
    await app.refreshCampaigns(true);
    if (!getElementById('campaignsBody').innerHTML.includes('saving done')) {
      throw new Error('a re-render inside the four seconds dropped the note');
    }
  } finally {
    sandbox.fetch = originalFetch;
    sandbox.setTimeout = originalTimeout;
  }
});

checkAsync('campaign switches leave one landscape loop, not one per switch', async () => {
  const originalTimeout = sandbox.setTimeout, originalClear = sandbox.clearTimeout;
  const pending = new Map();
  let next = 1;
  const flush = () => new Promise((resolve) => setImmediate(resolve));
  const loops = () => [...pending.values()].filter((fn) => fn && fn.name === 'pollLandscape').length;
  try {
    sandbox.setTimeout = (fn) => { const id = next++; pending.set(id, fn); return id; };
    sandbox.clearTimeout = (id) => { pending.delete(id); };
    for (const id of ['3', '4', '5', '6', '7']) {
      sandbox.dispatchEvent(new sandbox.CustomEvent('rr:campaign', { detail: { campaign: id } }));
      await flush();
    }
    if (loops() !== 1) throw new Error(`${loops()} landscape loops are pending after five switches`);
    for (let tick = 0; tick < 3; tick += 1) {
      const due = [...pending.entries()].filter(([, fn]) => fn && fn.name === 'pollLandscape');
      due.forEach(([id]) => pending.delete(id));
      due.forEach(([, fn]) => fn());
      await flush(); await flush();
      if (loops() !== 1) throw new Error(`${loops()} landscape loops after tick ${tick + 1}`);
    }
  } finally {
    sandbox.setTimeout = originalTimeout;
    sandbox.clearTimeout = originalClear;
  }
});

check('the gate panel says what the switch waits for and what the campaign refused (790)', () => {
  sandbox.GSD_RENDER_GATE = sandbox.GSD_APP.renderGate;
  const rule = { gap_exponent_at_most: -0.3752, diameter_exponent_at_least: 0.1751, gap_window: [4096, 65536],
    diameter_window: [4096, 262144], early_gate_at_n: 16384, gate_at_n: 65536, audit_in_flight_at_most: 4 };
  sandbox.GSD_RENDER_GATE({ rule, early_stage: { switch: true, agreements_needed: 100, agree: 37, disagree: 2, would_refuse: 41 },
    campaign: { campaign_id: '3', laws_by_latest_rule: { no_finite_dimension: 58, gate_audit: 2 } } });
  const html = getElementById('gateBody').innerHTML;
  if (!html.includes('acts once 100 agree (37 so far)')) throw new Error(`the switch does not say what it waits for: ${html.slice(0, 300)}`);
  if (!html.includes('no finite dimension') || !html.includes('>58<')) throw new Error('the campaign refusals are missing');
  if (!html.includes('-0.3752') || !html.includes('0.1751')) throw new Error('the rule is not stated');
  sandbox.GSD_RENDER_GATE({ rule, early_stage: { switch: false, agreements_needed: 100 } });
  if (!getElementById('gateBody').innerHTML.includes('never acted on')) throw new Error('the switch off does not say it is shadow only');
});

check('688: a law link in the study scope carries its batch, never campaign=study', () => {
  const study = sandbox.GSD_APP.candidateHref('abc', 'study');
  if (/campaign=study/.test(study)) throw new Error(`the study scope's id went on a law's link: ${study}`);
  const batch = sandbox.GSD_APP.candidateHref('abc', '3');
  if (!/campaign=3/.test(batch)) throw new Error(`a row's batch did not go on its link: ${batch}`);
});

(async () => {
  for (const [label, fn] of asyncChecks) {
    try { await fn(); } catch (error) { failures.push(`${label}: ${error && error.message}`); }
  }
  if (layoutDump) fs.writeFileSync(process.env.GSD_LAYOUT_DUMP, JSON.stringify(Object.fromEntries(layoutDump)));
  if (failures.length) {
    console.log('FAIL');
    failures.forEach((line) => console.log(line));
    process.exit(1);
  }
  console.log('OK');
})();
