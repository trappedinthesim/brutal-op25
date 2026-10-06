// Browser smoke test for the empty-library Systems dashboard. The server under
// test must use disposable data and can_listen=false; no radio is accessed.
const assert = require('node:assert/strict');
const net = require('node:net');
const os = require('node:os');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');

const edge = process.argv[2];
const url = process.argv[3] || 'http://127.0.0.1:8080/';
if (!edge) throw new Error('Usage: node test_empty_dashboard.cjs <edge.exe> [dashboard-url]');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const freePort = () => new Promise((resolve, reject) => {
  const server = net.createServer();
  server.once('error', reject);
  server.listen(0, '127.0.0.1', () => {
    const port = server.address().port;
    server.close(() => resolve(port));
  });
});

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'brutal-empty-ui-'));
  let browser, ws;
  try {
    const debugPort = await freePort();
    browser = spawn(edge, ['--headless=new', '--disable-gpu', '--edge-skip-compat-layer-relaunch', '--no-first-run',
      '--no-default-browser-check', '--no-sandbox', '--remote-allow-origins=*',
      `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, 'about:blank'],
      { windowsHide: true, stdio: 'ignore' });
    let target;
    for (let i = 0; i < 100; i++) {
      try {
        const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json();
        target = pages.find(page => page.type === 'page' && page.webSocketDebuggerUrl);
        if (target) break;
      } catch (_) {}
      await pause(100);
    }
    assert.ok(target, 'Edge debugging target did not start');
    ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', reject, { once: true });
    });
    let sequence = 0;
    const pending = new Map();
    ws.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (!message.id || !pending.has(message.id)) return;
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
    });
    const command = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
      const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
      return result.result.value;
    };
    const until = async expression => {
      for (let i = 0; i < 100; i++) {
        if (await evaluate(expression)) return;
        await pause(100);
      }
      throw new Error(`Timed out: ${expression}`);
    };
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Page.navigate', { url });
    await until('document.readyState === "complete" && !!document.querySelector(".brutal-tab[data-tab=manual]")');
    assert.match(await evaluate('document.title'), /Brutal OP25 \/\/ Systems/);
    assert.match(await evaluate('document.getElementById("radio-hint").textContent'), /not connected/i);
    for (const name of ['Smoke Alpha', 'Smoke Beta']) {
      await evaluate('document.querySelector(".brutal-tab[data-tab=manual]").click()');
      await until('!!document.querySelector(".brutal-body input[placeholder*=County]")');
      const disabled = await evaluate('document.querySelectorAll(".brutal-body input[type=checkbox]")[1].disabled');
      assert.equal(disabled, true, 'Listening must be disabled without USB');
      await evaluate(`(() => { const fields = document.querySelectorAll('.brutal-body input[type=text]');
        fields[0].value=${JSON.stringify(name)}; fields[1].value='Test Site'; fields[2].value='851.0125';
        [...document.querySelectorAll('.brutal-body button')].find(b => b.textContent === 'Save system').click(); })()`);
      await until(`document.querySelector('.brutal-body')?.textContent.includes(${JSON.stringify(name)})`);
    }
    const rows = await evaluate('document.querySelectorAll(".brutal-row").length');
    assert.equal(rows, 2);
    const response = await fetch(url + 'brutal/api/status');
    const state = await response.json();
    assert.equal(state.active, null);
    console.log('PASS: empty dashboard adds two systems without a radio or receiver start');
  } finally {
    ws?.close();
    // On Windows, terminating only Edge's parent leaves child processes holding
    // its temporary profile open. Stop only this test browser's process tree.
    if (browser && process.platform === 'win32' && Number.isInteger(browser.pid)) {
      spawnSync('taskkill', ['/T', '/F', '/PID', String(browser.pid)],
        { windowsHide: true, stdio: 'ignore' });
    } else browser?.kill();
    if (browser && browser.exitCode === null) {
      await Promise.race([new Promise(resolve => browser.once('exit', resolve)), pause(2000)]);
    }
    const tempRoot = fs.realpathSync(os.tmpdir());
    const target = fs.realpathSync(profile);
    if (!target.startsWith(tempRoot + path.sep) || !path.basename(target).startsWith('brutal-empty-ui-'))
      throw new Error('Refusing to remove an unexpected browser test directory');
    try { fs.rmSync(target, { recursive: true, force: true, maxRetries: 20, retryDelay: 250 }); }
    catch (error) { console.warn(`Temporary browser profile cleanup deferred: ${error.code}`); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
