const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await p.goto('file:///C:/Users/Acer/pin-probe/data/dashboard.html');
  await p.waitForTimeout(2500);
  await p.screenshot({ path: 'docs/screenshot.png', clip: { x: 0, y: 0, width: 1440, height: 900 } });
  // full-page too for repo wiki use
  await p.screenshot({ path: 'docs/screenshot-full.png', fullPage: true });
  await b.close();
  console.log('shots done');
})();
