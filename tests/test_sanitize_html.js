/* 米哈游公告正文清洗（static/index.html::sanitizeHtml）用例
   把清洗结果真正写进 DOM，检查脚本是否被执行、白名单是否放行正常标签。
   运行：node tests/test_sanitize_html.js
   解析器优先用 jsdom（npm i jsdom），其次用 chromium --headless；都没有则 SKIP（退出码 0）。 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const page = fs.readFileSync(path.join(ROOT, 'static', 'index.html'), 'utf8');
const s0 = page.indexOf('<script>', page.indexOf('<script src="scraper.js"></script>')) + 8;
const SANITIZER = page.slice(page.indexOf('const ALLOW_TAGS', s0), page.indexOf('/* 米哈游事件', s0));

/* [输入, 必须保留的片段(null=不检查), 不得出现的片段]
   清洗结果会被写进真实 DOM；只要任一用例触发脚本（含异步事件属性），整轮判失败。 */
const CASES = [
  ['<svg/onload=window.__XSS=1>hello</svg>', null, 'onload'],
  ['<svg/onLoad = window.__XSS=1>', null, 'onLoad'],
  ['</title><svg/onload=window.__XSS=1>', null, 'onload'],
  ['<img src=x onerror=window.__XSS=1>', null, 'onerror'],
  ['<IMG SRC=x ONERROR=window.__XSS=1>', null, 'ONERROR'],
  ['<script>window.__XSS=1</script>', null, '<script'],
  ['<iframe src="https://evil.example"></iframe>', null, '<iframe'],
  ['<object data="x"></object>', null, '<object'],
  ['<div onclick="window.__XSS=1">文字</div>', '文字', 'onclick'],
  ['<a href="javascript:window.__XSS=1">x</a>', null, 'javascript:'],
  ['<a href="JaVaScRiPt:alert(1)">x</a>', null, 'JaVaScRiPt'],
  ['<p>正常段落<strong>粗体</strong></p>', '<strong>粗体</strong>', null],
  ['<h3>标题</h3>', '<h3>标题</h3>', null],
  ['<table><tr><td>1</td></tr></table>', '<td>1</td>', null],
  ['<div style="color:red">样式被剥离</div>', '样式被剥离', 'color:red'],
  ['<img src="https://sdk.hoyoverse.com/a.png" alt="图">', 'sdk.hoyoverse.com/a.png', null],
  ['<a href="https://www.miyoushe.com/x">官网</a>', 'https://www.miyoushe.com/x', null],
];

function payload() {
  return `${SANITIZER}
const CASES = ${JSON.stringify(CASES).replace(/<\//g, '<\\/')};
const out = [];
for (const [src, must, forbid] of CASES) {
  let res;
  try { res = sanitizeHtml(src); } catch (e) { res = 'ERROR ' + e.message; }
  if (!/^ERROR /.test(res)) { const box = document.createElement('div'); box.innerHTML = res; document.body.appendChild(box); }
  out.push({ src, res, must, forbid });
}
if (typeof window !== 'undefined') {
  window.__CASES = out;
  window.__XSS = undefined;
  setTimeout(() => { window.__DONE = true; }, 200);   // 等事件属性异步触发完
}
'PENDING';`;
}

async function runWithJsdom() {
  let JSDOM;
  try { ({ JSDOM } = require('jsdom')); } catch (e) { return null; }
  const dom = new JSDOM('<body></body>', { runScripts: 'outside-only' });
  dom.window.eval(payload());
  const report = dom.window.__CASES;
  if (!report) return null;
  await new Promise((r) => setTimeout(r, 400));      // onload/onerror 是异步的
  const xss = dom.window.__XSS;
  if (xss !== undefined) throw new Error('清洗后的公告仍执行了脚本 window.__XSS=' + xss);
  return report;
}

function runWithChromium() {
  const bin = ['chromium', 'chromium-browser', 'google-chrome'].find((b) => {
    try { execFileSync('which', [b], { stdio: 'ignore' }); return true; } catch (e) { return false; }
  });
  if (!bin) return null;
  const file = path.join(os.tmpdir(), 'ycal_sanitize_test.html');
  const script = payload().replace(/'PENDING';$/,
    `setTimeout(() => {
       const pre = document.createElement('pre'); pre.id = 'report';
       pre.textContent = btoa(unescape(encodeURIComponent(JSON.stringify(
         { cases: window.__CASES, xss: window.__XSS }))));
       document.body.appendChild(pre);
     }, 400);`);
  fs.writeFileSync(file, `<html><body><script>${script}</script></body></html>`);
  const dom = execFileSync(bin, ['--headless', '--no-sandbox', '--disable-gpu',
    '--virtual-time-budget=5000', '--dump-dom', file],
    { encoding: 'utf8', timeout: 90000, stdio: ['ignore', 'pipe', 'ignore'] });
  const m = dom.match(/<pre id="report">([\s\S]*?)<\/pre>/);
  if (!m) throw new Error('chromium 未产出报告（脚本报错或超时）');
  const rep = JSON.parse(Buffer.from(m[1], 'base64').toString('utf8'));
  if (rep.xss !== undefined && rep.xss !== null) throw new Error('清洗后的公告仍执行了脚本 window.__XSS=' + rep.xss);
  return rep.cases;
}

async function main() {
  let report = null;
  let via = '';
  try { report = await runWithJsdom(); if (report) via = 'jsdom'; } catch (e) { report = null; console.log('WARN jsdom 执行失败:' + e.message); }
  if (!report) {
    try { report = runWithChromium(); if (report) via = 'chromium'; } catch (e) { console.log('WARN chromium 执行失败:' + e.message); }
  }
  if (!report) {
    console.log('SKIP 未找到 jsdom / chromium，跳过（需真实 HTML 解析器才能验证 XSS）');
    process.exit(0);
  }

  let fail = 0;
  for (const r of report) {
    const problems = [];
    if (r.must && !r.res.includes(r.must)) problems.push('缺少 ' + JSON.stringify(r.must));
    if (r.forbid && r.res.includes(r.forbid)) problems.push('残留 ' + JSON.stringify(r.forbid));
    if (/^ERROR /.test(r.res)) problems.push('抛异常: ' + r.res);
    if (problems.length) { fail++; console.log('FAIL ' + JSON.stringify(r.src) + ' -> ' + JSON.stringify(r.res) + ' | ' + problems.join('; ')); }
    else console.log('OK   ' + JSON.stringify(r.src));
  }
  console.log(fail ? `\n${fail}/${report.length} FAILED (via ${via})` : `\nALL PASS (${report.length} 项, via ${via})`);
  process.exit(fail ? 1 : 0);
}
main();
