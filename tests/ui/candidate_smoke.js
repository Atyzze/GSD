
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const uiDir = process.argv[2];

function makeClassList() {
  const set = new Set();
  return { add: (c) => set.add(c), remove: (c) => set.delete(c),
           contains: (c) => set.has(c), toggle: (c) => set.has(c) ? set.delete(c) : set.add(c) };
}

function makeElement(tag) {
  const node = {
    tagName: String(tag || 'div').toUpperCase(),
    attributes: {}, children: [], dataset: {}, style: {},
    classList: makeClassList(), _text: '', _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(value) { this._html = String(value); },
    get textContent() {
      return this._text + this.children.map((c) => (c && c.textContent) || String(c || '')).join('');
    },
    set textContent(value) { this._text = String(value); this.children = []; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return this.attributes[name] ?? null; },
    removeAttribute(name) { delete this.attributes[name]; },
    append(...kids) { kids.forEach((k) => this.children.push(k)); },
    appendChild(k) { this.children.push(k); return k; },
    addEventListener() {}, removeEventListener() {}, remove() {},
    querySelectorAll(selector) { return collect(this, selector); },
    querySelector(selector) { return collect(this, selector)[0] || null; },
  };
  return node;
}

function collect(root, selector) {
  const wanted = String(selector).toUpperCase();
  const found = [];
  (function walk(node) {
    (node.children || []).forEach((child) => {
      if (!child || typeof child !== 'object') return;
      if (child.tagName === wanted) found.push(child);
      walk(child);
    });
  })(root);
  return found;
}

const elements = new Map();
const documentStub = {
  getElementById: (id) => {
    if (!elements.has(id)) elements.set(id, makeElement('div'));
    return elements.get(id);
  },
  createElement: makeElement,
  createTextNode: (text) => ({ tagName: '#text', textContent: String(text), children: [], attributes: {} }),
  createElementNS: (ns, tag) => makeElement(tag),
  addEventListener() {}, removeEventListener() {},
  documentElement: makeElement('html'),
  body: makeElement('body'),
  querySelector: () => null, querySelectorAll: () => [],
  title: '', readyState: 'complete',
  scripts: [{ src: 'http://127.0.0.1:8765/assets/system.js?v=219' }],
};

const sandbox = {
  console,
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  Math, Date, JSON, Number, String, Array, Object, Boolean, Error, RangeError,
  Set, Map, Intl, isNaN, isFinite, parseFloat, parseInt, encodeURIComponent,
  decodeURIComponent, URLSearchParams, URL, Promise, devicePixelRatio: 1,
  document: documentStub,
  location: { href: 'http://127.0.0.1:8765/', pathname: '/', search: '', hash: '' },
  history: { pushState() {}, replaceState() {} },
  requestAnimationFrame: (fn) => { fn(0); return 1; }, cancelAnimationFrame: () => {},
  fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}),
                                 text: () => Promise.resolve('') }),
  getComputedStyle: () => ({ getPropertyValue: () => '#123456' }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true,
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } },
  scrollTo() {}, alert() {},
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  navigator: { clipboard: null },
  GSD_UI_CONFIG: { basePath: '', buildNumber: '219', runtimeFingerprint: 'test',
                    runtimeShort: 'test', homeHref: '/' },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const page = fs.readFileSync(path.join(uiDir, 'candidate.html'), 'utf8');
const inline = [...page.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => m[1])
  .sort((a, b) => b.length - a.length)[0];

const failures = [];
function check(label, fn) {
  try { fn(); } catch (error) { failures.push(`${label}: ${error && error.message}`); }
}

check('load candidate page script', () => {
  const source = inline.replace('__GSD_BASE_PATH_JSON__', '""');
  try { vm.runInContext(source, sandbox, { filename: 'candidate.html' }); }
  catch (error) { if (!sandbox.renderLawScore) throw error; }
});

check('the page says how the law moves, near its top: temperature, locality and the global moves (2026-11-14 12:14)', () => {
  const text = (node) => String(node.textContent);
  const spec = { init: 'empty', dynamics: { kind: 'equilibrium', beta: 0.184275, locality: 0.887362, sweeps: 33,
    move_mix: { add: 0.262707, delete: 0.262707, swap: 0.474586 } } };
  const warm = text(sandbox.lawDynamicsBlock({ spec, regime: 'equilibrium' }, {}));
  for (const needle of ['beta 0.184275', 'a temperature of 5.42667', 'locality', '0.887362: 88.7% of the moves are local',
                        'other 11.3% are global', 'add 26.3%', 'swap 47.5%', '33 a chain']) {
    if (!warm.includes(needle)) throw new Error(`the dynamics block lacks "${needle}": ${warm}`);
  }
  const cold = text(sandbox.lawDynamicsBlock({ spec: { dynamics: { beta: 0.5, zero_temperature: true, sweeps: 30 } },
                                              regime: 'zero_temperature' }, {}));
  if (!cold.includes('zero: a move is taken only if it does not raise the energy') || !cold.includes('0.5, is not used')) {
    throw new Error(`a zero-temperature law does not say its beta is unused: ${cold}`);
  }
  if (!cold.includes('0, the default: every move is global') || !cold.includes('add 42.5%')) {
    throw new Error(`a law at the default locality and move mix does not write them out: ${cold}`);
  }
  const given = text(sandbox.lawDynamicsBlock({ spec: { dynamics: {} } }, { law_dynamics: { locality: 0.25, beta: 1,
    zero_temperature: false, move_mix: { add: 0.5, delete: 0.5, swap: 0 }, sweeps: 40 } }));
  if (!given.includes('0.25: 25.0% of the moves are local')) throw new Error(`the resolved record is not read: ${given}`);
});

