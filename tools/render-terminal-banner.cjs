// Rebuild the transparent terminal splash from its editable HTML source.
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.BRUTAL_RENDER_BROWSER ? { executablePath: process.env.BRUTAL_RENDER_BROWSER } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 480, height: 190 }, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(path.join(__dirname, 'terminal-banner.html')).href);
    await page.locator('#banner img').evaluate(image => image.decode());
    await page.locator('#banner').screenshot({
      path: path.join(__dirname, '..', 'src', 'terminal-banner.png'),
      omitBackground: true,
    });
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
