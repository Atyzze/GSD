const path = require('path');

function loadPlaywright() {
  const global = path.join(path.dirname(path.dirname(process.execPath)), 'lib', 'node_modules', 'playwright');
  for (const name of ['playwright', global]) {
    try { return require(name); } catch (error) {  }
  }
  return null;
}

function inspectTables() {
  const problems = [];
  const lines = (range) => new Set([...range.getClientRects()].filter((r) => r.width > 0.5)
    .map((r) => Math.round(r.top))).size;
  const word = /[A-Za-z0-9_][A-Za-z0-9_.,%]*[A-Za-z0-9_%]/g;
  for (const cell of document.querySelectorAll('main td, main th')) {
    const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent;
      word.lastIndex = 0;
      for (let m = word.exec(text); m; m = word.exec(text)) {
        if (m[0].length < 3) continue;
        const range = document.createRange();
        range.setStart(node, m.index);
        range.setEnd(node, m.index + m[0].length);
        if (lines(range) > 1) problems.push(`a word split across lines: ${m[0]}`);
      }
    }
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) {
    problems.push(`the page scrolls sideways: ${document.documentElement.scrollWidth}px in ${window.innerWidth}px`);
  }
  return problems;
}

(async () => {
  const [file] = process.argv.slice(2);
  const playwright = loadPlaywright();
  if (!playwright) { console.log('SKIP playwright is not installed'); return; }
  let browser;
  try {
    browser = await playwright.chromium.launch();
  } catch (error) {
    console.log(`SKIP no browser could be launched: ${String(error.message).split('\n')[0]}`);
    return;
  }
  const problems = [], report = { stretched: 0 };
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', (e) => problems.push(`an error in the page: ${String(e.message || e).split('\n')[0]}`));
  page.on('console', (m) => { if (m.type() === 'error') problems.push(`the console: ${m.text().slice(0, 200)}`); });
  const url = `file://${path.resolve(file)}`;
  const folder = `file://${path.dirname(path.resolve(file))}/`;
  page.on('request', (r) => {
    const u = r.url();
    if (!u.startsWith(folder) && !u.startsWith('blob:') && !u.startsWith('data:') && u !== 'about:blank') problems.push(`a request: ${u}`);
  });
  const info = () => page.evaluate(() => window.__gateTrees.info());
  const ready = () => page.waitForFunction(() => window.__gateTrees && window.__gateTrees.ready, null, { timeout: 30000 });
  try {
    await page.goto(url);
    await ready();
    let now = await info();
    const data = await page.evaluate(() => window.__gateTrees.data);
    const camps = data.campaigns.filter((c) => c.tree);
    if (now.page !== 'tree' || now.columns !== data.campaigns.length) problems.push(`the Tree drew ${now.columns} columns for ${data.campaigns.length} campaigns`);
    if (!now.segments) problems.push('the Tree drew no segment');
    const sums = await page.evaluate(() => [...document.querySelectorAll('.column')].map((col) => [...col.querySelectorAll('.rung')]
      .map((r) => [col.dataset.campaign, +r.dataset.n, [...r.querySelectorAll('.seg')].reduce((a, s) => a + (+s.style.flexGrow || 0), 0)])).flat());
    for (const [cid, n, total] of sums) {
      const rung = (data.campaigns.find((c) => c.id === cid).tree.rungs || []).find((r) => r.n === n);
      if (rung && rung.finished && total !== rung.finished) problems.push(`campaign ${cid} at ${n}: segments add to ${total}, the rung has ${rung.finished}`);
    }
    let stretched = 0;
    for (const c of data.campaigns.filter((x) => x.tree)) {
      const rungs = c.tree.rungs || [];
      const widest = Math.max(1, ...rungs.map((r) => r.finished || 0));
      for (const r of rungs) {
        if (!r.finished) continue;
        const row = await page.evaluate(([cid, n]) => {
          const el = document.querySelector(`.column[data-campaign="${cid}"] .rung[data-n="${n}"]`);
          return el ? { truth: !!el.querySelector('.truth'), zoom: !!el.querySelector('.zoom'), width: el.querySelector('.bar').style.width } : null;
        }, [c.id, r.n]);
        if (!row) { problems.push(`campaign ${c.id} has no row for ${r.n}`); continue; }
        const should = r.n >= data.stretch_from && r.finished < widest;
        if (should !== row.truth || should !== row.zoom) problems.push(`campaign ${c.id} at ${r.n}: stretched ${row.truth}, should be ${should}`);
        if (should && Math.abs(parseFloat(row.width) - 100) > 0.01) problems.push(`campaign ${c.id} at ${r.n}: a stretched bar is ${row.width} wide`);
        if (should) stretched++;
      }
    }
    const seg = page.locator('.seg[data-cat="final verdict"]').first();
    if (await seg.count() === 0) problems.push('no law stopped by a final verdict is drawn');
    else {
      await seg.hover();
      await page.waitForTimeout(150);
      const tip = await page.evaluate(() => { const t = document.querySelector('.tip'); return t && t.style.display !== 'none' ? t.textContent : ''; });
      if (!/law/.test(tip) || !/stopped by/.test(tip)) problems.push(`a hover on a stop shows: ${tip.slice(0, 80)}`);
      await seg.click();
      await page.waitForTimeout(200);
      now = await info();
      if (now.open !== 1) problems.push(`a click on a segment opened ${now.open} rungs`);
      const link = page.locator('.detail a', { hasText: /^list/ }).first();
      if (await link.count() === 0) { if (data.links && data.links.explorer) problems.push('an opened rung offers no link to the explorer'); }
      else {
        const text = await link.innerText();
        const counted = +text.replace(/[^0-9]/g, '');
        const href = await link.getAttribute('href');
        await page.goto(new URL(href, url).href);
        await page.waitForFunction(() => window.__explorer && window.__explorer.ready, null, { timeout: 30000 });
        await page.waitForTimeout(300);
        const ex = await page.evaluate(() => window.__explorer.info());
        if (ex.page !== 'laws' || ex.visibleLaws !== counted) problems.push(`the explorer opened ${ex.page} with ${ex.visibleLaws} laws for "${text}"`);
        await page.goto(url);
        await ready();
      }
    }
    const firstChip = page.locator('.toolbar .chips .chip').first();
    await firstChip.click();
    await page.waitForTimeout(150);
    now = await info();
    if (now.columns !== data.campaigns.length - 1) problems.push(`unticking a campaign left ${now.columns} columns`);
    await firstChip.click();
    await page.waitForTimeout(150);
    const widths = () => page.evaluate(() => [...document.querySelectorAll('.bar')].map((b) => b.style.width).join(','));
    const before = await widths();
    await page.locator('.toolbar select').nth(1).selectOption('share');
    await page.waitForTimeout(150);
    if ((await widths()) === before) problems.push("each rung's own scale drew the same bars");
    await page.locator('.toolbar select').nth(1).selectOption('one');
    await page.waitForTimeout(150);
    if (await page.locator('.toolbar select').first().locator('option[value=graphs]').count()) {
      await page.locator('.toolbar select').first().selectOption('graphs');
      await page.waitForTimeout(150);
      const graphSegs = await page.locator('.seg').count();
      if (!graphSegs) problems.push('the graphs measure drew no segment');
      await page.locator('.toolbar select').first().selectOption('laws');
      await page.waitForTimeout(150);
    }
    for (const [name, check] of [['gates', (i) => i.gates > 0], ['survival', (i) => i.lines === camps.length], ['table', () => true], ['about', () => true]]) {
      await page.locator(`nav.tabs button[data-page=${name}]`).click();
      await page.waitForTimeout(250);
      now = await info();
      if (now.page !== name || !check(now)) problems.push(`the ${name} page did not render: ${JSON.stringify(now)}`);
      const text = await page.locator('main').innerText();
      if (text.trim().length < 60) problems.push(`the ${name} page is empty`);
    }
    await page.locator('nav.tabs button[data-page=survival]').click();
    await page.waitForTimeout(200);
    const chart = await page.locator('.chart svg rect').last().boundingBox();
    if (chart) {
      await page.mouse.move(chart.x + chart.width * 0.3, chart.y + chart.height * 0.5);
      await page.waitForTimeout(150);
      const tip = await page.evaluate(() => { const t = document.querySelector('.tip'); return t && t.style.display !== 'none' ? t.textContent : ''; });
      if (!/N=/.test(tip)) problems.push(`a hover on the survival chart shows: ${tip.slice(0, 80)}`);
    }
    for (const width of [390, 1024, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const name of ['tree', 'gates', 'survival', 'table', 'about']) {
        await page.locator(`nav.tabs button[data-page=${name}]`).click();
        await page.waitForTimeout(200);
        for (const p of await page.evaluate(inspectTables)) problems.push(`${name} at ${width}px: ${p}`);
      }
    }
    report.stretched = stretched;
  } catch (error) {
    problems.push(`the check itself failed: ${String(error.message).split('\n')[0]}`);
  }
  await browser.close();
  const unique = [...new Set(problems)];
  if (unique.length) {
    console.log('FAIL');
    for (const p of unique.slice(0, 40)) console.log(p);
    process.exitCode = 1;
  } else {
    console.log(`OK (stretched rungs: ${report.stretched})`);
  }
})();
