const fs = require('fs');
const path = require('path');

function loadPlaywright() {
  const global = path.join(path.dirname(path.dirname(process.execPath)), 'lib', 'node_modules', 'playwright');
  for (const name of ['playwright', global]) {
    try { return require(name); } catch (error) {  }
  }
  return null;
}

const [uiDir, dumpPath, widthsArg] = process.argv.slice(2);
const WIDTHS = (widthsArg || '1024,1280,1440,1767,1920').split(',').map(Number);

function inspectAll(dumps) {
  const problems = [];
  const lines = (range) => new Set([...range.getClientRects()].filter((r) => r.width > 0.5)
    .map((r) => Math.round(r.top))).size;
  const exempt = (el) => !el || el.closest('.breakable, code, pre, svg, .raw-json-viewer')
    || getComputedStyle(el).wordBreak === 'break-all';
  const fallback = document.createElement('main');
  fallback.className = 'gsd-app-page';
  fallback.innerHTML = '<section class="panel"></section>';
  document.body.appendChild(fallback);
  const word = /[A-Za-z0-9_][A-Za-z0-9_.,%]*[A-Za-z0-9_%]/g;

  const CELLS = 'td, th, .live-cell, .lease > div';
  function inspect(root, id) {
    for (const cell of root.querySelectorAll(CELLS)) {
      if (exempt(cell)) continue;
      const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (exempt(node.parentElement)) continue;
        const text = node.textContent;
        word.lastIndex = 0;
        for (let m = word.exec(text); m; m = word.exec(text)) {
          if (m[0].length < 3) continue;
          const range = document.createRange();
          range.setStart(node, m.index);
          range.setEnd(node, m.index + m[0].length);
          if (lines(range) > 1) {
            problems.push({ id, kind: 'a word split across lines', what: m[0],
                            where: cell.textContent.trim().replace(/\s+/g, ' ').slice(0, 90) });
          }
        }
      }
      const style = getComputedStyle(cell);
      if (cell.scrollWidth > cell.clientWidth + 1 && style.overflowX !== 'visible' && style.textOverflow !== 'ellipsis'
          && cell.textContent.trim()) {
        problems.push({ id, kind: `a ${cell.tagName === 'TH' ? 'header' : 'cell'} cut off`,
                        what: cell.textContent.trim().replace(/\s+/g, ' ').slice(0, 60),
                        where: `${cell.scrollWidth}px of text in ${cell.clientWidth}px` });
      }
    }
    for (const table of root.querySelectorAll('table')) {
      let panel = null;
      let scrolls = false;
      for (let a = table.parentElement; a; a = a.parentElement) {
        if (a.classList.contains('panel') || a.classList.contains('gsd-app-page')) { panel = a; break; }
        if (['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(a).overflowX)) scrolls = true;
      }
      if (!panel || scrolls) continue;
      const over = table.getBoundingClientRect().right - panel.getBoundingClientRect().right;
      if (over > 1) {
        const head = [...table.querySelectorAll('th')].map((th) => th.textContent.trim()).filter(Boolean);
        problems.push({ id, kind: 'a table wider than its panel', what: `${Math.round(over)}px over`,
                        where: head.slice(0, 6).join(' | ').slice(0, 90) });
      }
    }
  }

  for (const [id, snapshots] of Object.entries(dumps)) {
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement('div');
      el.id = id;
      fallback.firstElementChild.appendChild(el);
    }
    for (const page of document.querySelectorAll('.gsd-app-page')) page.hidden = !page.contains(el);
    for (let a = el; a && a !== document.body; a = a.parentElement) a.hidden = false;
    const kept = el.innerHTML;
    snapshots.forEach((html) => { el.innerHTML = html; inspect(el, id); });
    el.innerHTML = kept;
  }
  return problems;
}

(async () => {
  const playwright = loadPlaywright();
  if (!playwright) { console.log('SKIP playwright is not installed'); return; }
  let browser;
  try {
    browser = await playwright.chromium.launch();
  } catch (error) {
    console.log(`SKIP no browser could be launched: ${String(error.message).split('\n')[0]}`);
    return;
  }
  const dumps = JSON.parse(fs.readFileSync(dumpPath, 'utf8'));
  const shell = fs.readFileSync(path.join(uiDir, 'index.html'), 'utf8')
    .replace(/__GSD_BUILD_NUMBER__/g, '0').replace(/<script[\s\S]*?<\/script>/g, '');
  const page = await browser.newPage();
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.hostname !== 'gsd.test') return route.abort();
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: shell });
    const file = path.join(uiDir, url.pathname.replace(/^\/assets\//, ''));
    if (url.pathname.startsWith('/assets/') && fs.existsSync(file)) return route.fulfill({ path: file });
    return route.abort();
  });
  await page.goto('http://gsd.test/');
  const found = [];
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 1000 });
    for (const problem of await page.evaluate(inspectAll, dumps)) found.push({ width, ...problem });
  }
  await browser.close();
  const merged = new Map();
  for (const p of found) {
    const key = `${p.id}: ${p.kind}: ${p.what} (${p.where})`;
    merged.set(key, (merged.get(key) || new Set()).add(p.width));
  }
  if (!merged.size) { console.log(`OK ${Object.values(dumps).flat().length} tables at ${WIDTHS.join(', ')} px`); return; }
  console.log('FAIL');
  for (const [key, widths] of merged) console.log(`${key} at ${[...widths].join(', ')} px`);
  process.exitCode = 1;
})();
