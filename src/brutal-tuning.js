/* Brutal OP25 listening controls: talkgroup priority and blocking, radio names, advanced options, volume.
   Plugs into brutal-systems.js (load it first). Same rule as there: every name from the database or the
   user goes in as a text node, never as HTML. Changes are saved as a new revision of the listening
   system and the receiver restarts for a few seconds, because OP25 reads these files at startup. */
(function () {
  'use strict';
  const S = window.brutalSystems;
  if (!S) return;
  const { el, put, api, run, setMessage, waitForReceiver, open } = S.ctx;
  const FIRST_PAGE = 150, MORE = 200, MAX_RID = 16777215;
  const STATES = [['priority', '★', 'Priority'], ['normal', '•', 'Normal'], ['blocked', '⊘', 'Blocked']];

  async function applyAndRestart(changes) {
    const result = await api('systems/settings', changes);
    if (result.unchanged) { setMessage('Nothing changed, so there is nothing to apply.', 'ok'); return; }
    const active = S.ctx.status && S.ctx.status.active;
    await waitForReceiver(active ? active.id : null);
  }

  const restartNote = () => el('p', { class: 'brutal-hint' },
    'Applying saves these as a new version of this system and restarts the receiver, which takes a few seconds of silence.');

  // ---------- Talkgroups tab ----------
  let tg = null;

  async function renderTalkgroups(body) {
    put(body, el('p', { class: 'brutal-hint' }, 'Loading…'));
    let data;
    try { data = await api('talkgroups'); } catch (e) { put(body, el('p', { class: 'brutal-hint bad' }, e.message)); return; }
    tg = { data, state: new Map(data.talkgroups.map(t => [t.id, t.state])), only: data.listen_only,
           filter: '', category: 'all', hideEnc: false, limit: FIRST_PAGE, rows: new Map() };
    if (!data.talkgroups.length) {
      put(body, el('p', { class: 'brutal-hint' },
        'This system has no talkgroup list (it was added manually), so there is nothing to prioritise or block. Radio IDs and Advanced still apply.'));
      return;
    }
    draw(body);
  }

  function visible() {
    const q = tg.filter.trim().toLowerCase();
    return tg.data.talkgroups.filter(t => {
      if (tg.category !== 'all' && String(t.category_id) !== tg.category) return false;
      if (tg.hideEnc && t.encrypted) return false;
      return !q || String(t.id).includes(q) || t.label.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q);
    });
  }

  function changedCount() {
    let n = tg.data.talkgroups.filter(t => tg.state.get(t.id) !== t.state).length;
    return n + (tg.only !== tg.data.listen_only ? 1 : 0);
  }

  function setStates(ids, value) {
    ids.forEach(id => { tg.state.set(id, value); paintRow(id); });
    summary();
  }

  function paintRow(id) {
    const entry = tg.rows.get(id);
    if (!entry) return;
    const current = tg.state.get(id);
    entry.root.dataset.state = current;
    entry.buttons.forEach(([value, button]) => {
      button.classList.toggle('on', value === current);
      button.setAttribute('aria-pressed', String(value === current));
    });
  }

  function rowFor(t) {
    const buttons = STATES.map(([value, glyph, label]) => [value, el('button', {
      class: 'tg-state ' + value, type: 'button', title: label, 'aria-label': label + ': ' + t.label,
      onclick: () => setStates([t.id], value) }, glyph)]);
    const root = el('div', { class: 'tg-row', 'data-state': tg.state.get(t.id) },
      el('span', { class: 'tg-states', role: 'group' }, buttons.map(b => b[1])),
      el('span', { class: 'tg-id' }, String(t.id)),
      el('span', { class: 'tg-name' }, el('strong', {}, t.label),
        t.description && t.description !== t.label ? el('small', {}, t.description) : null),
      t.encrypted ? el('span', { class: 'tg-enc', title: 'Encrypted: OP25 cannot decode this' }, 'ENC') : null);
    tg.rows.set(t.id, { root, buttons });
    return root;
  }

  function summary() {
    const counts = { priority: 0, normal: 0, blocked: 0 };
    tg.state.forEach(s => { counts[s] += 1; });
    const note = document.getElementById('tgSummary');
    if (!note) return;
    const changes = changedCount();
    note.textContent = counts.priority + ' priority · ' + counts.blocked + ' blocked · ' + counts.normal + ' normal'
      + (changes ? ' · ' + changes + ' unsaved change' + (changes === 1 ? '' : 's') : '');
    note.classList.toggle('dirty', changes > 0);
    const warn = document.getElementById('tgWarn');
    if (warn) warn.textContent = tg.only && counts.priority === 0 ? 'Mark at least one talkgroup as Priority, or listen to everything.' : '';
  }

  function paintList() {
    const list = document.getElementById('tgList');
    if (!list) return;
    const matches = visible();
    const shown = matches.slice(0, tg.limit);
    tg.rows = new Map();
    put(list, shown.map(rowFor), matches.length > shown.length ? el('button', { class: 'brutal-btn tg-more', type: 'button',
      onclick: () => { tg.limit += MORE; paintList(); } }, 'Show ' + Math.min(MORE, matches.length - shown.length) + ' more (' + (matches.length - shown.length) + ' hidden)') : null,
      matches.length ? null : el('p', { class: 'brutal-hint' }, 'No talkgroups match.'));
    const bulk = document.getElementById('tgBulkCount');
    if (bulk) bulk.textContent = String(matches.length);
    summary();
  }

  function draw(body) {
    const data = tg.data;
    const search = el('input', { class: 'brutal-search', type: 'search', placeholder: 'Search name, description or number…',
      oninput: event => { tg.filter = event.target.value; tg.limit = FIRST_PAGE; paintList(); } });
    const category = el('select', { 'aria-label': 'Category', onchange: event => { tg.category = event.target.value; tg.limit = FIRST_PAGE; paintList(); } },
      el('option', { value: 'all' }, 'All categories (' + data.talkgroups.length + ')'),
      data.categories.map(c => el('option', { value: String(c.id) }, c.name + ' (' + c.count + ')')));
    const hideEnc = el('input', { type: 'checkbox', onchange: event => { tg.hideEnc = event.target.checked; tg.limit = FIRST_PAGE; paintList(); } });
    const mode = (value, text) => el('label', { class: 'brutal-check' },
      el('input', { type: 'radio', name: 'tgmode', checked: tg.only === value, onchange: () => { tg.only = value; summary(); } }), ' ', text);
    const bulk = value => el('button', { class: 'brutal-btn', type: 'button',
      onclick: () => setStates(visible().map(t => t.id), value) }, STATES.find(s => s[0] === value)[2]);
    put(body,
      el('p', { class: 'brutal-hint' }, el('strong', {}, data.profile.name), ' · ', '★ Priority calls interrupt lower-priority ones (a manual hold is never interrupted). ⊘ Blocked talkgroups are never followed.'),
      el('div', { class: 'tg-mode' }, mode(false, 'Listen to everything (except Blocked)'), mode(true, 'Only my Priority talkgroups')),
      !data.has_category_names && data.profile.source === 'radioreference' ? el('p', { class: 'brutal-hint' },
        'Category names (Fire, Police…) are not saved for this system yet. ',
        el('button', { class: 'brutal-btn', type: 'button', disabled: !(S.ctx.status && S.ctx.status.rr_connected),
          title: S.ctx.status && S.ctx.status.rr_connected ? 'Fetch them from RadioReference' : 'Sign in on the Add from RadioReference tab first',
          onclick: () => run(async () => { await api('rr/categories', {}); await renderTalkgroups(body); setMessage('Category names loaded.', 'ok'); }) }, 'Load category names')) : null,
      el('div', { class: 'tg-controls' }, search, category,
        el('label', { class: 'brutal-check' }, hideEnc, ' Hide encrypted')),
      el('div', { class: 'tg-bulk' }, el('span', { class: 'brutal-hint' }, 'Mark the ', el('b', { id: 'tgBulkCount' }, '0'), ' shown as:'),
        bulk('priority'), bulk('normal'), bulk('blocked')),
      el('div', { id: 'tgList', class: 'tg-list' }),
      el('p', { id: 'tgSummary', class: 'tg-summary' }), el('p', { id: 'tgWarn', class: 'brutal-hint bad' }),
      el('div', { class: 'brutal-toolbar' },
        el('button', { class: 'brutal-btn', type: 'button', onclick: () => renderTalkgroups(body) }, 'Reset changes'),
        el('button', { class: 'brutal-btn primary', type: 'button', onclick: () => run(async () => {
          const priority = [], blocked = [];
          tg.state.forEach((s, id) => { if (s === 'priority') priority.push(id); else if (s === 'blocked') blocked.push(id); });
          if (tg.only && !priority.length) throw new Error('Mark at least one talkgroup as Priority first, or choose to listen to everything.');
          await applyAndRestart({ priority_tgids: priority, blocked_tgids: blocked, only_priority: tg.only });
        }) }, 'Apply and restart')),
      restartNote());
    paintList();
  }

  // ---------- Radio IDs tab ----------
  function recentUnnamedIds() {
    const seen = new Set(), found = [];
    const add = text => {
      const m = /ID:\s*(\d{1,8})/.exec(text || '');
      const id = m ? Number(m[1]) : 0;
      if (id > 0 && id <= MAX_RID && !seen.has(id)) { seen.add(id); found.push(id); }
    };
    document.querySelectorAll('#callHistoryBody tr').forEach(tr => add(tr.lastElementChild && tr.lastElementChild.textContent));
    document.querySelectorAll('#subscribers tr').forEach(tr => add(tr.cells[4] && tr.cells[4].textContent));
    const current = document.getElementById('displaySourceId');
    if (current && /^\d+$/.test(current.textContent.trim())) add('ID: ' + current.textContent.trim());
    return found.slice(0, 30);
  }

  async function renderRids(body, args) {
    put(body, el('p', { class: 'brutal-hint' }, 'Loading…'));
    let data;
    try { data = await api('talkgroups'); } catch (e) { put(body, el('p', { class: 'brutal-hint bad' }, e.message)); return; }
    const labels = new Map(Object.entries(data.rid_labels || {}).map(([id, name]) => [Number(id), name]));
    const original = JSON.stringify([...labels].sort((a, b) => a[0] - b[0]));
    const idBox = el('input', { type: 'number', min: '1', max: String(MAX_RID), placeholder: 'Radio ID', 'aria-label': 'Radio ID' });
    const nameBox = el('input', { type: 'text', maxlength: '40', placeholder: 'Name, e.g. Engine 5', 'aria-label': 'Name' });
    const list = el('div', { class: 'rid-list' }), heardBox = el('div', { class: 'rid-heard' });
    const add = () => {
      const id = Number(idBox.value), name = nameBox.value.trim();
      if (!Number.isInteger(id) || id < 1 || id > MAX_RID) { setMessage('Enter a radio ID between 1 and ' + MAX_RID + '.', 'bad'); return; }
      if (!name) { setMessage('Type a name for that radio.', 'bad'); return; }
      labels.set(id, name); idBox.value = ''; nameBox.value = ''; setMessage('', ''); paint(); idBox.focus();
    };
    nameBox.addEventListener('keydown', event => { if (event.key === 'Enter') add(); });
    const paint = () => {
      put(list, labels.size ? [...labels].sort((a, b) => a[0] - b[0]).map(([id, name]) => el('div', { class: 'rid-row' },
        el('span', { class: 'tg-id' }, String(id)),
        el('input', { type: 'text', maxlength: '40', value: name, 'aria-label': 'Name for ' + id, oninput: event => labels.set(id, event.target.value) }),
        el('button', { class: 'brutal-btn danger', type: 'button', title: 'Remove this name', onclick: () => { labels.delete(id); paint(); } }, 'Remove')))
        : el('p', { class: 'brutal-hint' }, 'No radio names yet.'));
      const unnamed = recentUnnamedIds().filter(id => !labels.has(id));
      put(heardBox, unnamed.length ? [el('span', { class: 'brutal-hint' }, 'Heard recently, not yet named (click one):'),
        el('div', { class: 'rid-chips' }, unnamed.map(id => el('button', { class: 'brutal-pick rid-chip', type: 'button',
          onclick: () => { idBox.value = String(id); nameBox.focus(); } }, String(id))))] : null);
    };
    put(body,
      el('p', { class: 'brutal-hint' }, el('strong', {}, data.profile.name), ' · RadioReference does not publish names for individual radios, so these are yours. '
        + 'A named radio shows its name in the Source box and the call history instead of “ID: 123”. Tip: click an ID anywhere on the dashboard to name it.'),
      el('div', { class: 'rid-add' }, idBox, nameBox, el('button', { class: 'brutal-btn', type: 'button', onclick: add }, 'Add')),
      heardBox, list,
      el('div', { class: 'brutal-toolbar' },
        el('button', { class: 'brutal-btn', type: 'button', onclick: () => renderRids(body) }, 'Reset changes'),
        el('button', { class: 'brutal-btn primary', type: 'button', onclick: () => run(async () => {
          const out = {};
          labels.forEach((name, id) => { if (String(name).trim()) out[id] = String(name).trim(); });
          if (JSON.stringify([...Object.entries(out)].map(([id, n]) => [Number(id), n]).sort((a, b) => a[0] - b[0])) === original) {
            setMessage('Nothing changed, so there is nothing to apply.', 'ok'); return; }
          await applyAndRestart({ rid_labels: out });
        }) }, 'Apply and restart')),
      restartNote());
    paint();
    if (args && args.rid) { idBox.value = String(args.rid); nameBox.focus(); }
  }

  // ---------- Advanced tab ----------
  async function renderAdvanced(body) {
    put(body, el('p', { class: 'brutal-hint' }, 'Loading…'));
    let data;
    try { data = await api('talkgroups'); } catch (e) { put(body, el('p', { class: 'brutal-hint bad' }, e.message)); return; }
    const choice = (value, title, text) => el('label', { class: 'brutal-check adv-choice' },
      el('input', { type: 'radio', name: 'crypt', value: String(value), checked: data.crypt_behavior === value }),
      el('span', {}, el('strong', {}, title), el('small', {}, text)));
    const hold = el('input', { type: 'number', min: '0', max: '30', step: '0.5', placeholder: '2 (default)',
      value: data.hold_time == null ? '' : String(data.hold_time), 'aria-label': 'Hold time in seconds' });
    put(body,
      el('p', { class: 'brutal-hint' }, el('strong', {}, data.profile.name)),
      el('h3', { class: 'adv-title' }, 'Encrypted talkgroups'),
      choice(2, 'Skip them (recommended)', 'The receiver never follows an encrypted talkgroup, so you do not sit on silence.'),
      choice(1, 'Do not skip them', 'OP25’s own default: it stays on encrypted calls. Without keys their audio cannot be decoded.'),
      el('h3', { class: 'adv-title' }, 'Hold time'),
      el('p', { class: 'brutal-hint' }, 'How many seconds the receiver stays on a talkgroup after a call ends, so a back-and-forth conversation is not split. 0 to 30; empty uses OP25’s default of 2.'),
      el('div', { class: 'adv-hold' }, hold, el('span', { class: 'brutal-hint' }, 'seconds'),
        el('button', { class: 'brutal-btn', type: 'button', onclick: () => { hold.value = ''; } }, 'Use default')),
      el('div', { class: 'brutal-toolbar' }, el('span', {}),
        el('button', { class: 'brutal-btn primary', type: 'button', onclick: () => run(async () => {
          const crypt = Number(body.querySelector('input[name="crypt"]:checked').value);
          const raw = hold.value.trim();
          await applyAndRestart({ crypt_behavior: crypt, hold_time: raw === '' ? null : Number(raw) });
        }) }, 'Apply and restart')),
      restartNote());
  }

  S.registerTab({ id: 'talkgroups', label: 'Talkgroups', render: body => renderTalkgroups(body) });
  S.registerTab({ id: 'rids', label: 'Radio IDs', render: (body, args) => renderRids(body, args) });
  S.registerTab({ id: 'advanced', label: 'Advanced', render: body => renderAdvanced(body) });

  // ---------- click an ID anywhere on the dashboard to name it ----------
  function ridFrom(node) {
    const target = node.closest && node.closest('#callHistoryBody td, #subscribers td, #displaySource, #displaySourceId');
    if (!target) return null;
    const text = target.textContent.trim();
    const m = /^ID:\s*(\d{1,8})$/.exec(text);
    const id = m ? m[1] : (target.id === 'displaySourceId' && /^\d{1,8}$/.test(text) && text !== '0' ? text : null);
    return id && Number(id) <= MAX_RID ? { target, id } : null;
  }
  document.addEventListener('mouseover', event => {
    const hit = ridFrom(event.target);
    if (hit) { hit.target.style.cursor = 'pointer'; hit.target.title = 'Click to name this radio'; }
  });
  document.addEventListener('click', event => {
    const hit = ridFrom(event.target);
    if (hit) open('rids', { rid: hit.id });
  });

  // ---------- volume ----------
  const VOLUME_KEY = 'brutalVolume';
  let volume = 1, gainNode = null, gainContext = null;
  try { const saved = parseFloat(localStorage.getItem(VOLUME_KEY)); if (isFinite(saved)) volume = Math.min(1.5, Math.max(0, saved)); } catch (e) { /* storage may be blocked */ }

  // main.js (patched in brutal_ui.py) routes every audio chunk through this, so one gain node covers them all.
  window.brutalAudioOut = function (ctx) {
    if (!gainNode || gainContext !== ctx) {
      gainNode = ctx.createGain();
      gainNode.gain.value = volume;
      gainNode.connect(ctx.destination);
      gainContext = ctx;
    }
    return gainNode;
  };

  function mountVolume() {
    const strip = document.querySelector('.ops-context');
    if (!strip || document.getElementById('brutal-volume')) return;
    const readout = el('span', { class: 'ops-volume-value' }, Math.round(volume * 100) + '%');
    const slider = el('input', { id: 'brutal-volume', type: 'range', min: '0', max: '150', step: '5', value: String(Math.round(volume * 100)),
      'aria-label': 'Browser audio volume', oninput: event => {
        volume = Number(event.target.value) / 100;
        readout.textContent = event.target.value + '%';
        if (gainNode) gainNode.gain.value = volume;
        try { localStorage.setItem(VOLUME_KEY, String(volume)); } catch (e) { /* ignore */ }
      } });
    const box = el('label', { class: 'ops-volume', title: 'Volume for audio played in this browser.' },
      el('small', {}, 'VOL'), slider, readout);
    strip.insertBefore(box, document.getElementById('wsAudioButton') || strip.querySelector('.ops-context-end'));
  }
  mountVolume();

  // An ordinary page load may not have permission to start Web Audio. Keep the
  // default volume at 100%, but show the one-click recovery only while the
  // browser has actually suspended playback. Moving the slider is not required.
  function mountAudioPrompt() {
    const strip = document.querySelector('.ops-context');
    if (!strip || document.getElementById('brutal-audio-enable')) return;
    const button = el('button', { id: 'brutal-audio-enable', type: 'button', class: 'ops-audio-enable',
      title: 'Your browser paused audio until you interact with this page', onclick: () => {
        if (typeof audioCtx !== 'undefined' && audioCtx && audioCtx.state === 'suspended') {
          audioCtx.resume().catch(() => {});
        }
      } }, 'ENABLE AUDIO');
    strip.insertBefore(button, strip.querySelector('.ops-context-end'));
    let watchedContext = null;
    function update() {
      const ctx = typeof audioCtx === 'undefined' ? null : audioCtx;
      if (ctx && ctx !== watchedContext) {
        ctx.addEventListener('statechange', update);
        watchedContext = ctx;
      }
      button.hidden = (typeof muteAudioAtStartup !== 'undefined' && muteAudioAtStartup) ||
                      (ctx && ctx.state === 'running');
    }
    document.addEventListener('DOMContentLoaded', update);
    document.addEventListener('pointerdown', () => setTimeout(update, 0));
    document.addEventListener('keydown', () => setTimeout(update, 0));
    const mutePreference = document.getElementById('muteAudioAtStartup');
    if (mutePreference) mutePreference.addEventListener('change', update);
  }
  mountAudioPrompt();
})();
