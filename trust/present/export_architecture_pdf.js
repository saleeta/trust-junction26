// Export the two-minute browser presentation as a static, screen-sized PDF.
// Run with NODE_PATH pointing to the bundled workspace node_modules.
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');
const { PDFDocument } = require('pdf-lib');

async function main() {
  const root = path.resolve(__dirname, '..', '..');
  const source = path.join(root, 'docs', 'architecture-presentation.html');
  const target = path.join(root, 'docs', 'architecture-presentation.pdf');
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 920 }, deviceScaleFactor: 1.5 });
    await page.goto(pathToFileURL(source).href, { waitUntil: 'load' });
    await page.addStyleTag({ content: `
      *, *::before, *::after { animation: none !important; transition: none !important; }
      .active .reveal { opacity: 1 !important; transform: none !important; }
      .active .route { stroke-dashoffset: 0 !important; }
      .active .route-node { opacity: 1 !important; }
    ` });
    const count = await page.locator('.slide').count();
    const pdf = await PDFDocument.create();
    for (let i = 0; i < count; i++) {
      await page.evaluate(i => show(i), i);
      const png = await page.locator('.stage').screenshot({ animations: 'disabled' });
      const image = await pdf.embedPng(png);
      const slide = pdf.addPage([1152, 648]);
      slide.drawImage(image, { x: 0, y: 0, width: 1152, height: 648 });
    }
    fs.writeFileSync(target, await pdf.save());
    console.log(`${count} slides: ${target}`);
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
