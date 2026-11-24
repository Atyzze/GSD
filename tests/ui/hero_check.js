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
const WIDTHS = (widthsArg || '1100,1280,1440,1749,1920').split(',').map(Number);
const META = '970 measured candidates 8,900 refused 1,092 at a limit 1 at 1 probe 3 at 2 0 at 3 0 at 4 2 by Einstein '
  + 'include lattice starts 9,902 proposal opportunities';

function measure({ filters, meta }) {
  document.getElementById('homeFilters').innerHTML = filters;
  document.getElementById('landMeta').textContent = meta;
  const panel = document.getElementById('filterPanel');
  document.documentElement.style.setProperty('--gsd-filter-h', `${Math.ceil(panel.getBoundingClientRect().height)}px`);
  const land = document.querySelector('.land-panel');
  const wrap = document.querySelector('.canvaswrap');
  const top = document.querySelector('.top100-panel');
  const hero = document.querySelector('.hero');
  const box = (el) => el.getBoundingClientRect();
  return {
    landClipped: land.scrollHeight - land.clientHeight,
    wrapBelowPanel: box(wrap).bottom - (box(land).bottom - parseFloat(getComputedStyle(land).paddingBottom)),
    wrapHeight: box(wrap).height,
    floor: parseFloat(getComputedStyle(wrap).minHeight),
    topHeight: box(top).height,
    heroHeight: box(hero).height,
    filterBottom: box(panel).bottom,
    heroBottom: box(hero).bottom,
  };
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
  const filters = (dumps.homeFilters || [])[0];
  if (!filters) { console.log('FAIL the smoke drew no filter panel to measure'); process.exitCode = 1; await browser.close(); return; }
  const wide = filters.replace(/<\/div>\s*<div class=filter-row>/, Array.from({ length: 9 }, (_, i) =>
    `<label class="kind-pill"><input type=checkbox checked>a kind of law ${i} ${100 * i}</label>`).join('')
    + '</div><div class=filter-row>');
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
  const problems = [];
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 1000 });
    for (const [name, html] of [['the smoke\'s filters', filters], ['a filter panel of many kinds', wide]]) {
      const m = await page.evaluate(measure, { filters: html, meta: META });
      const where = `${name} at ${width}px`;
      if (m.landClipped > 1) problems.push(`${where}: the landscape's panel cuts off ${m.landClipped}px of its plot`);
      if (m.wrapBelowPanel > 1) problems.push(`${where}: the plot ends ${m.wrapBelowPanel}px below its panel`);
      if (m.wrapHeight + 1 < m.floor) problems.push(`${where}: the plot is ${m.wrapHeight}px, under its ${m.floor}px floor`);
      if (width <= 1250) continue;
      if (Math.abs(m.topHeight - m.heroHeight) > 1) problems.push(`${where}: the Top 100 is ${m.topHeight}px in a ${m.heroHeight}px row`);
      if (m.filterBottom > m.heroBottom + 1) problems.push(`${where}: the filters run ${m.filterBottom - m.heroBottom}px past the row`);
    }
  }
  await browser.close();
  if (!problems.length) { console.log(`OK the landscape holds its plot beside the Top 100 at ${WIDTHS.join(', ')} px`); return; }
  console.log('FAIL');
  for (const problem of problems) console.log(problem);
  process.exitCode = 1;
})();
