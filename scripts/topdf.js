// HTML -> PDF (A4) via puppeteer；参数: <html路径> <pdf路径>
const puppeteer = require('puppeteer');
const path = require('path');

(async () => {
  const [htmlPath, pdfPath] = process.argv.slice(2);
  const browser = await puppeteer.launch({ headless: 'new' });
  const page = await browser.newPage();
  await page.goto('file://' + path.resolve(htmlPath), { waitUntil: 'networkidle0' });
  await page.pdf({
    path: pdfPath,
    format: 'A4',
    printBackground: true,
    margin: { top: '13mm', bottom: '15mm', left: '12mm', right: '12mm' },
    displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: `<div style="width:100%;font-size:8px;color:#999;padding:0 12mm;display:flex;justify-content:space-between;font-family:'PingFang SC',sans-serif;">
      <span>叶思染财富月报 · 2026年6月</span>
      <span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
  });
  await browser.close();
  console.log('PDF written:', pdfPath);
})();