check('the heading is the readable identity, not a static label', () => {
  const page = fs.readFileSync(path.join(uiDir, 'candidate.html'), 'utf8');
  if (/el\('h1',\{\},'candidate '/.test(page)) {
    throw new Error('the heading is still the static word "candidate"');
  }
  if (!page.includes('c.ensemble_code')) throw new Error('the heading does not use the ensemble code');
});

check('the heading names the law C<campaign>-G<n>, and the identity line its hashes and their matches', () => {
  if (sandbox.candidateCode({ ensemble_code: 'G-917', campaign_id: '3' }, {}) !== 'C3-G917') throw new Error('no C code');
  if (sandbox.candidateCode({ ensemble_code: 'G-917' }, { campaign_id: '1' }) !== 'C1-G917') throw new Error('the payload campaign is not used');
  if (sandbox.candidateCode({ candidate_id: 'abc' }, { campaign_id: '1' }) !== null) throw new Error('a law with no graph got a code');
  const line = sandbox.lawIdentityLine({ candidate_id: '6f364db7b709' }, {
    law_hash: '6f364db7b709', function_hash: '78be0f36215807cdbf2344d9', same_law_in: ['5', '6'],
    same_function: [{ campaign_id: '1', candidate_id: 'aa11', ensemble_code: 'G-17' }], same_function_count: 3 });
  const text = String(line.textContent || '');
  for (const want of ['law 6f364db7b709', 'function 78be0f36215807cdbf2344d9', 'the same law in campaign 5, campaign 6',
                      'the same function as C1-G17', 'and 2 more']) {
    if (!text.includes(want)) throw new Error(`the identity line lacks "${want}": ${text}`);
  }
  const alone = String(sandbox.lawIdentityLine({ candidate_id: 'x' }, { law_hash: 'x', function_hash: 'f', same_law_in: [], same_function: [] }).textContent || '');
  if (!alone.includes('no other law, in any campaign, is this function')) throw new Error(`an unmatched function is not said: ${alone}`);
});

check('the flow chart is read before the screening table', () => {
  const page = fs.readFileSync(path.join(uiDir, 'candidate.html'), 'utf8');
  const assemble = page.indexOf('root.append(flowSection, thermSection, contextSection)');
  if (assemble < 0) throw new Error('sections are not assembled in an explicit order');
  if (!page.includes("'candidate context'")) {
    throw new Error('the middle section still has no heading');
  }
});

check('a partial channel carries its denominator, a complete one does not', () => {
  const page = fs.readFileSync(path.join(uiDir, 'candidate.html'), 'utf8');
  if (/\bch\.id\+' valid'/.test(page)) throw new Error('the valid column is still present');
  if (!page.includes('seeds)`')) throw new Error('the seed denominator is not shown anywhere');
});


check('the chain mixing table shows R-hat beside its equilibrium value and the chains\' verdicts', () => {
  const app = makeElement('div');
  sandbox.renderChainMixing(app, [{ n: 64, diagnostics: { contract: 'rung-chain-mixing-2', seeds: 3,
    seeds_with_moments: 3, seeds_with_chains_disagreement: 1,
    meeting_reading: { contract: 'meeting-reading-2', reading: 'disagreeing_while_moving', seeds: 3,
                    counts: { disagreeing_while_moving: 2, frozen: 0, converging: 1, agreeing: 0, not_enough_points: 0 } },
    chain_seconds: { empty: 1.2, given: 0.5 },
    observables: {
      energy_per_node: { split_rhat: 1.184, half_chains: 12, effective_samples_per_chain: 9.1,
                         equilibrium_rhat: 1.104, excess: 0.08 },
      mean_degree: { split_rhat: 1.01, half_chains: 12, effective_samples_per_chain: 9.1,
                     equilibrium_rhat: 1.104, excess: -0.094 },
      isolated_fraction: { split_rhat: null, half_chains: 0, effective_samples_per_chain: null,
                           equilibrium_rhat: null, excess: null } } } }]);
  const text = String(app.textContent);
  if (!text.includes('1.184') || !text.includes('+0.080')) throw new Error(`R-hat or its excess is missing: ${text}`);
  if (!text.includes('1 of 3')) throw new Error('the verdicts of the chains are not beside it');
  if (!text.includes('not measured')) throw new Error('an observable with no moments reads as a value');
  if (!text.includes('1.2 / 0.5')) throw new Error('the chain time split is not shown');
  if (!text.includes('disagreeing while moving')) throw new Error('513: the reading of the chains at this rung is not shown');
  const empty = makeElement('div');
  sandbox.renderChainMixing(empty, []);
  if (String(empty.textContent)) throw new Error('an empty diagnostics list rendered something');
});

check('the dynamics line names the law\'s regime and its local moves', () => {
  const spec = { init: 'empty', dynamics: { kind: 'equilibrium', beta: 1, sweeps: 30,
    move_mix: { add: 0.45, delete: 0.45, swap: 0.1 }, locality: 0.99, zero_temperature: true } };
  const cold = sandbox.dynamicsLine({ spec, regime: 'zero_temperature', dynamics: 'equilibrium', complexity: 3,
                                        campaign_id: '7' }, {});
  const text = String(cold.textContent);
  if (!text.startsWith('zero temperature')) throw new Error(`the regime does not lead the line: ${text}`);
  if (!text.includes('locality 0.99 toggle') || !text.includes('zero temperature'))
    throw new Error(`the law's own dynamics are not listed: ${text}`);
  const plain = sandbox.dynamicsLine({ spec: { init: 'empty', dynamics: { beta: 2, sweeps: 30, move_mix: {} } },
                                       dynamics: 'equilibrium', complexity: 1, campaign_id: '7' }, {});
  const plainText = String(plain.textContent);
  if (!plainText.startsWith('equilibrium') || plainText.includes('locality') || plainText.includes('zero temperature'))
    throw new Error(`a law at the defaults reads as something else: ${plainText}`);
});

function nodesWhere(root, pred) {
  const out = [];
  (function walk(node) {
    (node.children || []).forEach((child) => {
      if (!child || typeof child !== 'object') return;
      if (pred(child)) out.push(child);
      walk(child);
    });
  })(root);
  return out;
}
const hasClass = (node, name) => String((node.attributes || {}).class || '').split(/\s+/).includes(name);
function chainStat(mean, se, extra = {}) {
  return { mean, se, seed_sd: se, seeds: mean === null ? 0 : 3, of: 3, values: mean === null ? [] : [mean, mean, mean], ...extra };
}
function chainRung(n, { course = true, reading = 'agreeing', reason = 'completed', givenShift = 0, zs = [6, 2, 1] } = {}) {
  const side = (shift) => ({
    mean_degree: chainStat(4 + shift, 0.01), energy_per_node: chainStat(-0.15 - shift / 10, 0.001),
    triangles_per_node: chainStat(0.01 + shift / 10, 0.001), squares_per_node: chainStat(0.7, 0.01),
    giant_fraction: chainStat(1, 0), kappa: chainStat(-0.06 - shift / 20, 0.002), reach: chainStat(Math.log2(n) / 2 + shift, 0.1),
    d_s: chainStat(1.7 - shift / 4, 0.05, { read: true }), d_V: chainStat(2.4, 0.06, { read: true }),
    d_B: chainStat(null, null, { read: true, refused: { NOT_POWER_LAW: 3 } }),
    d_w: chainStat(null, null, { read: true, refused: { EXPONENTIAL_GROWTH: 3 },
      withheld: { mean: 1.727, seeds: 3, values: [1.72, 1.73, 1.73], reasons: { EXPONENTIAL_GROWTH: 3 } } }),
  });
  const checks = zs.map((z, i) => ({ sweeps: 100 * 2 ** (i + 2), multiplier: 2 ** (i + 1), passed: z <= 3,
    failures: z <= 3 ? [] : [{ code: 'STARTS_DISAGREED', detail: 'the chain from empty and the given chain disagree' }],
    z: { energy_per_node: z, mean_degree: z / 2 }, structural: {}, effective_samples: 9 + i, drift: 0.1,
    rest: null, rest_limit: null, mean_degree: 4, wall_seconds: 30 * (i + 1), ended: 'completed', given_ended: null }));
  const seedCourse = (seed) => (course ? { contract: 'chains-course-1', n,
    empty: { points: 480, course: [[0, 0.46, 0], [2.6, 0.27, 1.15], [400, -0.14, 4.0], [1600, -0.15, 4.0]],
               structure: [[0, 0, 0.001], [1600, 0.01, 1]] },
    given: { points: 160, course: [[0, -0.02, 3.98], [7.8, -0.03, 4.3], [400, -0.15 - givenShift / 10, 4 + givenShift], [1600, -0.15 - givenShift / 10, 4 + givenShift]],
            structure: [[0, 0, 1], [1600, 0.01 + givenShift / 10, 1]], start: 'family_random_geometric_2d_degree_4', kernel: 'local_walk' } } : null);
  return { n, seeds: 3, empty: side(0), given: side(givenShift),
    reading: { contract: 'meeting-reading-2', reading, counts: { [reading]: 3 }, seeds: 3 },
    lower_energy: givenShift ? { given: 3 } : { level: 3 }, ends: { [reason]: 3 }, courses: course ? 3 : 0,
    per_seed: [0, 1, 2].map((seed) => ({ seed,
      meeting: { reading, gaps: { energy_per_node: { late_gap: -givenShift / 10, late_noise: 0.001, agree: !givenShift, closing: false } },
                 moving: { empty: true, given: true }, lower_energy: givenShift ? 'given' : 'level' },
      stop: { reason, classification: reason === 'completed' ? 'EQUILIBRATED_ACTIVE' : 'METASTABLE_OR_NONMIXING',
              chunks: zs.length, final_multiplier: 2 ** zs.length, wall_seconds: 95, work_units: 1000, work_budget: 7500000000000,
              failures: reason === 'completed' ? [] : [{ code: 'STARTS_DISAGREED', detail: 'the chain from empty and the given chain disagree' }],
              given_rest: null },
      checks, met_from: { gap: zs[zs.length - 1] <= 3 ? 800 : null, rest: null }, course: seedCourse(seed) })) };
}
const CHAINS_PAYLOAD = { chains: { contract: 'two-chains-1', given_start: 'the declared answer, family_random_geometric_2d_degree_4',
  zero_temperature: false, given_probes_read: true,
  rule: { required_consecutive_passes: 2, max_sweeps_multiplier: 64, min_effective_samples: 8, split_z: 3, drift: 0.5, rest_share: 0.01 },
  quantities: ['mean_degree', 'energy_per_node', 'triangles_per_node', 'squares_per_node', 'giant_fraction', 'kappa', 'reach', 'd_s', 'd_V', 'd_B', 'd_w'],
  rungs: [chainRung(256, { course: false }), chainRung(1024),
          chainRung(4096, { reading: 'disagreeing_while_moving', reason: 'ceiling', givenShift: 1.5, zs: [40, 30, 20] })] } };

function scoreRung(n, distance, worst, props) {
  return { n, distance, worst, properties: Object.fromEntries(Object.entries(props).map(([k, d]) => [k, { distance: d, reading: 2 }])) };
}
const SPACE_SCORE = { contract: 'gsd-space-score-1', from_n: 1024, margins: { dimension: 0.15, per_node: 0.02, curvature: 0.02, piece: 0.02 },
  judged: [1024, 4096], stage: 2, of: 4, spaces: ['given'], full: { passed: true, cut: [] },
  stages: [{ key: 'full', name: 'the runs are full readings', passed: true }, { key: 'space', name: 'a chain is a space', passed: true },
    { key: 'closing', name: 'the other chain closes part of the gap', passed: false }, { key: 'met', name: 'the chains meet', passed: false }],
  chains: { empty: { d: 3, space: false, worst: 13.6, rungs: [scoreRung(1024, 2.46, 'dimension', { dimension: 2.46, agree: 0.99, piece: 0 }),
                                                                 scoreRung(4096, 13.6, 'reach', { dimension: 3.26, reach: 13.6, local: 5.63, piece: 0 })] },
            given: { d: 2, space: true, worst: 0.96, rungs: [scoreRung(1024, 0.52, 'agree', { dimension: 0.13, agree: 0.52, walk: 0.43, piece: 0 }),
                                                             scoreRung(4096, 0.96, 'agree', { dimension: 0.29, agree: 0.96, walk: 0.03, reach: 0, local: 0, piece: 0 })] } },
  gaps: [{ n: 1024, distance: 28.2, worst: 'reach', quantities: {} }, { n: 4096, distance: 37.4, worst: 'reach', quantities: {} }],
  facts: { zero_temperature: false, beta: 4, given_start: 'the declared answer, family_torus', given_probes_read: true,
           feels_n: { band: 'none', knows_n: false } } };

function tableOf(app) { return nodesWhere(app, (n) => n.tagName === 'TABLE' && hasClass(n, 'tc-all'))[0]; }
function tableRows(app, quantity) {
  return nodesWhere(tableOf(app), (n) => n.tagName === 'TR' && n.attributes['data-quantity'] === quantity);
}
function tableCell(app, quantity, chain, n) {
  const table = tableOf(app);
  const head = nodesWhere(table, (x) => x.tagName === 'TH' && hasClass(x, 'tc-n')).map((x) => String(x.textContent));
  const row = tableRows(app, quantity).find((r) => chain === null || r.attributes['data-chain'] === chain);
  if (!row) return null;
  const values = row.children.filter((c) => c && c.tagName === 'TD' && hasClass(c, 'tc-v'));
  return values[head.indexOf('N=' + n.toLocaleString('en-US'))] || null;
}

function spaceScoreChecks(app, score, label, chainCount = 2) {
  const head = nodesWhere(tableOf(app), (n) => n.tagName === 'TR' && n.attributes['data-group'] === 'space')[0];
  if (!head) throw new Error(`${label}: no rows of how far the law is from a space`);
  const text = String(head.textContent);
  if (!text.includes(`stage ${score.stage} of ${score.of}`)) throw new Error(`${label}: the stage is not said`);
  for (const st of score.stages) if (!text.includes(st.name)) throw new Error(`${label}: the stage "${st.name}" is not named`);
  if ((text.match(/✓/g) || []).length !== score.stage) throw new Error(`${label}: the stages passed are not marked`);
  if (score.stage < score.of && !text.includes('✗ ' + score.stages[score.stage].name)) throw new Error(`${label}: the stage not reached is not marked`);
  const props = ['dimension', 'agree', 'walk', 'reach', 'local', 'piece'];
  for (const p of props) {
    const rows = tableRows(app, 'space_' + p);
    if (rows.length !== chainCount) throw new Error(`${label}: ${rows.length} rows of ${p} for ${chainCount} chains`);
  }
  if (tableRows(app, 'space_chain').length !== chainCount) throw new Error(`${label}: the chains' worst is not a row each`);
  return { box: tableOf(app), text: String(tableOf(app).textContent) + ' ' + text };
}

function twoChainsChecks(payload, label) {
  const app = makeElement('div');
  sandbox.renderTwoChains(app, payload);
  const text = String(app.textContent);
  const rungs = payload.chains.rungs;
  const every = (payload.chains.every_chain || []).length > 2 ? payload.chains.every_chain : null;
  const count = every ? every.length : 2;
  if (!text.includes(`the ${['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'][count]} chains`)) throw new Error(`${label}: no heading`);
  const keyItems = nodesWhere(app, (n) => hasClass(n, 'tc-key-item'));
  if (keyItems.length !== count || String(keyItems[0].attributes.title) !== 'from the empty graph') {
    throw new Error(`${label}: the key names ${keyItems.length} chains for ${count}, the chain from the empty graph first, its start on hover`);
  }
  if (text.includes('from the empty graph')) throw new Error(`${label}: a start is spelled out above the charts again`);
  if (nodesWhere(app, (n) => hasClass(n, 'tc-cell') || hasClass(n, 'tc-strip') || hasClass(n, 'ss-stage')).length) {
    throw new Error(`${label}: the strip or the stage cards are still drawn`);
  }
  const charts = nodesWhere(app, (n) => hasClass(n, 'tc-chart') && n.attributes['data-quantity'] && !hasClass(n, 'tc-run-across'));
  if (charts.length !== 13) throw new Error(`${label}: ${charts.length} charts across N, not 13`);
  const all = nodesWhere(app, (n) => hasClass(n, 'tc-chart') && n.attributes['data-quantity']);
  if (all.length !== 16) throw new Error(`${label}: ${all.length} charts, not a grid of 16`);
  const boxes = new Set(all.map((c) => (String(c.innerHTML).match(/viewBox="([^"]+)"/) || [])[1]).filter(Boolean));
  if (boxes.size !== 1) throw new Error(`${label}: the charts are not all one size: ${[...boxes]}`);
  const drawn = charts.map((c) => String(c.innerHTML || ''));
  if (!drawn.some((h) => h.includes('var(--start-empty')) || !drawn.some((h) => h.includes('var(--start-random'))) {
    throw new Error(`${label}: the charts do not draw both chains`);
  }
  const both = drawn.filter((h) => h.includes('var(--start-empty') && h.includes('var(--start-random')).length;
  if (both < 5) throw new Error(`${label}: only ${both} charts overlay the two chains`);
  const table = tableOf(app);
  if (!table) throw new Error(`${label}: no table of every value`);
  const heads = nodesWhere(table, (n) => n.tagName === 'TH' && hasClass(n, 'tc-n')).map((n) => String(n.textContent));
  const sizes = heads.map((h) => Number(h.slice(2).replace(/,/g, '')));
  if (sizes.some((n, i) => i && n >= sizes[i - 1]) || rungs.some((r) => !sizes.includes(r.n))) {
    throw new Error(`${label}: the table's columns are ${heads}, not every size largest first`);
  }
  if (nodesWhere(table, (n) => n.tagName === 'TD' && n.attributes.title !== undefined).length) throw new Error(`${label}: a cell of the table has a mouse-over`);
  const keys = every ? every.map((c) => c.key) : ['empty', 'given'];
  let copied = 0;
  all.forEach((chart) => {
    const quantity = chart.attributes['data-quantity'];
    (chart._tips || []).filter((t) => t.value !== undefined).forEach((t) => {
      const cell = tableCell(app, quantity, t.chain === undefined ? null : t.chain, t.n);
      if (!cell || String(cell.textContent) !== t.value) {
        throw new Error(`${label}: ${quantity} of ${t.chain || 'the law'} at N=${t.n} reads "${t.value}" on its plot and "${cell && cell.textContent}" in the table`);
      }
      copied += 1;
    });
  });
  if (copied < rungs.length * 2) throw new Error(`${label}: only ${copied} plotted values are found in the table`);
  for (const k of ['mean_degree', 'd_s', 'reach', 'einstein']) {
    if (tableRows(app, k).length !== keys.length) throw new Error(`${label}: ${k} is not a row a start`);
  }
  const silent = all.filter((c) => String(c.innerHTML).includes('<svg') && !(c._tips || []).length).map((c) => c.attributes['data-quantity']);
  if (silent.length) throw new Error(`${label}: the plots of ${silent} draw points no mouse-over answers`);
  const unexplained = all.filter((c) => {
    const bubble = nodesWhere(c, (n) => hasClass(n, 'tc-bubble'))[0];
    return !c.attributes['data-eli5'] || !bubble || String(bubble.textContent).length < 80 || !nodesWhere(c, (n) => hasClass(n, 'tc-head')).length;
  }).map((c) => c.attributes['data-quantity']);
  if (unexplained.length) throw new Error(`${label}: the plots of ${unexplained} carry no plain words behind their title`);
  const keptWords = String(nodesWhere(all.find((c) => c.attributes['data-quantity'] === 'kept'), (n) => hasClass(n, 'tc-bubble'))[0].textContent);
  for (const want of ['Above 1', 'Below 0', 'Between 0 and 1', 'a ring from the tesseract tends to 4']) {
    if (!keptWords.includes(want)) throw new Error(`${label}: the kept share's words do not say "${want}"`);
  }
  const ds = all.find((c) => c.attributes['data-quantity'] === 'd_s');
  const segs = ds._segments || [];
  const drawnLines = (String(ds.innerHTML).match(/<polyline/g) || []).length;
  if (drawnLines && (!segs.length || !segs.every((g) => g.lines[0] === 'between two readings:' && /^N=[\d,]+: /.test(g.lines[1]) && /^N=[\d,]+: /.test(g.lines[2])))) {
    throw new Error(`${label}: a line between two readings does not name both`);
  }
  segs.forEach((g) => {
    const chain = (ds._tips.find((t) => t.head === g.head) || {}).chain;
    [g.lines[1], g.lines[2]].forEach((line) => {
      const n = Number(line.slice(2, line.indexOf(':')).replace(/,/g, ''));
      const cell = tableCell(app, 'd_s', chain, n);
      if (!cell || line !== `N=${n.toLocaleString('en-US')}: ${cell.textContent}`) throw new Error(`${label}: a line's reading "${line}" is not the table's`);
    });
  });
  const keptChart = all.find((c) => c.attributes['data-quantity'] === 'kept');
  if (String(keptChart.innerHTML).includes('<svg') && ((String(keptChart.innerHTML).match(/class="tc-guide"/g) || []).length !== 2
      || !String(keptChart.innerHTML).includes('a random wiring') || !String(keptChart.innerHTML).includes('its start'))) {
    throw new Error(`${label}: the kept share is not drawn against a random wiring at 0 and its start at 1`);
  }
  const across = nodesWhere(app, (n) => n.attributes && n.attributes['data-quantity'] === 'd_s')[0];
  if (!(across._tips || []).every((t) => String(t.head).startsWith('from ') && /^N=[\d,]+: /.test(t.lines[0]))) {
    throw new Error(`${label}: a point's mouse-over does not name its start and its value`);
  }
  const withCourse = rungs.filter((r) => r.courses > 0);
  const want = (withCourse.length ? withCourse : rungs)[(withCourse.length ? withCourse : rungs).length - 1].n;
  if (!text.includes(`over the run, at N=${want.toLocaleString('en-US')}`)) throw new Error(`${label}: the run panel is not at N=${want}`);
  const runCharts = nodesWhere(app, (n) => hasClass(n, 'tc-run-chart'));
  if (withCourse.length && !runCharts.some((c) => String(c.innerHTML).includes('<polyline'))) {
    throw new Error(`${label}: no chain is drawn over the run`);
  }
  const stops = nodesWhere(app, (n) => hasClass(n, 'tc-stop'));
  const selected = rungs.find((r) => r.n === want);
  if (stops.length !== selected.per_seed.length) throw new Error(`${label}: ${stops.length} stop lines for ${selected.per_seed.length} seeds`);
  const rows = nodesWhere(app, (n) => hasClass(n, 'tc-grid')).map((g) => g.children.map((c) => c.attributes['data-quantity']));
  const wantRows = [['mean_degree', 'giant_fraction', 'triangles_per_node', 'squares_per_node'],
    ['d_s', 'd_V', 'd_B', 'd_w'], ['reach', 'kappa', 'energy_per_node', 'einstein'],
    ['met_from', 'energy_gap', 'checks', 'kept']];
  if (JSON.stringify(rows) !== JSON.stringify(wantRows)) throw new Error(`${label}: the chart rows are ${JSON.stringify(rows)}`);
  if (payload.space_score) spaceScoreChecks(app, payload.space_score, label, count);
  const detail = nodesWhere(app, (n) => n.tagName === 'DETAILS' && hasClass(n, 'tc-detail'))[0];
  if (!detail || detail.attributes.open !== undefined) throw new Error(`${label}: one size's detail is not a closed section`);
  const tabs = nodesWhere(detail, (n) => hasClass(n, 'tc-size'));
  if (tabs.length !== rungs.length) throw new Error(`${label}: ${tabs.length} size tabs for ${rungs.length} rungs`);
  if (rungs.length < 2) return { app, text };
  const other = tabs.find((c) => !hasClass(c, 'selected'));
  other.onclick();
  const after = String(app.textContent);
  const picked = rungs.find((r) => after.includes(`over the run, at N=${r.n.toLocaleString('en-US')}`) && r.n !== want);
  if (!picked) throw new Error(`${label}: picking another size in the detail does not move its run panel`);
  return { app, text };
}

check('both chains are drawn alike: met or apart per size, overlaid across N, paired in the table, over the run', () => {
  const { app, text } = twoChainsChecks({ ...CHAINS_PAYLOAD, space_score: SPACE_SCORE }, 'inline');
  if (!nodesWhere(app, (n) => hasClass(n, 'tc-key-item')).some((k) => String(k.attributes.title).includes('from a random geometric graph (2-D, degree 4)'))) {
    throw new Error('the given start is not said in words on its name in the key');
  }
  if (!text.includes('local_walk')) throw new Error("the given chain's kernel is not named");
  if (!text.includes('split z ≤ 3') || !text.includes('2 passing checks in a row')) throw new Error('the stopping rule is not stated');
  for (const want of ['met', 'apart', 'every check within z \u2264 3 from', '800 sweeps', 'seeds lower in energy than from empty']) {
    if (!text.includes(want)) throw new Error(`the table's run lacks "${want}"`);
  }
  if (String(tableCell(app, 'lower_energy', 'given', 4096).textContent) !== '3/3') throw new Error('the seeds lower in energy are not counted');
  const dw = nodesWhere(app, (n) => n.attributes && n.attributes['data-quantity'] === 'd_w')[0];
  if (!String(dw.innerHTML).includes('tc-withheld')) throw new Error('a withheld d_w is not drawn hollow');
  if (!text.includes('◌ 1.727')) throw new Error('a withheld d_w is not listed hollow in the table');
  if (!text.includes('not a power law')) throw new Error('a refusal is not named in the table');
  if (!nodesWhere(app, (n) => hasClass(n, 'tc-diff')).length) throw new Error('chains that differ are not marked');
  const meet = nodesWhere(app, (n) => n.attributes && n.attributes['data-quantity'] === 'met_from')[0];
  const meetSvg = String(meet.innerHTML);
  const marks = (meetSvg.match(/tc-met-dot/g) || []).length + (meetSvg.match(/tc-unmet-dot/g) || []).length;
  if (marks !== 2 * CHAINS_PAYLOAD.chains.rungs.length) throw new Error(`the rest chart draws ${marks} marks, not one a start a size`);
  if (!(meetSvg.match(/tc-unmet-dot/g) || []).length || !(meetSvg.match(/tc-met-dot/g) || []).length) {
    throw new Error('the rest chart does not draw a start that met filled and one that did not hollow');
  }
  if (!meetSvg.includes('not by the end of its run, at the ceiling at 1,600 sweeps')) throw new Error('an unmet seed does not say how its run ended');
  const gap = String(nodesWhere(app, (n) => n.attributes && n.attributes['data-quantity'] === 'energy_gap')[0].innerHTML);
  if ((gap.match(/tc-size-line/g) || []).length !== 2) throw new Error('the gap over the run is not one line per size with a course');
  if ((gap.match(/class="tc-end-label"/g) || []).length !== 2) throw new Error('each size of the gap is not named at its end');
  if (/opacity:/.test(gap.slice(gap.indexOf('tc-size-line'))) || !/color-mix\(in srgb, var\(--text\) 22%/.test(gap)) {
    throw new Error('the sizes are not a no-hue ramp from dark to the text colour');
  }
  if (/var\(--chain-/.test(gap)) throw new Error('a size is drawn in a start\'s colour');
  const checksSvg = String(nodesWhere(app, (n) => n.attributes && n.attributes['data-quantity'] === 'checks')[0].innerHTML);
  if (!checksSvg.includes('3: met below') || !checksSvg.includes('N=4,096, seed 2, at 1,600 sweeps: z = 20')) {
    throw new Error('the checks across N do not draw every seed against the line');
  }
  nodesWhere(app, (n) => hasClass(n, 'tc-size')).find((c) => String(c.textContent).includes('N=4,096')).onclick();
  const all = String(app.textContent);
  if (!/at the ceiling: ×8 the declared sweeps/.test(all)) throw new Error('a ceiling run does not say how it stopped');
  if (!all.includes('1,600 (×8)')) throw new Error('the checks table does not list the sweeps of each check');
  const first = nodesWhere(app, (n) => hasClass(n, 'tc-size'))[0];
  first.onclick();
  if (!String(app.textContent).includes('carry no course of each chain')) throw new Error('a rung without a course does not say why');
  if (!nodesWhere(app, (n) => hasClass(n, 'tc-checks')).length) throw new Error('the checks are not listed without a course');
});

check('how far the law is from a space: the stages, each property per size and chain, the chains apart', () => {
  const app = makeElement('div');
  sandbox.renderTwoChains(app, { ...CHAINS_PAYLOAD, space_score: SPACE_SCORE });
  const { box, text } = spaceScoreChecks(app, SPACE_SCORE, 'score');
  for (const want of ['apart by 28.2 at N=1,024, 37.4 at N=4,096', 'empty (d=3)', 'given (d=2)']) {
    if (!text.includes(want)) throw new Error(`the score lacks "${want}"`);
  }
  const explained = String(nodesWhere(app, (n) => hasClass(n, 'tc-explain'))[0].textContent);
  for (const want of ['it feels no N', 'never decided on']) {
    if (!explained.includes(want) || text.includes(want)) throw new Error(`"${want}" belongs to the explanation, not above the score`);
  }
  const within = nodesWhere(box, (n) => n.tagName === 'TD' && hasClass(n, 'ss-within')).length;
  const beyond = nodesWhere(box, (n) => n.tagName === 'TD' && hasClass(n, 'ss-beyond')).length;
  if (within < 10 || beyond < 4) throw new Error(`the score marks ${within} cells within and ${beyond} beyond`);
  const cut = JSON.parse(JSON.stringify(SPACE_SCORE));
  cut.stage = 0; cut.full = { passed: false, cut: [{ n: 4096, ends: { budget: 2 } }] }; cut.stages[0].passed = false;
  const app2 = makeElement('div');
  sandbox.renderTwoChains(app2, { ...CHAINS_PAYLOAD, space_score: cut });
  if (!String(app2.textContent).includes('N=4,096: 2 at its budget')) throw new Error('a run ended at its budget is not named');
  if (tableRows(app2, 'space_apart_given').length !== 1) throw new Error('the chains apart are not a row');
});

check('a zero-temperature law is read by rest, and a law with no seed says so', () => {
  const cold = JSON.parse(JSON.stringify(CHAINS_PAYLOAD));
  cold.chains.zero_temperature = true;
  cold.chains.rungs.forEach((r) => r.per_seed.forEach((s) => s.checks.forEach((c, i) => {
    c.rest = { empty: i ? 0.004 : 0.2, given: 0.001 }; c.rest_limit = 0.01; })));
  const app = makeElement('div');
  sandbox.renderTwoChains(app, cold);
  const text = String(app.textContent);
  if (!text.includes('zero temperature') || !text.includes('need meet, not even the twin starts')) throw new Error('the rest rule is not stated');
  if (!nodesWhere(app, (n) => hasClass(n, 'tc-run-chart')).some((c) => String(c.innerHTML).includes('late descent share'))) {
    throw new Error('the late descent share is not drawn');
  }
  const none = makeElement('div');
  sandbox.renderTwoChains(none, { chains: { rungs: [] } });
  if (!String(none.textContent).includes('no measured seed')) throw new Error('an empty law says nothing');
});

const MORE = ['honeycomb', 'cubic', 'tesseract'];
function fiveChains(payload) {
  const out = JSON.parse(JSON.stringify(payload));
  out.chains.every_chain = [{ name: 'empty', key: 'empty', start: 'the empty graph' },
    { name: 'random', key: 'given', start: 'random_mean_degree_6.132866' },
    ...MORE.map((name) => ({ name, key: name, start: 'periodic_' + name + '_lattice' }))];
  out.chains.more_probes_read = Object.fromEntries(MORE.map((k) => [k, true]));
  out.chains.rungs.forEach((r) => {
    r.more_given = Object.fromEntries(MORE.map((k, i) => [k, JSON.parse(JSON.stringify(i === 2 ? r.empty : r.given))]));
    r.more_readings = Object.fromEntries(MORE.map((k, i) => [k, { ...r.reading, reading: i === 1 ? 'frozen' : r.reading.reading }]));
    r.per_seed.forEach((sd) => {
      sd.more_meetings = Object.fromEntries(MORE.map((k) => [k, { ...sd.meeting, lower_energy: 'level' }]));
      sd.ended_at_cap = r.n === 4096 ? ['tesseract'] : [];
      if (sd.course) sd.course.more_given = Object.fromEntries(MORE.map((k) => [k, JSON.parse(JSON.stringify(sd.course.given))]));
      sd.checks.forEach((c) => { c.more_z = Object.fromEntries(MORE.map((k, i) => [k, { energy_per_node: c.z.energy_per_node + i, mean_degree: 1 }])); });
    });
  });
  return out;
}
const FIVE_SCORE = (() => {
  const score = JSON.parse(JSON.stringify(SPACE_SCORE));
  MORE.forEach((k) => { score.chains[k] = JSON.parse(JSON.stringify(SPACE_SCORE.chains.given)); });
  score.spaces = ['given', ...MORE];
  score.more_gaps = Object.fromEntries(MORE.map((k, i) => [k, SPACE_SCORE.gaps.map((g) => ({ ...g, distance: g.distance / (i + 1) }))]));
  return score;
})();

check('every chain of a law with a list of starts is drawn alike, each by its start', () => {
  const payload = { ...fiveChains(CHAINS_PAYLOAD), space_score: FIVE_SCORE };
  const { app, text } = twoChainsChecks(payload, 'five');
  const drawn = nodesWhere(app, (n) => hasClass(n, 'tc-chart') && n.attributes['data-quantity'] === 'mean_degree')[0];
  for (const ink of ['var(--start-empty', 'var(--start-random', 'var(--start-honeycomb', 'var(--start-cubic', 'var(--start-tesseract']) {
    if (!String(drawn.innerHTML).includes(ink)) throw new Error(`the chart does not draw ${ink}`);
  }
  const hovered = nodesWhere(app, (n) => hasClass(n, 'tc-key-item')).map((k) => String(k.attributes.title));
  for (const want of ['from the random start (a random graph at mean degree 6.13)', 'from the honeycomb start']) {
    if (!hovered.some((title) => title.includes(want))) throw new Error(`the key of five chains lacks "${want}" on hover`);
  }
  for (const want of ['runs this law 5 times, from five starts', 'ended alone at the mean degree cap', 'honeycomb (d=2)', 'empty and tesseract apart']) {
    if (!text.includes(want)) throw new Error(`five chains lack "${want}"`);
  }
  const severe = tableRows(app, 'the_chains')[0].children.filter((c) => c && c.tagName === 'TD' && hasClass(c, 'tc-v')).map((c) => String(c.textContent));
  if (!severe.includes('apart, frozen')) throw new Error(`the chains' row does not take the most severe chain: ${severe}`);
  const each = Object.fromEntries(['given', 'honeycomb', 'cubic', 'tesseract'].map((k) => [k, String(tableCell(app, 'reading', k, payload.chains.rungs[1].n).textContent)]));
  if (each.given !== 'met' || each.honeycomb !== 'met' || each.cubic !== 'apart, frozen' || each.tesseract !== 'met') {
    throw new Error(`each chain against the one from empty reads ${JSON.stringify(each)}`);
  }
  if (String(tableCell(app, 'at_cap', null, 4096).textContent) !== 'tesseract') throw new Error('the chain that ended alone at the cap is not named');
  const checks = String(nodesWhere(app, (n) => n.attributes && n.attributes['data-quantity'] === 'checks')[0].innerHTML);
  if (!checks.includes('N=4,096, seed 2, at 1,600 sweeps: z = 22')) throw new Error('the checks across N do not take the widest chain');
  nodesWhere(app, (n) => hasClass(n, 'tc-size')).find((c) => String(c.textContent).includes('N=4,096')).onclick();
  if (String(app.textContent).includes('z, widest other')) throw new Error('the checks table still lists a pair no chain is asked to meet');
  if (!nodesWhere(app, (n) => n.attributes && String(n.attributes.title || '').includes('the twin starts’ chains')).length) {
    throw new Error('the checks table does not say the twins are the pair it reads');
  }
  const cold = fiveChains(CHAINS_PAYLOAD);
  cold.chains.zero_temperature = true;
  cold.chains.rungs.forEach((r) => r.per_seed.forEach((s) => s.checks.forEach((c) => {
    c.rest = { empty: 0.004, given: 0.001 }; c.more_rest = { honeycomb: 0.002, cubic: 0.5 }; c.rest_limit = 0.01; })));
  const coldApp = makeElement('div');
  sandbox.renderTwoChains(coldApp, cold);
  nodesWhere(coldApp, (n) => hasClass(n, 'tc-size')).find((c) => String(c.textContent).includes('N=4,096')).onclick();
  const coldText = String(coldApp.textContent);
  for (const want of ['rest, empty', 'rest, random', 'rest, honeycomb', 'rest, tesseract', '50.00%']) {
    if (!coldText.includes(want)) throw new Error(`a cold law with five chains lacks "${want}"`);
  }
  const two = makeElement('div');
  sandbox.renderTwoChains(two, CHAINS_PAYLOAD);
  if (!String(two.textContent).includes('the two chains') || String(two.textContent).includes('honeycomb')) {
    throw new Error('a law of two chains after one of five is not drawn as two chains');
  }
});

const FS_NAMES = ['empty', 'random', ...MORE];
function fsRung(n, groups, cls, fates, lowest) {
  const distances = {}, worst = {};
  FS_NAMES.forEach((a, i) => FS_NAMES.slice(i + 1).forEach((b) => {
    const k = [a, b].sort().join('|'), together = groups.some((g) => g.includes(a) && g.includes(b));
    distances[k] = together ? 0.4 : 6.2; worst[k] = together ? 'd_s' : 'reach';
  }));
  return { n, chains: FS_NAMES, distances, worst, groups, class: cls, spread: Math.max(...Object.values(distances)),
    fates: Object.fromEntries(Object.entries(fates).map(([name, [fate, kept, moved]]) => [name, { fate, kept, degree: 6,
      start_degree: name === 'tesseract' ? 8 : 6, degree_moved: moved, like_start: { distance: fate === 'holds' ? 0 : 9.1, worst: 'reach' } }])),
    lowest_energy: lowest };
}
const FS_DENSE = { n: 16384, chains: ['empty'], distances: {}, worst: {}, groups: [['empty']], class: 'not_read', spread: null,
  fates: {}, lowest_energy: null };
const STARTS_READING = { contract: 'gsd-starts-reading-2', from_n: 1024, met_within: 1,
  chains: [{ name: 'empty', start: null, lattice: null }, { name: 'random', start: 'random_mean_degree_6.132866', lattice: null },
    { name: 'honeycomb', start: 'periodic_honeycomb_lattice', lattice: 2 }, { name: 'cubic', start: 'periodic_cubic_quotient', lattice: 3 },
    { name: 'tesseract', start: 'periodic_tesseract_quotient', lattice: 4 }],
  rungs: [fsRung(1024, [['empty'], ['random'], ['honeycomb'], ['cubic', 'tesseract']], 'converts',
                 { honeycomb: ['partly', 0.612, 0], cubic: ['holds', 1, 0], tesseract: ['stretched', 2.508, 0.25] },
                 { group: ['cubic', 'tesseract'], apart: true }),
          fsRung(4096, [FS_NAMES], 'one_space', { honeycomb: ['melted', 0.137, 1], cubic: ['holds', 1, 0], tesseract: ['changed', 1.591, 0.25] },
                 { group: FS_NAMES, apart: null }), FS_DENSE],
  class: 'one_space', class_name: 'every start ends in one shape',
  names: { one_space: 'every start ends in one shape', grows: 'a start without a shape reaches one', converts: "a lattice falls into another's shape",
           selects: 'one lattice holds, the others do not', holds: 'the lattices hold their shapes', forgets: 'every start ends alike, no shape',
           remembers: 'the starts end apart, no shape held', not_read: 'not read: fewer than two chains at a size from 1,024' },
  classes_by_n: { 1024: 'converts', 4096: 'one_space', 16384: 'not_read' },
  trend: { way: 'merging', joined: FS_NAMES.flatMap((a, i) => FS_NAMES.slice(i + 1).map((b) => [a, b].sort().join('|')))
    .filter((k) => k !== 'cubic|tesseract').sort(), parted: [], apart: 0, closing: [], groups: [4, 1], spread: [6.2, 0.4], from_n: 1024, to_n: 4096 },
  at_n: 4096, top_n: 16384, top_dense: true, references: true };

function startsReadingChecks(app, reading, label) {
  const box = nodesWhere(app, (n) => n.attributes && n.attributes.id === 'startsReading')[0];
  if (!box) throw new Error(`${label}: no section of the starts against each other`);
  const explain = nodesWhere(app, (n) => hasClass(n, 'tc-explain'))[0];
  if (!String((explain || box).textContent).includes('decides its depth from the last base rung')) {
    throw new Error(`${label}: it does not say what it decides`);
  }
  if (!reading.rungs.length) return { box, text: String(box.textContent) };
  const head = nodesWhere(tableOf(app), (n) => n.tagName === 'TR' && n.attributes['data-group'] === 'starts')[0];
  if (!head) throw new Error(`${label}: the table has no rows of the starts against each other`);
  const said = reading.at_n !== null && reading.at_n !== undefined ? reading.names[reading.class] : 'not read yet';
  if (!String(head.textContent).includes('starts against each other') || !String(head.textContent).includes(said)) throw new Error(`${label}: the class is not said`);
  reading.rungs.forEach((r) => {
    const cls = tableCell(app, 'starts_class', null, r.n);
    if (!cls || !hasClass(cls, 'fs-' + r.class)) throw new Error(`${label}: N=${r.n} is not drawn as ${r.class}`);
    const groups = nodesWhere(tableCell(app, 'starts_groups', null, r.n), (n) => hasClass(n, 'fs-group'));
    if (groups.length !== r.groups.length) throw new Error(`${label}: N=${r.n} draws ${groups.length} groups for ${r.groups.length}`);
    Object.entries(r.fates).filter(([, f]) => f.fate).forEach(([name, f]) => {
      const key = name === 'random' ? 'given' : name;
      const cell = tableCell(app, 'fate', key, r.n);
      if (!cell || !hasClass(cell, 'fs-' + f.fate)) throw new Error(`${label}: N=${r.n} lacks the ${name} lattice's fate`);
    });
  });
  return { box, text: String(box.textContent) + ' ' + String(tableOf(app).textContent) };
}

check('the eight starts: each its own colour, in the page\u2019s order, the charts first and the explanation last', () => {
  const run = ['empty', 'random', 'square', 'triangular', 'cubic', 'bcc', 'fcc', 'tesseract'];
  const payload = JSON.parse(JSON.stringify(CHAINS_PAYLOAD));
  payload.chains.every_chain = run.map((name) => ({ name, key: name === 'random' ? 'given' : name,
    start: name === 'empty' ? 'the empty graph' : name === 'random' ? 'random_mean_degree_2.81' : `periodic_${name}_lattice` }));
  payload.chains.rungs.forEach((r) => { r.more_given = Object.fromEntries(run.slice(2).map((k) => [k, r.given])); });
  const app = makeElement('div');
  sandbox.renderTwoChains(app, { ...payload, space_score: SPACE_SCORE, starts_reading: STARTS_READING });
  const items = nodesWhere(app, (n) => hasClass(n, 'tc-key-item'));
  const shown = items.map((n) => String(n.children[n.children.length - 1].textContent ?? n.children[n.children.length - 1]));
  const wanted = ['empty', 'random', 'triangular', 'square', 'cubic', 'bcc', 'fcc', 'tesseract'];
  if (shown.join(',') !== wanted.join(',')) throw new Error(`the page shows the starts as ${shown}, not ${wanted}`);
  const inks = items.map((n) => (/var\(--start-[a-z-]+/.exec(String(n.children[0].attributes.style)) || [''])[0]);
  if (new Set(inks).size !== 8 || inks.some((ink) => !ink)) throw new Error(`two starts share a colour: ${inks}`);
  wanted.forEach((name, i) => { if (inks[i] !== `var(--start-${name}`) throw new Error(`${name} is drawn in ${inks[i]}`); });
  const heads = tableRows(app, 'mean_degree').map((r) => String(r.children.find((c) => c && hasClass(c, 'tc-start')).textContent));
  if (heads.join(',') !== wanted.join(',')) throw new Error(`the table\u2019s rows are ${heads}`);
  const text = String(app.textContent);
  const at = (needle) => { const i = text.indexOf(needle); if (i < 0) throw new Error(`the page lacks "${needle}"`); return i; };
  const order = ['the eight chains', 'the graph counted', 'the four probes', 'geometry and energy', 'the run', 'every value the plots above draw',
                 'starts against each other', 'how far from a space', 'explanation: how the chains are run'];
  order.slice(1).forEach((needle, i) => { if (at(order[i]) > at(needle)) throw new Error(`"${needle}" comes before "${order[i]}"`); });
  const explain = nodesWhere(app, (n) => hasClass(n, 'tc-explain'));
  if (explain.length !== 1 || explain[0].tagName !== 'DETAILS' || explain[0].attributes.open !== undefined) {
    throw new Error('the explanation is one folded block at the end');
  }
  const said = String(explain[0].textContent);
  for (const want of ['Every seed runs this law 8 times', 'each property is a distance in tolerances', 'every two chains are compared']) {
    if (!said.includes(want)) throw new Error(`the explanation lost "${want}"`);
  }
  if (at('the graph counted') > text.indexOf('Every seed runs this law')) throw new Error('the explanation stands above the charts');
});

check('every start read against the others: the class, the groups, each lattice against its own start', () => {
  const app = makeElement('div');
  sandbox.renderTwoChains(app, { ...fiveChains(CHAINS_PAYLOAD), space_score: FIVE_SCORE, starts_reading: STARTS_READING });
  const { box, text } = startsReadingChecks(app, STARTS_READING, 'the starts');
  for (const want of ["a lattice falls into another's shape", 'stretched', 'changed', 'holds', 'melted', 'partly', 'against its own start',
                      'its start’s mean degree', 'are merging (groups 4 → 1); met: ', 'empty and random',
                      'every start ends in one shape at N=4,096; at N=16,384 only the chain from empty was read',
                      'what the starts did',
                      'lowest in energy a node at N=4,096: empty, random, honeycomb, cubic, tesseract', 'apart at N=4,096']) {
    if (!text.includes(want)) throw new Error(`the starts against each other lack "${want}"`);
  }
  const chips = nodesWhere(tableOf(app), (n) => hasClass(n, 'fs-chain'));
  if (!chips.some((c) => String(c.attributes.style).includes('var(--start-tesseract')) || !chips.some((c) => String(c.attributes.style).includes('var(--start-empty'))) {
    throw new Error('a chain in a group is not drawn in its own colour');
  }
  const cells = nodesWhere(box, (n) => n.tagName === 'TD' && (hasClass(n, 'ss-within') || hasClass(n, 'ss-beyond')));
  if (cells.length !== 20) throw new Error(`the distances at the top draw ${cells.length} cells, not every two of five chains both ways`);
  const stretched = nodesWhere(tableOf(app), (n) => n.tagName === 'TD' && hasClass(n, 'fs-stretched'))[0];
  const row = nodesWhere(tableOf(app), (n) => n.tagName === 'TR' && n.children.includes(stretched))[0];
  const degree = tableCell(app, 'start_degree', row.attributes['data-chain'], STARTS_READING.rungs.find((r) => Object.values(r.fates).some((f) => f.fate === 'stretched')).n);
  if (!degree || String(degree.textContent) !== '8.000') throw new Error('a fate does not say its start’s degree');
  const keptRows = tableRows(app, 'kept');
  if (!keptRows.length || !String(tableOf(app).textContent).includes('2.508')) throw new Error('the kept share is not a row of the table');
  const none = makeElement('div');
  sandbox.renderTwoChains(none, { ...fiveChains(CHAINS_PAYLOAD), starts_reading: { ...STARTS_READING, rungs: [], class: 'not_read', references: false,
    at_n: null, top_n: null, top_dense: false } });
  const noneText = String(nodesWhere(none, (n) => n.attributes && n.attributes.id === 'startsReading')[0].textContent);
  if (!noneText.includes('no size of N=1,024 or more read yet') || !noneText.includes('no lattice’s fate is read')
      || !noneText.includes('against each other: no size')) {
    throw new Error('a law not yet read from 1,024 does not say so');
  }
});

if (process.env.GSD_TWO_CHAINS_PAYLOAD) {
  check("two chains drawn from the reader's payload", () => {
    const payload = JSON.parse(fs.readFileSync(process.env.GSD_TWO_CHAINS_PAYLOAD, 'utf8'));
    const { app } = twoChainsChecks(payload, 'reader');
    if (payload.starts_reading) startsReadingChecks(app, payload.starts_reading, 'reader');
    const lattices = ((payload.starts_reading || {}).chains || []).filter((c) => c.lattice);
    if (payload.starts_reading && payload.starts_reading.rungs.length && tableRows(app, 'fate').length !== lattices.length) {
      throw new Error(`${tableRows(app, 'fate').length} lattice rows drawn for ${lattices.length} lattice starts`);
    }
    if (process.env.GSD_CHAINS_EXPECTED) {
      const wanted = process.env.GSD_CHAINS_EXPECTED.split(',');
      const drawn = nodesWhere(app, (n) => hasClass(n, 'fs-chain')).map((n) => String(n.textContent).trim());
      for (const name of wanted) {
        if (!drawn.includes(name)) throw new Error(`the chain from the ${name} start is in no group drawn`);
      }
      const top = payload.starts_reading.rungs[payload.starts_reading.rungs.length - 1];
      const fates = nodesWhere(app, (n) => n.tagName === 'TD' && hasClass(n, 'fs-fate'));
      if (fates.length !== payload.starts_reading.rungs.reduce((sum, r) => sum + Object.values(r.fates).filter((f) => f.fate).length, 0)) {
        throw new Error('not every lattice fate of every size is drawn');
      }
      if (top.chains.length !== wanted.length) throw new Error(`the top size reads ${top.chains.length} chains of ${wanted.length}`);
    }
    console.log("two chains drawn from the reader's payload");
  });
}

const censusOf = (gap, diam, n) => ({ spectral_gap: gap === null ? null : { mean: gap, seeds: 3, seed_sd: gap / 10 },
  largest_component_diameter: { mean: diam, seeds: 3 }, largest_component_diameter_upper: { mean: diam, seeds: 3 },
  largest_component_size: { mean: n * 0.9, seeds: 3 }, largest_component_cycle_rank: { mean: n * 0.1, seeds: 3 },
  component_count: { mean: 4, seeds: 3 }, triangles: { mean: 12, seeds: 3 }, largest_clique: { mean: 3, seeds: 3 },
  squares: null, assortativity: { mean: -0.05, seeds: 3 }, degeneracy: { mean: 2, seeds: 3 } });
const censusRungs = () => [{ n: 4096, census: censusOf(4e-3, 64, 4096) }, { n: 16384, census: censusOf(1e-3, 128, 16384) },
  { n: 262144, census: censusOf(null, 512, 262144) }];
const graphStat = (mean) => ({ mean, seeds: 3 });
const graphRung = (n, kappa, shift = 0) => ({ n, p0: graphStat(0), p1: graphStat(0.1), p2: graphStat(0.4 - shift),
  p3_plus: graphStat(0.5 + shift), mean_degree: graphStat(2.4 + shift), molloy_reed: graphStat(1.4),
  measured_giant_fraction: graphStat(0.9), predicted_giant_fraction: graphStat(0.84), giant_excess: 0.06,
  cycle_rank_per_node: graphStat(0.012),
  ...(kappa === null ? {} : { kappa_mean: graphStat(kappa), kappa_positive_share: graphStat(0.25), kappa_weighted: graphStat(kappa) }) });
const GRAPH_THRESHOLDS = { gap_exponent_at_most: -0.3752, diameter_exponent_at_least: 0.1751 };
const graphChain = (key, name, start, rungs, finite, why) => ({ key, name, start,
  structure: { rungs, finite_dimension: finite, why, thresholds: GRAPH_THRESHOLDS }, census: censusRungs() });
const EVERY_CHAIN = { contract: 'every-chain-graph-1', chains: [
  graphChain('empty', 'empty', null, [graphRung(1024, null), graphRung(4096, -0.6667)], false,
             'gap exponent -0.100 > -0.3752 (stays open or shuts as a logarithm)'),
  graphChain('given', 'random', 'random_mean_degree_6.132866', [graphRung(1024, -0.5, 0.1), graphRung(4096, -0.5, 0.1)], null,
             'one rung with a gap'),
  ...MORE.map((name, i) => graphChain(name, name, 'periodic_' + name + '_lattice',
    [graphRung(1024, 0, 0.2), graphRung(4096, 0, 0.2)], i === 1 ? true : null, i === 1 ? 'gap exponent -0.667 ≤ -0.3752' : 'one rung with a gap'))] };
const dataRows = (table) => nodesWhere(table, (n) => n.tagName === 'TR' && n.children.some((c) => c && c.tagName === 'TD'));

function alikeChecks(table, chains, perChain, label) {
  const rows = dataRows(table);
  if (rows.length !== chains.length * perChain) throw new Error(`${label}: ${rows.length} rows for ${chains.length} chains of ${perChain}`);
  const widths = new Set();
  chains.forEach((chain, i) => {
    const own = rows.slice(i * perChain, (i + 1) * perChain);
    const lead = own[0].children[0];
    if (!hasClass(own[0], 'ec-first') || !hasClass(lead, 'ec-chain') || !hasClass(lead, 'tc-' + chain.key)) {
      throw new Error(`${label}: the rows of ${chain.name} do not open with its name`);
    }
    if (String(lead.textContent) !== chain.name || lead.attributes.rowspan !== String(perChain)) {
      throw new Error(`${label}: ${chain.name} is named ${lead.textContent} over ${lead.attributes.rowspan} rows`);
    }
    if (own.slice(1).some((r) => hasClass(r, 'ec-first') || r.children.some((c) => hasClass(c, 'ec-chain')))) {
      throw new Error(`${label}: a later row of ${chain.name} names a chain again`);
    }
    widths.add(own.map((r, k) => r.children.length - (k ? 0 : 1)).join(','));
  });
  if (widths.size !== 1) throw new Error(`${label}: the chains are not drawn with the same cells: ${[...widths].join(' | ')}`);
  return rows;
}

check('the census of every chain is drawn alike: the gap, its decay and the diameter, a group of rows a chain', () => {
  const app = makeElement('div');
  sandbox.renderStructureCensus(app, EVERY_CHAIN.chains);
  const text = String(app.textContent);
  if (!text.includes('the census of each chain’s final graphs')) throw new Error('no census heading');
  if (!text.includes('4.00e-3') || !text.includes('1.00e-3')) throw new Error('the gap is not printed');
  if (!text.includes('-1.000')) throw new Error('the gap exponent per x4 is not printed');
  if (!text.includes('2.00')) throw new Error('the dimension the gap implies is not printed');
  if (!text.includes('0.500')) throw new Error('the diameter exponent per x4 is not printed');
  if (!text.includes('128.0')) throw new Error('the diameter is not printed');
  const table = nodesWhere(app, (n) => n.tagName === 'TABLE' && hasClass(n, 'census-table'))[0];
  const rows = alikeChecks(table, EVERY_CHAIN.chains, 3, 'the census');
  const first = rows.slice(0, 3).map((r) => String(r.textContent).replace(/^empty/, ''));
  EVERY_CHAIN.chains.forEach((chain, i) => {
    const own = rows.slice(3 * i, 3 * i + 3).map((r) => String(r.textContent).replace(new RegExp('^' + chain.name), ''));
    if (own.join('|') !== first.join('|')) throw new Error(`the same census reads differently on ${chain.name}`);
  });
  const none = makeElement('div');
  sandbox.renderStructureCensus(none, []);
  if (!String(none.textContent).includes('no structure census')) throw new Error('a law without a census says nothing');
});

check('every chain’s graph is drawn alike: the degrees, the giant against random, the curvature, a verdict a chain, the rule once', () => {
  const five = makeElement('div');
  sandbox.renderTwoChains(five, fiveChains(CHAINS_PAYLOAD));
  const app = makeElement('div');
  const payload = { every_chain: EVERY_CHAIN,
    what_happened: { rung: 65536, clauses: [{ topic: 'how the seeds ended', text: '3 of 3 seeds ended ceiling' },
      { topic: 'how the chains from the empty start moved', text: 'wandering on a plateau: of 190 accepted late moves' }] } };
  sandbox.renderEveryChainGraph(app, payload);
  sandbox.renderWhatHappened(app, payload);
  const text = String(app.textContent);
  if (!text.includes('each chain’s graph')) throw new Error('no heading for every chain’s graph');
  if (!text.includes('40.0%') || !text.includes('50.0%')) throw new Error('the degree shares are not printed');
  if (!text.includes('0.840') || !text.includes('+0.060')) throw new Error('the random-graph giant and the difference are missing');
  if (!text.includes('κ mean')) throw new Error('the curvature column is missing');
  if (!text.includes('-0.6667') || !text.includes('25.0%')) throw new Error('the curvature of the chain from empty is not printed');
  if (!text.includes('0.0000')) throw new Error('a lattice chain’s flat curvature is not printed');
  if (!text.includes('n/a')) throw new Error('a rung measured before 544 does not say so');
  if (!text.includes('-2(d-2)/d')) throw new Error('the known answers are not stated');
  const table = nodesWhere(app, (n) => n.tagName === 'TABLE' && hasClass(n, 'structure-reading-table'))[0];
  const rows = alikeChecks(table, EVERY_CHAIN.chains, 2, 'every chain’s graph');
  const inks = EVERY_CHAIN.chains.map((_, i) => String(rows[2 * i].children[0].attributes.style));
  ['var(--start-empty', 'var(--start-random', 'var(--start-honeycomb', 'var(--start-cubic', 'var(--start-tesseract'].forEach((ink, i) => {
    if (!inks[i].includes(ink)) throw new Error(`the chain ${EVERY_CHAIN.chains[i].name} is not drawn in its own colour: ${inks[i]}`);
  });
  const verdicts = nodesWhere(app, (n) => hasClass(n, 'structure-verdict'));
  if (verdicts.length !== EVERY_CHAIN.chains.length) throw new Error(`${verdicts.length} verdicts for ${EVERY_CHAIN.chains.length} chains`);
  const said = verdicts.map((v) => String(v.textContent));
  if (!said[0].startsWith('empty: no finite dimension by the committed rule')) throw new Error(`the chain from empty reads: ${said[0]}`);
  if (!said[1].startsWith('random: not decidable yet')) throw new Error(`the random chain reads: ${said[1]}`);
  if (!said[3].startsWith('cubic: a finite dimension by the committed rule')) throw new Error(`the cubic chain reads: ${said[3]}`);
  const rule = nodesWhere(app, (n) => hasClass(n, 'ec-rule'));
  if (rule.length !== 1 || !String(rule[0].textContent).includes('-0.3752') || !String(rule[0].textContent).includes('for every chain')) {
    throw new Error('the committed rule is not stated once, for every chain');
  }
  const order = nodesWhere(app, (n) => ['H2', 'H3'].includes(n.tagName)).map((n) => String(n.textContent).split(' (')[0]);
  if (order.join(' | ') !== 'each chain’s graph | the census of each chain’s final graphs | what happened at N=65536') {
    throw new Error(`the sections are ${order.join(' | ')}`);
  }
  if (!text.includes('wandering on a plateau')) throw new Error('what happened is not drawn');
  const empty = makeElement('div');
  sandbox.renderEveryChainGraph(empty, { every_chain: { chains: [{ key: 'empty', name: 'empty', structure: { rungs: [] }, census: [] }] } });
  sandbox.renderWhatHappened(empty, { what_happened: { clauses: [], why: 'no measured seed to read' } });
  if (!String(empty.textContent).includes('no census') || !String(empty.textContent).includes('no measured seed')) {
    throw new Error('an empty reading says nothing');
  }
  const old = makeElement('div');
  sandbox.renderEveryChainGraph(old, null, [{ n: 4096, summary: { census: censusOf(4e-3, 64, 4096) } }]);
  if (!String(old.textContent).includes('4.00e-3')) throw new Error('without the readings, the census of the rungs is not drawn');
  sandbox.renderTwoChains(makeElement('div'), CHAINS_PAYLOAD);
});

const CURVE_KINDS = ['return_probability', 'volume_growth', 'walk_displacement', 'box_covering'];
function curvesPayload(n, keys) {
  const curve = (slope, lift) => ({ x: [1, 2, 4, 8, 16], y: [1, 2, 4, 8, 16].map((x) => lift * x ** slope) });
  const chain = (i) => Object.fromEntries(CURVE_KINDS.map((kind, k) => [kind, curve(k % 2 ? 1.5 : -1, 1 + i)]));
  return { contract: 'every-chain-curves-1', n, chains: keys.map(([key, name]) => ({ key, name })),
    seeds: [0, 1, 2].map((seed) => ({ seed, chains: Object.fromEntries(keys.map(([key], i) => [key, key === 'tesseract' ? null : chain(i)])
      .filter(([, v]) => v)) })) };
}
const CURVE_CHAINS = [['empty', 'empty'], ['given', 'random'], ...MORE.map((name) => [name, name])];

check('a pointer picks the nearest reading, else the line between two, else nothing', () => {
  const points = [{ x: 0, y: 0, head: 'a', lines: ['the point'] }, { x: 100, y: 0, head: 'a', lines: ['the other'] }];
  const segments = [{ x1: 0, y1: 0, x2: 100, y2: 0, head: 'a', lines: ['between two readings:', 'N=64: 1', 'N=256: 2'] }];
  if (sandbox.tcPick(points, segments, 3, 2).lines[0] !== 'the point') throw new Error('a reading under the pointer is not picked');
  const between = sandbox.tcPick(points, segments, 50, 4);
  if (!between || between.lines[0] !== 'between two readings:' || Math.abs(between.x - 50) > 1e-9) throw new Error('the line between two readings is not picked');
  if (sandbox.tcPick(points, segments, 50, 40) !== null) throw new Error('a pointer far from every line picks something');
  if (sandbox.tcPick(points, [], 20, 5).lines[0] !== 'the point') throw new Error('without a line the nearest reading within reach is not picked');
});

check('every chain’s curves are drawn alike: one chart a probe, one line a chain and seed, a chain without curves named', () => {
  sandbox.renderTwoChains(makeElement('div'), fiveChains(CHAINS_PAYLOAD));
  const host = makeElement('div');
  sandbox.cvDraw(host, curvesPayload(4096, CURVE_CHAINS));
  const charts = nodesWhere(host, (n) => hasClass(n, 'cv-cell'));
  if (charts.map((c) => c.attributes['data-kind']).join(',') !== CURVE_KINDS.join(',')) throw new Error('the four probes are not each a chart');
  charts.forEach((chart) => {
    const svg = String(nodesWhere(chart, (n) => hasClass(n, 'cv-plot'))[0].innerHTML);
    for (const key of ['empty', 'given', 'honeycomb', 'cubic']) {
      const lines = (svg.match(new RegExp(`class="cv-line cv-${key}"`, 'g')) || []).length;
      if (lines !== 3) throw new Error(`${chart.attributes['data-kind']}: ${lines} lines for the three seeds of ${key}`);
    }
    if (svg.includes('cv-tesseract')) throw new Error('a chain that kept no curves is drawn');
    for (const ink of ['var(--start-empty', 'var(--start-random', 'var(--start-honeycomb', 'var(--start-cubic']) {
      if (!svg.includes(ink)) throw new Error(`${chart.attributes['data-kind']}: no line in ${ink}`);
    }
  });
  const note = String(nodesWhere(host, (n) => hasClass(n, 'cv-note'))[0].textContent);
  if (!note.includes('drawn: empty, random, honeycomb, cubic') || !note.includes('3 seeds')) throw new Error(`the note reads: ${note}`);
  charts.forEach((chart) => {
    if (chart.attributes['data-eli5'] !== chart.attributes['data-kind'] || !nodesWhere(chart, (n) => hasClass(n, 'tc-bubble')).length) {
      throw new Error(`${chart.attributes['data-kind']}: the curve carries no plain words behind its title`);
    }
    if (!(chart._segments || []).length || !chart._segments.every((g) => g.lines[0] === 'between two readings:')) {
      throw new Error(`${chart.attributes['data-kind']}: a curve between two of its points says nothing`);
    }
    const tips = chart._tips || [];
    if (!tips.length || !tips.some((t) => t.head === 'honeycomb, seed 2') || !tips.every((t) => t.lines[0] === 'N=4,096')) {
      throw new Error(`${chart.attributes['data-kind']}: a point's mouse-over does not name its start, seed and size`);
    }
  });
  const refusing = curvesPayload(4096, CURVE_CHAINS);
  refusing.seeds.forEach((s) => { s.chains.cubic.box_covering = { x: [], y: [], refused: 'NO_SCALING_WINDOW' };
    Object.values(s.chains).forEach((c) => { c.walk_displacement = { x: [], y: [], refused: 'WALK_SATURATED' }; }); });
  const told = makeElement('div');
  sandbox.cvDraw(told, refusing);
  const byKind = Object.fromEntries(nodesWhere(told, (n) => hasClass(n, 'cv-cell')).map((c) => [c.attributes['data-kind'], c]));
  if (!String(byKind.box_covering.textContent).includes('no curve: cubic (no scaling window)') || String(byKind.box_covering.innerHTML).includes('cv-cubic')) {
    throw new Error('a chain a probe refused is not named under the chart of the others');
  }
  if (nodesWhere(byKind.walk_displacement, (n) => hasClass(n, 'cv-plot')).length
      || !String(byKind.walk_displacement.textContent).includes('no curve of any chain: walk saturated')) {
    throw new Error('a probe every chain was refused by does not say so');
  }
  const none = makeElement('div');
  sandbox.cvDraw(none, { chains: CURVE_CHAINS.map(([key, name]) => ({ key, name })), seeds: [] });
  if (!String(none.textContent).includes('no curve was kept at this size')) throw new Error('a size without curves says nothing');
  sandbox.renderTwoChains(makeElement('div'), CHAINS_PAYLOAD);
});

if (process.env.GSD_EVERY_CHAIN_PAYLOAD) {
  check("every chain's graph and curves drawn from the reader's payload", () => {
    const { structure, curves } = JSON.parse(fs.readFileSync(process.env.GSD_EVERY_CHAIN_PAYLOAD, 'utf8'));
    const chains = structure.every_chain.chains;
    sandbox.renderTwoChains(makeElement('div'), structure);
    const app = makeElement('div');
    sandbox.renderEveryChainGraph(app, structure);
    const sizes = Math.max(...chains.map((c) => c.structure.rungs.length));
    const read = chains.filter((c) => c.structure.rungs.length);
    if (read.some((c) => c.structure.rungs.length !== sizes)) throw new Error('reader: the chains are not read at the same sizes');
    alikeChecks(nodesWhere(app, (n) => n.tagName === 'TABLE' && hasClass(n, 'structure-reading-table'))[0], read, sizes, 'reader, the graph');
    alikeChecks(nodesWhere(app, (n) => n.tagName === 'TABLE' && hasClass(n, 'census-table'))[0],
                chains.filter((c) => c.census.some((r) => r.census)), sizes, 'reader, the census');
    const host = makeElement('div');
    sandbox.cvDraw(host, curves);
    const kept = curves.chains.filter((c) => curves.seeds.some((s) => s.chains[c.key]));
    if (kept.length !== curves.chains.length) throw new Error('reader: a chain kept no curves');
    let plots = 0;
    nodesWhere(host, (n) => hasClass(n, 'cv-cell')).forEach((chart) => {
      const kind = chart.attributes['data-kind'];
      const has = (c) => curves.seeds.some((s) => (((s.chains[c.key] || {})[kind] || {}).x || []).length);
      const plot = nodesWhere(chart, (n) => hasClass(n, 'cv-plot'))[0];
      if (!plot && kept.some(has)) throw new Error(`reader: ${kind} is kept and not drawn`);
      if (plot) plots += 1;
      const svg = plot ? String(plot.innerHTML) : '';
      kept.forEach((c) => {
        if (has(c) && !svg.includes(`cv-line cv-${c.key}"`)) throw new Error(`reader: ${kind} lacks ${c.name}`);
        const said = String(chart.textContent);
        if (!has(c) && !said.includes('no curve of any chain: ') && !said.includes(`${c.key === 'empty' ? 'empty' : c.name} (`)) {
          throw new Error(`reader: ${kind} does not say why ${c.name} has no curve`);
        }
      });
    });
    if (plots < 3) throw new Error(`reader: only ${plots} of the four probes drew a curve`);
    console.log("every chain's graph and curves drawn from the reader's payload");
  });
}

const SCORE_SIZES = [1024, 4096, 16384, 65536];
function probeSide(values) {
  return Object.fromEntries(Object.entries(values).map(([k, v]) => [k, { mean: v, se: 0.02, seeds: 3, of: 3, values: [v, v, v] }]));
}
const PLANE = { d_s: 2.0, d_V: 2.02, d_B: 1.98, d_w: 2.0, mean_degree: 4.0, giant_fraction: 1.0 };
const RANDOM = { d_s: 4.1, d_V: 5.6, d_B: 4.5, d_w: 2.4, mean_degree: 6.0, giant_fraction: 1.0 };
function scorePayload() {
  const steps = (v) => Object.fromEntries(['d_s', 'd_V', 'd_B', 'd_w'].map((p) => [p, { step: 0.01, margin: 0.06, from: v, to: v }]));
  const entry = (key, start, kind, extra) => ({ key, start, kind, from_n: 4096, settled: [], steps: {}, residual: null, tau: 0.075,
    einstein: false, points: 0, value: 0, how: 'no probe reads at both sizes', ...extra });
  const five = { settled: ['d_s', 'd_V', 'd_B', 'd_w'], steps: steps(2.0), residual: 0.0, einstein: true, points: 15,
    how: '15 of 15: d_s, d_V, d_B, d_w settle again, and the Einstein relation settles again' };
  return {
    chains: { given_probes_read: true,
      every_chain: [{ name: 'empty', key: 'empty', start: 'the empty graph' }, { name: 'random', key: 'given', start: 'random_at_drawn_degree' },
                    ...MORE_SCORED.map((name) => ({ name, key: name, start: 'periodic_' + name + '_lattice' }))],
      rungs: [256, ...SCORE_SIZES].map((n) => ({ n, seeds: 3, empty: probeSide(PLANE), given: probeSide(RANDOM),
        more_given: { honeycomb: probeSide(RANDOM), cubic: probeSide({ ...PLANE, d_s: 2.6, d_V: 2.8, d_B: 2.7, giant_fraction: 0.55 }),
                      tesseract: n >= 16384 ? {} : probeSide({ ...RANDOM, mean_degree: 8 }) } })) },
    score: { contract: 'gsd-law-score-5', score: 57, of: 100, by: 'empty', chain: 'empty', to_n: 65536, top_n: 65536, points: 15, points_of: 15, einstein: true,
      weights: { empty: 1.0, random: 1.0, lattice: 0.6, kept: 0.3 }, ladder: [1024, 4096, 16384, 65536, 262144, 1048576, 4194304],
      parts: { empty: { weight: 1.0, to_n: 65536, chain: 'empty', depth: 0.5714, points: 57.14, of: 15 },
               random: { weight: 1.0, to_n: null, chain: null, points: 0.0, of: 0 }, lattice: { weight: 0.6, to_n: null, chain: null, points: 0.0, of: 0 },
               kept: { weight: 0.3, to_n: 16384, chain: 'cubic', depth: 0.4286, points: 5.14, of: 2 } },
      sizes: [16384, 65536].map((n) => ({ n, chains: {
        empty: entry('empty', 'empty', 'empty', { ...five, from_n: n / 4, value: n === 65536 ? 57.14 : 42.86 }),
        random: entry('given', 'random', 'random', { steps: steps(4.1), how: 'no probe settles: d_V moves 0.2 of itself, 0.06 allowed' }),
        honeycomb: entry('honeycomb', 'lattice', 'lattice', { fate: 'loses' }),
        cubic: entry('cubic', 'lattice', 'kept', { fate: 'holds', settled: ['d_s', 'd_V'], points: 2, steps: steps(2.7),
          how: '2 of 15: d_s reads at two sizes, d_V reads at two sizes; the lattice start holds, so it counts 0.3' }),
        tesseract: entry('tesseract', 'lattice', 'kept', {}) } })) } };
}
const MORE_SCORED = ['honeycomb', 'cubic', 'tesseract'];

function flowChecks(app, payload, label) {
  const panels = nodesWhere(app, (n) => hasClass(n, 'flow-start'));
  const keys = panels.map((n) => n.attributes['data-chain']);
  const expected = ['empty', 'given', ...((payload.chains.every_chain || []).slice(2).map((c) => c.key))];
  if (keys.join(',') !== expected.join(',')) throw new Error(`${label}: the flow draws ${keys} for ${expected}`);
  const text = String(app.textContent);
  if (!text.includes('finite-size flow, every start')) throw new Error(`${label}: the flow is not headed for every start`);
  return { panels, text };
}

check('the flow is drawn for every start, alike, and shaded where the score reads a geometry', () => {
  const payload = scorePayload();
  const app = makeElement('div');
  sandbox.renderFlowEveryStart(app, payload);
  const { panels, text } = flowChecks(app, payload, 'flow');
  const svgOf = (panel) => String((nodesWhere(panel, (n) => hasClass(n, 'flow-start-svg'))[0] || {}).innerHTML || '');
  const empty = svgOf(panels[0]);
  for (const probe of ['d_s', 'd_V', 'd_B', 'd_w']) {
    const plotted = (empty.match(new RegExp(`${probe} on from empty, N=`, 'g')) || []).length;
    if (plotted !== 5) throw new Error(`${probe} plotted ${plotted} of 5 sizes on the chain from empty`);
  }
  for (const shape of ['<circle', '<polygon', '<rect']) {
    if (!empty.includes(shape)) throw new Error(`no ${shape} markers: the probes are not distinguishable`);
  }
  if ((empty.match(/class="flow-geometry"/g) || []).length !== 2) throw new Error('the chain from empty is not shaded at the two sizes it scores at');
  if (/class="flow-geometry"/.test(svgOf(panels[1]) + svgOf(panels[2]))) throw new Error('a start with no point is shaded');
  if (empty.includes('class="flow-branching"')) throw new Error('the tree line left at 790, so no <d> - 1 is drawn');
  const tesseract = svgOf(panels[4]);
  if ((tesseract.match(/d_s on tesseract, N=/g) || []).length !== 3) throw new Error('the 4D start is not drawn at the sizes it was read');
  for (const want of ['counts 1 · points to N=65,536', 'counts 1 · no probe settles', 'counts 0.3 · points to N=65,536', 'random', 'honeycomb',
                      'points, as the score reads them']) {
    if (!text.includes(want)) throw new Error(`the flow lacks "${want}": ${text}`);
  }
  const unread = scorePayload();
  unread.chains.rungs.forEach((r) => { r.more_given.tesseract = {}; });
  const none = makeElement('div');
  sandbox.renderFlowEveryStart(none, unread);
  if (!String(nodesWhere(none, (n) => hasClass(n, 'flow-start'))[4].textContent).includes('no probe read on this start')) {
    throw new Error('a start with no probe read is not said');
  }
  const nothing = makeElement('div');
  sandbox.renderFlowEveryStart(nothing, { chains: { rungs: [] } });
  if (!String(nothing.textContent).includes('no measured seed')) throw new Error('a law with no measured seed is not said');
});

function scoreChecks(app, score, label) {
  const text = String(app.textContent);
  if (!text.includes(`${score.score} of 100`)) throw new Error(`${label}: the score is not on the page: ${text}`);
  const sizes = nodesWhere(app, (n) => n.tagName === 'TABLE' && hasClass(n, 'ls-sizes'))[0];
  if (!sizes) throw new Error(`${label}: every start at every size is not drawn`);
  const sizeRows = nodesWhere(sizes, (n) => n.tagName === 'TR');
  if (sizeRows.length !== score.sizes.length + 1) throw new Error(`${label}: ${sizeRows.length - 1} sizes drawn for ${score.sizes.length}`);
  const cells = nodesWhere(sizes, (n) => n.tagName === 'TD' && (hasClass(n, 'ls-geometry') || hasClass(n, 'ls-not')));
  const chains = Object.keys(score.sizes[0].chains).length;
  if (cells.length !== score.sizes.length * chains) throw new Error(`${label}: ${cells.length} cells for ${score.sizes.length} sizes of ${chains} starts`);
  const held = score.sizes.reduce((k, size) => k + Object.values(size.chains).filter((e) => e.points > 0).length, 0);
  if (cells.filter((c) => hasClass(c, 'ls-geometry')).length !== held) throw new Error(`${label}: the points drawn are not the score's`);
  return { text, cells };
}

check('the score says who built it, each part, and every start at every size', () => {
  const payload = scorePayload();
  const app = makeElement('div');
  sandbox.renderLawScore(app, payload);
  const { text, cells } = scoreChecks(app, payload.score, 'score');
  for (const want of ['the score', 'the chain from empty: 15 of 15 at N=65,536, all four agreeing by Einstein', 'the random start',
                      'a lattice start, kept', '4 of 7', '57.1', 'Points times depth times who', 'the landscape\u2019s 5th band',
                      '15 of 15 ✓', '2 of 15', '0 of 15']) {
    if (!text.includes(want)) throw new Error(`the score lacks "${want}"`);
  }
  const kept = cells.find((c) => String(c.textContent) === '2 of 15');
  if (!String(kept.attributes.title).includes('d_s: 2.7 to 2.7, a step of 1.0% of itself, 6% allowed: settles')
      || !String(kept.attributes.title).includes('its fate as a lattice start: holds')) {
    throw new Error(`a cell does not say each probe's step against its margin: ${kept.attributes.title}`);
  }
  const top = cells.find((c) => String(c.textContent) === '15 of 15 ✓');
  if (!String(top.attributes.title).includes('the Einstein relation: d_s within 0.0% of 2 d_f / d_w, 7.5% allowed')) {
    throw new Error(`the Einstein relation is not said: ${top.attributes.title}`);
  }
  const unread = makeElement('div');
  sandbox.renderLawScore(unread, { chains: { rungs: [] }, score: null });
  if (!String(unread.textContent).includes('not read')) throw new Error('a law the score has not read is not said');
  const young = makeElement('div');
  sandbox.renderLawScore(young, { chains: { rungs: [] }, score: { score: 0, by: null, chain: null, to_n: null, top_n: 256, sizes: [], parts: {}, weights: {} } });
  if (!String(young.textContent).includes('not yet at N=16,384')) throw new Error('a law not yet at 16,384 nodes is not said');
});

check('the header chip carries the score read from every start, and says when it could not', () => {
  const chip = makeElement('span');
  sandbox.fillScoreChip(chip, scorePayload().score);
  if (String(chip.textContent) !== '57' || chip.attributes.class !== 'hdr-score strong') throw new Error(`the chip reads ${chip.textContent} (${chip.attributes.class})`);
  if (!String(chip.attributes.title).includes('the chain from empty: 15 of 15 at N=65,536')) throw new Error('the chip does not say who built it');
  sandbox.fillScoreChip(chip, { score: 17, by: 'kept', chain: 'honeycomb', to_n: 65536, top_n: 65536, points: 15, points_of: 15, einstein: true });
  if (chip.attributes.class !== 'hdr-score partial' || !String(chip.attributes.title).includes('a lattice start, kept (honeycomb): 15 of 15')) throw new Error('a lattice’s score is not said');
  sandbox.fillScoreChip(chip, { score: 0, by: null, chain: null, to_n: null, top_n: 65536 });
  if (String(chip.textContent) !== '0' || chip.attributes.class !== 'hdr-score zero') throw new Error('a 0 is not drawn as one');
  sandbox.fillScoreChip(chip, null);
  if (String(chip.textContent) !== '?' || !String(chip.attributes.title).includes('unavailable')) throw new Error('an unanswered reading reads as a score');
});

check('the page draws no stability score, no flow of one chain and no factor-4 transitions', () => {
  const page = fs.readFileSync(path.join(uiDir, 'candidate.html'), 'utf8');
  for (const gone of ['function renderStability', 'function renderTransitions', 'function chart(', "'factor-4 transitions'",
                      'finite-size flow, the chain from the empty graph', 'base stability score']) {
    if (page.includes(gone)) throw new Error(`the page still has ${gone}`);
  }
  for (const want of ['renderFlowEveryStart(flowHost,payload)', 'renderLawScore(scoreHost,payload)', 'fillScoreChip(scoreChip,payload&&payload.score)']) {
    if (!page.includes(want)) throw new Error(`the page does not call ${want}`);
  }
  const flow = page.indexOf('app.append(flowHost,scoreHost)'), twoChains = page.indexOf('app.append(twoChainsHost)');
  if (!(twoChains >= 0 && flow > twoChains)) throw new Error('the flow and the score are not after the chains');
});

if (process.env.GSD_SCORE_PAYLOAD) {
  check("the flow and the score drawn from the reader's payload", () => {
    const payload = JSON.parse(fs.readFileSync(process.env.GSD_SCORE_PAYLOAD, 'utf8'));
    const flow = makeElement('div');
    sandbox.renderFlowEveryStart(flow, payload);
    flowChecks(flow, payload, 'reader');
    const app = makeElement('div');
    sandbox.renderLawScore(app, payload);
    scoreChecks(app, payload.score, 'reader');
    const chip = makeElement('span');
    sandbox.fillScoreChip(chip, payload.score);
    if (String(chip.textContent) !== String(payload.score.score)) throw new Error('reader: the chip is not the score');
    console.log("the flow and the score drawn from the reader's payload");
  });
}

async function retryChecks() {
  const answers = [503, 503, 200];
  const waits = [];
  sandbox.fetch = () => {
    const status = answers.shift();
    return Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve({ candidate: { id: 'x' } }) });
  };
  const d = await sandbox.jRetry('/candidate-data/1/abc', { sleep: () => Promise.resolve(), onWait: (n) => waits.push(n) });
  if (!d || !d.candidate || waits.join(',') !== '1,2') throw new Error('a busy answer is not asked again');
  sandbox.fetch = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  let thrown = null;
  try { await sandbox.jRetry('/candidate-data/1/abc', { sleep: () => Promise.resolve() }); } catch (e) { thrown = e; }
  if (!thrown || thrown.status !== 404) throw new Error('a missing law is not an error at once');
  sandbox.fetch = () => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) });
  thrown = null;
  try { await sandbox.jRetry('/candidate-data/1/abc', { tries: 3, sleep: () => Promise.resolve() }); } catch (e) { thrown = e; }
  if (!thrown || thrown.status !== 503) throw new Error('a busy answer that never ends is not reported');
}

async function pageChecks() {
  const id = 'ab'.repeat(32);
  const names = ['empty', 'random', ...MORE];
  const structure = { ...fiveChains(CHAINS_PAYLOAD), campaign_id: '1', candidate_id: id, space_score: FIVE_SCORE,
    starts_reading: STARTS_READING, every_chain: EVERY_CHAIN, score: scorePayload().score,
    what_happened: { rung: 4096, clauses: [{ topic: 'how the seeds ended', text: '3 of 3 seeds ended completed' }] } };
  const sizes = structure.chains.rungs.map((r) => r.n);
  const block = (mean) => ({ mean, se: 0.01, seeds: 3 });
  const data = { campaign_id: '1',
    candidate: { candidate_id: id, campaign_id: '1', state: 'stabilizing', candidate_number: 3, ensemble_code: 'G-3',
      law: 'H = 1.0 * edges', fingerprint_verified: true, dynamics: 'equilibrium', complexity: 1,
      spec: { init: 'empty', terms: [], dynamics: { kind: 'equilibrium', beta: 1, sweeps: 30, move_mix: {} } } },
    rungs: sizes.map((n) => ({ n, summary: { seeds: 3, mean_degree: block(4), connected_fraction: block(1), census: censusOf(4e-3, 64, n) },
      compute: { jobs: 3, attempts: 3, core_seconds: 30, cumulative_core_seconds: 60 },
      channels: ['d_s', 'd_V', 'd_B', 'd_w'].map((channel) => ({ channel, mean: 2, se: 0.02, valid_fraction: 1, n_seeds: 3 })) })),
    equilibration: [], rung_diagnostics: [], engine_decisions: [], proposal_assessments: [], stability: { connectivity_floor: 0.5 } };
  const asked = [];
  let structureStatus = 200;
  sandbox.fetch = (url) => {
    const u = String(url);
    asked.push(u);
    const body = u.includes('/candidate-data/') ? data : u.includes('/structure-data/') ? (structureStatus === 200 ? structure : null)
      : u.includes('/curves-data/') ? curvesPayload(+u.split('/').pop(), CURVE_CHAINS) : null;
    return Promise.resolve({ ok: body !== null, status: body === null ? structureStatus : 200, json: () => Promise.resolve(body || {}) });
  };
  vm.runInContext("currentCampaign='1'", sandbox);
  const settle = async () => { for (let i = 0; i < 40; i += 1) await new Promise((r) => setImmediate(r)); };
  const draw = async () => {
    const root = documentStub.getElementById('app');
    root.textContent = '';
    await sandbox.candidateView(id);
    await settle();
    return root;
  };
  const root = await draw();
  const tables = nodesWhere(root, (n) => n.tagName === 'TABLE' && hasClass(n, 'rung-table'));
  if (tables.length !== 1) throw new Error(`${tables.length} rung tables on the page`);
  const rows = nodesWhere(tables[0], (n) => n.tagName === 'TR' && hasClass(n, 'rung-row'));
  if (rows.map((r) => String(r.children[0].textContent)).join(',') !== sizes.map((n) => `N=${n}`).join(',')) {
    throw new Error(`the rungs table is not one row a size: ${rows.map((r) => String(r.children[0].textContent))}`);
  }
  if (nodesWhere(tables[0], (n) => hasClass(n, 'ec-chain')).length) throw new Error('the rungs table still repeats every chain’s reading');
  const pushes = nodesWhere(root, (n) => n.tagName === 'BUTTON' && hasClass(n, 'push-toggle'));
  if (pushes.length !== 1 || String(pushes[0].textContent) !== 'push to the N limit') throw new Error('the law page has no push to the N limit toggle (889)');
  if (!asked.some((u) => u.includes('/api/focus/top'))) throw new Error('the law page does not ask whether its law is pushed');
  const top_n = sizes[sizes.length - 1];
  if (String(tableCell(root, 'mean_degree', 'given', top_n).textContent) !== '5.500 ± 0.010') throw new Error('the given chain’s own mean degree is not in the table');
  if (String(tableCell(root, 'mean_degree', 'empty', top_n).textContent) !== '4.000 ± 0.010') throw new Error('the mean degree of the chain from empty is not in the table');
  if (!String(tableOf(root).textContent).includes('◌ 1.727')) throw new Error('a withheld probe of a further chain is not drawn hollow in the table');
  const dynamics = nodesWhere(root, (n) => n.tagName === 'TABLE' && hasClass(n, 'law-dynamics'));
  if (dynamics.length !== 1 || !String(dynamics[0].textContent).includes('locality')) throw new Error('the law page has no dynamics table');
  const firstH2 = nodesWhere(root, (n) => n.tagName === 'H2')[0];
  const order = nodesWhere(root, (n) => n === dynamics[0] || n === firstH2);
  if (order[0] !== dynamics[0]) throw new Error('the dynamics table is not above the readings');
  const heads = nodesWhere(root, (n) => n.tagName === 'H2').map((n) => String(n.textContent));
  const wanted = ['finite-size flow, every start', 'the score', 'the rungs', 'each chain’s graph', 'what happened'];
  const places = wanted.map((w) => heads.findIndex((h) => h.startsWith(w)));
  if (places.some((p) => p < 0) || places.some((p, i) => i && p < places[i - 1])) throw new Error(`the sections are ${heads.join(' | ')}`);
  const chainsAt = heads.findIndex((h) => h.includes('five chains'));
  if (!(chainsAt >= 0 && chainsAt < places[0])) throw new Error('the chains are not the first section of the readings');
  sizes.forEach((n) => { if (!asked.includes(`/curves-data/1/${id}/${n}`)) throw new Error(`the curves of N=${n} were not asked for: ${asked}`); });
  if (nodesWhere(root, (n) => hasClass(n, 'cv-size')).length) throw new Error('the curves still wait behind a size button');
  const curveRows = nodesWhere(root, (n) => hasClass(n, 'cv-n')).map((n) => String(n.textContent));
  if (curveRows.join(',') !== sizes.slice().sort((a, b) => a - b).map((n) => 'N=' + n.toLocaleString('en-US')).join(',')) {
    throw new Error(`the curves are not a row a size, the smallest first: ${curveRows}`);
  }
  if (nodesWhere(root, (n) => hasClass(n, 'cv-cell')).length !== CURVE_KINDS.length * sizes.length) throw new Error('the curves are not drawn four a size');
  const h2 = nodesWhere(root, (n) => n.tagName === 'H2');
  if (h2.map((n) => n.attributes['data-letter']).join('') !== 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.slice(0, h2.length)) {
    throw new Error(`the sections are not lettered A to Z in order: ${h2.map((n) => n.attributes['data-letter'])}`);
  }
  const letter = h2[chainsAt].attributes['data-letter'];
  const section = nodesWhere(root, (n) => n.attributes && n.attributes.id === 'twoChains')[0];
  const plots = nodesWhere(section, (n) => hasClass(n, 'tc-chart'));
  const grid = plots.filter((n) => n.attributes['data-quantity']);
  if (grid.map((n) => n.attributes['data-num']).join(',') !== Array.from({ length: 16 }, (_, i) => letter + (i + 1)).join(',')) {
    throw new Error(`the grid is not numbered ${letter}1 to ${letter}16: ${grid.map((n) => n.attributes['data-num'])}`);
  }
  const badge = nodesWhere(grid[0], (n) => hasClass(n, 'pg-num'))[0];
  if (!badge || String(badge.textContent) !== letter + '1' || !String(badge.attributes.title || '').includes('mean degree')) {
    throw new Error('a plot does not carry its number, with what it draws on the number');
  }
  const tableHead = nodesWhere(tableOf(root), (n) => n.tagName === 'TH')[0];
  if (tableHead.attributes['data-num'] !== letter + '17') throw new Error(`the table is not numbered after the grid: ${tableHead.attributes['data-num']}`);
  const curveCells = plots.filter((n) => hasClass(n, 'cv-cell'));
  if (curveCells[0].attributes['data-num'] !== letter + '18' || curveCells[curveCells.length - 1].attributes['data-num'] !== letter + (17 + curveCells.length)) {
    throw new Error('the curves are not numbered after the table, row by row');
  }
  if (!curveCells.every((c) => (c._tips || []).length && c._tips.every((t) => /, seed \d+$/.test(t.head) && /^N=[\d,]+$/.test(t.lines[0])))) {
    throw new Error('a curve’s mouse-over does not name its start, its seed and its size');
  }
  structureStatus = 404;
  const bare = await draw();
  const bareRows = nodesWhere(bare, (n) => n.tagName === 'TR' && hasClass(n, 'rung-chain'));
  if (bareRows.length !== sizes.length || bareRows.some((r) => String(r.children.find((c) => hasClass(c, 'ec-chain')).textContent) !== 'empty')) {
    throw new Error('without the readings the rungs are not drawn from what the page holds');
  }
  if (!String(bare.textContent).includes('every chain’s reading is unavailable')) throw new Error('readings that fail are not said');
  if (!String(bare.textContent).includes('4.00e-3')) throw new Error('without the readings the census the page holds is not drawn');
}

retryChecks().catch((error) => failures.push(`a busy answer is asked again: ${error && error.message}`))
  .then(() => pageChecks())
  .catch((error) => failures.push(`the whole page, every chain alike: ${error && error.message}`)).then(() => {
  if (failures.length) {
    console.log('FAIL');
    failures.forEach((line) => console.log(line));
    process.exit(1);
  }
  console.log('OK');
});
