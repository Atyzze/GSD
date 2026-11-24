const { chromium } = require('playwright'); const fs=require('fs');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }).catch(() => chromium.launch());
  const p = await b.newPage({ viewport: { width: 2400, height: 2000 } });
  await p.setContent('<html><head><meta charset="utf-8"></head><body style="margin:0;background:#fff"></body></html>');
  await p.addScriptTag({ path: require.resolve('mermaid/dist/mermaid.min.js', { paths: [__dirname] }) });
  await p.addScriptTag({ path: __dirname + '/flatten_in_browser.js' });
  const src = fs.readFileSync(process.argv[2],'utf8');
  const out = await p.evaluate(([s, t]) => { window.TITLE = t; return window.go(s); }, [src, process.argv[4] || 'diagram']);
  fs.writeFileSync(process.argv[3], out);
  console.log('bytes', out.length);
  await b.close();
})();
