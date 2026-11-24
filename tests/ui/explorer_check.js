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
    if (cell.closest('.breakable, code, pre')) continue;
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
    const style = getComputedStyle(cell);
    if (cell.scrollWidth > cell.clientWidth + 1 && style.overflowX !== 'visible' && style.textOverflow !== 'ellipsis'
        && cell.textContent.trim()) {
      problems.push(`a cell cut off: ${cell.textContent.trim().slice(0, 50)}`);
    }
  }
  for (const table of document.querySelectorAll('main table')) {
    let box = null;
    let scrolls = false;
    for (let a = table.parentElement; a; a = a.parentElement) {
      if (a.classList.contains('card') || a.tagName === 'MAIN') { box = a; break; }
      if (['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(a).overflowX)) scrolls = true;
    }
    if (!box || scrolls) continue;
    const over = table.getBoundingClientRect().right - box.getBoundingClientRect().right;
    if (over > 1) problems.push(`a table ${Math.round(over)}px wider than its card: ${table.textContent.trim().slice(0, 40)}`);
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
  const problems = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', (e) => problems.push(`an error in the page: ${String(e.message || e).split('\n')[0]}`));
  page.on('console', (m) => { if (m.type() === 'error') problems.push(`the console: ${m.text().slice(0, 200)}`); });
  const url = `file://${path.resolve(file)}`;
  page.on('request', (r) => { if (r.url() !== url && !r.url().startsWith('blob:') && !r.url().startsWith('data:')) problems.push(`a request: ${r.url()}`); });
  const info = () => page.evaluate(() => window.__explorer.info());
  try {
    await page.goto(url);
    await page.waitForFunction(() => window.__explorer && window.__explorer.ready, null, { timeout: 30000 });
    await page.waitForTimeout(400);
    let now = await info();
    if (now.page !== 'maps' || now.panels !== 16) problems.push(`the maps page drew ${now.panels} panels, not 16`);
    if (now.drawn.some((n) => n === 0)) problems.push(`a panel drew no reading: ${now.drawn.join(',')}`);
    const painted = await page.evaluate(() => {
      const c = document.querySelector('.panel canvas.base');
      const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      const seen = new Set();
      for (let i = 0; i < data.length; i += 4) seen.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);
      return seen.size;
    });
    if (painted < 6) problems.push(`the first panel is blank (${painted} colours)`);
    const before = now;
    await page.locator('aside input[type=checkbox]').first().uncheck();
    await page.waitForTimeout(300);
    now = await info();
    if (!(now.visible < before.visible)) problems.push(`unticking a campaign left ${now.visible} of ${before.visible} readings`);
    if (now.drawn[0] !== 0) problems.push(`the first campaign's panel still draws ${now.drawn[0]} readings after it was unticked`);
    await page.locator('aside input[type=checkbox]').first().check();
    await page.waitForTimeout(300);
    await page.locator('.panel .pmax').nth(5).click();
    await page.waitForTimeout(300);
    now = await info();
    if (now.panels !== 1 || !(now.drawn[0] > 0)) problems.push(`a panel asked to fill the page left ${now.panels} panels`);
    const box1 = await page.locator('.panel.focused .plot').boundingBox();
    if (!box1 || box1.height < 360) problems.push(`the panel filling the page is ${box1 ? Math.round(box1.height) : 0}px tall`);
    await page.locator('.panel.focused .pmax').click();
    await page.waitForTimeout(300);
    if ((await info()).panels !== 16) problems.push('its button did not take it back to the grid');
    await page.locator('.panel .pmax').nth(2).click();
    await page.waitForTimeout(300);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    if ((await info()).panels !== 16) problems.push('Esc did not take a filled panel back to the grid');
    const over = page.locator('.panel canvas.over').first();
    const box = await over.boundingBox();
    await page.mouse.move(box.x + box.width * 0.12, box.y + box.height * 0.05);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5, { steps: 6 });
    await page.mouse.move(box.x + box.width * 0.97, box.y + box.height * 0.9, { steps: 6 });
    await page.mouse.up();
    await page.waitForTimeout(300);
    now = await info();
    if (!now.selected) problems.push('a drag across a panel selected no law');
    const selected = now.selected;
    await page.locator('nav.tabs button[data-page=laws]').click();
    await page.waitForTimeout(300);
    const listed = await page.locator('main table tbody tr').count();
    if (listed !== Math.min(100, selected)) problems.push(`the Laws page lists ${listed} laws of ${selected} selected`);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    if ((await info()).selected) problems.push('Esc left the selection');
    await page.locator('nav.tabs button[data-page=start]').click();
    await page.waitForTimeout(300);
    const views = await page.locator('main .card button').count();
    if (views < 3) problems.push(`Start here offers ${views} views`);
    for (let v = 0; v < views; v++) {
      await page.locator('nav.tabs button[data-page=start]').click();
      await page.waitForTimeout(200);
      await page.locator('main .card button').nth(v).click();
      await page.waitForTimeout(500);
      now = await info();
      if (now.page === 'start') problems.push(`view ${v + 1} of Start here did not open`);
      if (now.page !== 'maps') continue;
      for (const size of ['2', '4']) {
        await page.locator('main .toolbar select').nth(0).selectOption(size);
        await page.locator('main .toolbar select').nth(1).selectOption(size);
        await page.waitForTimeout(200);
        const keys = await page.evaluate(() => window.__explorer.shown());
        const twice = keys.filter((k, i) => keys.indexOf(k) !== i);
        if (keys.length !== size * size) problems.push(`view ${v + 1} at ${size} by ${size} drew ${keys.length} panels`);
        if (twice.length) problems.push(`view ${v + 1} at ${size} by ${size} shows a plot twice: ${[...new Set(twice)].join(', ')}`);
      }
    }
    await page.locator('aside button', { hasText: 'Clear the filters' }).click();
    await page.waitForTimeout(300);
    await page.locator('nav.tabs button[data-page=laws]').click();
    await page.waitForTimeout(300);
    const head = await page.locator('main table thead').innerText();
    if (!/nearest family/.test(head)) problems.push(`the Laws page has no Classify column: ${head.slice(0, 160)}`);
    for (const [name, panels] of [['byn', true], ['spread', true], ['curves', true], ['scan', false], ['counts', false], ['laws', false], ['about', false]]) {
      await page.locator(`nav.tabs button[data-page=${name}]`).click();
      await page.waitForTimeout(name === 'scan' ? 2500 : 350);
      now = await info();
      if (now.page !== name) problems.push(`the ${name} page did not open`);
      if (panels && (!now.panels || !now.drawn.some((n) => n > 0))) problems.push(`the ${name} page drew nothing`);
      const text = await page.locator('main').innerText();
      if (text.trim().length < 40) problems.push(`the ${name} page is empty`);
      if (name === 'scan' && !/pairs measured/.test(text)) problems.push('the scan did not finish');
    }
    for (const width of [1024, 1280, 1440, 1767, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const name of ['spread', 'curves', 'scan', 'counts', 'laws']) {
        await page.locator(`nav.tabs button[data-page=${name}]`).click();
        await page.waitForTimeout(name === 'scan' ? 2000 : 250);
        for (const p of await page.evaluate(inspectTables)) problems.push(`${name} at ${width}px: ${p}`);
      }
    }
    const first = await page.evaluate(() => window.__explorer.data.laws.id[0]);
    const view = (v) => `${url}#${encodeURIComponent(JSON.stringify(v))}`;
    await page.goto('about:blank');
    await page.goto(view({ p: 'laws', sel: [first] }));
    await page.waitForFunction(() => window.__explorer && window.__explorer.ready, null, { timeout: 30000 });
    now = await info();
    if (now.page !== 'laws' || now.selected !== 1) problems.push(`an advice link to a law opened ${now.page} with ${now.selected} selected`);
    await page.goto('about:blank');
    await page.goto(view({ p: 'maps', m: { rows: 1, cols: 2, panels: [{ x: 'd_s', y: 'd_V', rung: 1024 }, { x: 'd_s', y: 'd_V', rung: 4096 }] },
      f: { cats: { regime: ['zero temperature'] } } }));
    await page.waitForFunction(() => window.__explorer && window.__explorer.ready, null, { timeout: 30000 });
    await page.waitForFunction(() => window.__explorer.info().drawn.some((n) => n > 0), null, { timeout: 15000 }).catch(() => {});
    now = await info();
    if (now.page !== 'maps' || now.panels !== 2 || !now.drawn.every((n) => n > 0)) {
      problems.push(`an advice link to a lead drew ${now.panels} panels (${now.drawn.join(',')}) on ${now.page}`);
    }
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
    console.log('OK');
  }
})();
