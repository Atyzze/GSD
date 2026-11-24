(function () {
  'use strict';

  const finite = Number.isFinite;
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    setAttrs(e, attrs);
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }
  function setAttrs(e, attrs) {
    if (!attrs) return;
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') e.setAttribute('class', v);
      else if (k === 'text') e.textContent = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k === 'style') e.style.cssText = v;
      else e.setAttribute(k, v === true ? '' : v);
    }
  }
  const SVGNS = 'http://www.w3.org/2000/svg';
  function s(tag, attrs, ...kids) {
    const e = document.createElementNS(SVGNS, tag);
    setAttrs(e, attrs);
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }
  const fmtInt = (v) => (finite(v) ? Math.round(v).toLocaleString('en-US') : '');
  function share(part, whole) {
    if (!whole) return '';
    const p = (100 * part) / whole;
    return p === 0 || p >= 10 ? `${Math.round(p)}%` : `${p.toFixed(1)}%`;
  }
  const pctOf = (v) => (v == null || !finite(v) ? 'n/a' : `${(100 * v).toFixed(1)}%`);
  const nLabel = (n) => `N=${fmtInt(n)}`;
  function sortedEntries(obj) {
    return Object.entries(obj || {}).filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  }
  const sum = (values) => values.reduce((a, b) => a + (+b || 0), 0);
  function download(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
    const a = h('a', { href: url, download: name });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }
  function csvOf(rows) {
    const cell = (v) => {
      const t = v == null ? '' : String(v);
      return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
    };
    return rows.map((r) => r.map(cell).join(',')).join('\n') + '\n';
  }

  let D;
  try {
    D = JSON.parse(document.getElementById('gate-trees-data').textContent);
  } catch (e) {
    document.getElementById('app').replaceChildren(h('p', { class: 'failed' }, `The page could not read its data: ${e.message}`));
    return;
  }
  const RULES = D.rules || {};
  const LINKS = D.links || {};
  const CAT = new Map((D.categories || []).map((c, i) => [c.key, { ...c, order: i }]));
  const STOP_STAGES = D.stop_stages || [];
  const COSTS = D.costs || [];
  const GATE_ORDER = D.gate_order || [];
  const CAMPS = (D.campaigns || []).map((c, i) => {
    const tree = c.tree || null;
    return { ...c, index: i, tree,
      rungs: new Map(((tree && tree.rungs) || []).map((r) => [Number(r.n), r])),
      gates: new Map(((tree && tree.gates) || []).map((g) => [g.gate, g])),
      hasGraphs: Boolean(tree && (tree.rungs || []).some((r) => r.graphs != null)) };
  });
  const ANY_GRAPHS = CAMPS.some((c) => c.hasGraphs);
  const PAGES = [['tree', 'Tree'], ['gates', 'Gates'], ['survival', 'Survival'], ['table', 'Table'], ['about', 'About']];
  const S = { page: 'tree', shown: null, measure: 'laws', scale: 'campaign', what: 'finished', ylog: false, theme: 'auto',
    open: {}, every: false };
  const UI = {};

  function shownCamps() { return CAMPS.filter((c) => !S.shown || S.shown.includes(c.id)); }
  function rungsOf(camps) {
    const all = new Set();
    for (const c of camps) for (const n of c.rungs.keys()) all.add(n);
    return [...all].sort((a, b) => a - b);
  }
  function campTitle(c) { return `Campaign ${c.id}`; }
  function catOf(key) { return CAT.get(key) || CAT.get('other'); }
  function stopCat(rule) {
    const stage = (RULES[rule] || {}).stage;
    return STOP_STAGES.includes(stage) ? stage : 'other';
  }
  function swatch(key) { return h('span', { class: 'swatch', style: `background: var(--cat-${catOf(key).slug})` }); }

  function segmentsOf(r, measure) {
    const segs = [];
    if (measure === 'graphs') {
      const g = r.graphs_by_branch || {};
      for (const key of ['on', 'done', 'held', 'stopped']) if (g[key] > 0) segs.push({ cat: key, rule: null, count: g[key] });
      if (r.graphs_in_progress > 0) segs.push({ cat: 'running', rule: null, count: r.graphs_in_progress });
      return segs;
    }
    for (const [rule, c] of sortedEntries(r.went_on_by)) segs.push({ cat: 'on', rule, count: c });
    if (r.done > 0) segs.push({ cat: 'done', rule: 'ladder_complete', count: r.done });
    for (const [rule, c] of sortedEntries(r.held)) segs.push({ cat: 'held', rule, count: c });
    for (const [rule, c] of sortedEntries(r.stopped)) segs.push({ cat: stopCat(rule), rule, count: c });
    const counted = sum(segs.map((x) => x.count));
    if ((r.finished || 0) > counted) segs.push({ cat: 'other', rule: null, count: r.finished - counted });
    segs.sort((a, b) => catOf(a.cat).order - catOf(b.cat).order);
    return segs;
  }
  function totalOf(r, measure) {
    return measure === 'graphs' ? (r.graphs || 0) + (r.graphs_in_progress || 0) : (r.finished || 0);
  }
  function unit(measure, count) { return measure === 'graphs' ? (count === 1 ? 'graph' : 'graphs') : (count === 1 ? 'law' : 'laws'); }
  function ruleWords(rule) {
    const r = RULES[rule];
    if (!r) return rule ? 'a rule outside the tree' : '';
    return r.kind === 'gate' ? r.reads : r.means;
  }
  function segTitle(seg, measure) {
    if (measure === 'graphs') return catOf(seg.cat).label;
    if (seg.cat === 'on') return `went on: ${seg.rule}`;
    if (seg.cat === 'done') return 'the ladder is done';
    if (seg.cat === 'held') return `held by ${seg.rule}`;
    return seg.rule ? `stopped by ${seg.rule}` : 'another decision';
  }

  function explorerHref(camp, rule, n, page) {
    if (!LINKS.explorer || camp.explorer == null || !rule) return null;
    const f = { campaigns: [camp.explorer], cats: { fate: [rule] }, ranges: [{ key: 'law.fate_n', min: n, max: n }] };
    const view = page === 'maps'
      ? { p: 'maps', f, m: { rows: 1, cols: 2, panels: [
        { x: 'k', y: 'd_s', color: 'rung', camp: -1, range: 'data', trend: 'none', papers: false },
        { x: 'n', y: 'k', color: 'rung', camp: -1, range: 'data', xlog: true, trend: 'median', fam: false, papers: false }] } }
      : { p: 'laws', f };
    return `${LINKS.explorer}#${encodeURIComponent(JSON.stringify(view))}`;
  }
  function fateCount(camp, rule, n) {
    const v = (camp.fates || {})[`${rule}|${n}`];
    return v == null ? null : v;
  }

  const tip = h('div', { class: 'tip', role: 'tooltip', style: 'display:none' });
  function showTip(x, y, lines) {
    tip.replaceChildren(...lines);
    tip.style.display = 'block';
    const w = tip.offsetWidth, ht = tip.offsetHeight;
    const left = Math.min(Math.max(8, x + 14), window.innerWidth - w - 8);
    const top = y + 16 + ht > window.innerHeight ? Math.max(8, y - ht - 12) : y + 16;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }
  function hideTip() { tip.style.display = 'none'; }
  function tipNear(el, lines) {
    const box = el.getBoundingClientRect();
    showTip(box.left + box.width / 2, box.bottom - 8, lines);
  }

  function shell() {
    const app = document.getElementById('app');
    app.replaceChildren();
    const study = D.study || {};
    UI.tabs = h('nav', { class: 'tabs', role: 'tablist' }, PAGES.map(([key, label]) => h('button', {
      type: 'button', role: 'tab', 'data-page': key, onclick: () => go(key) }, label)));
    UI.themeSel = h('select', { title: 'light, dark, or as the system is', 'aria-label': 'theme',
      onchange: (e) => { S.theme = e.target.value; applyTheme(); save(); } },
    ['auto', 'light', 'dark'].map((t) => h('option', { value: t }, t)));
    const laws = sum(CAMPS.map((c) => (c.tree && c.tree.laws) || 0));
    const sub = [study.built_utc ? `bundle of ${study.built_utc}` : '', study.build_number ? `made on build ${study.build_number}` : '',
      study.page_build && study.page_build !== study.build_number ? `this page written on build ${study.page_build}` : '',
      `${CAMPS.length} campaign${CAMPS.length === 1 ? '' : 's'}`, `${fmtInt(laws)} laws decided`].filter(Boolean).join(' · ');
    const nav = [LINKS.front ? h('a', { href: LINKS.front }, 'the front page') : null,
      LINKS.explorer ? h('a', { href: LINKS.explorer }, 'the explorer') : null].filter(Boolean);
    app.append(h('header', { class: 'top' },
      h('div', null, h('h1', null, D.title || 'Gate trees'), h('span', { class: 'sub' }, sub),
        nav.length ? h('div', { class: 'sub' }, nav.flatMap((a, i) => (i ? [' · ', a] : [a]))) : null),
      UI.themeSel, UI.tabs));
    UI.main = h('main', { class: 'gt-main' });
    app.append(UI.main, tip);
  }
  function applyTheme() {
    if (S.theme === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = S.theme;
    UI.themeSel.value = S.theme;
  }
  function go(page) {
    S.page = page;
    for (const b of UI.tabs.children) b.setAttribute('aria-selected', String(b.dataset.page === page));
    render();
    save();
  }
  function changed() { render(); save(); }

  function chip(label, pressed, onclick, title) {
    return h('button', { class: 'chip', type: 'button', 'aria-pressed': String(Boolean(pressed)), onclick, title }, label);
  }
  function selectOf(label, options, value, onchange, title) {
    return h('label', { title }, label, h('select', { onchange: (e) => onchange(e.target.value) },
      options.map(([v, text]) => h('option', { value: v, selected: String(v) === String(value) ? true : null }, text))));
  }
  function controls(parts) {
    const camps = h('div', { class: 'chips', role: 'group', 'aria-label': 'campaigns' }, CAMPS.map((c) => chip(
      `${c.id}`, !S.shown || S.shown.includes(c.id), () => {
        const now = S.shown ? S.shown.slice() : CAMPS.map((x) => x.id);
        const at = now.indexOf(c.id);
        if (at >= 0) { if (now.length > 1) now.splice(at, 1); } else now.push(c.id);
        S.shown = now.length === CAMPS.length ? null : CAMPS.filter((x) => now.includes(x.id)).map((x) => x.id);
        changed();
      }, `campaign ${c.id}: ${c.label || ''}`)));
    const row = [h('label', null, 'campaigns', camps)];
    if (parts.includes('measure')) {
      row.push(selectOf('measure', [['laws', 'laws'], ...(ANY_GRAPHS ? [['graphs', 'graphs']] : [])], S.measure,
        (v) => { S.measure = v; changed(); }, 'what a bar counts: the laws that finished the rung, or the graphs grown at it'));
    }
    if (parts.includes('scale')) {
      row.push(selectOf('scale', [['campaign', "each campaign's own"], ['one', 'one for all'], ['share', "each rung's own"]], S.scale,
        (v) => { S.scale = v; changed(); }, "each campaign's own: its bars against its widest rung; one for all: every bar against the widest rung shown, so the campaigns compare; each rung's own: every bar full, so the shares read"));
    }
    if (parts.includes('what')) {
      row.push(selectOf('show', [['finished', 'laws that finished each rung'], ['share', "share of a rung's laws that went on"],
        ...(ANY_GRAPHS ? [['graphs', 'graphs at each rung']] : [])], S.what, (v) => { S.what = v; changed(); }));
      if (S.what !== 'share') {
        row.push(selectOf('axis', [['lin', 'linear'], ['log', 'logarithmic']], S.ylog ? 'log' : 'lin',
          (v) => { S.ylog = v === 'log'; changed(); }));
      }
    }
    if (parts.includes('every')) {
      row.push(h('label', null, h('input', { type: 'checkbox', checked: S.every ? true : null,
        onchange: (e) => { S.every = e.target.checked; changed(); } }), 'every gate, also the ones that never fired'));
    }
    return h('div', { class: 'toolbar' }, row);
  }
  function legend(measure) {
    const keys = measure === 'graphs' ? ['on', 'done', 'held', 'stopped', 'running']
      : ['on', 'done', 'held', ...STOP_STAGES, 'other'];
    const present = new Set();
    for (const c of shownCamps()) for (const r of c.rungs.values()) for (const seg of segmentsOf(r, measure)) present.add(seg.cat);
    return h('div', { class: 'legend' }, keys.filter((k) => present.has(k)).map((k) => h('span', null, swatch(k), catOf(k).label)));
  }

  function pageTree() {
    const camps = shownCamps();
    const measure = S.measure === 'graphs' && ANY_GRAPHS ? 'graphs' : 'laws';
    const rungs = rungsOf(camps);
    const widestOf = (list) => Math.max(1, ...list.flatMap((c) => [...c.rungs.values()].map((r) => totalOf(r, measure))));
    const widest = widestOf(camps);
    UI.main.append(controls(['measure', 'scale']), legend(measure),
      h('p', { class: 'gt-intro' }, measure === 'graphs'
        ? 'Each rung: the graphs grown at it, by where their law went from it (report 28 does not split the graphs by gate), and the graphs of laws still running there. '
        : 'Each rung: the laws that finished it, by the rule of their last decision there: on to the next rung, the ladder done, held, or stopped by a gate (coloured by its stage). ',
      'Hover a segment for its numbers; click a rung to open it.'));
    const columns = h('div', { class: 'columns' });
    for (const c of camps) columns.append(treeColumn(c, rungs, S.scale === 'campaign' ? widestOf([c]) : widest, measure));
    UI.main.append(columns);
  }
  function treeColumn(c, rungs, widest, measure) {
    const card = h('section', { class: 'column', 'data-campaign': c.id });
    card.append(h('h2', null, `${campTitle(c)}`), h('div', { class: 'sub' }, [c.label, c.subtitle].filter(Boolean).join(' · ')));
    if (!c.tree) {
      card.append(h('p', { class: 'empty' }, "This campaign's report 28 carries no gate tree."));
      return card;
    }
    if (measure === 'graphs' && !c.hasGraphs) {
      card.append(h('p', { class: 'empty' }, 'Its report 28 does not count the graphs under the laws (a report made before 542).'));
      return card;
    }
    for (const n of rungs) card.append(rungRow(c, n, c.rungs.get(n), widest, measure));
    return card;
  }
  function rungRow(c, n, r, widest, measure) {
    const isOpen = S.open[c.id] === n;
    const row = h('div', { class: `rung${isOpen ? ' open' : ''}`, 'data-n': String(n) });
    const graphs = r && r.graphs != null ? (r.graphs || 0) + (r.graphs_in_progress || 0) : null;
    const opener = h('button', { class: 'openbtn', type: 'button', 'aria-expanded': String(isOpen),
      title: isOpen ? 'close this rung' : 'open this rung: every rule, its laws, and the laws in the explorer',
      onclick: () => { S.open[c.id] = isOpen ? undefined : n; changed(); } }, nLabel(n));
    row.append(h('div', { class: 'n' }, opener, graphs != null ? h('small', null, `${fmtInt(graphs)} graphs`) : null));
    const what = h('div', { class: 'what' });
    row.append(what);
    const total = r ? totalOf(r, measure) : 0;
    if (!r || !total) {
      what.append(h('div', { class: 'none' }, r && r.graphs_in_progress
        ? `no law finished this rung yet; ${fmtInt(r.graphs_in_progress)} graphs of laws still on it`
        : 'no law finished this rung'));
      return row;
    }
    const segs = segmentsOf(r, measure);
    const trueWidth = (100 * total) / widest;
    const stretched = S.scale !== 'share' && n >= (D.stretch_from || Infinity) && trueWidth < 100;
    const width = S.scale === 'share' || stretched ? 100 : Math.max(0.4, trueWidth);
    const bar = h('div', { class: 'bar', style: `width:${width.toFixed(3)}%`, role: 'group',
      'aria-label': `${nLabel(n)}: ${fmtInt(total)} ${unit(measure, total)}` });
    for (const seg of segs) {
      const label = `${fmtInt(seg.count)} ${unit(measure, seg.count)}, ${segTitle(seg, measure)}, ${share(seg.count, total)} of the rung`;
      const lines = () => [h('div', null, h('span', { class: 'val' }, `${fmtInt(seg.count)} ${unit(measure, seg.count)}`),
        ` ${share(seg.count, total)} of ${fmtInt(total)}`),
      h('div', { class: 'rowline' }, swatch(seg.cat), ' ', segTitle(seg, measure)),
      seg.rule && ruleWords(seg.rule) ? h('div', { class: 'muted' }, ruleWords(seg.rule)) : null,
      h('div', { class: 'muted' }, `${campTitle(c)} · ${nLabel(n)}${seg.cat !== 'on' && seg.rule ? ' · click to open the rung' : ''}`)];
      const b = h('button', { class: 'seg', type: 'button', 'aria-label': label, 'data-cat': seg.cat,
        'data-rule': seg.rule || '', style: `--seg: var(--cat-${catOf(seg.cat).slug}); flex-grow: ${seg.count}`,
        onmousemove: (e) => showTip(e.clientX, e.clientY, lines()), onmouseleave: hideTip,
        onfocus: (e) => tipNear(e.target, lines()), onblur: hideTip,
        onclick: () => { S.open[c.id] = n; hideTip(); changed(); } });
      bar.append(b);
    }
    const track = h('div', { class: 'track' }, bar);
    if (stretched) {
      track.append(h('span', { class: 'truth', style: `left:${Math.max(0.2, trueWidth).toFixed(3)}%`,
        title: `where this bar ends on the common scale: ${fmtInt(total)} of ${fmtInt(widest)} ${unit(measure, widest)}` }));
    }
    what.append(track);
    if (stretched) {
      what.append(h('div', { class: 'line zoom', title: 'stretched to its own laws: the empty length is hidden; the mark on the bar is its true length (542)' },
        `drawn ×${fmtInt(widest / total)}, its true length marked`));
    }
    if (measure === 'graphs') {
      const g = r.graphs_by_branch || {};
      what.append(h('div', { class: 'line' }, [`${fmtInt(total)} graphs`, ...['on', 'done', 'held', 'stopped']
        .filter((k) => g[k] > 0).map((k) => `${fmtInt(g[k])} ${k}`), r.graphs_in_progress ? `${fmtInt(r.graphs_in_progress)} running` : null]
        .filter(Boolean).join(' · ')));
    } else {
      const held = sum(Object.values(r.held || {})), stopped = sum(Object.values(r.stopped || {}));
      what.append(h('div', { class: 'line' }, [`${fmtInt(r.finished)} finished`, `${fmtInt(r.went_on || 0)} on`,
        r.done ? `${fmtInt(r.done)} done` : null, held ? `${fmtInt(held)} held` : null, `${fmtInt(stopped)} stopped`]
        .filter(Boolean).join(' · ')));
      const ranked = [...sortedEntries(r.stopped), ...sortedEntries(r.held).map(([k, v]) => [`${k} (held)`, v])];
      if (ranked.length) what.append(h('div', { class: 'line rules' }, ranked.map(([k, v]) => `${k} ${fmtInt(v)}`).join(' · ')));
      const salted = sortedEntries(r.salted_past);
      if (salted.length) {
        what.append(h('div', { class: 'line salted', title: 'laws a gate let through, one rung past it (533, 537)' },
          `let through past ${salted.map(([k, v]) => `${k} ${fmtInt(v)}`).join(' · ')}`));
      }
    }
    if (isOpen) row.append(rungDetail(c, n, r, measure));
    return row;
  }
  function explorerLinks(c, rule, n) {
    const list = explorerHref(c, rule, n, 'laws');
    if (!list) return null;
    const count = fateCount(c, rule, n);
    return h('span', null, h('a', { href: list, title: `the laws whose last decision is ${rule} at ${nLabel(n)}, on the explorer's Laws page` },
      count == null ? 'list' : `list ${fmtInt(count)}`), ' · ',
    h('a', { href: explorerHref(c, rule, n, 'maps'), title: 'where those laws sit: d_s against the mean degree, and the mean degree as N grows' }, 'where they sit'));
  }
  function rungDetail(c, n, r, measure) {
    const total = totalOf(r, measure);
    const linked = measure === 'laws' && LINKS.explorer && c.explorer != null;
    const rowOf = (key, title, count, words, links) => h('tr', null,
      h('td', null, h('span', { class: 'where' }, key ? swatch(key) : null, title),
        words ? h('div', { class: 'muted small' }, words) : null, links ? h('div', { class: 'small' }, links) : null),
      h('td', { class: 'num' }, fmtInt(count)), h('td', { class: 'num' }, share(count, total)));
    const body = segmentsOf(r, measure).map((seg) => rowOf(seg.cat, segTitle(seg, measure), seg.count,
      seg.rule ? ruleWords(seg.rule) : '', seg.rule && seg.cat !== 'on' ? explorerLinks(c, seg.rule, n) : null));
    if (measure === 'laws') {
      for (const [gate, v] of sortedEntries(r.salted_past)) {
        body.push(rowOf(null, `let through past ${gate}`, v, 'the gate let them through, one rung past it', null));
      }
      for (const [gate, v] of sortedEntries(r.salt_spent)) {
        body.push(rowOf(null, `let-through spent on ${gate}`, v, 'laws it let through that the gate fired on again here, so they stopped', null));
      }
    }
    const head = h('tr', null, h('th', null, `${campTitle(c)}, ${nLabel(n)}`), h('th', { class: 'num' }, measure === 'graphs' ? 'graphs' : 'laws'),
      h('th', { class: 'num' }, 'share'));
    return h('div', { class: 'detail' }, h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, head), h('tbody', null, body))),
      linked ? h('div', { class: 'note' }, "A list opens the explorer on the laws whose last decision is that rule at this rung (report 28's fate); a law that went on is listed at the rung it reached, not here.") : null);
  }

  function gateNames(camps) {
    const fired = (g) => g && ((g.withheld || 0) + (g.let_through || 0) + (g.salt_spent || 0)) > 0;
    const names = GATE_ORDER.filter((name) => S.every || camps.some((c) => fired(c.gates.get(name))));
    for (const c of camps) for (const name of c.gates.keys()) if (!names.includes(name) && (S.every || fired(c.gates.get(name)))) names.push(name);
    return names;
  }
  function gateCat(name) {
    const rule = RULES[name] || {};
    return rule.action === 'hold' ? 'held' : stopCat(name);
  }
  function pageGates() {
    const camps = shownCamps().filter((c) => c.tree);
    UI.main.append(controls(['every']), h('p', { class: 'gt-intro' },
      "Each gate in the order a law meets it at a rung. Withheld and let through count each law once, at the first rung it happened; a law let through that the gate fires on again at the rung it was let through to is spent there, not withheld twice. Of the laws a gate let through that went on, the share that settled d_s at a later rung against the laws that went on by their own reading from the same rungs is the gate's cost: close shares mean it withholds laws as good as the ones it keeps."));
    const names = gateNames(camps);
    if (!names.length) { UI.main.append(h('p', { class: 'empty' }, 'No gate fired in these campaigns.')); return; }
    const cards = h('div', { class: 'gatecards' });
    for (const name of names) cards.append(gateCard(name, camps));
    UI.main.append(cards);
  }
  function gateCard(name, camps) {
    const rule = RULES[name] || {};
    const card = h('section', { class: 'gatecard', 'data-gate': name });
    card.append(h('h3', null, swatch(gateCat(name)), name, h('span', { class: 'muted', style: 'font-weight:400' }, ` ${rule.stage || 'not in the tree'}`)),
      h('p', { class: 'reads' }, rule.reads || ''),
      h('p', { class: 'why' }, rule.salted ? 'Lets a share through: of the laws it would stop, a share goes one rung past it.'
        : rule.why_not ? `Lets none through: ${rule.why_not}.` : 'Lets none through.'));
    const cols = camps.map((c) => ({ c, g: c.gates.get(name) || null }));
    const measures = [
      ['withheld', (g) => fmtInt(g.withheld || 0)],
      ['let through', (g) => fmtInt(g.let_through || 0)],
      ['share let through', (g) => pctOf(g.share_let_through)],
      ...COSTS.map((cost) => [`the let-through share ${cost}`, (g) => (g.salt_share && g.salt_share[cost] != null ? pctOf(g.salt_share[cost]) : '')]),
      ['let through, then went on', (g) => (g.let_through ? fmtInt(g.went_on || 0) : '')],
      ['of those, settled d_s later', (g) => (g.let_through ? pctOf(g.settled_later_share) : '')],
      ['by their own reading at the same rungs', (g) => (g.let_through ? pctOf(g.unsalted_settled_later_share_at_the_same_rungs) : '')],
      ["let through, next rung: the gate fired again", (g) => fmtInt((g.salt_next_rung || {}).gate_held || 0)],
      ["let through, next rung: its reading changed", (g) => fmtInt((g.salt_next_rung || {}).reading_changed || 0)],
      ["let through, next rung: not yet", (g) => fmtInt((g.salt_next_rung || {}).no_next_rung_yet || 0)],
      ['let-through spent (stopped at the rung it was let through to)', (g) => fmtInt(g.salt_spent || 0)],
    ];
    const ledgerKeys = new Set();
    for (const { g } of cols) for (const k of Object.keys((g && g.salt_ledger) || {})) ledgerKeys.add(k);
    const costs = [...COSTS.filter((k) => ledgerKeys.has(k)), ...[...ledgerKeys].filter((k) => !COSTS.includes(k)).sort()];
    for (const cost of costs) {
      const at = (g) => ((g && g.salt_ledger) || {})[cost];
      for (const [key, words] of [['salted', 'let through'], ['clean', 'ended clean'], ['ended_untested', 'ended untested'],
        ['missed', 'missed (read finite later)'],
        ['open', 'still open'], ['bought_nothing', 'bought nothing']]) {
        measures.push([`ledger ${cost}: ${words}`, (g) => (at(g) ? fmtInt(at(g)[key] || 0) : '')]);
      }
      measures.push([`ledger ${cost}: its label`, (g) => (at(g) ? `${at(g).label} (${fmtInt(at(g).clean_since_last_miss || 0)} of ${fmtInt(at(g).needed || 0)})` : '')]);
    }
    const head = h('tr', null, h('th', null, ''), cols.map(({ c }) => h('th', { class: 'num', title: c.label || '' }, campTitle(c))));
    const rows = measures.map(([label, fn]) => h('tr', null, h('td', null, label),
      cols.map(({ g }) => h('td', { class: 'num' }, g ? fn(g) : '-'))));
    card.append(h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, head), h('tbody', null, rows))));
    const rungs = new Set();
    for (const { g } of cols) for (const n of Object.keys((g && g.by_rung) || {})) rungs.add(Number(n));
    const ordered = [...rungs].sort((a, b) => a - b);
    if (ordered.length) {
      let most = 1;
      for (const { g } of cols) for (const v of Object.values((g && g.by_rung) || {})) most = Math.max(most, v.withheld || 0);
      const head2 = h('tr', null, h('th', null, 'N'), cols.map(({ c }) => h('th', null, campTitle(c))));
      const body2 = ordered.map((n) => h('tr', null, h('td', { class: 'num' }, fmtInt(n)), cols.map(({ c, g }) => {
        const v = ((g && g.by_rung) || {})[String(n)];
        if (!v) return h('td', { class: 'muted' }, '');
        const fate = fateCount(c, name, n);
        const link = v.withheld && fate ? explorerHref(c, name, n, 'laws') : null;
        return h('td', { style: 'white-space:nowrap' },
          h('span', { class: 'inline-bar', style: `width:${Math.max(2, (60 * (v.withheld || 0)) / most).toFixed(1)}px; background: var(--cat-${catOf(gateCat(name)).slug})` }),
          fmtInt(v.withheld || 0),
          link ? h('a', { href: link, title: `the ${fmtInt(fate)} laws whose last decision is ${name} at ${nLabel(n)}` },
            ` (${fmtInt(fate)} now)`) : null,
          v.let_through ? h('span', { class: 'muted' }, ` + ${fmtInt(v.let_through)} let through`) : null);
      })));
      card.append(h('h4', null, 'Rung by rung: withheld, and let through'),
        h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, head2), h('tbody', null, body2))));
    }
    const later = new Set();
    for (const { g } of cols) for (const k of Object.keys((g && g.let_through_later) || {})) later.add(k);
    if (later.size) {
      const head3 = h('tr', null, h('th', null, 'what the laws it let through did'), cols.map(({ c }) => h('th', { class: 'num' }, campTitle(c))));
      const body3 = [...later].map((k) => h('tr', null, h('td', null, k.replace(/_/g, ' ')),
        cols.map(({ g }) => h('td', { class: 'num' }, fmtInt((((g && g.let_through_later) || {})[k]) || 0)))));
      card.append(h('h4', null, 'After the let-through'), h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, head3), h('tbody', null, body3))));
    }
    const readings = new Set();
    for (const { g } of cols) for (const k of Object.keys((g && g.salt_next_rung_reading) || {})) readings.add(k);
    if (readings.size) {
      const body4 = [...readings].map((k) => h('tr', null, h('td', null, k),
        cols.map(({ g }) => h('td', { class: 'num' }, fmtInt((((g && g.salt_next_rung_reading) || {})[k]) || 0)))));
      card.append(h('h4', null, 'Its own reading at the next rung of those let through'), h('div', { class: 'tablewrap' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, 'reading'), cols.map(({ c }) => h('th', { class: 'num' }, campTitle(c))))), h('tbody', null, body4))));
    }
    return card;
  }

  function survivalValue(c, n, what) {
    const r = c.rungs.get(n);
    if (!r) return null;
    if (what === 'share') return r.finished ? (r.went_on || 0) / r.finished : null;
    if (what === 'graphs') return r.graphs != null ? (r.graphs || 0) + (r.graphs_in_progress || 0) : null;
    return r.finished ? r.finished : null;
  }
  function firstValue(c, rungs, what) {
    for (const n of rungs) { const v = survivalValue(c, n, what); if (v != null) return [n, v]; }
    return [null, null];
  }
  function seriesVar(c) { return `var(--series-${(c.index % 8) + 1})`; }
  function pageSurvival() {
    const camps = shownCamps().filter((c) => c.tree);
    const what = S.what === 'graphs' && !ANY_GRAPHS ? 'finished' : S.what;
    UI.main.append(controls(['what']));
    const rungs = rungsOf(camps);
    if (!rungs.length || !camps.length) { UI.main.append(h('p', { class: 'empty' }, 'No rung to draw.')); return; }
    const log = S.ylog && what !== 'share';
    const values = camps.flatMap((c) => rungs.map((n) => survivalValue(c, n, what))).filter((v) => v != null && (!log || v > 0));
    let lo = what === 'share' ? 0 : log ? Math.min(...values) : 0;
    let hi = what === 'share' ? 1 : Math.max(1, ...values);
    if (log) { lo = Math.pow(10, Math.floor(Math.log10(Math.max(lo, 1)))); hi = Math.pow(10, Math.ceil(Math.log10(Math.max(hi, 10)))); }
    const W = Math.max(320, Math.min(1100, (UI.main.clientWidth || 900) - 24)), H = 340, L = 64, R = 170, T = 14, B = 40;
    const x = (i) => L + (rungs.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (rungs.length - 1));
    const y = (v) => (log ? T + (H - T - B) * (1 - (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)))
      : T + (H - T - B) * (1 - (v - lo) / (hi - lo || 1)));
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': `${what === 'share' ? "the share of each rung's laws that went on" : what === 'graphs' ? 'graphs at each rung' : 'laws that finished each rung'}, a line a campaign` });
    const ticks = [];
    if (what === 'share') for (let v = 0; v <= 1.0001; v += 0.25) ticks.push(v);
    else if (log) for (let v = lo; v <= hi * 1.0001; v *= 10) ticks.push(v);
    else { const step = niceStep(hi / 4); for (let v = 0; v <= hi * 1.0001; v += step) ticks.push(v); }
    for (const v of ticks) {
      svg.append(s('line', { class: 'gridline', x1: L, x2: W - R, y1: y(v), y2: y(v) }),
        s('text', { x: L - 8, y: y(v) + 4, 'text-anchor': 'end' }, what === 'share' ? `${Math.round(v * 100)}%` : fmtInt(v)));
    }
    svg.append(s('line', { class: 'axis', x1: L, x2: W - R, y1: H - B, y2: H - B }));
    rungs.forEach((n, i) => svg.append(s('text', { x: x(i), y: H - B + 18, 'text-anchor': 'middle' }, fmtInt(n))));
    svg.append(s('text', { x: (L + W - R) / 2, y: H - 4, 'text-anchor': 'middle' }, 'N, the rung'));
    const ends = [];
    for (const c of camps) {
      const pts = rungs.map((n, i) => [i, survivalValue(c, n, what)]).filter(([, v]) => v != null && (!log || v > 0));
      if (!pts.length) continue;
      svg.append(s('path', { class: 'series', d: pts.map(([i, v], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(''),
        style: `stroke: ${seriesVar(c)}`, 'data-campaign': c.id }));
      for (const [i, v] of pts) svg.append(s('circle', { class: 'dot', cx: x(i), cy: y(v), r: 4, style: `fill: ${seriesVar(c)}` }));
      const [i, v] = pts[pts.length - 1];
      ends.push({ c, x: x(i), y: y(v), text: `${campTitle(c)}: ${what === 'share' ? share(v, 1) : fmtInt(v)}` });
    }
    const placed = [];
    for (const e of ends.sort((a, b) => a.y - b.y)) {
      if (camps.length > 4 || placed.some((p) => Math.abs(p.y - e.y) < 15 && Math.abs(p.x - e.x) < 140)) continue;
      placed.push(e);
      svg.append(s('text', { class: 'endlabel', x: e.x + 8, y: e.y + 4 }, e.text));
    }
    const cross = s('line', { class: 'cross', x1: 0, x2: 0, y1: T, y2: H - B, style: 'display:none' });
    svg.append(cross);
    const hit = s('rect', { x: L - 10, y: T, width: W - L - R + 20, height: H - T - B, fill: 'transparent' });
    svg.append(hit);
    const readout = (i) => [h('div', null, h('b', null, nLabel(rungs[i]))), ...camps.map((c) => {
      const v = survivalValue(c, rungs[i], what);
      const [firstN, first] = firstValue(c, rungs, what);
      return h('div', { class: 'rowline' }, h('span', { class: 'key', style: `background: ${seriesVar(c)}` }),
        h('span', { class: 'val' }, v == null ? 'none yet' : what === 'share' ? share(v, 1) : fmtInt(v)),
        ` ${campTitle(c)}`, v != null && what !== 'share' && first && firstN !== rungs[i]
          ? h('span', { class: 'muted' }, ` (${share(v, first)} of its ${fmtInt(first)} at N=${fmtInt(firstN)})`) : null);
    })];
    hit.addEventListener('mousemove', (e) => {
      const box = svg.getBoundingClientRect();
      const px = ((e.clientX - box.left) / box.width) * W;
      let best = 0;
      rungs.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i; });
      cross.setAttribute('x1', x(best)); cross.setAttribute('x2', x(best)); cross.style.display = '';
      showTip(e.clientX, e.clientY, readout(best));
    });
    hit.addEventListener('mouseleave', () => { cross.style.display = 'none'; hideTip(); });
    UI.main.append(h('div', { class: 'legend' }, camps.map((c) => h('span', null,
      h('span', { class: 'swatch', style: `background: ${seriesVar(c)}; height: 3px; width: 14px` }), `${campTitle(c)} ${c.label || ''}`))),
    h('div', { class: 'chart' }, svg));
    const head = h('tr', null, h('th', null, 'N'), camps.map((c) => h('th', { class: 'num' }, campTitle(c))));
    const body = rungs.map((n) => h('tr', null, h('td', { class: 'num' }, fmtInt(n)), camps.map((c) => {
      const v = survivalValue(c, n, what);
      const [firstN, first] = firstValue(c, rungs, what);
      return h('td', { class: 'num' }, v == null ? '' : what === 'share' ? share(v, 1)
        : `${fmtInt(v)}${first && n !== firstN ? ` (${share(v, first)})` : ''}`);
    })));
    UI.main.append(h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, head), h('tbody', null, body))));
  }
  function niceStep(raw) {
    const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
    const n = raw / mag;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
  }

  function pageTable() {
    const camps = shownCamps().filter((c) => c.tree);
    const csv = [['campaign', 'N', 'finished', 'went on', 'went on by', 'done', 'held', 'held by', 'stopped', 'stopped by',
      'let through past', 'let-through spent', 'graphs', 'graphs running']];
    UI.main.append(controls([]));
    const words = (obj) => sortedEntries(obj).map(([k, v]) => `${k} ${fmtInt(v)}`).join(' · ');
    for (const c of camps) {
      const rows = [];
      for (const n of [...c.rungs.keys()].sort((a, b) => a - b)) {
        const r = c.rungs.get(n);
        const held = sum(Object.values(r.held || {})), stopped = sum(Object.values(r.stopped || {}));
        csv.push([c.id, n, r.finished || 0, r.went_on || 0, words(r.went_on_by), r.done || 0, held, words(r.held), stopped,
          words(r.stopped), words(r.salted_past), words(r.salt_spent), r.graphs == null ? '' : r.graphs, r.graphs_in_progress == null ? '' : r.graphs_in_progress]);
        const cell = (v, sub) => (sub != null ? h('td', { class: 'list' }, fmtInt(v), sub ? h('div', { class: 'muted small' }, sub) : null)
          : h('td', { class: 'num' }, fmtInt(v)));
        rows.push(h('tr', null, h('td', { class: 'num' }, fmtInt(n)), cell(r.finished || 0), cell(r.went_on || 0, words(r.went_on_by)),
          cell(r.done || 0), cell(held, words(r.held)), cell(stopped, words(r.stopped)),
          h('td', { class: 'muted' }, words(r.salted_past)), h('td', { class: 'muted' }, words(r.salt_spent)),
          h('td', { class: 'num' }, r.graphs == null ? '' : fmtInt(r.graphs)), h('td', { class: 'num' }, r.graphs_in_progress ? fmtInt(r.graphs_in_progress) : '')));
      }
      const head = h('tr', null, ['N', 'finished', 'went on', 'done', 'held', 'stopped', 'let through past', 'let-through spent', 'graphs', 'running']
        .map((t, i) => h('th', { class: [0, 1, 3, 8, 9].includes(i) ? 'num' : null }, t)));
      UI.main.append(h('h3', null, `${campTitle(c)} `, h('span', { class: 'muted', style: 'font-weight:400' }, c.label || '')),
        h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, head), h('tbody', null, rows))));
    }
    UI.main.append(h('button', { class: 'btn', type: 'button', onclick: () => download('gate_trees.csv', csvOf(csv)) }, 'Download as CSV'));
  }

  function pageAbout() {
    const gates = GATE_ORDER.map((name) => [name, RULES[name] || {}]);
    const streams = Object.entries(RULES).filter(([, r]) => r.kind === 'stream');
    UI.main.append(h('div', { class: 'about' },
      h('h2', null, 'What this page is'),
      h('p', null, "Every campaign's tree of gates, as its report 28 counts it (research/gate_tree.py): at each rung, the laws that finished it and where each went by the rule of its last decision there, the graphs they grew, and for each gate what it withheld, what it let through and what those laws did next. Everything is counted from the record; nothing is recomputed."),
      D.reading ? h('p', null, D.reading) : null,
      h('h2', null, 'Where a law goes from a rung'),
      h('dl', null, (D.categories || []).filter((c) => !['stopped', 'running'].includes(c.key)).map((c) => [
        h('dt', null, swatch(c.key), ' ', c.label), h('dd', null, ABOUT_CATS[c.key] || '')])),
      h('h2', null, 'The gates, in the order a law meets them'),
      h('dl', null, gates.map(([name, r]) => [h('dt', null, swatch(gateCat(name)), ' ', name, h('span', { class: 'muted', style: 'font-weight:400' }, ` ${r.stage || ''}${r.action === 'hold' ? ', a hold' : ''}`)),
        h('dd', null, `${r.reads || ''}${r.salted ? '; lets a share through' : r.why_not ? `; lets none through: ${r.why_not}` : ''}`)])),
      h('h2', null, 'The streams that buy a rung or end the ladder'),
      h('dl', null, streams.map(([name, r]) => [h('dt', null, name, r.audit ? h('span', { class: 'muted', style: 'font-weight:400' }, ' audit traffic') : null),
        h('dd', null, r.means || '')])),
      h('h2', null, 'Reading it'),
      h('ul', null,
        h('li', null, `Each campaign's own scale draws a campaign's bars against its widest rung, so a bar's length is its laws; one for all draws every bar against the widest rung shown, so campaigns of different sizes compare. On either, from N=${fmtInt(D.stretch_from)} up a rung holds a sliver of the widest, so its bar is stretched to its own laws, its true length marked and its zoom said. Each rung's own draws every bar full, so its shares read at any N.`),
        h('li', null, 'Graphs: the graphs grown at a rung, split by where their law went from it; report 28 does not split them by gate. Running: graphs of laws that have not finished the rung.'),
        h('li', null, "A list opens the explorer on the laws whose last decision is that rule at that rung: report 28's ledger gives each law its fate, so a law that went on is listed at the rung it reached, and a law stopped by a gate is listed where it stopped."),
        h('li', null, 'The let-through: a gate that stops compute lets a share of the laws it would stop go one rung past it; if it fires again there, the law stops (its let-through spent). Shares of laws still going grow while a campaign runs.'))));
  }
  const ABOUT_CATS = {
    on: 'the law bought its next rung (the rule says why: the base block, d_s settled, a second look, a let-through, an audit).',
    done: 'the law measured its last declared rung.',
    held: 'the law waits at the rung (a hold, not a stop: it may go on later).',
    settling: 'stopped by a gate of depth: whether d_s settled, or (602, a campaign decided chain by chain) what its starts did.',
    'deep rungs': 'stopped by a gate of the deep rungs.',
    structure: 'stopped by the structure gate: no finite dimension, or no giant component.',
    'final verdict': 'stopped by a final verdict: empty, too dense, disconnected.',
    operational: 'stopped for the fleet, not the law: a failed seed or a first chunk over its budget.',
    other: 'a rule outside the gates this page knows, or a decision that is none of these.',
  };

  function render() {
    hideTip();
    UI.main.replaceChildren();
    ({ tree: pageTree, gates: pageGates, survival: pageSurvival, table: pageTable, about: pageAbout }[S.page] || pageTree)();
  }
  function save() {
    try {
      const open = Object.fromEntries(Object.entries(S.open).filter(([, v]) => v != null));
      const view = { p: S.page, c: S.shown, m: S.measure, s: S.scale, w: S.what, y: S.ylog ? 'log' : 'lin', t: S.theme, o: open, e: S.every };
      history.replaceState(null, '', `#${encodeURIComponent(JSON.stringify(view))}`);
    } catch (e) {  }
  }
  function restore() {
    try {
      if (!location.hash || location.hash.length < 3) return;
      const v = JSON.parse(decodeURIComponent(location.hash.slice(1)));
      if (PAGES.some(([k]) => k === v.p)) S.page = v.p;
      if (Array.isArray(v.c)) S.shown = CAMPS.filter((c) => v.c.includes(c.id)).map((c) => c.id) || null;
      if (S.shown && !S.shown.length) S.shown = null;
      if (v.m === 'graphs' || v.m === 'laws') S.measure = v.m;
      if (['campaign', 'one', 'share'].includes(v.s)) S.scale = v.s;
      if (['finished', 'share', 'graphs'].includes(v.w)) S.what = v.w;
      S.ylog = v.y === 'log';
      if (['auto', 'light', 'dark'].includes(v.t)) S.theme = v.t;
      if (v.o && typeof v.o === 'object') S.open = Object.fromEntries(Object.entries(v.o).filter(([, n]) => finite(+n)).map(([k, n]) => [k, +n]));
      S.every = Boolean(v.e);
    } catch (e) {  }
  }

  let lastWidth = 0;
  window.addEventListener('resize', () => {
    const w = UI.main ? UI.main.clientWidth : 0;
    if (S.page === 'survival' && Math.abs(w - lastWidth) > 40) { lastWidth = w; render(); }
  });
  shell();
  restore();
  applyTheme();
  go(S.page);
  window.__gateTrees = {
    ready: true, state: S, data: D, go, changed,
    info() {
      return { page: S.page, campaigns: shownCamps().map((c) => c.id), columns: UI.main.querySelectorAll('.column').length,
        rungs: UI.main.querySelectorAll('.rung').length, segments: UI.main.querySelectorAll('.seg').length,
        open: UI.main.querySelectorAll('.detail').length, gates: UI.main.querySelectorAll('.gatecard').length,
        lines: UI.main.querySelectorAll('path.series').length };
    },
  };
  document.dispatchEvent(new CustomEvent('gate-trees-ready'));
}());
