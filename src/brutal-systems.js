/* Brutal OP25 Systems panel: add, switch and remove saved systems from the dashboard.
   Talks only to /brutal/api/* on this same origin. All text is inserted as text nodes,
   never as HTML, because system and talkgroup names come from an external database. */
(function () {
  'use strict';
  const API = '/brutal/api/';
  let token = null, session = null, status = null, known = null, busy = false;
  let rr = { states: [], countySystems: [], stateSystems: [], systems: [], chosen: null, filter: '' };
  let popup = null, tab = 'saved', tabArgs = {};
  const extraTabs = []; // tabs added by other scripts (brutal-tuning.js) through registerTab

  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === 'class') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (value === true) node.setAttribute(key, '');
      else if (value !== false && value != null) node.setAttribute(key, value);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return node;
  }


  // Replace a node's children, flattening arrays and dropping null/false (replaceChildren would print them).
  function put(node, ...kids) {
    node.replaceChildren(...kids.flat(Infinity).filter(kid => kid != null && kid !== false));
  }
  async function api(path, body) {
    const options = body === undefined ? {} : {
      method: 'POST', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', 'X-Brutal-Token': token || '' } };
    const response = await fetch(API + path, { cache: 'no-store', ...options });
    let data = {};
    try { data = await response.json(); } catch (e) { /* non-JSON error page */ }
    if (!response.ok) throw new Error(data.error || ('Request failed (' + response.status + ')'));
    return data;
  }

  async function start() {
    const info = await api('session');
    token = info.token; session = info;
  }

  function uptime(seconds) {
    const pad = n => String(n).padStart(2, '0');
    return pad(Math.floor(seconds / 3600)) + ':' + pad(Math.floor(seconds % 3600 / 60)) + ':' + pad(seconds % 60);
  }

  // ---------- live status strip ----------
  function paintStrip(s) {
    const dot = document.getElementById('brutal-ctx-dot');
    const system = document.getElementById('brutal-ctx-system');
    const session_ = document.getElementById('brutal-ctx-session');
    const state = s ? s.state : 'offline';
    if (dot) dot.dataset.state = state;
    if (system) system.textContent = s ? (s.active ? s.active.name : 'NO SYSTEM') : 'OFFLINE';
    if (session_) session_.textContent = state === 'running' ? uptime(s.uptime_s) : state.toUpperCase();
    paintBanner(s);
  }

  function paintBanner(s) {
    let banner = document.getElementById('brutal-banner');
    const bad = s && s.active && (s.state === 'error' || s.state === 'stopped') && !busy;
    if (!bad) { if (banner) banner.remove(); return; }
    const key = s.state + '|' + s.message;
    if (banner && banner.dataset.key === key) return; // unchanged: rebuilding every poll would eat clicks
    if (!banner) {
      banner = el('div', { id: 'brutal-banner', role: 'alert' });
      const strip = document.querySelector('.ops-context');
      (strip ? strip.after(banner) : document.body.prepend(banner));
    }
    banner.dataset.key = key;
    put(banner, el('span', {}, s.message || 'The receiver is not running.'),
      el('button', { class: 'brutal-btn', onclick: () => run(() => api('receiver/restart', {}).then(() => waitForReceiver())) }, 'Restart receiver'),
      el('button', { class: 'brutal-btn', onclick: () => open('saved') }, 'Choose a system'));
  }

  async function poll() {
    try {
      status = await api('status');
      if (known && status.active && status.active.id !== known && status.state === 'running' && !busy) {
        location.reload(); // another window switched systems: re-sync this page
        return;
      }
      if (status.active && status.state === 'running') known = status.active.id;
    } catch (e) { status = null; }
    paintStrip(status);
  }

  // ---------- switching ----------
  async function waitForReceiver(target) {
    busy = true;
    setMessage('Switching: the receiver restarts, which takes a few seconds of silence…', 'warn');
    const deadline = Date.now() + 120000;
    try {
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 1200));
        await poll();
        if (status && status.state === 'error') throw new Error(status.message);
        if (status && status.state === 'running' && (!target || (status.active && status.active.id === target))) {
          await new Promise(r => setTimeout(r, 1500));
          location.reload();
          return;
        }
      }
      throw new Error('The receiver took too long to start. Check the terminal window.');
    } finally { busy = false; }
  }

  async function run(action) {
    if (busy) return;
    try { setMessage('', ''); if (!token) await start(); await action(); }
    catch (error) {
      busy = false;
      setMessage(error.message, 'bad');
      if (tab === 'saved') render(); // lists can be stale after a failure; forms must keep what was typed
    }
  }

  // ---------- popup shell ----------
  function setMessage(text, kind) {
    const box = popup && popup.querySelector('.brutal-msg');
    if (box) { box.textContent = text; box.className = 'brutal-msg ' + (kind || ''); }
  }

  function build() {
    popup = el('div', { id: 'brutalSystemsPopup', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'brutalSystemsTitle',
      onclick: event => { if (event.target === popup && !busy) close(); } },
      el('div', { class: 'brutal-card' },
        el('div', { class: 'brutal-head' },
          el('h2', { id: 'brutalSystemsTitle' }, 'Systems'),
          el('button', { class: 'brutal-x', 'aria-label': 'Close', onclick: () => { if (!busy) close(); } }, '×')),
        el('div', { class: 'brutal-tabs', role: 'tablist' },
          ...[['saved', 'Saved'], ...extraTabs.map(x => [x.id, x.label]), ['rr', 'Add from RadioReference'], ['manual', 'Add manually']].map(([id, label]) =>
            el('button', { class: 'brutal-tab', role: 'tab', 'data-tab': id, onclick: () => { if (!busy) open(id); } }, label))),
        el('div', { class: 'brutal-body' }),
        el('div', { class: 'brutal-msg', role: 'status', 'aria-live': 'polite' })));
    document.body.append(popup);
  }

  async function open(which, args) {
    if (!popup) build();
    tab = which || tab;
    tabArgs = args || {};
    popup.classList.add('show');
    try { if (!token) await start(); } catch (e) { setMessage('The control service is not available: ' + e.message, 'bad'); }
    render();
  }

  function close() { if (popup) popup.classList.remove('show'); }

  async function render() {
    if (!popup) return;
    popup.querySelectorAll('.brutal-tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.tab === tab)));
    const body = popup.querySelector('.brutal-body');
    const extra = extraTabs.find(x => x.id === tab);
    if (tab === 'saved') await renderSaved(body);
    else if (extra) await extra.render(body, tabArgs);
    else if (tab === 'rr') renderRR(body);
    else renderManual(body);
  }

  // ---------- Saved tab ----------
  async function renderSaved(body) {
    put(body, el('p', { class: 'brutal-hint' }, 'Loading…'));
    let data;
    try { data = await api('systems'); } catch (e) { put(body, el('p', { class: 'brutal-hint' }, e.message)); return; }
    const rows = data.systems.map(s => el('div', { class: 'brutal-row' + (s.active ? ' active' : '') },
      el('div', { class: 'brutal-row-main' },
        el('strong', {}, s.name),
        el('span', { class: 'brutal-meta' }, [s.site, s.talkgroups + ' talkgroups', s.control_channels + ' control channels',
          s.source === 'manual' ? 'manual' : 'RadioReference'].join(' · '))),
      s.active ? el('span', { class: 'brutal-badge' }, 'LISTENING') : null,
      !s.active ? el('button', { class: 'brutal-btn primary', disabled: !s.compatible, title: s.reason || 'Switch to this system',
        onclick: () => run(() => api('systems/activate', { id: s.id }).then(() => waitForReceiver(s.id))) },
        s.compatible ? 'Listen' : 'Other radio') : null,
      !s.active ? el('button', { class: 'brutal-btn danger', title: 'Remove from this list (kept in an archive folder)',
        onclick: () => { if (confirm('Remove "' + s.name + '" from your saved systems?')) run(async () => { await api('systems/remove', { id: s.id }); await render(); setMessage('Removed.', 'ok'); }); } },
        'Remove') : null));
    put(body, 
      data.unreadable.length ? el('p', { class: 'brutal-hint bad' }, data.unreadable.length + ' saved file(s) could not be read and were skipped.') : null,
      rows.length ? rows : el('p', { class: 'brutal-hint' }, 'No saved systems yet. Add one from RadioReference or manually.'),
      el('p', { class: 'brutal-hint' }, session && !session.can_listen
        ? 'Systems are saved locally. Relaunch with the guided USB connection to start listening.'
        : 'Switching restarts the receiver for a few seconds. Systems stay saved for next time.'));
  }

  // ---------- RadioReference tab ----------
  function select(label, id, options, onchange, placeholder) {
    return el('label', { class: 'brutal-field' }, label,
      el('select', { id, onchange }, el('option', { value: '' }, placeholder || 'Choose…'),
        options.map(o => el('option', { value: o.id }, o.name))));
  }

  async function renderRR(body) {
    if (!session || !session.rr_enabled) {
      put(body, el('p', { class: 'brutal-hint bad' },
        'RadioReference import is not set up for this installation (no application key). Saved systems and manual setup still work.'));
      return;
    }
    if (!status || !status.rr_connected) {
      const user = el('input', { id: 'rrUser', type: 'text', autocomplete: 'off', spellcheck: 'false' });
      const pass = el('input', { id: 'rrPass', type: 'password', autocomplete: 'off' });
      const submit = () => run(async () => {
        await api('rr/login', { username: user.value, password: pass.value });
        pass.value = '';
        await poll();
        rr = { states: [], countySystems: [], stateSystems: [], systems: [], chosen: null, filter: '' };
        await render(); // renders the browser and loads the country list
      });
      pass.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
      put(body, 
        el('p', { class: 'brutal-hint' }, 'Sign in to browse systems. Your login is kept in memory for this session only. It is never saved, logged or written to disk.'),
        el('label', { class: 'brutal-field' }, 'RadioReference username', user),
        el('label', { class: 'brutal-field' }, 'Password', pass),
        el('button', { class: 'brutal-btn primary', onclick: submit }, 'Sign in'));
      return;
    }
    put(body, 
      el('div', { class: 'brutal-toolbar' },
        el('span', { class: 'brutal-hint' }, 'Signed in to RadioReference'),
        el('button', { class: 'brutal-btn', onclick: () => run(async () => { await api('rr/logout', {}); await poll(); await render(); }) }, 'Sign out')),
      el('div', { class: 'brutal-grid' },
        select('Country', 'rrCountry', [], () => run(loadStates)),
        select('State / province', 'rrState', [], () => run(loadCounties)),
        select('County / area', 'rrCounty', [], () => run(loadSystems))),
      el('input', { id: 'rrFilter', class: 'brutal-search', type: 'search', placeholder: 'Filter systems by name…',
        oninput: event => { rr.filter = event.target.value; paintSystems(); } }),
      el('div', { id: 'rrSystems', class: 'brutal-list' }),
      el('div', { id: 'rrSites' }));
    if (!rr.countries) loadCountries(); else fillCountries();
  }

  function fill(id, options, chosen) {
    const node = document.getElementById(id);
    if (!node) return;
    put(node, el('option', { value: '' }, 'Choose…'), options.map(o => el('option', { value: o.id }, o.name)));
    if (chosen != null) node.value = chosen;
  }

  async function loadCountries() {
    await run(async () => {
      rr.countries = (await api('rr/browse', { level: 'countries' })).countries;
      fillCountries();
      const us = rr.countries.find(c => c.code === 'US' || c.name.toLowerCase() === 'united states');
      if (us) { document.getElementById('rrCountry').value = us.id; await loadStates(); }
    });
  }
  function fillCountries() { fill('rrCountry', rr.countries || []); }

  async function loadStates() {
    const id = document.getElementById('rrCountry').value;
    fill('rrState', []); fill('rrCounty', []); rr.systems = []; paintSystems();
    if (!id) return;
    rr.states = (await api('rr/browse', { level: 'states', id })).states;
    fill('rrState', rr.states);
  }

  async function loadCounties() {
    const id = document.getElementById('rrState').value;
    fill('rrCounty', []); rr.systems = []; rr.stateSystems = []; paintSystems();
    if (!id) return;
    const data = await api('rr/browse', { level: 'counties', id });
    rr.stateSystems = data.systems || [];
    fill('rrCounty', data.counties);
    rr.systems = rr.stateSystems.slice();
    paintSystems();
  }

  async function loadSystems() {
    const id = document.getElementById('rrCounty').value;
    if (!id) { rr.systems = rr.stateSystems.slice(); paintSystems(); return; }
    const data = await api('rr/browse', { level: 'systems', id });
    const merged = new Map(rr.stateSystems.map(s => [s.id, s]));
    data.systems.forEach(s => merged.set(s.id, s));
    rr.systems = [...merged.values()];
    paintSystems();
  }

  function paintSystems() {
    const list = document.getElementById('rrSystems');
    if (!list) return;
    const needle = rr.filter.trim().toLowerCase();
    const shown = rr.systems.filter(s => !needle || s.name.toLowerCase().includes(needle))
      .sort((a, b) => a.name.localeCompare(b.name));
    put(list, shown.length ? shown.map(s => el('button', { class: 'brutal-pick' + (rr.chosen && rr.chosen.id === s.id ? ' active' : ''),
      onclick: () => run(() => chooseSystem(s.id)) }, s.name, s.city ? el('span', { class: 'brutal-meta' }, ' · ' + s.city) : null))
      : el('p', { class: 'brutal-hint' }, rr.systems.length ? 'No systems match that filter.' : 'Pick a state (and optionally a county) to list P25 systems.'));
  }

  async function chooseSystem(id) {
    setMessage('Fetching sites and talkgroups…', 'warn');
    rr.chosen = await api('rr/system', { id });
    setMessage('', '');
    paintSystems();
    const sites = document.getElementById('rrSites');
    const canListen = !!(session && session.can_listen);
    const listen = el('input', { type: 'checkbox', id: 'rrListen', checked: canListen, disabled: !canListen });
    put(sites, 
      el('h3', {}, rr.chosen.name),
      el('p', { class: 'brutal-hint' }, rr.chosen.talkgroups + ' talkgroups. Encrypted voice cannot be decoded. New systems use the selected radio settings.'),
      rr.chosen.import_warnings.length ? el('p', { class: 'brutal-hint bad' }, rr.chosen.import_warnings.length + ' database entries were skipped or merged: ' + rr.chosen.import_warnings.slice(0, 3).join(' ')) : null,
      el('div', { class: 'brutal-list' }, rr.chosen.sites.map(site => el('label', { class: 'brutal-pick' + (site.selectable ? '' : ' disabled') },
        el('input', { type: 'radio', name: 'rrSite', value: site.id, disabled: !site.selectable }),
        ' ', site.name, el('span', { class: 'brutal-meta' }, ' · ' + (site.selectable ? site.control_channels + ' control channels' : 'no control channels listed'))))),
      el('label', { class: 'brutal-check' }, listen, ' Start listening to it right away'),
      el('button', { class: 'brutal-btn primary', onclick: () => run(async () => {
        const picked = sites.querySelector('input[name="rrSite"]:checked');
        if (!picked) throw new Error('Choose a site first.');
        const result = await api('systems/save', { site_id: Number(picked.value), activate: listen.checked });
        if (listen.checked) await waitForReceiver(result.saved.id);
        else { tab = 'saved'; await render(); setMessage('Saved ' + result.saved.name + '.', 'ok'); }
      }) }, 'Save system'));
  }

  // ---------- Manual tab ----------
  function renderManual(body) {
    const f = {
      name: el('input', { type: 'text', autocomplete: 'off', placeholder: 'e.g. County Public Safety' }),
      site: el('input', { type: 'text', autocomplete: 'off', placeholder: 'e.g. Downtown tower' }),
      freqs: el('input', { type: 'text', autocomplete: 'off', placeholder: '851.0125, 851.5125' }),
      tdma: el('input', { type: 'checkbox' }),
      listen: el('input', { type: 'checkbox', checked: !!(session && session.can_listen),
        disabled: !(session && session.can_listen) }) };
    put(body, 
      el('p', { class: 'brutal-hint' }, 'For a system you already know the control channels for. No RadioReference login needed.'),
      el('label', { class: 'brutal-field' }, 'System name', f.name),
      el('label', { class: 'brutal-field' }, 'Site name', f.site),
      el('label', { class: 'brutal-field' }, 'Control channels (MHz, comma separated)', f.freqs),
      el('label', { class: 'brutal-check' }, f.tdma, ' The control channel is TDMA / Phase 2 (leave off if unsure)'),
      el('label', { class: 'brutal-check' }, f.listen, ' Start listening to it right away'),
      el('button', { class: 'brutal-btn primary', onclick: () => run(async () => {
        const result = await api('systems/manual', { name: f.name.value, site: f.site.value,
          frequencies: f.freqs.value, tdma: f.tdma.checked, activate: f.listen.checked });
        if (f.listen.checked) await waitForReceiver(result.saved.id);
        else { tab = 'saved'; await render(); setMessage('Saved ' + result.saved.name + '.', 'ok'); }
      }) }, 'Save system'));
  }

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && popup && popup.classList.contains('show') && !busy) close();
  });

  // Plot frames are only worth downloading and decoding while somebody can see them. main.js (patched in
  // brutal_ui.py) asks this before swapping each plot image, so a background tab or a hidden Plot panel
  // stops fetching about 5 images per second.
  window.brutalPlotsVisible = function () {
    const panel = document.getElementById('plot-container');
    return !document.hidden && !!panel && panel.offsetParent !== null;
  };

  // What other scripts need to build tabs that look and behave like the built-in ones.
  const ctx = { el, put, api, run, setMessage, waitForReceiver, open, render: () => render(),
    get status() { return status; }, get session() { return session; } };
  window.brutalSystems = { open, ctx, registerTab(definition) { extraTabs.push(definition); } };
  poll();
  setInterval(poll, 3000);
})();
