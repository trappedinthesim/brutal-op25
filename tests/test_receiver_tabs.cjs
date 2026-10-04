// Isolated browser audit of the generated receiver UI. POSTs are limited to
// boatbod's read-only dashboard commands; SDR-changing controls are not clicked.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const assets = process.argv[2];
const edge = process.argv[3];
const shots = process.argv[4];
if (!assets || !edge || !shots) throw new Error('Usage: node test_receiver_tabs.cjs <patched-www-static> <edge.exe> <shots-dir>');
const allowed = new Set(['index.html', 'main.js', 'main.css', 'brutal-ui.css', 'config.js', 'favicon.ico']);
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.ico': 'image/x-icon' };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function port() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const value = server.address().port;
      server.close(() => resolve(value));
    });
  });
}

async function run() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'brutal-op25-ui-'));
  let browser;
  let server;
  let ws;
  try {
    server = http.createServer(async (req, res) => {
      try {
        if (req.method === 'POST' && req.url === '/') {
          const chunks = [];
          for await (const chunk of req) chunks.push(chunk);
          const commands = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          const permitted = new Set(['get_terminal_config', 'get_full_config', 'get_ws_instances', 'update']);
          if (!Array.isArray(commands) || !commands.every(item => permitted.has(item.command))) {
            res.writeHead(403).end('Receiver-changing command blocked by UI audit');
            return;
          }
          const upstream = await fetch('http://127.0.0.1:8080/', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(commands)
          });
          res.writeHead(upstream.status, { 'Content-Type': 'application/json' }).end(await upstream.text());
          return;
        }
        if (req.method === 'GET' && /^\/plot-[a-zA-Z0-9_.-]+\.png(?:\?.*)?$/.test(req.url)) {
          const upstream = await fetch(`http://127.0.0.1:8080${req.url}`);
          res.writeHead(upstream.status, { 'Content-Type': 'image/png' })
            .end(Buffer.from(await upstream.arrayBuffer()));
          return;
        }
        const name = req.url === '/' ? 'index.html' : decodeURIComponent(req.url.slice(1));
        if (req.method !== 'GET' || !allowed.has(name)) {
          res.writeHead(404).end('Not found');
          return;
        }
        res.writeHead(200, { 'Content-Type': mime[path.extname(name)] || 'application/octet-stream' });
        fs.createReadStream(path.join(assets, name)).pipe(res);
      } catch (error) {
        res.writeHead(500).end(String(error));
      }
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const url = `http://127.0.0.1:${server.address().port}/`;
    const debugPort = await port();
    browser = spawn(edge, ['--headless=new', '--disable-gpu', '--no-first-run',
      '--no-default-browser-check', '--no-sandbox', '--remote-allow-origins=*',
      `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`,
      '--window-size=1440,1000', 'about:blank'], { windowsHide: true, stdio: 'ignore' });
    let target;
    for (let i = 0; i < 100; i++) {
      try {
        const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json();
        target = pages.find(page => page.type === 'page' && page.webSocketDebuggerUrl);
        if (target) break;
      } catch (_) {}
      await delay(100);
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
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else resolve(message.result);
    });
    function command(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = ++sequence;
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
      });
    }
    async function evaluate(expression) {
      const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
      return result.result.value;
    }
    async function until(expression) {
      for (let i = 0; i < 80; i++) {
        if (await evaluate(expression)) return;
        await delay(100);
      }
      throw new Error(`Timed out: ${expression}`);
    }
    async function screenshot(name) {
      const result = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      fs.writeFileSync(path.join(shots, name), Buffer.from(result.data, 'base64'));
    }
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Page.navigate', { url });
    await until('document.readyState === "complete" && typeof showHome === "function" && document.querySelector(".brutal-brand")');
    await evaluate('window.muteAudioAtStartup = true; localStorage.setItem("muteAudioAtStartup", "true"); document.getElementById("muteAudioAtStartup").checked = true');
    const base = await evaluate(`({title:document.title,brand:document.querySelector('.brutal-brand').innerText,
      tabs:[...document.querySelectorAll('.nav-left .nav-item')].map(x=>x.textContent.trim()),
      duplicateIds:[...document.querySelectorAll('[id]')].map(x=>x.id).filter((x,i,a)=>a.indexOf(x)!==i),
      color:getComputedStyle(document.body).backgroundColor})`);
    assert.match(base.title, /Brutal OP25/);
    assert.deepEqual(base.tabs, ['Home', 'Plot', 'Settings', 'View Config', 'About']);
    assert.deepEqual(base.duplicateIds, []);
    assert.equal(await evaluate('getComputedStyle(document.getElementById("plot-container")).display !== "none"'), true);
    await screenshot('01-home.png');

    await evaluate('document.getElementById("btn-plot").click()');
    assert.equal(await evaluate('getComputedStyle(document.getElementById("plot-container")).display'), 'none');
    await evaluate('document.getElementById("btn-home").click()');
    const plot = await evaluate(`({visible:getComputedStyle(document.getElementById('plot-container')).display!=='none',
      buttons:document.querySelectorAll('#plot-controls input[type=button]').length,
      images:document.querySelectorAll('.plot-image').length,
      accent:getComputedStyle(document.getElementById('btn-plot')).color})`);
    assert.equal(plot.visible, true);
    assert.equal(plot.buttons, 6);
    assert.equal(plot.images, 6);
    assert.equal(plot.accent, 'rgb(15, 255, 80)');
    await screenshot('02-plot.png');

    await evaluate('document.getElementById("btn-settings").click()');
    const settings = await evaluate(`({visible:getComputedStyle(document.getElementById('settingsPopupContainer')).display!=='none',
      green:document.getElementById('valueColorPicker').value,
      height:document.getElementById('callHeightControl').value,
      band:document.getElementById('showBandPlan').checked,
      subs:document.getElementById('trackSubsToggle').checked,
      history:document.getElementById('callHistoryToggle').checked,
      panel:getComputedStyle(document.querySelector('.settings-popup-content')).backgroundColor})`);
    assert.equal(settings.visible, true);
    assert.equal(settings.green, '#0fff50');
    assert.equal(settings.height, '320');
    assert.equal(settings.band, true);
    assert.equal(settings.subs, true);
    assert.equal(settings.history, true);
    assert.equal(settings.panel, 'rgb(17, 32, 23)');
    await delay(400);
    await screenshot('03-settings.png');
    await evaluate(`document.getElementById('callHistoryToggle').click();
      document.getElementById('valueColorPicker').value='#123456';
      document.getElementById('valueColorPicker').dispatchEvent(new Event('change'))`);
    assert.equal(await evaluate('localStorage.getItem("callHistoryToggle")'), 'false');
    assert.equal(await evaluate('getComputedStyle(document.getElementById("callHistoryContainer")).display'), 'none');
    await evaluate('document.getElementById("resetColor").click()');
    assert.equal(await evaluate('document.getElementById("valueColorPicker").value'), '#0fff50');
    await evaluate('document.getElementById("callHistoryToggle").click()');
    const localSettings = await evaluate(`(() => {
      const changed = {};
      for (const [id, container] of [
        ['channelsTableToggle', 'channels-container'],
        ['adjacentSitesToggle', 'adjacentSitesContainer']
      ]) {
        const box = document.getElementById(id);
        box.click();
        changed[id] = { saved: localStorage.getItem(id),
          display: getComputedStyle(document.getElementById(container)).display };
        box.click();
      }
      const height = document.getElementById('callHeightControl');
      height.value = '410'; height.dispatchEvent(new Event('input'));
      changed.callHeight = { saved: localStorage.getItem('callHeight'),
        display: document.querySelector('#callHistoryContainer .call-history-scroll').style.height };
      height.value = '320'; height.dispatchEvent(new Event('input'));
      const width = document.getElementById('plotSizeControl');
      width.value = '420'; width.dispatchEvent(new Event('input'));
      changed.plotWidth = { saved: localStorage.getItem('plotWidth'),
        display: document.querySelector('.plot-image').style.width };
      width.value = '300'; width.dispatchEvent(new Event('input'));
      for (const id of ['smartColorToggle', 'radioIdFreqTable', 'showBandPlan',
                        'trackSubsToggle', 'muteAudioAtStartup']) {
        const box = document.getElementById(id);
        box.click(); changed[id] = localStorage.getItem(id === 'smartColorToggle' ? 'smartColorsToggle' : id); box.click();
      }
      for (const [id, value, restore] of [
        ['subMode', 'selected', 'all'], ['callHistorySource', 'voice', 'frequency']
      ]) {
        const select = document.getElementById(id);
        select.value = value; select.dispatchEvent(new Event('change'));
        changed[id] = localStorage.getItem(id);
        select.value = restore; select.dispatchEvent(new Event('change'));
      }
      return changed;
    })()`);
    assert.deepEqual(localSettings.channelsTableToggle, { saved: 'false', display: 'none' });
    assert.deepEqual(localSettings.adjacentSitesToggle, { saved: 'false', display: 'none' });
    assert.deepEqual(localSettings.callHeight, { saved: '410', display: '410px' });
    assert.deepEqual(localSettings.plotWidth, { saved: '420', display: '420px' });
    assert.equal(localSettings.smartColorToggle, 'false');
    assert.equal(localSettings.radioIdFreqTable, 'true');
    assert.equal(localSettings.showBandPlan, 'false');
    assert.equal(localSettings.trackSubsToggle, 'false');
    assert.equal(localSettings.muteAudioAtStartup, 'false');
    assert.equal(localSettings.subMode, 'selected');
    assert.equal(localSettings.callHistorySource, 'voice');
    await command('Page.reload');
    await until('document.readyState === "complete" && document.getElementById("callHistoryToggle").checked');
    assert.equal(await evaluate('document.getElementById("valueColorPicker").value'), '#0fff50');
    assert.equal(await evaluate('document.getElementById("showBandPlan").checked'), true);
    assert.equal(await evaluate('document.getElementById("trackSubsToggle").checked'), true);
    await evaluate('togglePopup("settingsPopupContainer", false); document.getElementById("btn-about").click()');
    assert.equal(await evaluate('getComputedStyle(document.getElementById("aboutPopupContainer")).display'), 'flex');
    assert.match(await evaluate('document.querySelector(".about-content").innerText'), /boatbod/);
    await delay(400);
    await screenshot('04-about.png');
    await evaluate('togglePopup("aboutPopupContainer", false); document.getElementById("btn-config").click()');
    await until('document.getElementById("popupContainer").classList.contains("show") && document.querySelectorAll("#configDisplay .config-section").length > 0');
    await evaluate(`([...document.querySelectorAll('.config-header')].find(x=>x.textContent.includes('Trunking'))).click()`);
    const config = await evaluate(`({text:document.getElementById('configDisplay').innerText,
      panel:getComputedStyle(document.querySelector('.popup-content')).backgroundColor,
      section:getComputedStyle(document.querySelector('.config-section')).backgroundColor})`);
    assert.match(config.text, /Alamo Area Regional Radio System/);
    assert.equal(config.panel, 'rgb(17, 32, 23)');
    assert.equal(config.section, 'rgb(10, 24, 15)');
    await screenshot('05-config.png');
    await evaluate('document.getElementById("btn-home").click()');
    assert.equal(await evaluate('getComputedStyle(document.getElementById("popupContainer")).display'), 'none');
    const commandNames = await evaluate(`(() => {
      const sent = [];
      window.send_command = (...args) => sent.push(args);
      window.prompt = () => '123';
      window.alert = () => {};
      for (const label of ['SCAN', 'HOLD', 'LOCKOUT', 'GO TO']) {
        [...document.querySelectorAll('.left-panel button')]
          .find(button => button.textContent.trim() === label).click();
      }
      document.getElementById('btn-auto-focus').click();
      document.getElementById('s2_ch_dmp').click();
      document.getElementById('s2_buffer_dmp').click();
      document.getElementById('cap_bn').click();
      for (const label of ['Log Verbosity', 'Blacklist TGID', 'Whitelist TGID']) {
        [...document.querySelectorAll('#settings-container button')]
          .find(button => button.textContent.trim() === label).click();
      }
      document.getElementById('pb-fft').click();
      document.getElementById('tune3').click();
      return sent.map(args => args[0]);
    })()`);
    for (const name of ['skip', 'hold', 'lockout', 'whitelist', 'set_debug',
                        'dump_tgids', 'dump_buffer', 'capture',
                        'toggle_plot', 'adj_tune']) {
      assert.ok(commandNames.includes(name), `${name} button did not dispatch`);
    }
    assert.ok(!commandNames.includes('dump_tracking'), 'Unsupported backend command was dispatched');
    await command('Emulation.setDeviceMetricsOverride', {
      width: 700, height: 900, deviceScaleFactor: 1, mobile: false
    });
    await evaluate('document.getElementById("btn-settings").click()');
    await delay(400);
    const compact = await evaluate(`({viewport:innerWidth, page:document.documentElement.scrollWidth,
      settings:document.querySelector('.settings-popup-content').getBoundingClientRect().width})`);
    assert.ok(compact.page <= compact.viewport + 2, `Compact viewport overflow: ${JSON.stringify(compact)}`);
    assert.ok(compact.settings <= compact.viewport, `Settings popup overflow: ${JSON.stringify(compact)}`);
    await screenshot('06-settings-compact.png');
    console.log('PASS: Home, Plot, Settings, View Config, About, theme, defaults and local settings');
    console.log('PASS: Receiver-control buttons dispatch expected commands (intercepted; radio unchanged)');
    console.log(`Screenshots: ${shots}`);
  } finally {
    if (ws && ws.readyState === WebSocket.OPEN) ws.close();
    if (browser && !browser.killed) browser.kill();
    if (browser && browser.exitCode === null) {
      await Promise.race([new Promise(resolve => browser.once('exit', resolve)), delay(1500)]);
    }
    if (server) await new Promise(resolve => server.close(resolve));
    const resolved = path.resolve(profile);
    if (resolved.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolved).startsWith('brutal-op25-ui-')) {
      try { fs.rmSync(resolved, { recursive: true, force: true }); }
      catch (error) { console.warn(`Temporary browser profile cleanup deferred: ${error.code}`); }
    }
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
