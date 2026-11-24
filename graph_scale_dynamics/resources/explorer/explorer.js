(function () {
  'use strict';

  const finite = Number.isFinite;
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
        else if (k === 'style') e.style.cssText = v;
        else if (k === 'value') e.value = v;
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }
  function fmt(v, d) {
    if (v == null || !finite(v)) return '';
    const a = Math.abs(v);
    if (a >= 10000) return Math.round(v).toLocaleString('en-US');
    if (a >= 100) return String(+v.toFixed(1));
    if (a > 0 && a < 0.001) return v.toExponential(2);
    return String(+v.toFixed(d == null ? 3 : d));
  }
  const fmtInt = (v) => (finite(v) ? Math.round(v).toLocaleString('en-US') : '');
  const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : '');
  function fmtN(n) {
    if (!finite(n)) return '';
    if (n >= 1048576 && n % 1048576 === 0) return `${n / 1048576}M`;
    if (n >= 1024 && n % 1024 === 0) return `${n / 1024}k`;
    return String(n);
  }
  function quantile(sorted, q) {
    const n = sorted.length;
    if (!n) return NaN;
    const at = q * (n - 1), lo = Math.floor(at), hi = Math.min(n - 1, lo + 1);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo);
  }
  function sortedOf(values) { return Float64Array.from(values).sort(); }
  function debounce(fn, ms) {
    let t = 0;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }
  function hexRgb(hex) {
    const s = hex.replace('#', '');
    return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
  }
  function packed(rgb, alpha) {
    return (((alpha == null ? 255 : alpha) << 24) | (rgb[2] << 16) | (rgb[1] << 8) | rgb[0]) >>> 0;
  }
  function mix(a, b, t) { return [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t)); }
  const RAMP = ['#2c5bd6', '#1f8fc4', '#14a3a3', '#4caf50', '#a5b22c', '#e0a800', '#f07d1a', '#e0482a', '#b71c3c']
    .map(hexRgb);
  function ramp(t) {
    const x = Math.max(0, Math.min(1, t)) * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(x));
    return mix(RAMP[i], RAMP[i + 1], x - i);
  }
  const PALETTE = ['#4e79a7', '#f28e2b', '#e15759', '#59a14f', '#b07aa1', '#76b7b2', '#edc948', '#ff9da7',
    '#9c755f', '#3b8bd0', '#8cd17d', '#d37295'].map(hexRgb);
  const css = (rgb, a) => (a == null ? `rgb(${rgb.join(',')})` : `rgba(${rgb.join(',')},${a})`);
  function theme() {
    const s = getComputedStyle(document.documentElement);
    const get = (name) => s.getPropertyValue(name).trim() || '#888888';
    const t = { panel: get('--panel'), plot: get('--plot'), ink: get('--ink'), ink2: get('--ink-2'),
      muted: get('--muted'), line: get('--line'), grid: get('--grid'), accent: get('--accent'), warn: get('--warn'),
      select: get('--select') };
    t.dark = (document.documentElement.dataset.theme === 'dark')
      || (document.documentElement.dataset.theme !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
    t.mutedRgb = t.dark ? [74, 74, 82] : [196, 196, 204];
    return t;
  }
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type: type || 'text/csv' }));
    const a = h('a', { href: url, download: name });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }
  function csvOf(header, rows) {
    const cell = (v) => {
      const s = v == null ? '' : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    return [header, ...rows].map((r) => r.map(cell).join(',')).join('\n') + '\n';
  }

  async function decode() {
    const node = document.getElementById('explorer-data');
    const text = atob(node.textContent.trim());
    const bytes = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('this browser cannot unpack the data (no DecompressionStream): open it in a current Chrome, '
        + 'Edge, Firefox or Safari');
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
  }

  const PROBES = ['d_s', 'd_V', 'd_B', 'd_w'];
  const DIMENSIONS = new Set(['d_s', 'd_V', 'd_B', 'd_w', 'walk_ds', 'walk_ds_B', 'given_d_s', 'from_empty_implied',
    'given_implied']);
  let D = null;
  const M = {};

  function buildModel(raw) {
    D = raw;
    const n = raw.rows.law.length;
    M.nRows = n;
    M.rowLaw = Int32Array.from(raw.rows.law);
    M.col = {};
    for (const f of raw.row_fields) {
      const src = raw.rows[f.key], a = new Float64Array(n);
      for (let i = 0; i < n; i++) a[i] = src[i] == null ? NaN : src[i];
      M.col[f.key] = a;
    }
    M.campaigns = raw.campaigns.map((c, i) => ({ ...c, index: i, color: PALETTE[i % PALETTE.length],
      regime: c.zero_temperature === true ? 'zero temperature' : c.zero_temperature === false
        ? 'finite temperature' : c.zero_temperature === 'drawn' ? 'drawn a law' : 'not set',
      short: `C${c.id}` }));
    const lawZero = (raw.laws && raw.laws.zero) || [];
    M.rowZero = (i) => {
      const own = lawZero[M.rowLaw[i]];
      return own === true || own === false ? own : M.campaigns[M.rowCampaign[i]].zero_temperature;
    };
    for (const c of M.campaigns) {
      c.tag = c.regime === 'zero temperature' ? `${c.short} T0${finite(c.cap) ? ` k to ${c.cap}` : ''}`
        : c.regime === 'finite temperature' ? `${c.short} T>0${finite(c.cap) ? ` k to ${c.cap}` : ''}`
          : c.regime === 'drawn a law' ? `${c.short} T drawn${finite(c.cap) ? ` k to ${c.cap}` : ''}`
          : `${c.short} ${String(c.label || '').replace(/^campaign-/, '')}`;
    }
    M.nLaws = (raw.laws.campaign || []).length;
    M.lawCampaign = Int32Array.from(raw.laws.campaign || []);
    M.rowCampaign = new Int32Array(n);
    for (let i = 0; i < n; i++) M.rowCampaign[i] = M.lawCampaign[M.rowLaw[i]];
    M.rowRegime = new Int8Array(n);
    for (let i = 0; i < n; i++) { const z = M.rowZero(i); M.rowRegime[i] = z === true ? 0 : z === false ? 1 : 2; }
    M.rungs = [...new Set(M.col.n)].filter(finite).sort((a, b) => a - b);
    M.rungAt = new Map(M.rungs.map((v, i) => [v, i]));
    M.rowRung = new Int16Array(n);
    for (let i = 0; i < n; i++) M.rowRung[i] = M.rungAt.get(M.col.n[i]);
    M.rungColor = M.rungs.map((_, i) => ramp(M.rungs.length > 1 ? i / (M.rungs.length - 1) : 0.5));
    const fewest = (raw.rules || {}).ceiling_min_laws ?? 100;
    M.ceiling = M.rungs.map((v) => { const c = (raw.ceiling || {})[String(v)] || {}; return c.laws >= fewest ? c.max : NaN; });
    M.order = Int32Array.from({ length: n }, (_, i) => i).sort((a, b) => M.rowRung[a] - M.rowRung[b] || a - b);
    M.lawRows = Array.from({ length: M.nLaws }, () => []);
    for (let i = 0; i < n; i++) M.lawRows[M.rowLaw[i]].push(i);
    for (const rows of M.lawRows) rows.sort((a, b) => M.col.n[a] - M.col.n[b]);
    derive();
    fields();
  }

  function derive() {
    const c = M.col, n = M.nRows, rules = D.rules || {};
    const make = (key, fn) => {
      const a = new Float64Array(n);
      for (let i = 0; i < n; i++) a[i] = fn(i);
      c[key] = a;
    };
    M.derived = [];
    const add = (key, label, what, need, fn) => {
      if (need.every((k) => c[k])) { make(key, fn); M.derived.push({ key, label, what }); }
    };
    add('ds_dV', 'd_s - d_V', 'how far the walk and the volume disagree', ['d_s', 'd_V'], (i) => c.d_s[i] - c.d_V[i]);
    add('ds_dB', 'd_s - d_B', 'how far the walk and the boxes disagree', ['d_s', 'd_B'], (i) => c.d_s[i] - c.d_B[i]);
    add('walk_ds', '2 d_V / d_w', 'the d_s the walk relation gives from the volume and the walk (d_s = 2 d_f / d_w); '
      + 'where the probes agree with each other a law sits on the diagonal against d_s', ['d_V', 'd_w'],
    (i) => (c.d_w[i] > 0 ? (2 * c.d_V[i]) / c.d_w[i] : NaN));
    add('walk_ds_B', '2 d_B / d_w', 'the walk relation from the boxes', ['d_B', 'd_w'],
      (i) => (c.d_w[i] > 0 ? (2 * c.d_B[i]) / c.d_w[i] : NaN));
    add('ceiling_share', 'd_s / ceiling', "d_s over the largest d_s any law read at its N (the probe's ceiling)",
      ['d_s'], (i) => c.d_s[i] / (M.ceiling[M.rowRung[i]] || NaN));
    add('k_frac', 'k off a whole number', 'how far the mean degree is from the nearest whole number', ['k'],
      (i) => c.k[i] - Math.round(c.k[i]));
    if (c.k) {
      const regimeOf = M.rowRegime;
      for (const [key, short] of [['d_s', 'd_s'], ['d_V', 'd_V'], ['d_B', 'd_B'], ['d_w', 'd_w'], ['kappa', 'curvature']]) {
        if (!c[key]) continue;
        const groups = new Map();
        for (let i = 0; i < n; i++) {
          if (!finite(c[key][i]) || !finite(c.k[i])) continue;
          const g = `${M.rowRung[i]}|${regimeOf[i]}|${Math.round(c.k[i] * 4)}`;
          if (!groups.has(g)) groups.set(g, []);
          groups.get(g).push(c[key][i]);
        }
        const median = new Map();
        for (const [g, values] of groups) if (values.length >= 5) median.set(g, quantile(sortedOf(values), 0.5));
        add(`${key}_beyond_k`, `${short} beyond k`, `${short} less the median ${short} of the readings at the same mean degree `
          + '(to 0.25), N and temperature: what the degree does not explain (at least five readings a group)', [key, 'k'], (i) => {
          const m = median.get(`${M.rowRung[i]}|${regimeOf[i]}|${Math.round(c.k[i] * 4)}`);
          return m === undefined ? NaN : c[key][i] - m;
        });
      }
    }
    const whole = rules.whole ?? 0.02, atCeiling = rules.at_ceiling ?? 0.9;
    M.whole = new Int8Array(n);
    M.atCeil = new Int8Array(n);
    for (let i = 0; i < n; i++) {
      const s = c.d_s ? c.d_s[i] : NaN, k = c.k ? c.k[i] : NaN;
      if (finite(k)) M.whole[i] = Math.abs(k - Math.round(k)) <= whole ? 1 : 2;
      const top = M.ceiling[M.rowRung[i]];
      if (finite(s) && finite(top)) M.atCeil[i] = s >= atCeiling * top ? 1 : 2;
    }
  }

  function fields() {
    const num = [];
    for (const f of D.row_fields) num.push({ key: f.key, label: f.label, what: f.what, scope: 'row' });
    for (const f of M.derived) num.push({ ...f, scope: 'row' });
    const lawNumbers = ['beta', 'locality', 'swap', 'sweeps', 'fate_n', 'top_n', 'from_empty_implied',
      'given_implied', 'nearest_distance'];
    for (const f of D.law_fields) {
      if (!lawNumbers.includes(f.key)) continue;
      const src = D.laws[f.key], a = new Float64Array(M.nRows);
      for (let i = 0; i < M.nRows; i++) { const v = src[M.rowLaw[i]]; a[i] = v == null ? NaN : +v; }
      M.col[`law.${f.key}`] = a;
      num.push({ key: `law.${f.key}`, label: f.label, what: `${f.what} (the law's)`, scope: 'law' });
    }
    M.numbers = num.filter((f) => M.col[f.key]);
    M.numberOf = new Map(M.numbers.map((f) => [f.key, f]));
    const cats = [];
    const fromRows = (key, label, what, values, codeOf, colors) => {
      cats.push({ key, label, what, values, code: codeOf, colors });
    };
    fromRows('rung', 'N', 'the rung', M.rungs.map((v) => v.toLocaleString('en-US')), M.rowRung, M.rungColor);
    fromRows('campaign', 'campaign', 'the campaign', M.campaigns.map((c) => c.tag), M.rowCampaign,
      M.campaigns.map((c) => c.color));
    const regimes = ['zero temperature', 'finite temperature', 'not set'];
    const rowRegime = M.rowRegime;
    fromRows('regime', 'temperature', 'zero or finite temperature (the law\'s own, else its campaign\'s)', regimes, rowRegime,
      [hexRgb('#2c5bd6'), hexRgb('#e0702a'), [140, 140, 150]]);
    fromRows('whole', 'whole degree', 'a whole-number mean degree (a regular graph)', ['unread', 'whole', 'not whole'],
      M.whole, [[140, 140, 150], hexRgb('#4e79a7'), hexRgb('#f28e2b')]);
    fromRows('ceiling', "probe's ceiling", "d_s at the probe's ceiling for its N, or under it",
      ['unread', 'at the ceiling', 'under it'], M.atCeil, [[140, 140, 150], hexRgb('#e15759'), hexRgb('#4e79a7')]);
    for (const key of ['cls', 'conn', 'fate', 'kind', 'move', 'role', 'start', 'from_empty_top', 'given_top', 'label',
      'nearest']) {
      const src = D.laws[key];
      if (!src) continue;
      const counts = new Map();
      for (const v of src) counts.set(v == null ? '(none)' : String(v), (counts.get(v == null ? '(none)' : String(v)) || 0) + 1);
      if (counts.size < 2 && !counts.has('(none)')) continue;
      const values = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || (a < b ? -1 : 1));
      const at = new Map(values.map((v, i) => [v, i]));
      const lawCode = Int32Array.from(src, (v) => at.get(v == null ? '(none)' : String(v)));
      const rowCode = new Int32Array(M.nRows);
      for (let i = 0; i < M.nRows; i++) rowCode[i] = lawCode[M.rowLaw[i]];
      const f = D.law_fields.find((x) => x.key === key) || { label: key, what: '' };
      fromRows(key, f.label, f.what, values, rowCode,
        values.map((v, i) => (v === '(none)' ? [140, 140, 150] : PALETTE[i % PALETTE.length])));
      cats[cats.length - 1].lawCode = lawCode;
      cats[cats.length - 1].lawCounts = values.map((v) => counts.get(v));
    }
    M.cats = cats;
    M.catOf = new Map(cats.map((c) => [c.key, c]));
    const L = D.laws;
    M.search = Array.from({ length: M.nLaws }, (_, i) => [L.id && L.id[i], L.label && L.label[i],
      ...((L.terms && L.terms[i]) || []).map((t) => t[0])].filter(Boolean).join(' ').toLowerCase());
  }
  const labelOf = (key) => (M.numberOf.get(key) || M.catOf.get(key) || { label: key }).label;
  const pretty = (v) => (/^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$/.test(String(v)) ? String(v).toLowerCase().replace(/_/g, ' ') : String(v));
  function termsText(terms) {
    if (!terms) return '';
    return terms.map(([op, k, c0, scale, p]) => `${op}${k != null ? `(${k})` : ''} ${c0 >= 0 ? '+' : ''}${fmt(c0, 3)}`
      + `${scale && scale !== 'one' ? ` ${scale}` : ''}${p != null ? ` ^${p}` : ''}`).join('; ');
  }

  const S = {
    page: 'maps', active: 0,
    f: { campaigns: null, rungs: null, whole: 'any', ceiling: 'any', cats: {}, search: '', ranges: [],
      only: null },
    maps: { rows: 4, cols: 4, size: 2, fit: false, panels: [] },
    byn: { x: 'd_s', y: 'd_V', color: 'campaign', camps: null, split: 'together', trend: 'none', range: 'std' },
    spread: { y: 'd_s', paths: true, dots: true, bands: true, together: false, range: 'std' },
    curves: { x: 'd_s', y: 'd_V', method: 'median', degree: 2 },
    laws: { sort: 'n_top', dir: -1, page: 0, open: -1 },
    scan: { by: 'regime', min: 50, tied: false },
    focus: null,
    theme: 'auto',
  };
  let SEL = new Uint8Array(0);
  let selCount = 0;
  let MASK = new Uint8Array(0);
  let maskCount = 0;

  function defaultPanels() {
    const pairs = ['d_V', 'd_B', 'd_w', 'k'].filter((k) => M.col[k]).map((y) => ['d_s', y]);
    S.maps.pairs = pairs;
    return gridOf(pairs, 'rung', M.campaigns.map((c) => c.index));
  }
  function panelSpec(o) {
    return { x: 'd_s', y: 'd_V', color: 'rung', camp: -1, rung: null, range: 'std', xmin: null, xmax: null,
      ymin: null, ymax: null, xlog: false, ylog: false, refs: true, fam: true, papers: true, trend: 'none', mine: false, ...o };
  }

  function panelKey(p) { return `${p.x}|${p.y}|${p.camp}|${p.rung ?? ''}|${p.regime ?? ''}`; }
  function rangeFor(x, y) { return (DIMENSIONS.has(x) || x === 'k') && (DIMENSIONS.has(y) || y === 'k') ? 'std' : 'data'; }
  function pairPool(first) {
    const out = [], seen = new Set();
    const add = (x, y) => {
      const key = `${x}|${y}`;
      if (x !== y && M.col[x] && M.col[y] && !seen.has(key)) { seen.add(key); out.push([x, y]); }
    };
    for (const [x, y] of first || []) add(x, y);
    for (const y of [...PROBES, 'k', 'kappa']) add('d_s', y);
    for (const y of PROBES) add('k', y);
    for (let i = 1; i < PROBES.length; i++) for (let j = i + 1; j < PROBES.length; j++) add(PROBES[i], PROBES[j]);
    for (const f of M.numbers) add('d_s', f.key);
    for (const f of M.numbers) add('k', f.key);
    return out;
  }
  function columnCamps(camps) {
    const cols = camps.length > 1 ? camps.slice(0, 4) : [camps.length ? camps[0] : -1];
    if (camps.length > 1 && cols.length < 4) cols.push(-1);
    while (cols.length < 4) cols.push(cols[cols.length - 1]);
    return cols;
  }
  function gridOf(pairs, color, camps, range) {
    const cols = columnCamps(camps);
    const out = [];
    for (let r = 0; r < 4; r++) {
      for (let c = 0; c < 4; c++) {
        const pair = pairs[r];
        const [x, y] = pair ? [M.col[pair[0]] ? pair[0] : 'd_s', M.col[pair[1]] ? pair[1] : 'd_V'] : ['', ''];
        out.push(panelSpec({ x, y, color: color && (M.catOf.get(color) || M.col[color]) ? color : 'rung',
          range: range ? range(pair) : rangeFor(x, y), camp: cols[c] }));
      }
    }
    return out;
  }
  function distinctPanels(mp) {
    const shown = new Set();
    const pool = pairPool(mp.pairs);
    for (let r = 0; r < mp.rows; r++) {
      for (let c = 0; c < mp.cols; c++) {
        const at = r * 4 + c;
        let p = mp.panels[at];
        if (!p) {
          const above = mp.panels[c];
          p = mp.panels[at] = panelSpec({ x: '', y: '', camp: above ? above.camp : -1, color: above ? above.color : 'rung' });
        }
        if (!p.mine && (!p.x || !p.y || shown.has(panelKey(p)))) {
          const free = pool.find(([x, y]) => !shown.has(panelKey({ ...p, x, y })));
          if (free) { p.x = free[0]; p.y = free[1]; p.range = rangeFor(free[0], free[1]); }
          else if (!p.x || !p.y) { p.x = 'd_s'; p.y = 'd_V'; }
        }
        shown.add(panelKey(p));
      }
    }
  }

  function computeMask() {
    const F = S.f, n = M.nRows;
    const campOk = new Uint8Array(M.campaigns.length).fill(1);
    if (F.campaigns) M.campaigns.forEach((c, i) => { campOk[i] = F.campaigns.includes(i) ? 1 : 0; });
    const rungOk = new Uint8Array(M.rungs.length).fill(1);
    if (F.rungs) M.rungs.forEach((v, i) => { rungOk[i] = F.rungs.includes(v) ? 1 : 0; });
    const lawOk = new Uint8Array(M.nLaws).fill(1);
    const q = (F.search || '').trim().toLowerCase();
    if (q) {
      const words = q.split(/\s+/);
      for (let l = 0; l < M.nLaws; l++) if (!words.every((w) => M.search[l].includes(w))) lawOk[l] = 0;
    }
    if (F.only) {
      const keep = new Set(F.only);
      for (let l = 0; l < M.nLaws; l++) if (!keep.has(D.laws.id[l])) lawOk[l] = 0;
    }
    const rowCats = [];
    for (const [key, allowed] of Object.entries(F.cats || {})) {
      const cat = M.catOf.get(key);
      if (!cat || !allowed) continue;
      const ok = new Uint8Array(cat.values.length);
      for (const v of allowed) { const at = cat.values.indexOf(v); if (at >= 0) ok[at] = 1; }
      if (cat.lawCode) { for (let l = 0; l < M.nLaws; l++) if (!ok[cat.lawCode[l]]) lawOk[l] = 0; } else rowCats.push([cat.code, ok]);
    }
    if (F.whole !== 'any') rowCats.push([M.whole, F.whole === 'whole' ? Uint8Array.of(0, 1, 0) : Uint8Array.of(0, 0, 1)]);
    if (F.ceiling !== 'any') rowCats.push([M.atCeil, F.ceiling === 'at' ? Uint8Array.of(0, 1, 0) : Uint8Array.of(0, 0, 1)]);
    const ranges = (F.ranges || []).filter((r) => M.col[r.key] && (finite(r.min) || finite(r.max)))
      .map((r) => [M.col[r.key], finite(r.min) ? r.min : -Infinity, finite(r.max) ? r.max : Infinity]);
    const mask = new Uint8Array(n);
    let count = 0;
    outer: for (let i = 0; i < n; i++) {
      if (!lawOk[M.rowLaw[i]] || !rungOk[M.rowRung[i]] || !campOk[M.rowCampaign[i]]) continue;
      for (const [code, ok] of rowCats) if (!ok[code[i]]) continue outer;
      for (const [col, lo, hi] of ranges) { const v = col[i]; if (!(v >= lo && v <= hi)) continue outer; }
      mask[i] = 1;
      count++;
    }
    MASK = mask;
    maskCount = count;
    let laws = 0;
    const seen = new Uint8Array(M.nLaws);
    for (let i = 0; i < n; i++) if (mask[i] && !seen[M.rowLaw[i]]) { seen[M.rowLaw[i]] = 1; laws++; }
    M.lawVisible = seen;
    M.visibleLaws = laws;
  }

  function setSelection(laws, how) {
    if (how === 'replace') SEL.fill(0);
    for (const l of laws) SEL[l] = how === 'remove' ? 0 : 1;
    selCount = 0;
    for (let l = 0; l < M.nLaws; l++) selCount += SEL[l];
    onSelection();
  }

  function niceStep(span, count) {
    const raw = span / Math.max(1, count), p = 10 ** Math.floor(Math.log10(raw)), r = raw / p;
    return (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * p;
  }
  function ticksOf(lo, hi, log, key, count) {
    if (log) {
      const out = [];
      const base = key === 'n' ? 4 : 10;
      const a = Math.floor(Math.log(lo) / Math.log(base)), b = Math.ceil(Math.log(hi) / Math.log(base));
      for (let e = a; e <= b; e++) { const v = base ** e; if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v); }
      return out.length >= 2 ? out : [lo, hi];
    }
    const step = niceStep(hi - lo, count || 5), out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function scale(lo, hi, log, a, b) {
    if (log) {
      const l0 = Math.log10(lo), l1 = Math.log10(hi);
      return (v) => a + ((Math.log10(Math.max(v, lo * 1e-6)) - l0) / (l1 - l0 || 1)) * (b - a);
    }
    return (v) => a + ((v - lo) / (hi - lo || 1)) * (b - a);
  }
  const tickLabel = (v, key) => (key === 'n' ? fmtN(v) : fmt(v, 2));
  function capOf(camp) {
    const caps = (camp >= 0 ? [M.campaigns[camp]] : M.campaigns).map((c) => c.cap).filter(finite);
    return caps.length ? Math.max(...caps) : 16;
  }
  function rangeOf(spec, axis, values, idx) {
    const key = spec[axis], log = spec[`${axis}log`];
    if (spec.range === 'custom') {
      const lo = spec[`${axis}min`], hi = spec[`${axis}max`];
      if (finite(lo) && finite(hi) && hi > lo && (!log || lo > 0)) return [lo, hi];
    }
    if (spec.range !== 'data' && !log) {
      if (DIMENSIONS.has(key)) return [0, 8];
      if (key === 'k') return [0, Math.max(8, capOf(spec.camp))];
    }
    const pick = [];
    for (const i of idx) { const v = values[i]; if (finite(v) && (!log || v > 0)) pick.push(v); }
    if (!pick.length) return log ? [1, 10] : [0, 1];
    const s = sortedOf(pick);
    let lo = quantile(s, spec.range === 'data' ? 0.002 : 0.005), hi = quantile(s, spec.range === 'data' ? 0.998 : 0.995);
    if (key === 'n') { lo = s[0]; hi = s[s.length - 1]; }
    if (log) {
      if (lo <= 0) lo = s.find((v) => v > 0) || 1;
      if (hi <= lo) hi = lo * 10;
      return [lo / 1.15, hi * 1.15];
    }
    if (hi <= lo) { hi = lo + 1; lo -= 1; }
    const pad = (hi - lo) * 0.04;
    return [lo - pad, hi + pad];
  }

  const colorCache = new Map();
  function rowColors(key, T) {
    const cacheKey = `${key}|${T.dark}`;
    if (colorCache.has(cacheKey)) return colorCache.get(cacheKey);
    const out = new Uint32Array(M.nRows);
    const cat = M.catOf.get(key);
    let legend = [];
    if (cat) {
      const words = cat.colors.map((rgb) => packed(rgb));
      for (let i = 0; i < M.nRows; i++) out[i] = words[cat.code[i]] ?? words[0];
      legend = cat.values.slice(0, 14).map((v, i) => ({ label: v, rgb: cat.colors[i] }));
    } else if (M.col[key]) {
      const col = M.col[key], pick = [];
      for (let i = 0; i < M.nRows; i++) if (finite(col[i])) pick.push(col[i]);
      const s = sortedOf(pick), lo = quantile(s, 0.02), hi = quantile(s, 0.98);
      const grey = packed([140, 140, 150]);
      for (let i = 0; i < M.nRows; i++) {
        const v = col[i];
        out[i] = finite(v) ? packed(ramp(hi > lo ? (v - lo) / (hi - lo) : 0.5)) : grey;
      }
      legend = [{ label: `${fmt(lo)}`, rgb: ramp(0) }, { label: `${fmt((lo + hi) / 2)}`, rgb: ramp(0.5) },
        { label: `${fmt(hi)}`, rgb: ramp(1) }];
    }
    const result = { words: out, legend };
    colorCache.set(cacheKey, result);
    return result;
  }

  const PANELS = [];
  const tip = h('div', { class: 'tip', hidden: true });

  const EXPAND = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';
  const COLLAPSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 2v4H2M14 6h-4V2M10 14v-4h4M2 10h4v4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';
  function sizeButton(opts) {
    if (!opts.focusKey) return null;
    const b = h('button', { class: 'pmax', type: 'button', title: opts.focused ? 'back to the grid (Esc)' : 'fill the page with this panel',
      'aria-label': opts.focused ? 'back to the grid' : 'fill the page with this panel',
      onclick: () => (opts.focused ? unfocus() : focusOn(opts.focusKey)) });
    b.innerHTML = opts.focused ? `${COLLAPSE}<span>back to the grid</span>` : EXPAND;
    return b;
  }
  function focusOn(key) { S.focus = { page: S.page, key: String(key) }; tip.hidden = true; renderPage(); save(); }
  function unfocus() {
    const back = S.focus && S.focus.back;
    S.focus = null;
    tip.hidden = true;
    if (back) { go(back); return; }
    renderPage();
    save();
  }
  const focusedHere = () => (S.focus && S.focus.page === S.page ? S.focus.key : null);
  function focusHeight(el) {
    const top = el.getBoundingClientRect().top + window.scrollY;
    return Math.max(380, Math.floor(window.innerHeight - top - 70));
  }

  function makeScatter(spec, opts) {
    const base = h('canvas', { class: 'base' }), over = h('canvas', { class: 'over', 'aria-label': 'drag to select' });
    const titleBtn = h('button', { class: 'ptitle', type: 'button', title: 'this panel\'s settings' });
    const count = h('span', { class: 'pcount' });
    const foot = h('div', { class: 'pfoot' });
    const plot = h('div', { class: 'plot', style: opts.height ? `height:${opts.height}px` : 'aspect-ratio: 4 / 3' });
    plot.append(base, over);
    const el = h('div', { class: `panel${opts.active ? ' active' : ''}${opts.focused ? ' focused' : ''}` },
      h('div', { class: 'phead' }, titleBtn, count, sizeButton(opts)), plot, foot);
    const P = { kind: 'scatter', spec, el, base, over, plot, titleBtn, count, foot, view: null, opts };
    titleBtn.addEventListener('click', () => opts.onActivate && opts.onActivate(P));
    wireBrush(P);
    PANELS.push(P);
    return P;
  }

  const shortOf = (key) => labelOf(key).replace(/\s\([a-z][a-z -]*\)$/i, '');
  function panelTitle(spec) {
    const camps = spec.camps || (spec.camp >= 0 ? [spec.camp] : null);
    const where = (!camps ? 'every campaign' : camps.length === 1 ? M.campaigns[camps[0]].tag
      : camps.map((c) => M.campaigns[c].short).join(', '))
      + (spec.regime != null ? `, ${['zero temperature', 'finite temperature', 'not set'][spec.regime]}` : '');
    const pair = `${shortOf(spec.y)} against ${shortOf(spec.x)}`;
    return spec.rung != null ? `N ${fmtInt(spec.rung)}${camps ? ` · ${where}` : ''} · ${pair}` : `${pair} · ${where}`;
  }

  function visibleRows(spec, X, Y) {
    const idx = [];
    const rungAt = spec.rung != null ? M.rungAt.get(spec.rung) : -1;
    const camps = spec.camps || (spec.camp >= 0 ? [spec.camp] : null);
    for (let i = 0; i < M.nRows; i++) {
      if (!MASK[i]) continue;
      if (rungAt >= 0 && M.rowRung[i] !== rungAt) continue;
      if (camps && !camps.includes(M.rowCampaign[i])) continue;
      if (spec.regime != null && M.rowRegime[i] !== spec.regime) continue;
      const x = X[i], y = Y[i];
      if (!finite(x) || !finite(y) || (spec.xlog && x <= 0) || (spec.ylog && y <= 0)) continue;
      idx.push(i);
    }
    return idx;
  }

  function drawScatter(P) {
    const spec = P.spec, T = theme();
    const rect = P.plot.getBoundingClientRect();
    const W = Math.max(80, Math.floor(rect.width)), H = Math.max(80, Math.floor(rect.height));
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    for (const c of [P.base, P.over]) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const ctx = P.base.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = T.panel;
    ctx.fillRect(0, 0, W, H);
    P.titleBtn.textContent = panelTitle(spec);
    P.titleBtn.title = `${panelTitle(spec)}: click for this panel's settings`;
    const X = M.col[spec.x], Y = M.col[spec.y];
    if (!X || !Y) {
      ctx.fillStyle = T.muted;
      ctx.fillText('this study has no such field', 12, 20);
      P.view = null;
      return;
    }
    const idx = visibleRows(spec, X, Y);
    const xr = rangeOf(spec, 'x', X, idx), yr = rangeOf(spec, 'y', Y, idx);
    const m = { l: 42, r: 10, t: 8, b: 30 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
    const sx = scale(xr[0], xr[1], spec.xlog, m.l, m.l + pw), sy = scale(yr[0], yr[1], spec.ylog, m.t + ph, m.t);
    ctx.fillStyle = T.plot;
    ctx.fillRect(m.l, m.t, pw, ph);
    ctx.font = '10px Inter, system-ui, sans-serif';
    ctx.lineWidth = 1;
    ctx.strokeStyle = T.grid;
    ctx.fillStyle = T.muted;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const v of ticksOf(xr[0], xr[1], spec.xlog, spec.x, Math.max(3, Math.round(pw / 70)))) {
      const x = Math.round(sx(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, m.t); ctx.lineTo(x, m.t + ph); ctx.stroke();
      ctx.fillText(tickLabel(v, spec.x), x, m.t + ph + 3);
    }
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const v of ticksOf(yr[0], yr[1], spec.ylog, spec.y, Math.max(3, Math.round(ph / 45)))) {
      const y = Math.round(sy(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(m.l, y); ctx.lineTo(m.l + pw, y); ctx.stroke();
      ctx.fillText(tickLabel(v, spec.y), m.l - 4, y);
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = T.ink2;
    ctx.fillText(labelOf(spec.x), m.l + pw / 2, H - 1);
    ctx.save();
    ctx.translate(10, m.t + ph / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = 'middle';
    ctx.fillText(labelOf(spec.y), 0, 0);
    ctx.restore();
    const ix = Math.round(m.l * dpr), iy = Math.round(m.t * dpr), iw = Math.round(pw * dpr), ih = Math.round(ph * dpr);
    const img = new ImageData(iw, ih), buf = new Uint32Array(img.data.buffer);
    const xs = new Float32Array(idx.length), ys = new Float32Array(idx.length);
    const vis = new Uint8Array(M.nRows);
    const clampX = (v) => Math.min(m.l + pw - 0.5, Math.max(m.l + 0.5, v));
    const clampY = (v) => Math.min(m.t + ph - 0.5, Math.max(m.t + 0.5, v));
    let outside = 0;
    idx.forEach((i, j) => {
      vis[i] = 1;
      const x = sx(X[i]), y = sy(Y[i]);
      if (x < m.l || x > m.l + pw || y < m.t || y > m.t + ph) outside++;
      xs[j] = clampX(x); ys[j] = clampY(y);
    });
    const pos = new Map();
    idx.forEach((i, j) => pos.set(i, j));
    const crowd = idx.length < 400 ? 2 : idx.length < 4000 ? 1 : 0;
    const size = Math.max(1, Math.round(((S.maps.size || 2) + crowd) * dpr * 0.75));
    const put = (j, word, s) => {
      const px = Math.round((xs[j] - m.l) * dpr) - (s >> 1), py = Math.round((ys[j] - m.t) * dpr) - (s >> 1);
      for (let yy = Math.max(0, py); yy < Math.min(ih, py + s); yy++) {
        const row = yy * iw;
        for (let xx = Math.max(0, px); xx < Math.min(iw, px + s); xx++) buf[row + xx] = word;
      }
    };
    let legend = [];
    if (spec.color === 'density') {
      const counts = new Uint32Array(iw * ih);
      let top = 0;
      for (let j = 0; j < idx.length; j++) {
        const px = Math.round((xs[j] - m.l) * dpr), py = Math.round((ys[j] - m.t) * dpr);
        if (px < 0 || py < 0 || px >= iw || py >= ih) continue;
        const at = py * iw + px, c = ++counts[at];
        if (c > top) top = c;
      }
      const lt = Math.log(1 + top) || 1;
      for (let at = 0; at < counts.length; at++) {
        if (!counts[at]) continue;
        const word = packed(ramp(Math.log(1 + counts[at]) / lt));
        const py = Math.floor(at / iw), px = at % iw;
        for (let yy = py; yy < Math.min(ih, py + size); yy++) for (let xx = px; xx < Math.min(iw, px + size); xx++) buf[yy * iw + xx] = word;
      }
      legend = [{ label: '1 reading', rgb: ramp(0) }, { label: `${fmtInt(top)} a pixel`, rgb: ramp(1) }];
    } else {
      const colors = rowColors(spec.color, T);
      legend = colors.legend;
      const muted = packed(T.mutedRgb);
      for (const i of M.order) {
        if (!vis[i]) continue;
        const selected = selCount && SEL[M.rowLaw[i]];
        if (selCount && selected) continue;
        put(pos.get(i), selCount ? muted : colors.words[i], size);
      }
      if (selCount) {
        for (const i of M.order) if (vis[i] && SEL[M.rowLaw[i]]) put(pos.get(i), colors.words[i], size + 1);
      }
    }
    blit(ctx, img, ix / dpr, iy / dpr, iw / dpr, ih / dpr);
    ctx.save();
    ctx.beginPath();
    ctx.rect(m.l, m.t, pw, ph);
    ctx.clip();
    const view = { idx, xs, ys, sx, sy, m, pw, ph, W, H, xr, yr, dpr, X, Y, fams: [] };
    if (spec.refs) drawReferences(ctx, spec, view, T);
    if (spec.fam) drawFamilies(ctx, spec, view, T);
    if (spec.papers) drawPapers(ctx, spec, view, T);
    const trendText = spec.trend !== 'none' ? drawTrend(ctx, spec, view, T) : '';
    if (selCount && selCount <= 400) drawSelectionPaths(ctx, spec, view, T);
    ctx.restore();
    ctx.strokeStyle = T.line;
    ctx.strokeRect(m.l + 0.5, m.t + 0.5, pw - 1, ph - 1);
    let laws = 0;
    const seen = new Uint8Array(M.nLaws);
    for (const i of idx) if (!seen[M.rowLaw[i]]) { seen[M.rowLaw[i]] = 1; laws++; }
    P.count.textContent = `${fmtInt(laws)} laws` + (outside ? ` · ${fmtInt(outside)} at the edge` : '');
    P.count.title = `${fmtInt(idx.length)} readings of ${fmtInt(laws)} laws on this panel`
      + (outside ? `; ${fmtInt(outside)} of them fall outside it and are drawn at its edge` : '');
    if (trendText) P.foot.replaceChildren(trendText);
    else P.foot.replaceChildren(...legend.slice(0, 10).map((x) => h('span', { class: 'key' }, h('span', { class: 'swatch', style: `background:${css(x.rgb)}` }), pretty(x.label))));
    P.foot.title = trendText || legend.map((x) => pretty(x.label)).join(' · ');
    P.view = view;
  }

  const layer = document.createElement('canvas');
  function blit(ctx, img, x, y, w, hgt) {
    layer.width = img.width;
    layer.height = img.height;
    layer.getContext('2d').putImageData(img, 0, 0);
    ctx.drawImage(layer, x, y, w, hgt);
  }
  function line(ctx, pts, color, dash, width) {
    ctx.strokeStyle = color;
    ctx.lineWidth = width || 1;
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawReferences(ctx, spec, v, T) {
    const { sx, sy, xr, yr } = v, x = spec.x, y = spec.y, dims = ['d_s', 'd_V', 'd_B'];
    const label = (text, px, py) => { ctx.fillStyle = T.muted; ctx.font = '10px Inter, system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'; ctx.fillText(text, px + 3, py - 2); };
    const along = (f) => {
      const pts = [];
      for (let t = 0; t <= 40; t++) { const xv = xr[0] + ((xr[1] - xr[0]) * t) / 40; pts.push([sx(xv), sy(f(xv))]); }
      return pts;
    };
    if ((dims.includes(x) && dims.includes(y)) || (x === 'd_s' && (y === 'walk_ds' || y === 'walk_ds_B' || y === 'given_d_s'))
      || (y === 'd_s' && (x === 'walk_ds' || x === 'walk_ds_B' || x === 'given_d_s'))) {
      const pts = along((t) => t);
      line(ctx, pts, T.muted, [6, 4]);
      label('both read the same', sx(Math.min(xr[1], yr[1]) * 0.8), sy(Math.min(xr[1], yr[1]) * 0.8));
    }
    if (y === 'd_w') { line(ctx, [[sx(xr[0]), sy(2)], [sx(xr[1]), sy(2)]], T.muted, [6, 4]); label('d_w = 2, diffusion', sx(xr[0]), sy(2)); }
    if (x === 'd_w') line(ctx, [[sx(2), sy(yr[0])], [sx(2), sy(yr[1])]], T.muted, [6, 4]);
    if (y === 'ds_dV' || y === 'ds_dB') line(ctx, [[sx(xr[0]), sy(0)], [sx(xr[1]), sy(0)]], T.muted, [6, 4]);
    if (x === 'd_s' || y === 'd_s') {
      const rungs = spec.rung != null ? [spec.rung] : M.rungs.filter((n) => !S.f.rungs || S.f.rungs.includes(n));
      let lastLabel = -1e9;
      for (const n of rungs) {
        const r = M.rungAt.get(n), top = M.ceiling[r];
        if (!finite(top)) continue;
        const color = css(M.rungColor[r], 0.75);
        if (x === 'd_s' && top >= xr[0] && top <= xr[1]) {
          line(ctx, [[sx(top), sy(yr[0])], [sx(top), sy(yr[1])]], color, [2, 3]);
          if (Math.abs(sx(top) - lastLabel) > 18) {
            ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.font = '9px Inter, system-ui, sans-serif';
            ctx.fillText(fmtN(n), sx(top), v.m.t + 2);
            lastLabel = sx(top);
          }
        }
        if (y === 'd_s' && top >= yr[0] && top <= yr[1]) {
          line(ctx, [[sx(xr[0]), sy(top)], [sx(xr[1]), sy(top)]], color, [2, 3]);
          if (Math.abs(sy(top) - lastLabel) > 11) {
            ctx.fillStyle = color; ctx.textAlign = 'right'; ctx.textBaseline = 'bottom'; ctx.font = '9px Inter, system-ui, sans-serif';
            ctx.fillText(fmtN(n), v.m.l + v.pw - 2, sy(top) - 1);
            lastLabel = sy(top);
          }
        }
      }
    }
  }

  function placeLabels(ctx, labels) {
    const placed = [];
    labels.sort((a, b) => a.y - b.y || a.x - b.x);
    for (const label of labels) {
      const w = ctx.measureText(label.text).width + 2, step = 10;
      let y = label.y;
      for (let tries = 0; tries < 40; tries++) {
        const hit = placed.find((q) => Math.abs(q.y - y) < step && label.x < q.x + q.w && q.x < label.x + w);
        if (!hit) break;
        y = hit.y + step;
      }
      placed.push({ x: label.x, y, w });
      ctx.fillStyle = label.color;
      ctx.fillText(label.text, label.x, y);
    }
  }

  const FAMILY_KEYS = new Set(['d_s', 'd_V', 'd_B', 'd_w', 'k', 'n']);
  function drawFamilies(ctx, spec, v, T) {
    if (!FAMILY_KEYS.has(spec.x) || !FAMILY_KEYS.has(spec.y)) return;
    const fams = D.families || {}, ink = hexRgb(T.dark ? '#d1d1d6' : '#1d1d1f'), labels = [];
    ctx.font = '9px Inter, system-ui, sans-serif';
    for (const fam of Object.values(fams)) {
      const pts = fam.points.filter((p) => finite(p[spec.x]) && finite(p[spec.y])
        && (spec.rung == null || p.n === spec.rung) && (!S.f.rungs || S.f.rungs.includes(p.n) || !M.rungAt.has(p.n)));
      if (!pts.length) continue;
      const xy = pts.map((p) => [v.sx(p[spec.x]), v.sy(p[spec.y])]);
      if (xy.length > 1) line(ctx, xy, css(ink, 0.45), [3, 3], 0.8);
      ctx.strokeStyle = css(ink, 0.5);
      ctx.lineWidth = 0.8;
      for (const p of pts) {
        const rx = Math.max(2, Math.abs(v.sx(p[spec.x] + (p[`${spec.x}_sd`] || 0)) - v.sx(p[spec.x])));
        const ry = Math.max(2, Math.abs(v.sy(p[spec.y] + (p[`${spec.y}_sd`] || 0)) - v.sy(p[spec.y])));
        ctx.beginPath();
        ctx.ellipse(v.sx(p[spec.x]), v.sy(p[spec.y]), rx, ry, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
      const [lx, ly] = xy[xy.length - 1];
      labels.push({ x: lx + 4, y: ly, text: fam.short, color: css(ink, 0.85) });
      pts.forEach((p, i) => v.fams.push({ x: xy[i][0], y: xy[i][1], fam, p }));
    }
    if (v.pw < 380) return;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    placeLabels(ctx, labels);
  }

  const PAPER_KEYS = new Set(['d_s', 'd_V', 'd_B', 'd_w', 'k', 'kappa', 'reach', 'n']);
  function drawPapers(ctx, spec, v, T) {
    if (!PAPER_KEYS.has(spec.x) || !PAPER_KEYS.has(spec.y)) return;
    ctx.font = '9px Inter, system-ui, sans-serif';
    const last = new Map(), labels = [];
    for (const p of D.papers || []) {
      if (!finite(p[spec.x]) || !finite(p[spec.y]) || (spec.rung != null && p.n !== spec.rung)) continue;
      const x = v.sx(p[spec.x]), y = v.sy(p[spec.y]);
      ctx.fillStyle = T.warn;
      ctx.beginPath();
      ctx.moveTo(x, y - 4); ctx.lineTo(x + 4, y); ctx.lineTo(x, y + 4); ctx.lineTo(x - 4, y); ctx.closePath();
      ctx.fill();
      if (!last.has(p.model) || last.get(p.model).n < p.n) last.set(p.model, { n: p.n, x, y });
    }
    for (const [model, at] of last) labels.push({ x: at.x + 6, y: at.y, text: `${model} to ${fmtN(at.n)}`, color: T.warn });
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    placeLabels(ctx, labels);
  }

  function drawSelectionPaths(ctx, spec, v, T) {
    const X = v.X, Y = v.Y;
    ctx.globalAlpha = 0.75;
    for (let l = 0; l < M.nLaws; l++) {
      if (!SEL[l]) continue;
      const pts = [];
      for (const i of M.lawRows[l]) {
        if (!MASK[i] || !finite(X[i]) || !finite(Y[i])) continue;
        if (spec.camp >= 0 && M.rowCampaign[i] !== spec.camp) continue;
        if (spec.rung != null && M.col.n[i] !== spec.rung) continue;
        pts.push([v.sx(X[i]), v.sy(Y[i])]);
      }
      if (pts.length > 1) line(ctx, pts, T.select, null, 1.2);
    }
    ctx.globalAlpha = 1;
  }

  function binned(xsData, ysData, lo, hi, bins) {
    const groups = Array.from({ length: bins }, () => []);
    for (let j = 0; j < xsData.length; j++) {
      const b = Math.floor(((xsData[j] - lo) / (hi - lo)) * bins);
      if (b >= 0 && b < bins) groups[b].push(ysData[j]);
    }
    const out = [];
    groups.forEach((g, b) => {
      if (g.length < 4) return;
      const s = sortedOf(g);
      out.push({ x: lo + ((b + 0.5) * (hi - lo)) / bins, q25: quantile(s, 0.25), q50: quantile(s, 0.5),
        q75: quantile(s, 0.75), n: g.length, b });
    });
    return out;
  }
  function polyfit(xsData, ysData, degree) {
    const n = xsData.length, d = degree;
    if (n <= d + 1) return null;
    let lo = Infinity, hi = -Infinity;
    for (const x of xsData) { if (x < lo) lo = x; if (x > hi) hi = x; }
    const mid = (lo + hi) / 2, half = (hi - lo) / 2 || 1;
    const A = Array.from({ length: d + 1 }, () => new Float64Array(d + 2));
    for (let j = 0; j < n; j++) {
      const t = (xsData[j] - mid) / half, pw = [1];
      for (let k = 1; k <= 2 * d; k++) pw.push(pw[k - 1] * t);
      for (let r = 0; r <= d; r++) {
        for (let c = 0; c <= d; c++) A[r][c] += pw[r + c];
        A[r][d + 1] += pw[r] * ysData[j];
      }
    }
    for (let c = 0; c <= d; c++) {
      let p = c;
      for (let r = c + 1; r <= d; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
      [A[c], A[p]] = [A[p], A[c]];
      if (Math.abs(A[c][c]) < 1e-12) return null;
      for (let r = 0; r <= d; r++) {
        if (r === c) continue;
        const f = A[r][c] / A[c][c];
        for (let k = c; k <= d + 1; k++) A[r][k] -= f * A[c][k];
      }
    }
    const scaled = A.map((row, i) => row[d + 1] / row[i]);
    const coef = new Float64Array(d + 1);
    for (let k = 0; k <= d; k++) {
      for (let j = 0; j <= k; j++) {
        coef[j] += scaled[k] * binomial(k, j) * (-mid) ** (k - j) / half ** k;
      }
    }
    const f = (x) => { let y = 0; for (let k = d; k >= 0; k--) y = y * x + coef[k]; return y; };
    let ss = 0, st = 0, mean = 0;
    for (const y of ysData) mean += y;
    mean /= n;
    for (let j = 0; j < n; j++) { const r = ysData[j] - f(xsData[j]); ss += r * r; st += (ysData[j] - mean) ** 2; }
    return { coef: Array.from(coef), r2: st > 0 ? 1 - ss / st : NaN, rms: Math.sqrt(ss / n), f, lo, hi, n };
  }
  function runs(bins) {
    const out = [];
    for (const p of bins) {
      if (out.length && p.b === out[out.length - 1][out[out.length - 1].length - 1].b + 1) out[out.length - 1].push(p);
      else out.push([p]);
    }
    return out;
  }
  function binomial(n, k) { let r = 1; for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i; return r; }
  function polyText(fit) {
    if (!fit) return '';
    return fit.coef.map((c, k) => (k === 0 ? fmt(c, 3) : `${c >= 0 ? '+' : '-'} ${fmt(Math.abs(c), 3)}x${k > 1 ? `^${k}` : ''}`))
      .join(' ');
  }
  function pearson(xsData, ysData) {
    const n = xsData.length;
    if (n < 3) return NaN;
    let mx = 0, my = 0;
    for (let j = 0; j < n; j++) { mx += xsData[j]; my += ysData[j]; }
    mx /= n; my /= n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let j = 0; j < n; j++) { const a = xsData[j] - mx, b = ysData[j] - my; sxy += a * b; sxx += a * a; syy += b * b; }
    return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : NaN;
  }
  function pairsOf(spec, idx, X, Y) {
    const tx = spec.xlog ? Math.log10 : (t) => t, ty = spec.ylog ? Math.log10 : (t) => t;
    const xsData = new Float64Array(idx.length), ysData = new Float64Array(idx.length);
    idx.forEach((i, j) => { xsData[j] = tx(X[i]); ysData[j] = ty(Y[i]); });
    return [xsData, ysData];
  }
  const FIT_MIN = 30, FIT_SPREAD = 0.05;
  function fitWhyNot(xsData, degree, axisSpan) {
    if (xsData.length < Math.max(FIT_MIN, 10 * (degree + 1))) return `${xsData.length} readings: too few for a fit of degree ${degree}`;
    const s = sortedOf(xsData), spread = quantile(s, 0.9) - quantile(s, 0.1);
    if (!(spread >= FIT_SPREAD * axisSpan)) return `x spans ${fmt(spread, 3)}: too narrow for a fit`;
    return null;
  }
  function drawTrend(ctx, spec, v, T) {
    const [xsData, ysData] = pairsOf(spec, v.idx, v.X, v.Y);
    if (xsData.length < 8) return 'too few readings for a trend';
    const ux = spec.xlog ? (t) => 10 ** t : (t) => t, uy = spec.ylog ? (t) => 10 ** t : (t) => t;
    const lo = spec.xlog ? Math.log10(v.xr[0]) : v.xr[0], hi = spec.xlog ? Math.log10(v.xr[1]) : v.xr[1];
    if (spec.trend === 'median') {
      const b = binned(xsData, ysData, lo, hi, 28);
      if (!b.length) return '';
      ctx.fillStyle = css(hexRgb(T.dark ? '#ffffff' : '#000000'), 0.12);
      for (const run of runs(b)) {
        ctx.beginPath();
        run.forEach((p, i) => (i ? ctx.lineTo(v.sx(ux(p.x)), v.sy(uy(p.q75))) : ctx.moveTo(v.sx(ux(p.x)), v.sy(uy(p.q75)))));
        for (let i = run.length - 1; i >= 0; i--) ctx.lineTo(v.sx(ux(run[i].x)), v.sy(uy(run[i].q25)));
        ctx.closePath();
        ctx.fill();
        if (run.length > 1) line(ctx, run.map((p) => [v.sx(ux(p.x)), v.sy(uy(p.q50))]), T.ink, null, 1.6);
      }
      return `the median in ${b.length} bins, the band the middle half; r ${fmt(pearson(xsData, ysData), 2)}`;
    }
    const degree = Number(spec.trend.slice(3)) || 1;
    const why = fitWhyNot(xsData, degree, hi - lo);
    if (why) return `no fit: ${why}`;
    const fit = polyfit(xsData, ysData, degree);
    if (!fit) return 'no fit';
    const sx5 = sortedOf(xsData), x5 = quantile(sx5, 0.05), x95 = quantile(sx5, 0.95);
    const pts = [];
    for (let t = 0; t <= 60; t++) { const x = x5 + ((x95 - x5) * t) / 60; pts.push([v.sx(ux(x)), v.sy(uy(fit.f(x)))]); }
    line(ctx, pts, T.ink, null, 1.6);
    return `y = ${polyText(fit)} · R² ${fmt(fit.r2, 3)} · rms ${fmt(fit.rms, 3)}`;
  }

  function nearest(P, x, y) {
    const v = P.view;
    if (!v) return -1;
    let best = -1, bd = 49;
    for (let j = 0; j < v.idx.length; j++) {
      const dx = v.xs[j] - x, dy = v.ys[j] - y, d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = j; }
    }
    return best;
  }
  function nearestFamily(P, x, y, j) {
    const v = P.view;
    if (!v || !v.fams.length) return null;
    const law = j >= 0 ? (v.xs[j] - x) ** 2 + (v.ys[j] - y) ** 2 : Infinity;
    let best = null, bd = Math.min(49, law);
    for (const f of v.fams) { const d = (f.x - x) ** 2 + (f.y - y) ** 2; if (d < bd) { bd = d; best = f; } }
    return best;
  }
  function describeFamily(f) {
    const keys = ['d_s', 'd_V', 'd_B', 'd_w'].filter((k) => finite(f.p[k]));
    return [h('b', null, `${f.fam.short}`), ' (a calibration family, measured by the instrument)', h('br'), `N ${fmtInt(f.p.n)}`,
      ...keys.map((k) => ` · ${k} ${fmt(f.p[k])} ± ${fmt(f.p[`${k}_sd`])}`), finite(f.p.k) ? ` · k ${fmt(f.p.k)}` : ''];
  }
  function describeRow(i, extra) {
    const law = M.rowLaw[i], camp = M.campaigns[M.rowCampaign[i]], L = D.laws;
    const parts = [h('b', null, `law ${L.id ? L.id[law] : law}`), L.label && L.label[law] ? ` (${L.label[law]})` : '',
      h('br'), `${camp.short} ${camp.label}`, h('br'), `N ${fmtInt(M.col.n[i])}`];
    const keys = [...new Set([...(extra || []), 'd_s', 'd_V', 'd_B', 'd_w', 'k', 'kappa'])].filter((k) => M.col[k] && k !== 'n');
    for (const k of keys) if (finite(M.col[k][i])) parts.push(` · ${labelOf(k).split(' (')[0]} ${fmt(M.col[k][i])}`);
    if (L.fate && L.fate[law]) parts.push(h('br'), `fate: ${L.fate[law]}${L.fate_n && L.fate_n[law] ? ` at ${fmtInt(L.fate_n[law])}` : ''}`);
    if (L.cls && L.cls[law]) parts.push(h('br'), `class: ${L.cls[law]}`);
    if (L.nearest && L.nearest[law]) parts.push(h('br'), `nearest family: ${L.nearest[law]}${L.nearest_distance && finite(L.nearest_distance[law]) ? ` at ${fmt(L.nearest_distance[law], 1)}` : ''}`);
    return parts;
  }
  function showTip(e, kids) {
    tip.replaceChildren(...kids);
    tip.hidden = false;
    const w = tip.offsetWidth, hgt = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + hgt > innerHeight - 8) y = e.clientY - hgt - 14;
    tip.style.left = `${Math.max(4, x)}px`;
    tip.style.top = `${Math.max(4, y)}px`;
  }
  function wireBrush(P) {
    let start = null;
    const local = (e) => { const r = P.over.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    const octx = () => { const c = P.over.getContext('2d'); const dpr = P.view ? P.view.dpr : 1; c.setTransform(dpr, 0, 0, dpr, 0, 0); return c; };
    const clear = () => { const c = P.over.getContext('2d'); c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, P.over.width, P.over.height); };
    P.over.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !P.view) return;
      start = local(e);
      P.over.setPointerCapture(e.pointerId);
      tip.hidden = true;
    });
    P.over.addEventListener('pointermove', (e) => {
      if (!P.view) return;
      const [x, y] = local(e);
      clear();
      const c = octx();
      if (start) {
        c.strokeStyle = theme().select;
        c.fillStyle = 'rgba(255,138,0,0.08)';
        c.lineWidth = 1;
        c.fillRect(Math.min(start[0], x), Math.min(start[1], y), Math.abs(x - start[0]), Math.abs(y - start[1]));
        c.strokeRect(Math.min(start[0], x) + 0.5, Math.min(start[1], y) + 0.5, Math.abs(x - start[0]), Math.abs(y - start[1]));
        return;
      }
      const j = nearest(P, x, y);
      const fam = nearestFamily(P, x, y, j);
      if (fam) {
        c.strokeStyle = theme().ink;
        c.lineWidth = 1.5;
        c.beginPath();
        c.arc(fam.x, fam.y, 5, 0, Math.PI * 2);
        c.stroke();
        showTip(e, describeFamily(fam));
        return;
      }
      if (j < 0) { tip.hidden = true; return; }
      c.strokeStyle = theme().ink;
      c.lineWidth = 1.5;
      c.beginPath();
      c.arc(P.view.xs[j], P.view.ys[j], 5, 0, Math.PI * 2);
      c.stroke();
      showTip(e, describeRow(P.view.idx[j], [P.spec.x, P.spec.y]));
    });
    P.over.addEventListener('pointerleave', () => { if (!start) { clear(); tip.hidden = true; } });
    P.over.addEventListener('pointerup', (e) => {
      if (!start || !P.view) { start = null; return; }
      const [x, y] = local(e), [x0, y0] = start;
      start = null;
      clear();
      const how = e.altKey ? 'remove' : e.shiftKey ? 'add' : 'replace';
      if (Math.abs(x - x0) < 4 && Math.abs(y - y0) < 4) {
        const j = nearest(P, x, y);
        if (j >= 0) setSelection([M.rowLaw[P.view.idx[j]]], how === 'replace' && SEL[M.rowLaw[P.view.idx[j]]] && selCount === 1 ? 'remove' : how);
        else if (how === 'replace' && selCount) setSelection([], 'replace');
        return;
      }
      const lx = Math.min(x, x0), hx = Math.max(x, x0), ly = Math.min(y, y0), hy = Math.max(y, y0);
      const laws = new Set();
      const v = P.view;
      for (let j = 0; j < v.idx.length; j++) {
        if (v.xs[j] >= lx && v.xs[j] <= hx && v.ys[j] >= ly && v.ys[j] <= hy) laws.add(M.rowLaw[v.idx[j]]);
      }
      setSelection(laws, how);
    });
  }

  function makeSpread(campaigns, opts) {
    const base = h('canvas', { class: 'base' }), over = h('canvas', { class: 'over' });
    const plot = h('div', { class: 'plot', style: opts.height ? `height:${opts.height}px` : 'aspect-ratio: 16 / 9' }, base, over);
    const title = h('span', { class: 'ptitle' });
    const count = h('span', { class: 'pcount' });
    const el = h('div', { class: `panel${opts.focused ? ' focused' : ''}` }, h('div', { class: 'phead' }, title, count, sizeButton(opts)), plot,
      h('div', { class: 'pfoot' }));
    const P = { kind: 'spread', campaigns, el, base, over, plot, title, count, opts, view: null };
    over.addEventListener('pointermove', (e) => {
      if (!P.view) return;
      const r = over.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      let best = -1, bd = 49;
      const v = P.view;
      for (let j = 0; j < v.idx.length; j++) { const d = (v.xs[j] - x) ** 2 + (v.ys[j] - y) ** 2; if (d < bd) { bd = d; best = j; } }
      if (best < 0) { tip.hidden = true; return; }
      showTip(e, describeRow(v.idx[best], [S.spread.y]));
    });
    over.addEventListener('pointerleave', () => { tip.hidden = true; });
    over.addEventListener('click', (e) => {
      if (!P.view) return;
      const r = over.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      const v = P.view;
      let best = -1, bd = 49;
      for (let j = 0; j < v.idx.length; j++) { const d = (v.xs[j] - x) ** 2 + (v.ys[j] - y) ** 2; if (d < bd) { bd = d; best = j; } }
      if (best >= 0) setSelection([M.rowLaw[v.idx[best]]], e.shiftKey ? 'add' : 'replace');
    });
    PANELS.push(P);
    return P;
  }

  function spreadStats(key, campaigns) {
    const col = M.col[key], out = [];
    for (let r = 0; r < M.rungs.length; r++) {
      const values = [];
      let atCeil = 0, laws = new Set();
      for (let i = 0; i < M.nRows; i++) {
        if (!MASK[i] || M.rowRung[i] !== r || !campaigns.includes(M.rowCampaign[i]) || !finite(col[i])) continue;
        values.push(col[i]);
        laws.add(M.rowLaw[i]);
        if (M.atCeil[i] === 1) atCeil++;
      }
      if (!values.length) continue;
      const s = sortedOf(values);
      out.push({ n: M.rungs[r], r, readings: values.length, laws: laws.size, p10: quantile(s, 0.1), p25: quantile(s, 0.25),
        p50: quantile(s, 0.5), p75: quantile(s, 0.75), p90: quantile(s, 0.9), min: s[0], max: s[s.length - 1], atCeil });
    }
    return out;
  }

  function drawSpread(P) {
    const T = theme(), key = S.spread.y, col = M.col[key];
    const rect = P.plot.getBoundingClientRect();
    const W = Math.max(80, Math.floor(rect.width)), H = Math.max(80, Math.floor(rect.height));
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    for (const c of [P.base, P.over]) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const ctx = P.base.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = T.panel;
    ctx.fillRect(0, 0, W, H);
    const camps = P.campaigns;
    P.title.textContent = `${labelOf(key)} as N grows · ${camps.length === 1 ? `${M.campaigns[camps[0]].short} ${M.campaigns[camps[0]].label}` : 'the campaigns together'}`;
    const m = { l: 42, r: 104, t: 10, b: 26 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
    const idx = [];
    for (let i = 0; i < M.nRows; i++) if (MASK[i] && camps.includes(M.rowCampaign[i]) && finite(col[i])) idx.push(i);
    const spec = { y: key, x: 'n', range: S.spread.range || 'std', camp: camps.length === 1 ? camps[0] : -1 };
    const yr = rangeOf(spec, 'y', col, idx);
    const lo = Math.log2(M.rungs[0] || 64), hi = Math.log2(M.rungs[M.rungs.length - 1] || 4096);
    const sx = (n) => m.l + ((Math.log2(n) - lo) / (hi - lo || 1)) * pw;
    const sy = scale(yr[0], yr[1], false, m.t + ph, m.t);
    ctx.fillStyle = T.plot;
    ctx.fillRect(m.l, m.t, pw, ph);
    ctx.strokeStyle = T.grid;
    ctx.font = '10px Inter, system-ui, sans-serif';
    ctx.fillStyle = T.muted;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const t of ticksOf(yr[0], yr[1], false, key, Math.max(3, Math.round(ph / 45)))) {
      const y = Math.round(sy(t)) + 0.5;
      ctx.beginPath(); ctx.moveTo(m.l, y); ctx.lineTo(m.l + pw, y); ctx.stroke();
      ctx.fillText(fmt(t, 2), m.l - 4, y);
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const n of M.rungs) {
      const x = Math.round(sx(n)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, m.t); ctx.lineTo(x, m.t + ph); ctx.stroke();
      ctx.fillText(fmtN(n), x, m.t + ph + 4);
    }
    const clampY = (y) => Math.min(m.t + ph - 0.5, Math.max(m.t + 0.5, y));
    const stats = spreadStats(key, camps);
    if (S.spread.paths && idx.length) {
      ctx.strokeStyle = css(hexRgb(T.dark ? '#c7c7cc' : '#8e8e93'), Math.max(0.03, Math.min(0.25, 300 / M.visibleLaws)));
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      const inCamps = new Uint8Array(M.campaigns.length);
      for (const c of camps) inCamps[c] = 1;
      for (let l = 0; l < M.nLaws; l++) {
        if (!M.lawVisible[l] || !inCamps[M.lawCampaign[l]]) continue;
        let first = true;
        for (const i of M.lawRows[l]) {
          if (!MASK[i] || !finite(col[i])) continue;
          const x = sx(M.col.n[i]), y = clampY(sy(col[i]));
          if (first) { ctx.moveTo(x, y); first = false; } else ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
    }
    const xs = new Float32Array(idx.length), ys = new Float32Array(idx.length);
    if (S.spread.dots) {
      const spacing = pw / Math.max(1, (hi - lo) / 2);
      idx.forEach((i, j) => {
        const jitter = (((M.rowLaw[i] * 2654435761) >>> 0) / 4294967296 - 0.5) * spacing * 0.35;
        xs[j] = sx(M.col.n[i]) + jitter;
        ys[j] = clampY(sy(col[i]));
      });
      const colors = rowColors('rung', T);
      const muted = packed(T.mutedRgb);
      const img = new ImageData(P.base.width, P.base.height), buf = new Uint32Array(img.data.buffer), iw = img.width, ih = img.height;
      const s = Math.max(1, Math.round(1.5 * dpr));
      const put = (j, word) => {
        const px = Math.round(xs[j] * dpr) - (s >> 1), py = Math.round(ys[j] * dpr) - (s >> 1);
        for (let yy = Math.max(0, py); yy < Math.min(ih, py + s); yy++) for (let xx = Math.max(0, px); xx < Math.min(iw, px + s); xx++) buf[yy * iw + xx] = word;
      };
      idx.forEach((i, j) => { if (!(selCount && SEL[M.rowLaw[i]])) put(j, selCount ? muted : colors.words[i]); });
      if (selCount) idx.forEach((i, j) => { if (SEL[M.rowLaw[i]]) put(j, packed(hexRgb('#ff8a00'))); });
      blit(ctx, img, 0, 0, W, H);
    }
    if (S.spread.bands) {
      const w = Math.max(6, Math.min(26, pw / (M.rungs.length * 3)));
      for (const st of stats) {
        const x = sx(st.n);
        ctx.fillStyle = css(M.rungColor[st.r], 0.18);
        ctx.fillRect(x - w / 2, clampY(sy(st.p90)), w, clampY(sy(st.p10)) - clampY(sy(st.p90)));
        ctx.fillStyle = css(M.rungColor[st.r], 0.38);
        ctx.fillRect(x - w / 2, clampY(sy(st.p75)), w, clampY(sy(st.p25)) - clampY(sy(st.p75)));
      }
      line(ctx, stats.map((st) => [sx(st.n), clampY(sy(st.p50))]), T.ink, null, 1.6);
    }
    if (key === 'd_s') {
      const pts = M.rungs.map((n, r) => [sx(n), sy(M.ceiling[r])]).filter((p) => finite(p[1]));
      line(ctx, pts.map(([x, y]) => [x, clampY(y)]), T.warn, [4, 3], 1.2);
      if (pts.length) { ctx.fillStyle = T.warn; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'; ctx.fillText("the probe's ceiling", m.l + 4, clampY(pts[0][1]) - 3); }
    }
    if (FAMILY_KEYS.has(key)) {
      ctx.font = '9px Inter, system-ui, sans-serif';
      const ends = [];
      for (const fam of Object.values(D.families || {})) {
        const pts = fam.points.filter((p) => finite(p[key]) && p.n >= M.rungs[0] && p.n <= M.rungs[M.rungs.length - 1]);
        if (!pts.length) continue;
        line(ctx, pts.map((p) => [sx(p.n), clampY(sy(p[key]))]), css(hexRgb(T.dark ? '#d1d1d6' : '#1d1d1f'), 0.75), [3, 3], 0.8);
        ends.push([clampY(sy(pts[pts.length - 1][key])), fam.short]);
      }
      ends.sort((a, b) => a[0] - b[0]);
      for (let i = 1; i < ends.length; i++) ends[i][0] = Math.max(ends[i][0], ends[i - 1][0] + 9);
      ctx.fillStyle = T.ink;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      for (const [y, name] of ends) ctx.fillText(name, m.l + pw + 4, Math.min(H - 4, y));
    }
    if (PAPER_KEYS.has(key) && key !== 'k' && key !== 'n') {
      for (const p of D.papers || []) {
        if (!finite(p[key]) || !finite(p.n)) continue;
        const x = sx(p.n), y = clampY(sy(p[key]));
        ctx.fillStyle = T.warn;
        ctx.beginPath(); ctx.moveTo(x, y - 4); ctx.lineTo(x + 4, y); ctx.lineTo(x, y + 4); ctx.lineTo(x - 4, y); ctx.closePath(); ctx.fill();
      }
    }
    ctx.strokeStyle = T.line;
    ctx.strokeRect(m.l + 0.5, m.t + 0.5, pw - 1, ph - 1);
    let laws = 0;
    const seen = new Uint8Array(M.nLaws);
    for (const i of idx) if (!seen[M.rowLaw[i]]) { seen[M.rowLaw[i]] = 1; laws++; }
    P.count.textContent = `${fmtInt(idx.length)} readings · ${fmtInt(laws)} laws`;
    P.view = { idx, xs, ys, dpr };
    return stats;
  }

  const PAGES = [['start', 'Start here'], ['maps', 'Maps'], ['byn', 'By N'], ['spread', 'Spread over N'], ['curves', 'Curves'],
    ['scan', 'Scan'], ['counts', 'Counts'], ['laws', 'Laws'], ['about', 'About']];
  const UI = {};

  function shell() {
    const app = document.getElementById('app');
    app.replaceChildren();
    const study = D.study || {};
    UI.tabs = h('nav', { class: 'tabs', role: 'tablist' }, PAGES.map(([key, label]) => h('button', {
      type: 'button', role: 'tab', 'data-page': key, onclick: () => go(key) }, label)));
    UI.toggle = h('button', { class: 'side-toggle', type: 'button', onclick: () => UI.body.classList.toggle('side-open') }, 'Filters');
    UI.themeSel = h('select', { title: 'light, dark, or as the system is', onchange: (e) => { S.theme = e.target.value; applyTheme(); save(); redraw(); } },
      ['auto', 'light', 'dark'].map((t) => h('option', { value: t }, t)));
    UI.sub = h('span', { class: 'sub' });
    app.append(h('header', { class: 'top' }, h('div', null, h('h1', null, D.title || 'Study explorer'), UI.sub),
      UI.toggle, UI.themeSel, UI.tabs));
    UI.side = h('aside', { class: 'side' });
    UI.main = h('main', { class: 'main' });
    UI.body = h('div', { class: 'body' }, UI.side, UI.main);
    app.append(UI.body, tip);
    UI.sub.textContent = [study.built_utc ? `bundle of ${study.built_utc}` : '', study.build_number ? `build ${study.build_number}` : '',
      `${fmtInt(M.nLaws)} laws`, `${fmtInt(M.nRows)} readings`, `${M.campaigns.length} campaigns`].filter(Boolean).join(' · ');
  }
  function applyTheme() {
    if (S.theme === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = S.theme;
    UI.themeSel.value = S.theme;
    colorCache.clear();
  }

  function go(page) {
    if (S.page !== page) S.focus = null;
    S.page = page;
    for (const b of UI.tabs.children) b.setAttribute('aria-selected', String(b.dataset.page === page));
    renderSide();
    renderPage();
    save();
  }

  function chip(label, pressed, onclick, title) {
    return h('button', { class: 'chip', type: 'button', 'aria-pressed': String(Boolean(pressed)), onclick, title }, label);
  }
  function selectOf(options, value, onchange, attrs) {
    return h('select', { ...(attrs || {}), onchange: (e) => onchange(e.target.value) },
      options.map(([v, label]) => h('option', { value: v, selected: String(v) === String(value) ? true : null }, label)));
  }
  const numberOptions = () => M.numbers.map((f) => [f.key, f.label]);
  const colorOptions = () => [...M.cats.filter((c) => c.values.length <= 40).map((c) => [c.key, c.label]),
    ['density', 'density (readings a pixel)'], ...M.numbers.filter((f) => f.key !== 'n').map((f) => [f.key, f.label])];

  function renderSide() {
    const F = S.f, side = UI.side;
    side.replaceChildren();
    const counts = h('div', { class: 'note count' },
      `${fmtInt(maskCount)} of ${fmtInt(M.nRows)} readings, ${fmtInt(M.visibleLaws)} of ${fmtInt(M.nLaws)} laws pass the filters`);
    side.append(h('section', null, h('h2', null, 'Filters'), counts,
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: () => { resetFilters(); changed(); } }, 'Clear the filters'))));
    side.append(h('section', null, h('h2', null, 'Presets'), h('div', { class: 'chips' },
      PRESETS.filter((p) => !p.needs || p.needs.every((k) => M.col[k] || M.catOf.get(k)))
        .map((p) => h('button', { class: 'chip preset', type: 'button', title: p.what, onclick: () => { p.apply(); changed(true); } }, p.label)))));
    side.append(h('section', null, h('h2', null, 'Campaigns'), ...M.campaigns.map((c) => h('label', { class: 'camp',
      title: `${c.name || ''} · ${c.regime}${finite(c.cap) ? ` · mean degree cap ${c.cap}` : ''} · ${fmtInt(c.laws)} laws` },
    h('input', { type: 'checkbox', checked: !F.campaigns || F.campaigns.includes(c.index) ? true : null,
      onchange: (e) => { toggleIn('campaigns', c.index, e.target.checked, M.campaigns.map((x) => x.index)); changed(); } }),
    h('span', { class: 'swatch', style: `background:${css(c.color)}` }),
    h('span', null, `${c.short} ${c.label} `, h('span', { class: 'muted count' }, `${fmtInt(c.laws)} laws`))))));
    side.append(h('section', null, h('h2', null, 'N'), h('div', { class: 'chips' }, M.rungs.map((n) => chip(fmtInt(n),
      !F.rungs || F.rungs.includes(n), () => { toggleIn('rungs', n, !(!F.rungs || F.rungs.includes(n)), M.rungs); changed(); })))));
    const tri = (key, options, title) => h('div', { class: 'chips', title }, options.map(([v, label]) => chip(label, F[key] === v, () => { F[key] = v; changed(); })));
    side.append(h('section', null, h('h2', null, 'Where a reading sits'),
      h('h3', null, 'mean degree'), tri('whole', [['any', 'any'], ['whole', 'a whole number'], ['not', 'not whole']],
        `a whole number within ${D.rules.whole}: a regular graph, every node at one degree`),
      h('h3', null, "the probe's ceiling"), tri('ceiling', [['any', 'any'], ['at', 'at it'], ['under', 'under it']],
        `at the ceiling: d_s at least ${Math.round(D.rules.at_ceiling * 100)}% of the largest d_s any law read at its N`)));
    const lawCats = M.cats.filter((c) => c.lawCode && c.values.length <= 40);
    if (lawCats.length) {
      side.append(h('section', null, h('h2', null, 'The laws'), ...lawCats.map((cat) => {
        const allowed = F.cats[cat.key];
        const d = h('details', { open: allowed ? true : null }, h('summary', null, cat.label, allowed ? ` (${allowed.length})` : ''),
          h('div', { class: 'chips' }, cat.values.map((v, i) => chip(`${pretty(v)} ${fmtInt(cat.lawCounts[i])}`, !allowed || allowed.includes(v), () => {
            const all = cat.values.slice();
            let cur = F.cats[cat.key] ? F.cats[cat.key].slice() : all.slice();
            cur = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
            F.cats[cat.key] = cur.length === all.length ? null : cur;
            changed();
          }, cat.what))));
        return d;
      })));
    }
    const search = h('input', { type: 'search', placeholder: 'id, label or an operator', value: F.search || '' });
    search.addEventListener('input', debounce(() => { F.search = search.value; changed(); }, 250));
    side.append(h('section', null, h('h2', null, 'Search the laws'), search,
      F.only ? h('div', { class: 'row' }, h('span', { class: 'note' }, `only the ${F.only.length} laws kept`),
        h('button', { class: 'btn', type: 'button', onclick: () => { F.only = null; changed(); } }, 'show all')) : null));
    const ranges = h('section', null, h('h2', null, 'Ranges'));
    (F.ranges || []).forEach((r, at) => {
      const lo = h('input', { type: 'number', step: 'any', value: finite(r.min) ? r.min : '', placeholder: 'min' });
      const hi = h('input', { type: 'number', step: 'any', value: finite(r.max) ? r.max : '', placeholder: 'max' });
      const apply = () => { r.min = lo.value === '' ? null : +lo.value; r.max = hi.value === '' ? null : +hi.value; changed(); };
      lo.addEventListener('change', apply);
      hi.addEventListener('change', apply);
      ranges.append(h('div', { class: 'row' }, selectOf(numberOptions(), r.key, (v) => { r.key = v; changed(); }, { class: 'grow' })),
        h('div', { class: 'row' }, lo, 'to', hi, h('button', { class: 'btn', type: 'button', title: 'remove', onclick: () => { F.ranges.splice(at, 1); changed(); } }, 'remove')));
    });
    ranges.append(h('button', { class: 'btn', type: 'button', onclick: () => { F.ranges.push({ key: 'k', min: null, max: null }); renderSide(); } }, 'Add a range'));
    side.append(ranges);
    if (S.page === 'maps') side.append(panelSettings());
    side.append(selectionSection());
  }
  function toggleIn(key, value, on, all) {
    let cur = S.f[key] ? S.f[key].slice() : all.slice();
    cur = on ? [...new Set([...cur, value])] : cur.filter((v) => v !== value);
    S.f[key] = cur.length === all.length ? null : cur;
  }
  function resetFilters() {
    S.f = { campaigns: null, rungs: null, whole: 'any', ceiling: 'any', cats: {}, search: '', ranges: [], only: null };
  }

  function panelSettings() {
    const spec = S.maps.panels[S.active] || S.maps.panels[0];
    const sec = h('section', null, h('h2', null, `Panel ${S.active + 1}`));
    const field = (label, control) => h('div', { class: 'field' }, h('span', null, label), control);
    const set = (k) => (v) => { spec[k] = v; spec.mine = true; afterPanel(); };
    sec.append(field('x', selectOf(numberOptions(), spec.x, set('x'))), field('y', selectOf(numberOptions(), spec.y, set('y'))),
      field('colour', selectOf(colorOptions(), spec.color, set('color'))),
      field('campaign', selectOf([[-1, 'every campaign'], ...M.campaigns.map((c) => [c.index, `${c.short} ${c.label}`])], spec.camp, (v) => { spec.camp = +v; spec.mine = true; afterPanel(); })),
      field('N', selectOf([['', 'every N'], ...M.rungs.map((n) => [n, fmtInt(n)])], spec.rung ?? '', (v) => { spec.rung = v === '' ? null : +v; spec.mine = true; afterPanel(); })),
      field('range', selectOf([['std', 'standard (0 to 8 for a dimension)'], ['data', 'fit the data'], ['custom', 'my own']], spec.range, set('range'))));
    if (spec.range === 'custom') {
      for (const axis of ['x', 'y']) {
        const lo = h('input', { type: 'number', step: 'any', value: spec[`${axis}min`] ?? '' }), hi = h('input', { type: 'number', step: 'any', value: spec[`${axis}max`] ?? '' });
        const apply = () => { spec[`${axis}min`] = lo.value === '' ? null : +lo.value; spec[`${axis}max`] = hi.value === '' ? null : +hi.value; afterPanel(false); };
        lo.addEventListener('change', apply);
        hi.addEventListener('change', apply);
        sec.append(field(`${axis} from`, h('div', { class: 'row' }, lo, 'to', hi)));
      }
    }
    const box = (k, label, title) => h('label', { title }, h('input', { type: 'checkbox', checked: spec[k] ? true : null, onchange: (e) => { spec[k] = e.target.checked; afterPanel(false); } }), label);
    sec.append(h('div', { class: 'row' }, box('xlog', 'log x'), box('ylog', 'log y')),
      h('div', { class: 'row' }, box('refs', 'lines', "the diagonal, d_w = 2 and the probe's ceiling at each N"),
        box('fam', 'families', 'the calibration families where the instrument measured them, an ellipse of their spread'),
        box('papers', 'papers', "the papers' runs committed in the tree")),
      field('trend', selectOf([['none', 'none'], ['median', 'the median and the middle half'], ['fit1', 'a line'], ['fit2', 'a quadratic'], ['fit3', 'a cubic']], spec.trend, set('trend'))),
      h('div', { class: 'row' }, h('span', { class: 'muted' }, 'to every panel:'),
        ...[['x', 'x'], ['y', 'y'], ['color', 'colour'], ['range', 'range'], ['trend', 'trend'], ['camp', 'campaign']].map(([k, label]) => h('button', { class: 'btn', type: 'button', onclick: () => {
          for (const p of S.maps.panels) { p[k] = spec[k]; p.mine = true; if (k === 'range') { for (const a of ['xmin', 'xmax', 'ymin', 'ymax', 'xlog', 'ylog']) p[a] = spec[a]; } }
          afterPanel();
        } }, label))));
    return sec;
  }
  function afterPanel(rerenderSide) {
    if (rerenderSide !== false) renderSide();
    for (const P of PANELS) if (P.kind === 'scatter' && P.spec === S.maps.panels[S.active]) drawScatter(P);
    save();
  }

  function selectionSection() {
    const sec = h('section', null, h('h2', null, 'Selection'));
    if (!selCount) {
      sec.append(h('p', { class: 'note' }, 'Drag across a panel to select the laws there; shift adds, alt (option) takes away; a click picks one law. Esc clears.'));
      return sec;
    }
    sec.append(h('p', { class: 'note count' }, `${fmtInt(selCount)} laws selected`),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', onclick: () => setSelection([], 'replace') }, 'Clear'),
        h('button', { class: 'btn', type: 'button', onclick: () => go('laws') }, 'List them'),
        h('button', { class: 'btn', type: 'button', title: 'filter to these laws only', onclick: () => { S.f.only = selectedIds(); changed(); } }, 'Keep only these'),
        h('button', { class: 'btn', type: 'button', onclick: () => exportRows(true) }, 'Download')));
    if (selCount === 1) {
      const l = SEL.indexOf(1);
      sec.append(lawCard(l));
    }
    return sec;
  }
  function selectedIds() { const out = []; for (let l = 0; l < M.nLaws; l++) if (SEL[l]) out.push(D.laws.id[l]); return out; }
  function lawCard(l) {
    const L = D.laws, camp = M.campaigns[M.lawCampaign[l]];
    return h('div', { class: 'card' }, h('h3', null, `law ${L.id[l]}${L.label && L.label[l] ? ` (${L.label[l]})` : ''}`),
      h('div', { class: 'note' }, `${camp.short} ${camp.label}`),
      L.fate ? h('div', null, `fate: ${L.fate[l] ?? ''}${L.fate_n && L.fate_n[l] ? ` at ${fmtInt(L.fate_n[l])}` : ''}`) : null,
      L.cls ? h('div', null, `class: ${L.cls[l] ?? ''}`) : null,
      L.nearest && L.nearest[l] ? h('div', null, `Classify: nearest ${L.nearest[l]}${L.nearest_distance && finite(L.nearest_distance[l]) ? ` at ${fmt(L.nearest_distance[l], 1)} spreads` : ''}`) : null,
      L.role && L.role[l] ? h('div', null, `role: ${L.role[l]}${L.start && L.start[l] ? `, given start ${L.start[l]}` : ''}`) : null,
      L.terms ? h('div', { class: 'note' }, termsText(L.terms[l])) : null,
      L.beta ? h('div', { class: 'note' }, `beta ${fmt(L.beta[l])}${L.locality ? `, locality ${fmt(L.locality[l])}` : ''}${L.swap ? `, swap ${fmt(L.swap[l])}` : ''}`) : null);
  }

  const PRESETS = [
    { label: 'Zero temperature, a mean degree that is not whole', needs: ['d_s', 'k'],
      what: "the mean degrees k that do not settle on a whole number",
      apply() { resetFilters(); S.f.whole = 'not'; S.f.cats = atTemperature('zero temperature'); setMaps(['k', 'd_V', 'd_B', 'd_w'], 'rung'); } },
    { label: 'The split at degree 3 and 4', needs: ['d_s', 'k'],
      what: "the k against d_s line splits between 3 and 4",
      apply() { resetFilters(); S.f.ranges = [{ key: 'k', min: 2.5, max: 4.5 }]; S.byn = { ...S.byn, x: 'd_s', y: 'k', color: 'campaign', range: 'data' }; S.page = 'byn'; } },
    { label: "The arch at the probe's ceiling", needs: ['d_s', 'k'],
      what: "d_s against k at each N, with the largest d_s read at that N: a law denser than the ceiling's degree reads the ceiling",
      apply() { resetFilters(); S.byn = { ...S.byn, x: 'd_s', y: 'k', color: 'campaign', range: 'std' }; S.page = 'byn'; } },
    { label: "The walk's two clouds at finite temperature", needs: ['d_s', 'd_w'],
      what: 'rings (d_w 2) and random wirings (d_w 2.4 to 2.6, where a small world has no walk dimension)',
      apply() { resetFilters(); S.f.cats = atTemperature('finite temperature'); setMaps([['d_s', 'd_w'], ['k', 'd_w'], ['reach', 'd_w'], ['d_V', 'd_w']], 'rung'); } },
    { label: 'The probes against each other', needs: ['d_s', 'd_V', 'd_w'],
      what: 'd_s against the d_s the walk relation gives (2 d_V / d_w): on the diagonal where the probes agree',
      apply() { resetFilters(); setMaps(['walk_ds', 'walk_ds_B', 'ds_dV', 'ds_dB'], 'rung'); } },
    { label: 'From its shape against from empty', needs: ['given_d_s'],
      what: "a growth study: each law's chain from its shape against its chain from empty",
      apply() { resetFilters(); setMaps(['given_d_s', 'given_d_s', 'given_kappa', 'given_reach'], 'role'); } },
    { label: 'As it opens', what: 'every filter cleared, d_s against d_V, d_B, d_w and the mean degree, a column a campaign: the Classify maps', apply() { resetFilters(); S.maps.panels = defaultPanels(); S.page = 'maps'; } },
  ];
  function regimeGroups() {
    const labels = ['zero temperature', 'finite temperature', 'not set'];
    return labels.map((label, regime) => ({ label, regime, camps: null }))
      .filter((g) => M.rowRegime.some((v) => v === g.regime));
  }
  const atTemperature = (label) => ({ ...(S.f.cats || {}), regime: [label] });
  function setMaps(ys, color) {
    const camps = (S.f.campaigns || M.campaigns.map((c) => c.index));
    const pairs = ys.map((y) => (Array.isArray(y) ? y : ['d_s', y])).filter(([x, y]) => M.col[x] && M.col[y]);
    S.maps.pairs = pairs;
    S.maps.panels = gridOf(pairs, color, camps,
      (pair) => (pair && !DIMENSIONS.has(pair[0]) && pair[0] !== 'k' ? 'data' : 'std'));
    S.maps.rows = 4;
    S.maps.cols = Math.min(4, Math.max(1, camps.length));
    S.page = 'maps';
  }

  function setGridRows(rows, color) {
    const camps = (S.f.campaigns || M.campaigns.map((c) => c.index));
    const pairs = rows.filter(([x, y]) => M.col[x] && M.col[y]);
    S.maps.pairs = pairs;
    S.maps.panels = gridOf(pairs, color || 'rung', camps);
    S.maps.rows = Math.min(4, Math.max(1, pairs.length));
    S.maps.cols = Math.min(4, Math.max(1, camps.length));
    S.focus = null;
  }
  const VIEWS = [
    { title: 'The degree first', needs: ['d_s', 'k'],
      text: 'Almost everything the probes read follows one number, the mean degree k (finding 1). At finite temperature most laws wire '
        + 'their graphs at random, which no probe reads since 761; at zero temperature many make regular graphs (rows at a whole k). '
        + 'The second row takes the degree out: d_s beyond k, against k.',
      open() { resetFilters(); setGridRows([['d_s', 'k'], ['k', 'd_s_beyond_k']]); S.page = 'maps'; } },
    { title: "What is the probe's: its ceiling", needs: ['d_s', 'k'],
      text: 'The spectral dimension is read from a walk over the times N nodes allow, so it cannot read above a ceiling that grows with N '
        + "(the dotted lines, the largest d_s any law read there). Every dense law at 256 nodes reads about 4 whatever its graph: the arch "
        + "on the maps. Below the ceiling a reading is the graph's; at it, it is the probe's.",
      open() { resetFilters(); S.byn = { ...S.byn, x: 'd_s', y: 'k', color: 'campaign', split: 'together', range: 'std', trend: 'none' }; S.page = 'byn'; } },
    { title: 'The degrees that do not settle', needs: ['d_s', 'k'],
      text: 'At zero temperature, the laws whose mean degree is not a whole number. Most are within 0.1 of one: regular graphs with a few '
        + 'nodes off: Counts shows which operators they carry more often than the rest.',
      open() { resetFilters(); S.f.whole = 'not'; S.f.cats = atTemperature('zero temperature'); setGridRows([['d_s', 'k'], ['d_s', 'k_frac']], 'rung'); S.page = 'maps'; } },
    { title: 'Do the probes agree?', needs: ['d_s', 'd_V', 'd_w'],
      text: 'A geometry reads the same dimension every way. The walk relation gives a d_s from the volume and the walk (2 d_V / d_w): on '
        + 'the diagonal against d_s where the probes agree. The second row asks it beyond the degree: d_V beyond k against d_s beyond k.',
      open() { resetFilters(); setGridRows([['d_s', 'walk_ds'], ['d_s_beyond_k', 'd_V_beyond_k']]); S.page = 'maps'; } },
    { title: "The walk's two clouds", needs: ['d_s', 'd_w'],
      text: 'At finite temperature d_w falls into two clouds, the two fates there: rings (d_s near 1, d_w 2, ordinary diffusion along a '
        + 'chain) and random wirings (d_w 2.4 to 2.6, where a small world has no walk dimension and the estimator reads its window).',
      open() { resetFilters(); S.f.cats = atTemperature('finite temperature'); setGridRows([['d_s', 'd_w'], ['k', 'd_w']]); S.page = 'maps'; } },
    { title: 'What changes as the graphs grow', needs: ['d_s', 'd_V'],
      text: 'Each probe against d_s, a row a probe and a column a rung: the relations as N grows. Where a law has a geometry its probes '
        + 'should agree more the larger the graph; where they part, one of them is reading its window.',
      open() { resetFilters(); S.byn = { ...S.byn, x: 'd_s', y: 'd_V', color: 'campaign', split: 'probes', range: 'std', trend: 'none' }; S.page = 'byn'; } },
    { title: 'Let the data say what to look at', needs: ['d_s'],
      text: 'The Scan measures every pair of fields in each temperature and at each N and ranks them: what holds beyond the degree, what '
        + 'changes as N grows, what differs between the temperatures, and which clouds split in two. A lead, then a map.',
      open() { resetFilters(); S.scan = { ...S.scan, by: 'regime' }; S.page = 'scan'; } },
    { title: 'From its shape against from empty', needs: ['given_d_s'],
      text: "A growth study: each law's chain started from a shape, beside its chain grown from empty. A holder's chain from its shape keeps its "
        + "start's dimension; nothing yet grows one from empty.",
      open() { resetFilters(); setGridRows([['d_s', 'given_d_s'], ['given_reach', 'given_d_s']], 'role'); S.page = 'maps'; } },
    { title: 'What the laws resemble', needs: ['family_distance'],
      text: "The Classify ranking: each law of report 05 against the calibration families at "
        + 'every rung it read two probes or more, coloured by its nearest family at its top rung; the second row is how far from that '
        + "family it reads, in the family's measured seed spreads (1 or less resembles it). A resemblance, not an identification: the "
        + "front page says how many pairs of families the instrument can tell apart at the top rung, and no placement is finer.",
      open() { resetFilters(); setGridRows([['d_s', 'd_V'], ['d_s', 'family_distance']], M.catOf.get('nearest') ? 'nearest' : 'rung'); S.page = 'maps'; } },
  ];
  function pageStart() {
    UI.main.append(h('div', { class: 'about' },
      h('h2', null, 'Start here'),
      h('p', null, `${D.title}: ${fmtInt(M.nLaws)} laws, ${fmtInt(M.nRows)} readings. A few views carry what the studies have shown so `
        + 'far; each opens with the filters and maps it needs (the filters on the left stay yours to change, and "Clear the filters" '
        + 'undoes a view). After them, the Scan ranks every pair of fields, so a pattern is found by measuring rather than by trying '
        + 'plots. A panel\'s top-right button fills the page with it.')),
    h('div', { class: 'cards' }, VIEWS.filter((v) => !v.needs || v.needs.every((k) => M.col[k] || M.catOf.get(k))).map((v) => h('div', { class: 'card' },
      h('h3', null, v.title), h('p', { class: 'note' }, v.text),
      h('button', { class: 'btn', type: 'button', onclick: () => { S.focus = null; v.open(); computeMask(); go(S.page); } }, 'Open this view')))));
  }

  function renderPage() {
    PANELS.length = 0;
    tip.hidden = true;
    UI.main.replaceChildren();
    ({ start: pageStart, maps: pageMaps, byn: pageByN, spread: pageSpread, curves: pageCurves, scan: pageScan, counts: pageCounts,
      laws: pageLaws, about: pageAbout })[S.page]();
  }
  function redraw() {
    for (const P of PANELS) {
      if (P.kind === 'scatter') drawScatter(P);
      else if (P.kind === 'spread') drawSpread(P);
      else if (P.kind === 'curves') drawCurves(P);
    }
  }
  function changed(full) {
    computeMask();
    if (full) { renderSide(); go(S.page); return; }
    renderSide();
    if (['counts', 'laws', 'spread', 'curves'].includes(S.page)) renderPage(); else redraw();
    save();
  }
  function onSelection() {
    renderSide();
    if (S.page === 'laws') renderPage(); else redraw();
    save();
  }

  function pageMaps() {
    const mp = S.maps;
    const grid = h('div', { class: 'grid', style: `grid-template-columns: repeat(${mp.cols}, minmax(0, 1fr))` });
    const toolbar = h('div', { class: 'toolbar' },
      h('label', null, 'rows', selectOf([1, 2, 3, 4].map((v) => [v, v]), mp.rows, (v) => { mp.rows = +v; renderPage(); save(); })),
      h('label', null, 'columns', selectOf([1, 2, 3, 4].map((v) => [v, v]), mp.cols, (v) => { mp.cols = +v; renderPage(); save(); })),
      h('label', null, 'dots', selectOf([[1, 'small'], [2, 'medium'], [3, 'large'], [4, 'larger']], mp.size, (v) => { mp.size = +v; redraw(); save(); })),
      h('label', { title: 'the grid fills the window, so all its rows are in view' }, h('input', { type: 'checkbox', checked: mp.fit ? true : null, onchange: (e) => { mp.fit = e.target.checked; renderPage(); save(); } }), 'fit the window'),
      h('button', { class: 'btn', type: 'button', onclick: () => { mp.panels = defaultPanels(); renderPage(); renderSide(); save(); } }, 'Reset the grid'),
      h('span', { class: 'muted' }, 'Click a panel\'s title for its settings; drag across a panel to select.'));
    UI.main.append(toolbar, grid);
    const activate = (at, P) => { S.active = at; for (const Q of PANELS) Q.el.classList.toggle('active', Q === P); renderSide(); UI.body.classList.add('side-open'); };
    const focused = focusedHere();
    if (focused === 'scan' && S.scanSpec) {
      grid.style.gridTemplateColumns = 'minmax(0, 1fr)';
      grid.append(makeScatter(S.scanSpec, { height: focusHeight(grid), focusKey: 'scan', focused: true }).el);
      requestAnimationFrame(redraw);
      return;
    }
    if (focused !== null && mp.panels[+focused]) {
      const at = +focused;
      grid.style.gridTemplateColumns = 'minmax(0, 1fr)';
      const P = makeScatter(mp.panels[at], { active: at === S.active, height: focusHeight(grid), focusKey: at, focused: true,
        onActivate: () => activate(at, P) });
      grid.append(P.el);
      requestAnimationFrame(redraw);
      return;
    }
    let height = null;
    if (mp.fit) {
      const top = grid.getBoundingClientRect().top + window.scrollY;
      height = Math.max(140, Math.floor((window.innerHeight - top - 24 - (mp.rows - 1) * 10) / mp.rows) - 44);
    }
    distinctPanels(mp);
    for (let r = 0; r < mp.rows; r++) {
      for (let c = 0; c < mp.cols; c++) {
        const at = r * 4 + c;
        const P = makeScatter(mp.panels[at], { active: at === S.active, height, focusKey: at, onActivate: () => activate(at, P) });
        grid.append(P.el);
      }
    }
    requestAnimationFrame(redraw);
  }

  function pageByN() {
    const b = S.byn;
    const set = (k) => (v) => { b[k] = v; renderPage(); save(); };
    UI.main.append(h('div', { class: 'toolbar' },
      h('label', null, 'x', selectOf(numberOptions(), b.x, set('x'))), h('label', null, 'y', selectOf(numberOptions(), b.y, set('y'))),
      h('label', null, 'colour', selectOf(colorOptions(), b.color, set('color'))),
      h('label', null, 'rows', selectOf([['together', 'the campaigns together'], ['campaign', 'a row a campaign'], ['regime', 'a row a temperature'],
        ['probes', 'a row a probe against x']], b.split, set('split'))),
      h('label', null, 'range', selectOf([['std', 'standard'], ['data', 'fit the data']], b.range, set('range'))),
      h('label', null, 'trend', selectOf([['none', 'none'], ['median', 'median'], ['fit1', 'a line'], ['fit2', 'a quadratic']], b.trend, set('trend')))),
    h('p', { class: 'note' }, `${labelOf(b.y)} against ${labelOf(b.x)}, drawn once for each N: how the relation moves as the graphs grow.`));
    const rungs = M.rungs.filter((n) => !S.f.rungs || S.f.rungs.includes(n));
    const probes = ['d_V', 'd_B', 'd_w', 'k', 'd_s'].filter((k) => M.col[k] && k !== b.x);
    const groups = b.split === 'campaign' ? M.campaigns.filter((c) => !S.f.campaigns || S.f.campaigns.includes(c.index)).map((c) => ({ label: `${c.short} ${c.label}`, camps: [c.index] }))
      : b.split === 'regime' ? regimeGroups()
        : b.split === 'probes' ? probes.map((y) => ({ label: `${labelOf(y)} against ${labelOf(b.x)}`, camps: null, y }))
          : [{ label: null, camps: null }];
    const wrap = h('div', { style: 'overflow-x:auto' });
    const cols = Math.min(rungs.length, b.split === 'together' ? 4 : rungs.length);
    const grid = h('div', { class: 'grid', style: `grid-template-columns: repeat(${cols}, minmax(${b.split === 'together' ? 0 : 230}px, 1fr))` });
    const focused = focusedHere();
    const specOf = (g, n) => panelSpec({ x: b.x, y: g.y || b.y, color: b.color, rung: n, camps: g.camps, camp: g.camps && g.camps.length === 1 ? g.camps[0] : -1, range: b.range, trend: b.trend, regime: g.regime });
    wrap.append(grid);
    UI.main.append(wrap);
    if (focused !== null) {
      const [gi, n] = focused.split(':').map(Number);
      if (groups[gi] && rungs.includes(n)) {
        grid.style.gridTemplateColumns = 'minmax(0, 1fr)';
        if (groups[gi].label) grid.append(h('h3', { style: 'margin: 6px 0 0' }, groups[gi].label));
        grid.append(makeScatter(specOf(groups[gi], n), { focusKey: focused, focused: true, height: focusHeight(grid) }).el);
        requestAnimationFrame(redraw);
        return;
      }
    }
    groups.forEach((g, gi) => {
      if (g.label) grid.append(h('h3', { style: 'grid-column: 1 / -1; margin: 6px 0 0' }, g.label));
      for (const n of rungs) grid.append(makeScatter(specOf(g, n), { focusKey: `${gi}:${n}` }).el);
    });
    requestAnimationFrame(redraw);
  }

  function pageSpread() {
    const sp = S.spread;
    const set = (k) => (v) => { sp[k] = v; renderPage(); save(); };
    const box = (k, label) => h('label', null, h('input', { type: 'checkbox', checked: sp[k] ? true : null, onchange: (e) => { sp[k] = e.target.checked; renderPage(); save(); } }), label);
    UI.main.append(h('div', { class: 'toolbar' },
      h('label', null, 'field', selectOf(numberOptions().filter(([k]) => k !== 'n'), sp.y, set('y'))),
      h('label', null, 'range', selectOf([['std', 'standard'], ['data', 'fit the data']], sp.range || 'std', set('range'))),
      box('dots', 'readings'), box('paths', "each law's path"), box('bands', 'the quantiles'), box('together', 'the campaigns together')),
    h('p', { class: 'note' }, `Every law's ${labelOf(sp.y)} as N grows: the readings coloured by N, each law's path across its rungs, `
      + 'the band from the 10th to the 90th percentile and the middle half darker, the median joined; the families\' measured paths dashed where the instrument read them'
      + (sp.y === 'd_s' ? ", and the probe's ceiling, the largest d_s any law of the study read at each N." : '.')));
    const camps = M.campaigns.filter((c) => !S.f.campaigns || S.f.campaigns.includes(c.index)).map((c) => c.index);
    let groups = sp.together || camps.length <= 1 ? [camps] : camps.map((c) => [c]);
    const grid = h('div', { class: 'grid', style: `grid-template-columns: repeat(${Math.min(2, groups.length)}, minmax(0, 1fr))` });
    UI.main.append(grid);
    const focused = focusedHere();
    const keys = groups.map((g, gi) => gi);
    let made;
    if (focused !== null && groups[+focused]) {
      grid.style.gridTemplateColumns = 'minmax(0, 1fr)';
      groups = [groups[+focused]];
      made = [makeSpread(groups[0], { focusKey: focused, focused: true, height: focusHeight(grid) })];
    } else {
      made = groups.map((g, gi) => makeSpread(g, { focusKey: keys[gi] }));
    }
    made.forEach((P) => grid.append(P.el));
    const tables = h('div');
    UI.main.append(h('h2', { style: 'font-size:14px;margin:16px 0 4px' }, `The spread, by campaign and N`), tables);
    requestAnimationFrame(() => {
      const rows = [];
      made.forEach((P) => {
        const stats = drawSpread(P);
        const label = P.campaigns.length === 1 ? `${M.campaigns[P.campaigns[0]].short}` : 'together';
        for (const st of stats) rows.push([label, st]);
      });
      const head = ['campaign', 'N', 'readings', 'laws', '10%', '25%', 'median', '75%', '90%', 'largest', ...(sp.y === 'd_s' ? ['at the ceiling'] : [])];
      const table = h('table', null, h('thead', null, h('tr', null, head.map((x, i) => h('th', { class: i > 1 ? 'num' : null }, x)))),
        h('tbody', null, rows.map(([label, st]) => h('tr', null, h('td', null, label), h('td', { class: 'num' }, fmtInt(st.n)),
          h('td', { class: 'num' }, fmtInt(st.readings)), h('td', { class: 'num' }, fmtInt(st.laws)),
          ...[st.p10, st.p25, st.p50, st.p75, st.p90, st.max].map((v) => h('td', { class: 'num' }, fmt(v))),
          ...(sp.y === 'd_s' ? [h('td', { class: 'num' }, `${fmtInt(st.atCeil)} (${pct(st.atCeil, st.readings)})`)] : [])))));
      tables.replaceChildren(h('div', { class: 'tablewrap' }, table),
        h('button', { class: 'btn', type: 'button', onclick: () => download(`spread_${sp.y}.csv`, csvOf(head, rows.map(([label, st]) => [label, st.n, st.readings, st.laws, st.p10, st.p25, st.p50, st.p75, st.p90, st.max, ...(sp.y === 'd_s' ? [st.atCeil] : [])]))) }, 'Download the table'));
    });
  }

  function makeCurves(campaigns, opts) {
    opts = opts || {};
    const base = h('canvas', { class: 'base' }), over = h('canvas', { class: 'over' });
    const plot = h('div', { class: 'plot', style: opts.height ? `height:${opts.height}px` : 'aspect-ratio: 4 / 3' }, base, over);
    const title = h('span', { class: 'ptitle' });
    const el = h('div', { class: `panel${opts.focused ? ' focused' : ''}` }, h('div', { class: 'phead' }, title, sizeButton(opts)), plot,
      h('div', { class: 'pfoot' }));
    const P = { kind: 'curves', campaigns, el, base, over, plot, title, view: null, fits: [] };
    PANELS.push(P);
    return P;
  }
  function drawCurves(P) {
    const cv = S.curves, T = theme();
    const spec = panelSpec({ x: cv.x, y: cv.y, camps: P.campaigns, camp: P.campaigns.length === 1 ? P.campaigns[0] : -1, color: 'rung' });
    const X = M.col[cv.x], Y = M.col[cv.y];
    const rect = P.plot.getBoundingClientRect();
    const W = Math.max(80, Math.floor(rect.width)), H = Math.max(80, Math.floor(rect.height));
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    for (const c of [P.base, P.over]) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const ctx = P.base.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = T.panel;
    ctx.fillRect(0, 0, W, H);
    P.title.textContent = `${labelOf(cv.y)} against ${labelOf(cv.x)} · ${P.campaigns.length === 1 ? `${M.campaigns[P.campaigns[0]].short} ${M.campaigns[P.campaigns[0]].label}` : 'together'}`;
    if (!X || !Y) return [];
    const idx = visibleRows(spec, X, Y);
    const xr = rangeOf(spec, 'x', X, idx), yr = rangeOf(spec, 'y', Y, idx);
    const m = { l: 42, r: 10, t: 8, b: 30 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
    const sx = scale(xr[0], xr[1], false, m.l, m.l + pw), sy = scale(yr[0], yr[1], false, m.t + ph, m.t);
    ctx.fillStyle = T.plot;
    ctx.fillRect(m.l, m.t, pw, ph);
    ctx.strokeStyle = T.grid;
    ctx.fillStyle = T.muted;
    ctx.font = '10px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const v of ticksOf(xr[0], xr[1], false, cv.x, 6)) { const x = Math.round(sx(v)) + 0.5; ctx.beginPath(); ctx.moveTo(x, m.t); ctx.lineTo(x, m.t + ph); ctx.stroke(); ctx.fillText(fmt(v, 2), x, m.t + ph + 3); }
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const v of ticksOf(yr[0], yr[1], false, cv.y, 5)) { const y = Math.round(sy(v)) + 0.5; ctx.beginPath(); ctx.moveTo(m.l, y); ctx.lineTo(m.l + pw, y); ctx.stroke(); ctx.fillText(fmt(v, 2), m.l - 4, y); }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = T.ink2;
    ctx.fillText(labelOf(cv.x), m.l + pw / 2, H - 1);
    const img = new ImageData(Math.round(pw * dpr), Math.round(ph * dpr));
    const buf = new Uint32Array(img.data.buffer), iw = img.width, ih = img.height, faint = packed(T.mutedRgb);
    for (const i of idx) {
      const px = Math.round((sx(X[i]) - m.l) * dpr), py = Math.round((sy(Y[i]) - m.t) * dpr);
      if (px >= 0 && py >= 0 && px < iw && py < ih) buf[py * iw + px] = faint;
    }
    blit(ctx, img, m.l, m.t, iw / dpr, ih / dpr);
    ctx.save();
    ctx.beginPath(); ctx.rect(m.l, m.t, pw, ph); ctx.clip();
    const fits = [];
    for (let r = 0; r < M.rungs.length; r++) {
      const rows = idx.filter((i) => M.rowRung[i] === r);
      if (rows.length < 8) continue;
      const xsData = Float64Array.from(rows, (i) => X[i]), ysData = Float64Array.from(rows, (i) => Y[i]);
      const color = css(M.rungColor[r]);
      const degree = cv.method === 'median' ? 1 : Number(cv.degree);
      const why = fitWhyNot(xsData, degree, xr[1] - xr[0]);
      const fit = why ? null : polyfit(xsData, ysData, degree);
      const s = sortedOf(xsData);
      const entry = { n: M.rungs[r], points: rows.length, x10: quantile(s, 0.1), x90: quantile(s, 0.9), r: pearson(xsData, ysData), fit, why, rungIndex: r };
      if (cv.method === 'median') {
        const b = binned(xsData, ysData, xr[0], xr[1], 24);
        entry.medians = b;
        for (const run of runs(b)) if (run.length > 1) line(ctx, run.map((p) => [sx(p.x), sy(p.q50)]), color, null, 1.8);
      } else if (fit) {
        const pts = [];
        for (let t = 0; t <= 50; t++) { const x = entry.x10 + ((entry.x90 - entry.x10) * t) / 50; pts.push([sx(x), sy(fit.f(x))]); }
        line(ctx, pts, color, null, 1.8);
      }
      fits.push(entry);
    }
    ctx.restore();
    ctx.strokeStyle = T.line;
    ctx.strokeRect(m.l + 0.5, m.t + 0.5, pw - 1, ph - 1);
    P.el.querySelector('.pfoot').textContent = fits.map((f) => fmtN(f.n)).join(' · ');
    P.fits = fits;
    P.view = { idx };
    return fits;
  }

  function pageCurves() {
    const cv = S.curves;
    const set = (k) => (v) => { cv[k] = v; renderPage(); save(); };
    UI.main.append(h('div', { class: 'toolbar' },
      h('label', null, 'x', selectOf(numberOptions(), cv.x, set('x'))), h('label', null, 'y', selectOf(numberOptions(), cv.y, set('y'))),
      h('label', null, 'curve', selectOf([['median', 'the median along x'], ['fit', 'a polynomial']], cv.method, set('method'))),
      cv.method === 'fit' ? h('label', null, 'degree', selectOf([[1, '1'], [2, '2'], [3, '3']], cv.degree, set('degree'))) : null),
    h('p', { class: 'note' }, 'Each cloud compressed to a curve, one a rung, coloured by N: the median of y along x in 24 bins (where a bin has '
      + 'four readings or more), or a least-squares polynomial over the middle 80% of x, given only where it rests on 30 readings or more '
      + '(ten a coefficient) spread over a twentieth of the axis or more. The table gives each curve\'s numbers; the second, '
      + 'every probe against d_s at once (rungs with 30 readings or more), so the relations can be compared as N grows.'),
    h('div', { class: 'legend' }, M.rungs.map((n, r) => h('span', null, h('span', { class: 'swatch', style: `background:${css(M.rungColor[r])}` }), fmtInt(n)))));
    const camps = M.campaigns.filter((c) => !S.f.campaigns || S.f.campaigns.includes(c.index)).map((c) => c.index);
    const grid = h('div', { class: 'grid', style: `grid-template-columns: repeat(${Math.min(4, Math.max(1, camps.length))}, minmax(0, 1fr))` });
    UI.main.append(grid);
    const focused = focusedHere();
    let made;
    if (focused !== null && camps.includes(+focused)) {
      grid.style.gridTemplateColumns = 'minmax(0, 1fr)';
      made = [makeCurves([+focused], { focusKey: focused, focused: true, height: focusHeight(grid) })];
    } else {
      made = camps.map((c) => makeCurves([c], { focusKey: c }));
    }
    made.forEach((P) => grid.append(P.el));
    const tables = h('div');
    UI.main.append(tables);
    requestAnimationFrame(() => {
      const rows = [];
      made.forEach((P) => { for (const f of drawCurves(P)) rows.push([M.campaigns[P.campaigns[0]].short, f]); });
      const deg = cv.method === 'median' ? 1 : Number(cv.degree);
      const head = ['campaign', 'N', 'readings', 'x, 10% to 90%', 'r', `fit, degree ${deg}`, 'R²', 'rms'];
      const one = h('table', null, h('thead', null, h('tr', null, head.map((x, i) => h('th', { class: i > 1 && i !== 5 ? 'num' : null }, x)))),
        h('tbody', null, rows.map(([c, f]) => h('tr', null, h('td', null, c), h('td', { class: 'num' }, fmtInt(f.n)), h('td', { class: 'num' }, fmtInt(f.points)),
          h('td', { class: 'num' }, `${fmt(f.x10, 2)} to ${fmt(f.x90, 2)}`), h('td', { class: 'num' }, fmt(f.r, 3)),
          h('td', { class: f.fit ? 'code' : 'muted' }, f.fit ? `y = ${polyText(f.fit)}` : (f.why || '')), h('td', { class: 'num' }, f.fit ? fmt(f.fit.r2, 3) : ''),
          h('td', { class: 'num' }, f.fit ? fmt(f.fit.rms, 3) : '')))));
      const ys = ['d_V', 'd_B', 'd_w', 'k', 'walk_ds'].filter((k) => M.col[k] && M.col.d_s);
      const all = [];
      for (const y of ys) {
        for (const c of camps) {
          for (let r = 0; r < M.rungs.length; r++) {
            const xsData = [], ysData = [];
            for (let i = 0; i < M.nRows; i++) {
              if (!MASK[i] || M.rowRung[i] !== r || M.rowCampaign[i] !== c) continue;
              const a = M.col.d_s[i], b = M.col[y][i];
              if (finite(a) && finite(b)) { xsData.push(a); ysData.push(b); }
            }
            if (xsData.length < FIT_MIN) continue;
            const fit = polyfit(Float64Array.from(xsData), Float64Array.from(ysData), 1);
            all.push([labelOf(y), M.campaigns[c].short, M.rungs[r], xsData.length, pearson(xsData, ysData), fit]);
          }
        }
      }
      const head2 = ['probe', 'campaign', 'N', 'readings', 'r', 'slope', 'at d_s = 0', 'R²', 'rms'];
      const two = h('table', null, h('thead', null, h('tr', null, head2.map((x, i) => h('th', { class: i > 2 ? 'num' : i === 2 ? 'num' : null }, x)))),
        h('tbody', null, all.map(([y, c, n, count, r, fit]) => h('tr', null, h('td', null, y), h('td', null, c), h('td', { class: 'num' }, fmtInt(n)),
          h('td', { class: 'num' }, fmtInt(count)), h('td', { class: 'num' }, fmt(r, 3)), h('td', { class: 'num' }, fit ? fmt(fit.coef[1], 3) : ''),
          h('td', { class: 'num' }, fit ? fmt(fit.coef[0], 3) : ''), h('td', { class: 'num' }, fit ? fmt(fit.r2, 3) : ''), h('td', { class: 'num' }, fit ? fmt(fit.rms, 3) : '')))));
      tables.replaceChildren(h('h2', { style: 'font-size:14px;margin:16px 0 4px' }, 'The curves, rung by rung'), h('div', { class: 'tablewrap' }, one),
        h('h2', { style: 'font-size:14px;margin:16px 0 4px' }, 'Every probe against d_s, a line a rung'), h('div', { class: 'tablewrap' }, two),
        h('button', { class: 'btn', type: 'button', onclick: () => download('curves.csv', csvOf(head2, all.map(([y, c, n, count, r, fit]) => [y, c, n, count, r, fit && fit.coef[1], fit && fit.coef[0], fit && fit.r2, fit && fit.rms]))) }, 'Download the probes table'));
    });
  }

  function pageCounts() {
    const rules = D.rules;
    UI.main.append(h('p', { class: 'note' }, `The readings that pass the filters, each law at each rung where it read d_s and its mean degree k: `
      + `at a whole-number k (a regular graph) within ${rules.whole}, and at the probe's ceiling, d_s at least `
      + `${Math.round(rules.at_ceiling * 100)}% of the largest d_s any law of the study read at that N.`));
    const head = ['campaign', 'N', 'laws', 'whole k', 'at the ceiling'];
    const rows = [];
    for (const c of M.campaigns) {
      if (S.f.campaigns && !S.f.campaigns.includes(c.index)) continue;
      for (let r = 0; r < M.rungs.length; r++) {
        let laws = 0, whole = 0, ceil = 0;
        for (let i = 0; i < M.nRows; i++) {
          if (!MASK[i] || M.rowRung[i] !== r || M.rowCampaign[i] !== c.index || !M.whole[i] || !(M.col.d_s && finite(M.col.d_s[i]))) continue;
          laws++;
          if (M.atCeil[i] === 1) ceil++;
          if (M.whole[i] === 1) whole++;
        }
        if (!laws) continue;
        rows.push([`${c.short} ${c.regime !== 'not set' ? c.regime : c.label}`, M.rungs[r], laws, whole, ceil]);
      }
    }
    const pctCell = (a, b) => h('td', { class: 'num' }, `${fmtInt(a)} (${pct(a, b)})`);
    UI.main.append(h('h2', { style: 'font-size:14px;margin:8px 0 4px' }, 'Whole degrees and the ceiling'), h('div', { class: 'tablewrap' }, h('table', null,
      h('thead', null, h('tr', null, head.map((x, i) => h('th', { class: i > 0 ? 'num' : null }, x)))),
      h('tbody', null, rows.map((r) => h('tr', null, h('td', null, r[0]), h('td', { class: 'num' }, fmtInt(r[1])), h('td', { class: 'num' }, fmtInt(r[2])),
        pctCell(r[3], r[2]), pctCell(r[4], r[2])))))));
    UI.main.append(h('button', { class: 'btn', type: 'button', onclick: () => download('whole_degrees.csv', csvOf(head, rows)) }, 'Download the table'));
    const head2 = ['N', 'laws read d_s (study)', 'largest d_s (study)', '99th percentile (study)', 'read here', 'largest here', 'median here'];
    const rows2 = M.rungs.map((n, r) => {
      const study = (D.ceiling || {})[String(n)] || {};
      const values = [];
      for (let i = 0; i < M.nRows; i++) if (MASK[i] && M.rowRung[i] === r && M.col.d_s && finite(M.col.d_s[i])) values.push(M.col.d_s[i]);
      const s = sortedOf(values);
      return [n, study.laws, study.max, study.p99, values.length, values.length ? s[s.length - 1] : NaN, quantile(s, 0.5)];
    });
    UI.main.append(h('h2', { style: 'font-size:14px;margin:16px 0 4px' }, "The probe's ceiling"),
      h('p', { class: 'note' }, 'The spectral dimension is read from a walk\'s return probability over the times a graph of N nodes allows, so it has a '
        + 'ceiling that grows with N, and a graph denser than the ceiling\'s degree reads the ceiling, not itself. Below it a reading is the graph\'s.'),
      h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, head2.map((x) => h('th', { class: 'num' }, x)))),
        h('tbody', null, rows2.map((r) => h('tr', null, h('td', { class: 'num' }, fmtInt(r[0])), h('td', { class: 'num' }, fmtInt(r[1])),
          h('td', { class: 'num' }, fmt(r[2])), h('td', { class: 'num' }, fmt(r[3])), h('td', { class: 'num' }, fmtInt(r[4])),
          h('td', { class: 'num' }, fmt(r[5])), h('td', { class: 'num' }, fmt(r[6]))))))));
    const cats = M.cats.filter((c) => c.lawCode && c.values.length <= 40 && ['cls', 'fate', 'kind', 'role', 'given_top', 'from_empty_top'].includes(c.key));
    if (cats.length) {
      const cards = h('div', { class: 'cards' });
      for (const cat of cats) {
        const counts = new Array(cat.values.length).fill(0);
        for (let l = 0; l < M.nLaws; l++) if (M.lawVisible[l]) counts[cat.lawCode[l]]++;
        cards.append(h('div', { class: 'card' }, h('h3', null, cat.label), h('table', null, h('tbody', null,
          cat.values.map((v, i) => (counts[i] ? h('tr', null, h('td', null, pretty(v)), h('td', { class: 'num' }, fmtInt(counts[i]))) : null))))));
      }
      UI.main.append(h('h2', { style: 'font-size:14px;margin:16px 0 4px' }, 'The laws that pass the filters'), cards);
    }
    const found = patternSection();
    if (found) UI.main.append(...found);
  }

  function lawOps() {
    if (M.lawOps) return;
    const names = new Map();
    M.opNames = [];
    M.lawOps = Array.from({ length: M.nLaws }, (_, l) => {
      const set = new Set();
      for (const term of (D.laws.terms && D.laws.terms[l]) || []) {
        if (!names.has(term[0])) { names.set(term[0], M.opNames.length); M.opNames.push(term[0]); }
        set.add(names.get(term[0]));
      }
      return [...set];
    });
  }
  function patterns() {
    if (!D.laws.terms && !D.laws.beta) return null;
    lawOps();
    const here = new Uint8Array(M.nLaws), base = new Uint8Array(M.nLaws);
    let nh = 0, nb = 0;
    for (let l = 0; l < M.nLaws; l++) {
      if (!S.f.campaigns || S.f.campaigns.includes(M.lawCampaign[l])) { base[l] = 1; nb++; }
      if (selCount ? SEL[l] && M.lawVisible[l] : M.lawVisible[l]) { here[l] = 1; nh++; }
    }
    if (!nh || !nb) return null;
    const ops = M.opNames.map((name, o) => ({ name, here: 0, base: 0, o }));
    for (let l = 0; l < M.nLaws; l++) {
      for (const o of M.lawOps[l]) { if (base[l]) ops[o].base++; if (here[l]) ops[o].here++; }
    }
    for (const op of ops) { op.share = op.here / nh; op.baseShare = op.base / nb; op.lift = op.baseShare ? op.share / op.baseShare : NaN; }
    ops.sort((a, b) => (b.lift || 0) - (a.lift || 0) || b.here - a.here);
    const numbers = ['beta', 'locality', 'swap', 'sweeps'].filter((k) => D.laws[k]).map((k) => {
      const a = [], b = [];
      for (let l = 0; l < M.nLaws; l++) {
        const v = D.laws[k][l];
        if (v == null) continue;
        if (here[l]) a.push(v);
        if (base[l]) b.push(v);
      }
      const sa = sortedOf(a), sb = sortedOf(b);
      return { key: k, label: (D.law_fields.find((f) => f.key === k) || {}).label || k, q25: quantile(sa, 0.25), q50: quantile(sa, 0.5),
        q75: quantile(sa, 0.75), base50: quantile(sb, 0.5), base25: quantile(sb, 0.25), base75: quantile(sb, 0.75) };
    });
    const cats = ['kind', 'move', 'fate'].map((k) => M.catOf.get(k)).filter(Boolean).map((cat) => {
      const ch = new Array(cat.values.length).fill(0), cb = new Array(cat.values.length).fill(0);
      for (let l = 0; l < M.nLaws; l++) { if (here[l]) ch[cat.lawCode[l]]++; if (base[l]) cb[cat.lawCode[l]]++; }
      return { cat, rows: cat.values.map((v, i) => ({ v, here: ch[i], share: ch[i] / nh, baseShare: cb[i] / nb })).filter((r) => r.share >= 0.005 || r.baseShare >= 0.005) };
    });
    return { nh, nb, ops, numbers, cats };
  }
  function patternSection() {
    const found = patterns();
    if (!found) return null;
    const { nh, nb, ops, numbers, cats } = found;
    const what = selCount ? `the ${fmtInt(nh)} selected laws` : `the ${fmtInt(nh)} laws that pass the filters`;
    const lift = (x) => (finite(x) ? `${fmt(x, 2)}x` : '');
    const out = [h('h2', { style: 'font-size:14px;margin:16px 0 4px' }, 'What these laws have'),
      h('p', { class: 'note' }, `What ${what} are made of, against all ${fmtInt(nb)} laws of their campaigns: an operator or a value `
        + 'well above 1x is what the filters picked out.')];
    if (ops.length) {
      out.push(h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ['operator', 'laws here', 'share here', 'share of all', 'over all']
        .map((x, i) => h('th', { class: i ? 'num' : null }, x)))), h('tbody', null, ops.map((op) => h('tr', null, h('td', { class: 'code' }, op.name),
        h('td', { class: 'num' }, fmtInt(op.here)), h('td', { class: 'num' }, pct(op.here, nh)), h('td', { class: 'num' }, pct(op.base, nb)),
        h('td', { class: 'num' }, lift(op.lift))))))));
    }
    if (numbers.length) {
      out.push(h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ['parameter', 'median here', 'middle half here', 'median of all', 'middle half of all']
        .map((x, i) => h('th', { class: i ? 'num' : null }, x)))), h('tbody', null, numbers.map((n) => h('tr', null, h('td', null, n.label),
        h('td', { class: 'num' }, fmt(n.q50)), h('td', { class: 'num' }, `${fmt(n.q25)} to ${fmt(n.q75)}`), h('td', { class: 'num' }, fmt(n.base50)),
        h('td', { class: 'num' }, `${fmt(n.base25)} to ${fmt(n.base75)}`)))))));
    }
    const cards = h('div', { class: 'cards' });
    for (const { cat, rows } of cats) {
      cards.append(h('div', { class: 'card' }, h('h3', null, cat.label), h('table', null, h('thead', null, h('tr', null, h('th', null, ''), h('th', { class: 'num' }, 'here'), h('th', { class: 'num' }, 'of all'))),
        h('tbody', null, rows.map((r) => h('tr', null, h('td', null, pretty(r.v)), h('td', { class: 'num' }, `${Math.round(100 * r.share)}%`),
          h('td', { class: 'num' }, `${Math.round(100 * r.baseShare)}%`)))))));
    }
    out.push(cards);
    return out;
  }

  const SCAN_PARENTS = { ds_dV: ['d_s', 'd_V'], ds_dB: ['d_s', 'd_B'], walk_ds: ['d_V', 'd_w'],
    walk_ds_B: ['d_B', 'd_w'], ceiling_share: ['d_s'], k_frac: ['k'], d_s_beyond_k: ['d_s', 'k'], d_V_beyond_k: ['d_V', 'k'],
    d_B_beyond_k: ['d_B', 'k'], d_w_beyond_k: ['d_w', 'k'], kappa_beyond_k: ['kappa', 'k'],
    family_distance: ['d_s', 'd_V', 'd_B', 'd_w'] };
  function related(a, b) {
    const pa = new Set([a, ...(SCAN_PARENTS[a] || [])]), pb = new Set([b, ...(SCAN_PARENTS[b] || [])]);
    if (pa.has(b) || pb.has(a)) return true;
    for (const x of pa) if (x !== 'k' && pb.has(x)) return true;
    return false;
  }
  const SCAN_FAMILIES = [['reach', 'diameter', 'gap'], ['clustering', 'triangles']];
  function tied(a, b) { return SCAN_FAMILIES.some((f) => f.includes(a) && f.includes(b)); }
  function scanFields() {
    const keep = ['law.beta', 'law.locality', 'law.swap', 'law.sweeps'];
    return M.numbers.map((f) => f.key).filter((k) => k !== 'n' && k !== 'ceiling_share' && !/_se$/.test(k)
      && (!k.startsWith('law.') || keep.includes(k)));
  }
  function ranksOf(col, rows) {
    const out = new Float64Array(rows.length).fill(NaN);
    const at = [];
    rows.forEach((i, j) => { if (finite(col[i])) at.push(j); });
    at.sort((a, b) => col[rows[a]] - col[rows[b]]);
    for (let s0 = 0; s0 < at.length;) {
      let e = s0;
      while (e + 1 < at.length && col[rows[at[e + 1]]] === col[rows[at[s0]]]) e++;
      const r = (s0 + e) / 2;
      for (let q = s0; q <= e; q++) out[at[q]] = r;
      s0 = e + 1;
    }
    return out;
  }
  function corr(sx, sy, sxx, syy, sxy, n) {
    const vx = sxx - (sx * sx) / n, vy = syy - (sy * sy) / n;
    return vx > 0 && vy > 0 ? (sxy - (sx * sy) / n) / Math.sqrt(vx * vy) : NaN;
  }
  function valley(values) {
    const n = values.length;
    if (n < 30) return 0;
    const s = sortedOf(values), lo = s[0], hi = s[n - 1];
    if (!(hi > lo)) return 0;
    const sd = Math.sqrt(values.reduce((t, v) => t + v * v, 0) / n - (values.reduce((t, v) => t + v, 0) / n) ** 2);
    const spread = Math.min(sd, (quantile(s, 0.75) - quantile(s, 0.25)) / 1.349) || sd;
    const bins = 64, width = (hi - lo) / bins, band = Math.max(1, (0.9 * spread * n ** -0.2) / width);
    const hist = new Float64Array(bins);
    for (const v of values) hist[Math.min(bins - 1, Math.floor((v - lo) / width))]++;
    const smooth = new Float64Array(bins), reach = Math.ceil(3 * band);
    for (let i = 0; i < bins; i++) {
      let t = 0, w = 0;
      for (let j = Math.max(0, i - reach); j <= Math.min(bins - 1, i + reach); j++) {
        const k = Math.exp(-0.5 * ((i - j) / band) ** 2);
        t += k * hist[j]; w += k;
      }
      smooth[i] = t / w;
    }
    const peaks = [];
    for (let i = 0; i < bins; i++) {
      if ((i === 0 || smooth[i] > smooth[i - 1]) && (i === bins - 1 || smooth[i] >= smooth[i + 1])) peaks.push(i);
    }
    if (peaks.length < 2) return 0;
    peaks.sort((a, b) => smooth[b] - smooth[a]);
    const below = new Float64Array(bins + 1);
    for (let i = 0; i < bins; i++) below[i + 1] = below[i] + hist[i];
    let best = 0;
    for (const other of peaks.slice(1, 6)) {
      const [a, b] = [Math.min(peaks[0], other), Math.max(peaks[0], other)];
      let low = Infinity, at = a;
      for (let i = a; i <= b; i++) if (smooth[i] < low) { low = smooth[i]; at = i; }
      const lower = Math.min(smooth[a], smooth[b]), left = below[at + 1] / n;
      if (lower >= 0.1 * smooth[peaks[0]] && left >= 0.1 && left <= 0.9) best = Math.max(best, 1 - low / lower);
    }
    return best;
  }
  function lumpy(values) {
    const s = sortedOf(values), lo = quantile(s, 0.05), step = (quantile(s, 0.95) - lo) / 200;
    if (!(step > 0)) return true;
    const counts = new Map();
    for (const v of values) { const level = Math.round((v - lo) / step); counts.set(level, (counts.get(level) || 0) + 1); }
    const top = [...counts.values()].sort((a, b) => b - a).slice(0, 10).reduce((t, c) => t + c, 0);
    return top >= 0.5 * values.length;
  }
  function bimodality(xs, ys) {
    const n = xs.length;
    if (n < 30 || lumpy(xs) || lumpy(ys)) return NaN;
    const scaled = (v) => { const s = sortedOf(v), m = quantile(s, 0.5), q = (quantile(s, 0.75) - quantile(s, 0.25)) / 1.349 || 1;
      return v.map((x) => (x - m) / q); };
    const ra = scaled(xs), rb = scaled(ys), keep = ra.map((x, j) => Math.abs(x) < 4 && Math.abs(rb[j]) < 4);
    const a = ra.filter((_, j) => keep[j]), b = rb.filter((_, j) => keep[j]);
    if (a.length < 30) return NaN;
    let saa = 0, sbb = 0, sab = 0;
    for (let j = 0; j < a.length; j++) { saa += a[j] * a[j]; sbb += b[j] * b[j]; sab += a[j] * b[j]; }
    const theta = 0.5 * Math.atan2(2 * sab, saa - sbb), c = Math.cos(theta), s = Math.sin(theta);
    return valley(a.map((x, j) => c * x + s * b[j]));
  }
  let scanCache = null;
  function scan(by, min) {
    const key = `${by}|${min}|${S.scan.tied}|${maskCount}|${JSON.stringify(S.f)}`;
    if (scanCache && scanCache.key === key) return scanCache.result;
    const fields = scanFields();
    const groups = by === 'regime' ? regimeGroups().map((g) => ({ ...g, camps: M.campaigns.map((c) => c.index) }))
      : by === 'all' ? [{ label: 'every campaign', camps: M.campaigns.map((c) => c.index) }]
        : M.campaigns.map((c) => ({ label: c.tag, camps: [c.index] }));
    const out = [];
    groups.forEach((g, gi) => {
      const inGroup = new Uint8Array(M.campaigns.length);
      for (const c of g.camps) inGroup[c] = 1;
      for (let r = 0; r < M.rungs.length; r++) {
        const rows = [];
        for (let i = 0; i < M.nRows; i++) {
          if (MASK[i] && M.rowRung[i] === r && inGroup[M.rowCampaign[i]] && (g.regime == null || M.rowRegime[i] === g.regime)) rows.push(i);
        }
        if (rows.length < min) continue;
        const ranks = {};
        for (const f of fields) ranks[f] = ranksOf(M.col[f], rows);
        const kr = ranks.k;
        for (let a = 0; a < fields.length; a++) {
          for (let b = a + 1; b < fields.length; b++) {
            const x = fields[a], y = fields[b];
            if (related(x, y) || (!S.scan.tied && tied(x, y))) continue;
            const rx = ranks[x], ry = ranks[y];
            let n = 0, sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
            let n3 = 0, tx = 0, ty = 0, tk = 0, txx = 0, tyy = 0, tkk = 0, txy = 0, txk = 0, tyk = 0;
            for (let j = 0; j < rows.length; j++) {
              const u = rx[j], v = ry[j];
              if (!(u === u) || !(v === v)) continue;
              n++; sx += u; sy += v; sxx += u * u; syy += v * v; sxy += u * v;
              const w = kr ? kr[j] : NaN;
              if (w === w && x !== 'k' && y !== 'k') {
                n3++; tx += u; ty += v; tk += w; txx += u * u; tyy += v * v; tkk += w * w; txy += u * v; txk += u * w; tyk += v * w;
              }
            }
            if (n < min) continue;
            const rho = corr(sx, sy, sxx, syy, sxy, n);
            if (!finite(rho)) continue;
            let partial = NaN;
            if (n3 >= min) {
              const a1 = corr(tx, ty, txx, tyy, txy, n3), a2 = corr(tx, tk, txx, tkk, txk, n3), a3 = corr(ty, tk, tyy, tkk, tyk, n3);
              const d = Math.sqrt((1 - a2 * a2) * (1 - a3 * a3));
              partial = d > 1e-6 ? (a1 - a2 * a3) / d : NaN;
            }
            out.push({ x, y, g: gi, group: g.label, camps: g.camps, r, n: M.rungs[r], count: n, rho, partial });
          }
        }
      }
    });
    scanCache = { key, result: { rows: out, groups } };
    return scanCache.result;
  }
  function scanShape(row, min) {
    if (row.shape) return row.shape;
    const xs = [], ys = [];
    for (let i = 0; i < M.nRows; i++) {
      if (!MASK[i] || M.rowRung[i] !== row.r || !row.camps.includes(M.rowCampaign[i])) continue;
      const a = M.col[row.x][i], b = M.col[row.y][i];
      if (finite(a) && finite(b)) { xs.push(a); ys.push(b); }
    }
    let curved = NaN;
    if (xs.length >= min) {
      const order = xs.map((_, j) => j).sort((a, b) => xs[a] - xs[b]);
      const yr = ranksOf(Float64Array.from(ys), ys.map((_, j) => j));
      const bins = 10, sums = new Array(bins).fill(0), counts = new Array(bins).fill(0);
      order.forEach((j, q) => { const b = Math.min(bins - 1, Math.floor((q / order.length) * bins)); sums[b] += yr[j]; counts[b]++; });
      const mean = (yr.length - 1) / 2;
      let sst = 0, ssb = 0;
      for (const v of yr) sst += (v - mean) ** 2;
      for (let b = 0; b < bins; b++) if (counts[b]) ssb += counts[b] * (sums[b] / counts[b] - mean) ** 2;
      curved = sst > 0 ? ssb / sst - row.rho * row.rho : NaN;
    }
    row.shape = { curved, bimodal: bimodality(xs, ys) };
    return row.shape;
  }
  function showPair(row, how) {
    if (how === 'byn') {
      S.byn = { ...S.byn, x: row.x, y: row.y, color: 'campaign', range: DIMENSIONS.has(row.x) && DIMENSIONS.has(row.y) ? 'std' : 'data',
        split: S.scan.by === 'regime' ? 'regime' : S.scan.by === 'campaign' ? 'campaign' : 'together' };
      S.focus = null;
      go('byn');
      return;
    }
    S.scanSpec = panelSpec({ x: row.x, y: row.y, color: row.r == null ? 'rung' : 'campaign', camps: row.camps,
      camp: row.camps.length === 1 ? row.camps[0] : -1, rung: row.n ?? null,
      range: DIMENSIONS.has(row.x) && DIMENSIONS.has(row.y) ? 'std' : 'data', trend: 'median' });
    S.page = 'maps';
    S.focus = { page: 'maps', key: 'scan', back: 'scan' };
    for (const b of UI.tabs.children) b.setAttribute('aria-selected', String(b.dataset.page === 'maps'));
    renderSide();
    renderPage();
    save();
  }

  function pageScan() {
    const sc = S.scan;
    const set = (k) => (v) => { sc[k] = k === 'min' ? +v : v; renderPage(); save(); };
    UI.main.append(h('div', { class: 'toolbar' },
      h('label', null, 'within', selectOf([['campaign', 'each campaign'], ['regime', 'each temperature'], ['all', 'every campaign together']], sc.by, set('by'))),
      h('label', null, 'at least', selectOf([[30, '30'], [50, '50'], [100, '100'], [200, '200']], sc.min, set('min')), 'readings'),
      h('label', { title: 'the reach, the diameter and the spectral gap are the graph\'s size three ways; clustering counts triangles' },
        h('input', { type: 'checkbox', checked: sc.tied ? true : null, onchange: (e) => { sc.tied = e.target.checked; renderPage(); save(); } }),
        'pair the fields the definitions tie')),
    h('p', { class: 'note' }, 'Every pair of fields, in each campaign (or temperature) and at each N, among the readings that pass the filters, '
      + 'measured and ranked so the maps worth a look come first. rho: the rank correlation (Spearman), how strongly the two move together, '
      + 'from -1 to 1. given k: the same with the mean degree held (a partial rank correlation): what is left once the degree, which explains '
      + 'almost everything (finding 1), is taken out. curved: how much more of the relation a curve explains than a line. two clouds: '
      + 'how deep the valley between the two highest modes along the cloud\'s main axis is, 0 for one cloud and near 1 for two that part '
      + 'cleanly (a pair with a field read at few values, a whole degree or a diameter, is not scored). A field '
      + 'and one made from it (d_s and d_s - (k - 1)) are not paired, nor (unless asked) fields the definitions tie (the reach, the '
      + 'diameter and the spectral gap; clustering and triangles). A high score is a lead, not a finding: hundreds of pairs are tried, so '
      + 'look for one that holds at the next N too.'));
    const holder = h('div', null, h('p', { class: 'note' }, 'Measuring every pair...'));
    UI.main.append(holder);
    setTimeout(() => {
      const t0 = performance.now();
      const { rows } = scan(sc.by, sc.min);
      const show = (row, label, how) => h('button', { class: 'btn', type: 'button', onclick: () => showPair(row, how) }, label);
      const pair = (row) => `${shortOf(row.y)} against ${shortOf(row.x)}`;
      const num = (v, d) => h('td', { class: 'num' }, fmt(v, d == null ? 2 : d));
      const beyond = rows.filter((r) => finite(r.partial)).sort((a, b) => Math.abs(b.partial) - Math.abs(a.partial)).slice(0, 40);
      const by = new Map();
      for (const r of rows) {
        const k = `${r.x}|${r.y}|${r.g}`;
        if (!by.has(k)) by.set(k, []);
        by.get(k).push(r);
      }
      const moving = [...by.values()].filter((list) => list.length >= 3).map((list) => {
        list.sort((a, b) => a.n - b.n);
        const rhos = list.map((r) => r.rho).filter(finite);
        return { list, range: Math.max(...rhos) - Math.min(...rhos), first: list[0] };
      }).sort((a, b) => b.range - a.range).slice(0, 30);
      let temps = [];
      if (sc.by === 'regime') {
        const at = new Map();
        for (const r of rows) {
          const k = `${r.x}|${r.y}|${r.r}`;
          if (!at.has(k)) at.set(k, {});
          at.get(k)[r.group] = r;
        }
        temps = [...at.values()].filter((v) => v['zero temperature'] && v['finite temperature'])
          .map((v) => ({ zero: v['zero temperature'], fin: v['finite temperature'], diff: Math.abs(v['zero temperature'].rho - v['finite temperature'].rho) }))
          .filter((v) => finite(v.diff)).sort((a, b) => b.diff - a.diff).slice(0, 30);
      }
      const candidates = [...new Set([...beyond, ...rows.filter((r) => r.count >= 2 * sc.min && finite(r.rho)).sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho))])];
      const until = performance.now() + 1500;
      let measured = 0;
      for (const r of candidates) {
        if (performance.now() > until) break;
        scanShape(r, sc.min);
        measured++;
      }
      candidates.length = measured;
      const clouds = candidates.filter((r) => finite(r.shape.bimodal) && r.shape.bimodal >= 0.5).sort((a, b) => b.shape.bimodal - a.shape.bimodal).slice(0, 25);
      const table = (cells, list, cellsOf) => h('div', { class: 'tablewrap' }, h('table', null,
        h('thead', null, h('tr', null, cells.map((x, i) => h('th', { class: i >= 2 && x ? 'num' : null }, x)))),
        h('tbody', null, list.map((item) => h('tr', null, cellsOf(item))))));
      const heading = (text) => h('h2', { style: 'font-size:14px;margin:16px 0 4px' }, text);
      const sections = [];
      sections.push(heading('What holds beyond the degree'),
        h('p', { class: 'note' }, 'The pairs whose relation is strongest once the mean degree is held: structure the degree does not explain.'),
        table(['pair', 'within', 'N', 'readings', 'rho', 'given k', 'curved', 'two clouds', ''], beyond, (r) => {
          const sh = scanShape(r, sc.min);
          return [h('td', null, pair(r)), h('td', null, r.group), h('td', { class: 'num' }, fmtInt(r.n)), h('td', { class: 'num' }, fmtInt(r.count)),
            num(r.rho), num(r.partial), num(sh.curved), num(sh.bimodal), h('td', null, show(r, 'show', 'map'))];
        }));
      sections.push(heading('What changes as N grows'),
        h('p', { class: 'note' }, 'The pairs whose rank correlation moves most from rung to rung (three rungs or more): a relation that forms, '
          + 'fades or turns as the graphs grow.'),
        table(['pair', 'within', 'rho by N', 'range', ''], moving, (m) => [h('td', null, pair(m.first)), h('td', null, m.first.group),
          h('td', null, m.list.map((r) => `${fmtN(r.n)} ${fmt(r.rho, 2)}`).join(' · ')), num(m.range), h('td', null, show(m.first, 'by N', 'byn'))]));
      if (sc.by === 'regime') {
        sections.push(heading('What differs between the temperatures'),
          h('p', { class: 'note' }, 'The pairs whose rank correlation differs most between zero and finite temperature at the same N.'),
          table(['pair', 'N', 'rho, zero', 'rho, finite', 'difference', ''], temps, (t) => [h('td', null, pair(t.zero)),
            h('td', { class: 'num' }, fmtInt(t.zero.n)), num(t.zero.rho), num(t.fin.rho), num(t.diff),
            h('td', null, show(t.zero, 'zero', 'map'), ' ', show(t.fin, 'finite', 'map'))]));
      } else {
        sections.push(h('p', { class: 'note' }, 'Within each temperature (above), the scan also lists what differs between the two.'));
      }
      sections.push(heading('Clouds that split in two'),
        h('p', { class: 'note' }, 'Among the strongest pairs, those whose cloud parts in two (two clouds 0.5 or more: the valley at most half '
          + 'the lower mode, as the walk\'s rings and random wirings at finite temperature): two kinds of graph, or a probe reading two ways.'),
        table(['pair', 'within', 'N', 'readings', 'rho', 'given k', 'curved', 'two clouds', ''], clouds, (r) => [h('td', null, pair(r)),
          h('td', null, r.group), h('td', { class: 'num' }, fmtInt(r.n)), h('td', { class: 'num' }, fmtInt(r.count)), num(r.rho), num(r.partial),
          num(r.shape.curved), num(r.shape.bimodal), h('td', null, show(r, 'show', 'map'))]),
        h('p', { class: 'note' }, `${fmtInt(rows.length)} pairs measured, ${fmtInt(measured)} of them for their shape, in `
          + `${Math.round(performance.now() - t0)} ms.`));
      holder.replaceChildren(...sections);
    }, 30);
  }

  function topRow(l) {
    let best = -1;
    for (const i of M.lawRows[l]) if (MASK[i] && (best < 0 || M.col.n[i] > M.col.n[best])) best = i;
    return best;
  }
  function pageLaws() {
    const st = S.laws, L = D.laws;
    const list = [];
    for (let l = 0; l < M.nLaws; l++) if ((selCount ? SEL[l] : M.lawVisible[l]) && (selCount || M.lawVisible[l])) list.push(l);
    const cols = [
      ['law', (l) => L.id[l], 'text'], ...(L.label ? [['label', (l) => L.label[l] || '', 'text']] : []),
      ['campaign', (l) => M.campaigns[M.lawCampaign[l]].short, 'text'],
      ...(L.role ? [['role', (l) => L.role[l] || '', 'text']] : []),
      ...(L.fate ? [['fate', (l) => L.fate[l] || '', 'text']] : []),
      ...(L.cls ? [['class', (l) => L.cls[l] || '', 'text']] : []),
      ...(L.nearest ? [['nearest family', (l) => L.nearest[l] || '', 'text']] : []),
      ['top N', (l) => { const i = topRow(l); return i < 0 ? NaN : M.col.n[i]; }, 'int', 'n_top'],
      ...['d_s', 'd_V', 'd_B', 'd_w', 'k', 'kappa', 'given_d_s'].filter((k) => M.col[k]).map((k) => [labelOf(k).split(' (')[0], (l) => { const i = topRow(l); return i < 0 ? NaN : M.col[k][i]; }, 'num', k]),
      ...(L.terms ? [['terms', (l) => termsText(L.terms[l]), 'terms']] : []),
    ];
    const sortCol = cols.find((c) => (c[3] || c[0]) === st.sort) || cols.find((c) => c[3] === 'n_top');
    const keyOf = sortCol[1];
    const vals = new Map(list.map((l) => [l, keyOf(l)]));
    list.sort((a, b) => {
      const x = vals.get(a), y = vals.get(b);
      if (typeof x === 'number' || typeof y === 'number') {
        const fx = finite(x), fy = finite(y);
        if (fx !== fy) return fx ? -1 : 1;
        return (x - y) * st.dir || a - b;
      }
      return String(x).localeCompare(String(y)) * st.dir || a - b;
    });
    const pages = Math.max(1, Math.ceil(list.length / 100));
    st.page = Math.min(st.page, pages - 1);
    const shown = list.slice(st.page * 100, st.page * 100 + 100);
    UI.main.append(h('p', { class: 'note' }, selCount ? `The ${fmtInt(selCount)} selected laws, at the largest rung each read among the readings that pass the filters.`
      : `Every law with a reading that passes the filters (${fmtInt(list.length)}), at the largest rung it read. Select laws on a map to list only them.`));
    const pager = h('div', { class: 'pager' },
      h('button', { class: 'btn', type: 'button', disabled: st.page === 0 ? true : null, onclick: () => { st.page--; renderPage(); } }, 'previous'),
      h('span', { class: 'count' }, `page ${st.page + 1} of ${pages}`),
      h('button', { class: 'btn', type: 'button', disabled: st.page >= pages - 1 ? true : null, onclick: () => { st.page++; renderPage(); } }, 'next'),
      h('button', { class: 'btn', type: 'button', onclick: () => exportRows(Boolean(selCount)) }, 'Download every reading of these laws'));
    const table = h('table', null, h('thead', null, h('tr', null, cols.map((c) => {
      const key = c[3] || c[0];
      return h('th', { class: `sortable${key === st.sort ? ` sorted${st.dir > 0 ? ' up' : ''}` : ''}${c[2] === 'num' || c[2] === 'int' ? ' num' : ''}`,
        onclick: () => { st.dir = key === st.sort ? -st.dir : (c[2] === 'text' || c[2] === 'terms' ? 1 : -1); st.sort = key; renderPage(); save(); } }, c[0]);
    }))), h('tbody', null, shown.map((l) => h('tr', { class: `clickable${st.open === l ? ' picked' : ''}`, onclick: () => { st.open = st.open === l ? -1 : l; renderPage(); } },
      cols.map((c) => {
        const v = c[1](l);
        return h('td', { class: c[2] === 'num' || c[2] === 'int' ? 'num' : c[2] === 'terms' ? 'code terms' : c[0] === 'law' ? 'code' : null,
          title: c[2] === 'terms' ? v : null }, c[2] === 'num' ? fmt(v) : c[2] === 'int' ? fmtInt(v) : c[2] === 'text' ? pretty(v) : v);
      })))));
    UI.main.append(pager, h('div', { class: 'tablewrap' }, table));
    if (st.open >= 0 && st.open < M.nLaws) UI.main.append(lawDetail(st.open));
  }
  function lawDetail(l) {
    const keys = ['n', ...D.row_fields.map((f) => f.key).filter((k) => k !== 'n'), ...M.derived.map((f) => f.key)].filter((k) => M.col[k]);
    const rows = M.lawRows[l];
    return h('div', null, h('h2', { style: 'font-size:14px;margin:12px 0 4px' }, `Law ${D.laws.id[l]}, every rung`),
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: () => setSelection([l], 'replace') }, 'Select only this law'),
        h('button', { class: 'btn', type: 'button', onclick: () => { setSelection([l], 'replace'); go('maps'); } }, 'Show it on the maps')),
      lawCard(l),
      h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, keys.map((k) => h('th', { class: 'num', title: (M.numberOf.get(k) || {}).what }, labelOf(k))))),
        h('tbody', null, rows.map((i) => h('tr', null, keys.map((k) => h('td', { class: 'num' }, k === 'n' ? fmtInt(M.col.n[i]) : fmt(M.col[k][i])))))))));
  }
  function exportRows(selectedOnly) {
    const keys = ['n', ...D.row_fields.map((f) => f.key).filter((k) => k !== 'n')];
    const lawKeys = D.law_fields.map((f) => f.key).filter((k) => k !== 'campaign');
    const head = ['campaign', ...lawKeys, ...keys];
    const out = [];
    for (let i = 0; i < M.nRows; i++) {
      const l = M.rowLaw[i];
      if (!MASK[i] || (selectedOnly && !SEL[l])) continue;
      out.push([M.campaigns[M.lawCampaign[l]].id, ...lawKeys.map((k) => (k === 'terms' ? termsText(D.laws.terms[l]) : D.laws[k][l])), ...keys.map((k) => (finite(M.col[k][i]) ? M.col[k][i] : ''))]);
    }
    download(`study_${(D.study || {}).study_id || ''}_${selectedOnly ? 'selection' : 'filtered'}.csv`, csvOf(head, out));
  }

  function pageAbout() {
    const study = D.study || {};
    const dl = (items) => h('dl', null, items.map(([t, d]) => [h('dt', null, t), h('dd', null, d)]));
    UI.main.append(h('div', { class: 'about' },
      h('h2', null, 'What this is'),
      h('p', null, `${D.title}. Every law of the study at every rung where it read a probe or its mean degree: ${fmtInt(M.nLaws)} laws, `
        + `${fmtInt(M.nRows)} readings, from each campaign's report 05 (the phenotypes) and report 28 (the law ledger), read when the bundle was made`
        + `${study.built_utc ? ` (${study.built_utc}, build ${study.build_number || '?'})` : ''}. The page stands alone: its data is inside it and it fetches nothing.`),
      h('h2', null, 'How to use it'),
      h('ul', null, h('li', null, 'Start here: the views that carry what the study found, each one button that sets the filters and the panels, with what to look for. A good first hour.'),
        h('li', null, 'The filters on the left apply to every page. A preset sets the filters and the maps for one of the questions asked of the data.'),
        h('li', null, 'Maps: a grid of up to 4 x 4 panels. Click a panel\'s title for its settings: its axes (any two fields), its colour, its campaign and N, its range (standard: 0 to 8 for a dimension, the mean degree to half the cap; or fitted to the data; or your own), the reference lines and a trend.'),
        h('li', null, 'The button at the top right of a panel makes it fill the grid\'s space; the same button (back to the grid), or Esc, takes it back. It works on Maps, By N, Spread over N and Curves.'),
        h('li', null, 'Drag across any panel to select the laws there (shift adds, alt takes away, a click picks one, Esc clears): the selection is drawn on every panel, its laws joined across their rungs, and listed on the Laws page.'),
        h('li', null, 'By N draws one pair once a rung; Spread over N each law\'s field as N grows with its quantiles; Curves compresses each cloud to a curve a rung, with the numbers; Counts the degree map and the probe\'s ceiling on what passes the filters.'),
        h('li', null, 'Scan: instead of trying plots, every pair of fields measured on what passes the filters, a rung and a temperature at a time, and ranked four ways: what two fields share beyond the mean degree (the partial rank correlation given k), what changes most as N grows, what differs most between the temperatures, and where a cloud is two clouds (a valley along its long axis). Each row opens its map, filling the page.'),
        h('li', null, 'Beyond the degree: d_s, d_V, d_B, d_w and the curvature each have a field less the median of the readings at the same rung, temperature and mean degree (to a quarter; five readings or more), so what the degree alone explains is taken out. Any panel can use them.'),
        h('li', null, 'A fitted line is drawn only over the middle 90% of its readings, and only where there are enough of them (30, and 10 a coefficient) spread wide enough; otherwise the Curves table says why there is none.'),
        h('li', null, 'The view is kept in the page\'s address (after #), so a bookmark or a copied link opens the same view.')),
      h('h2', null, 'The readings'), dl([...D.row_fields, ...M.derived].map((f) => [f.label, f.what])),
      h('h2', null, 'The laws'), dl(D.law_fields.map((f) => [f.label, f.what])),
      h('h2', null, 'The lines on the maps'),
      dl([['both read the same', 'the diagonal, where a plain grid sits on any two of d_s, d_V and d_B'], ['d_w = 2', 'ordinary diffusion; a fractal sits above'],
        ['the tree line, d_s = k - 1', 'where random wiring of the mean degree sits'], ["the probe's ceiling", `the largest d_s any law of the study read at that N; a reading at ${Math.round(D.rules.at_ceiling * 100)}% of it or more is the probe's, not the graph's`],
        ['the families', 'the calibration families where the instrument measured them: an ellipse of their spread over seeds at each N, joined dashed in the order of N; the instrument\'s own path on that pair'],
        ['the papers', "the published models run by their own rules and read by this instrument (docs/readings/replication_*.json), each model's cell at its N"]]),
      h('h2', null, 'The campaigns'), dl(M.campaigns.map((c) => [`${c.short} ${c.label}`, `${c.name || ''}; ${c.regime}${finite(c.cap) ? `; mean degree cap ${c.cap}` : ''}; ${fmtInt(c.laws)} laws`])),
      h('p', { class: 'note' }, `Data contract ${D.contract}.`)));
  }

  function save() {
    try {
      const view = { p: S.page, a: S.active, f: S.f, m: S.maps, b: S.byn, s: S.spread, c: S.curves, l: { sort: S.laws.sort, dir: S.laws.dir }, t: S.theme,
        fo: S.focus, sc: S.scan,
        sel: selCount && selCount <= 300 ? selectedIds() : null };
      history.replaceState(null, '', `#${encodeURIComponent(JSON.stringify(view))}`);
    } catch (e) {  }
  }
  function restore() {
    try {
      if (!location.hash || location.hash.length < 3) return;
      const view = JSON.parse(decodeURIComponent(location.hash.slice(1)));
      if (view.p && PAGES.some(([k]) => k === view.p)) S.page = view.p;
      if (Number.isInteger(view.a)) S.active = view.a;
      if (view.f) S.f = { ...S.f, ...view.f };
      if (view.m && Array.isArray(view.m.panels)) S.maps = { ...S.maps, ...view.m, panels: view.m.panels.map((p) => panelSpec(p)) };
      if (view.b) S.byn = { ...S.byn, ...view.b };
      if (view.s) S.spread = { ...S.spread, ...view.s };
      if (view.c) S.curves = { ...S.curves, ...view.c };
      if (view.l) S.laws = { ...S.laws, ...view.l };
      if (view.t) S.theme = view.t;
      if (view.fo && typeof view.fo.key === 'string') S.focus = view.fo;
      if (view.sc) S.scan = { ...S.scan, ...view.sc };
      if (Array.isArray(view.sel)) {
        const want = new Set(view.sel);
        for (let l = 0; l < M.nLaws; l++) if (want.has(D.laws.id[l])) SEL[l] = 1;
        selCount = SEL.reduce((a, b) => a + b, 0);
      }
    } catch (e) {  }
  }

  async function start() {
    const app = document.getElementById('app');
    let raw;
    try {
      raw = await decode();
    } catch (e) {
      app.replaceChildren(h('p', { class: 'failed' }, `The explorer could not open its data: ${e.message}`));
      return;
    }
    buildModel(raw);
    if (!M.nRows) {
      app.replaceChildren(h('header', { class: 'top' }, h('div', null, h('h1', null, D.title || 'Study explorer'))),
        h('p', { class: 'loading' }, 'No law of this study has read a probe or its mean degree yet: the explorer fills as '
          + "the campaigns' reports do."));
      window.__explorer = { ready: true, info: () => ({ page: 'empty', rows: 0, laws: M.nLaws, visible: 0, panels: 0, drawn: [] }) };
      document.dispatchEvent(new CustomEvent('explorer-ready'));
      return;
    }
    SEL = new Uint8Array(M.nLaws);
    S.maps.panels = defaultPanels();
    S.maps.cols = Math.min(4, Math.max(1, M.campaigns.length));
    restore();
    shell();
    applyTheme();
    computeMask();
    go(S.page);
    const again = debounce(() => { if (S.page === 'maps' && S.maps.fit) renderPage(); else redraw(); }, 120);
    new ResizeObserver(again).observe(UI.main);
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { colorCache.clear(); redraw(); });
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (focusedHere() !== null) unfocus();
      else if (selCount) setSelection([], 'replace');
    });
    window.__explorer = {
      ready: true, state: S, model: M, data: D,
      info() {
        return { page: S.page, rows: M.nRows, laws: M.nLaws, visible: maskCount, visibleLaws: M.visibleLaws, selected: selCount,
          panels: PANELS.length, drawn: PANELS.map((P) => (P.view ? P.view.idx.length : 0)) };
      },
      go, setSelection, changed, redraw, filters: () => S.f, views: VIEWS, presets: PRESETS, renderPage,
      shown() {
        const mp = S.maps, out = [];
        for (const P of PANELS) if (P.kind === 'scatter' && mp.panels.includes(P.spec)) out.push(panelKey(P.spec));
        return out;
      },
    };
    document.dispatchEvent(new CustomEvent('explorer-ready'));
  }
  start();
}());
