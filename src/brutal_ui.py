"""Apply the Brutal OP25 receiver skin to a private copy of boatbod's UI."""
from pathlib import Path
import re


BRUTAL_VERSION = '0.3.0-dev'
UPSTREAM_COMMIT = '71abcd0'  # short form of OP25_COMMIT in Dockerfile; a test keeps them in step
ABOUT_BRUTAL = (
    '<div class="brutal-about">'
    '<p><strong>Brutal OP25</strong> <span class="brutal-version">' + BRUTAL_VERSION + '</span>'
    '</p>'
    '<p>Receive-only P25 monitoring with guided SDR setup, RadioReference imports, '
    'saved systems, talkgroup controls, browser audio, and live signal plots.</p>'
    '<p>Project: <a href="https://github.com/trappedinthesim/brutal-op25" '
    'target="_blank" rel="noopener noreferrer">github.com/trappedinthesim/brutal-op25</a>'
    ' &middot; Contact: <a href="mailto:j@brutal.net">j@brutal.net</a></p>'
    '<p>Built on <a href="https://github.com/boatbod/op25" target="_blank" '
    'rel="noopener noreferrer">boatbod/op25</a> (commit ' + UPSTREAM_COMMIT + ') and '
    'the work of the <a href="https://git.osmocom.org/op25" target="_blank" '
    'rel="noopener noreferrer">original OP25 contributors</a>. '
    'Not affiliated with or endorsed by the OP25 authors.</p>'
    '</div>')
UPSTREAM_DOWNLOAD = (
    '<strong>Download:</strong>\n'
    '                  <br>\n'
    '                  <code>git clone https://git.osmocom.org/op25</code> &nbsp; '
    '<a href="https://gitea.osmocom.org/op25/op25?h=master" target="_blank">[original]</a>\n'
    '                  <br>\n'
    '                  <code>git clone https://github.com/boatbod/op25</code> &nbsp; '
    '<a href="https://github.com/boatbod/op25" target="_blank">[boatbod fork]</a>')
BRUTAL_DOWNLOAD = (
    '<strong>Install Brutal OP25:</strong> '
    '<a href="https://github.com/trappedinthesim/brutal-op25#install-and-run-development-preview" '
    'target="_blank" rel="noopener noreferrer">Setup instructions and project downloads</a>\n'
    '                </p>\n'
    '                <p><strong>Upstream source (not Brutal OP25 installers):</strong> '
    '<a href="https://gitea.osmocom.org/op25/op25?h=master" target="_blank" '
    'rel="noopener noreferrer">original OP25</a> &middot; '
    '<a href="https://github.com/boatbod/op25" target="_blank" '
    'rel="noopener noreferrer">boatbod/op25</a>')
LEGACY_NAV ='<a href="legacy-index.html" class="nav-item" id="btn-legacy">Legacy UI</a>'
LEGACY_REDIRECT = re.compile(
    r'\s*// Determine UI version required \(rx\.py => force to legacy terminal for compatibility reasons\)\s*'
    r'if \(\(d\["terminal_interface"\] != undefined\) && \(d\["terminal_interface"\] == "legacy"\)\) \{\s*'
    r'window\.location\.replace\("legacy-index\.html"\);\s*\}', re.MULTILINE)


def _replace_once(source, old, new, label):
    if source.count(old) != 1:
        raise ValueError(f'Unsupported upstream receiver UI: {label} changed')
    return source.replace(old, new, 1)


def apply_branding(www_root, asset_root=None):
    """Patch only a writable runtime copy; upstream source and notices stay intact."""
    asset_root = Path(asset_root or Path(__file__).parent)
    static = Path(www_root) / 'www-static'
    index = static / 'index.html'
    js = static / 'main.js'
    html = index.read_text(encoding='utf-8')
    script = js.read_text(encoding='utf-8')
    html = _replace_once(html, '<title>OP25</title>',
                         '<title>Brutal OP25 // Live Receiver</title>', 'page title')
    html = _replace_once(html, '<link rel="stylesheet" type="text/css" href="main.css">',
                         '<link rel="stylesheet" type="text/css" href="main.css">\n'
                         '    <link rel="stylesheet" type="text/css" href="brutal-ui.css">',
                         'main stylesheet')
    html = _replace_once(html, LEGACY_NAV, '', 'legacy navigation')
    html = _replace_once(html, 'id="btn-new-settings" onclick="togglePopup(\'settingsPopupContainer\', true);"',
                         'id="btn-settings" onclick="togglePopup(\'settingsPopupContainer\', true); return false;"',
                         'settings navigation')
    html = _replace_once(html, 'id="btn-new-settings" onclick="togglePopup(\'aboutPopupContainer\', true);"',
                         'id="btn-about" onclick="togglePopup(\'aboutPopupContainer\', true); return false;"',
                         'about navigation')
    # About: lead with this project's own identity; upstream copyright, warranty and license text stay below, unchanged.
    html = _replace_once(html, '<div class="about-content">',
                         '<div class="about-content">\n                ' + ABOUT_BRUTAL, 'about content')
    html = _replace_once(html, UPSTREAM_DOWNLOAD, BRUTAL_DOWNLOAD, 'upstream download links')
    html = _replace_once(html, '<strong>Website:</strong>',
                         '<strong>Original OP25 website:</strong>', 'upstream website label')
    # Systems panel: a nav entry plus the script that builds the panel on demand.
    html = _replace_once(html, '<a href="#" class="nav-item" id="btn-settings"',
                         '<a href="#" class="nav-item" id="btn-systems" '
                         'onclick="window.brutalSystems && brutalSystems.open(); return false;">Systems</a>\n'
                         '              <a href="#" class="nav-item" id="btn-settings"', 'systems navigation')
    html = _replace_once(html, '<script src="main.js"></script>',
                         '<script src="main.js"></script>\n    <script src="brutal-systems.js" defer></script>\n    <script src="brutal-tuning.js" defer></script>',
                         'systems script')
    html = _replace_once(html, 'onclick="showHome();"', 'onclick="showHome(); return false;"',
                         'home navigation')
    html = _replace_once(html, "id=\"btn-plot\" onclick=\"toggleDivById('plot-container', 'btn-plot')\"",
                         "id=\"btn-plot\" style=\"color: var(--brutal-green)\" onclick=\"toggleDivById('plot-container', 'btn-plot'); return false;\"",
                         'plot navigation')
    html = _replace_once(html, '<table class="outer-table" id="plot-container" style="display: none;">',
                         '<table class="outer-table" id="plot-container">',
                         'default plot panel')
    html = _replace_once(html, "onclick=\"localStorage.setItem('getConfigBtn', 1); send_command('get_full_config');\"",
                         "onclick=\"localStorage.setItem('getConfigBtn', 1); send_command('get_full_config'); return false;\"",
                         'config navigation')
    html = _replace_once(html, 'id="s2_ch_dmp" onclick="f_dump_buffer(-1);"',
                         'id="s2_buffer_dmp" onclick="f_dump_buffer(-1);"', 'dump button id')
    html = _replace_once(html, 'All settings are automatically saved to the browser. <br>',
                         'Display preferences are saved in this browser. Receiver controls affect the live session. <br>',
                         'settings guidance')
    html = _replace_once(html, '<input type="number" id="callHeightControl" min="200" max="1000" value="500"',
                         '<input type="number" id="callHeightControl" min="200" max="1000" value="320"',
                         'history height default')
    html = _replace_once(html, '<input type="color" id="valueColorPicker" value="#00ffff">',
                         '<input type="color" id="valueColorPicker" value="#4c90f0">',
                         'accent default')
    html = _replace_once(html, '<span class="info-large" id="displayTalkgroup"></span>\n                    </span>',
                         '<span class="info-large" id="displayTalkgroup"></span>',
                         'talkgroup markup')
    html = _replace_once(html, '<label for="callHistoryToggle" style="color: #ccc;"> Track Affiliations Mode',
                         '<label for="subMode" style="color: #ccc;"> Track Affiliations Mode',
                         'affiliation label')
    if html.count('style="display:; none"') != 6:
        raise ValueError('Unsupported upstream receiver UI: plot image defaults changed')
    html = html.replace('style="display:; none"', 'style="display:none"')
    html = _replace_once(html, '<body style="background-color: #111; color: #E0E0E0; '
                         'font-family: Arial, Helvetica, sans-serif;" onload="javascript:do_onload();">',
                         '<body onload="javascript:do_onload();">', 'body attributes')
    html = _replace_once(html, '<meta http-equiv="Content-Type" content="text/html;charset=UTF-8">',
                         '<meta http-equiv="Content-Type" content="text/html;charset=UTF-8">\n'
                         '    <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                         '    <link rel="icon" type="image/png" href="brutal-logo.png">',
                         'character set')
    logos = re.compile(r'<svg class="logo(?:-lg)?"[^>]*>.*?</svg>', re.DOTALL)
    if len(logos.findall(html)) != 2:
        raise ValueError('Unsupported upstream receiver UI: brand marks changed')
    brand = ('<div class="brutal-brand" aria-label="Brutal OP25, built on boatbod OP25">'
             '<span class="brutal-brand-icon" aria-hidden="true">☠</span>'
             '<span><strong>BRUTAL <em>OP25</em></strong>'
             '<small>BUILT ON BOATBOD / OP25</small></span></div>')
    html = logos.sub(brand, html)
    # Make navigation a true page-wide command bar rather than a card confined
    # to the first receiver column. Keep the upstream controls and IDs intact.
    nav_start_token = '        <div class="top-nav-container">'
    nav_end_token = '        <div id="aboutPopupContainer">'
    if html.count(nav_start_token) != 1 or html.count(nav_end_token) != 1:
        raise ValueError('Unsupported upstream receiver UI: navigation layout changed')
    nav_start = html.index(nav_start_token)
    nav_end = html.index(nav_end_token, nav_start)
    navigation = html[nav_start:nav_end]
    html = html[:nav_start] + html[nav_end:]
    layout_marker = '    <!--  START OF 2-COLUMN LAYOUT -->'
    context_bar = ('    <div class="ops-context" aria-label="Receiver workspace">'
                   '<span class="ops-context-label"><span class="ops-context-dot" id="brutal-ctx-dot" '
                   'data-state="running" aria-hidden="true"></span>'
                   'SIGNAL OPERATIONS</span>'
                   '<span class="ops-context-item"><small>UPTIME</small><strong id="brutal-ctx-session">LOCAL</strong></span>'
                   '<span class="ops-context-item"><small>PROTOCOL</small><strong>PROJECT 25</strong></span>'
                   '<span class="ops-context-item"><small>SYSTEM</small><strong id="brutal-ctx-system">RECEIVER MONITOR</strong></span>'
                   '<span class="ops-context-end">BRUTAL OP25 <b>◆</b> BOATBOD ENGINE</span></div>\n')
    html = _replace_once(html, layout_marker, navigation + context_bar + layout_marker,
                         'page-wide receiver navigation')
    html = _replace_once(html, '<table class="outer-table" id="main-display">',
                         '<table class="outer-table" id="main-display">\n'
                         '          <caption class="ops-panel-caption"><span class="ops-panel-number">01</span>'
                         '<span>ACTIVE MONITOR</span><span class="ops-caption-end">RECEIVER TELEMETRY</span></caption>',
                         'receiver panel heading')
    html = _replace_once(html, '<span id="callHistoryTableTitle">Call History</span>',
                         '<span class="ops-heading-index">02 /</span> '
                         '<span id="callHistoryTableTitle">Call History</span>',
                         'traffic panel heading')
    html = _replace_once(html, '<th class="th-section">Plots</th>',
                         '<th class="th-section ops-plot-heading"><span class="ops-heading-index">03 /</span> '
                         'SIGNAL ANALYSIS <span class="ops-plot-heading-end">SPECTRUM · DECODE · TIMING</span></th>',
                         'signal analysis heading')
    if len(LEGACY_REDIRECT.findall(script)) != 1:
        raise ValueError('Unsupported upstream receiver UI: legacy redirect changed')
    script = LEGACY_REDIRECT.sub('', script)
    script = _replace_once(script, 'const defaultColor = "#00ffff";  // Your original default color',
                           'const defaultColor = "#4c90f0";  // Brutal OP25 default',
                           'reset accent')
    # Use a new storage key so an accent saved under upstream's key (or an earlier Brutal
    # default) cannot override the current default. Existing browsers start from the default.
    script = _replace_once(script, 'localStorage.getItem("valueColor") || "#00ffff"; // fallback if missing',
                           'localStorage.getItem("brutalAccent") || "#4c90f0"; // fallback if missing',
                           'accent fallback')
    script = _replace_once(script, 'localStorage.setItem("valueColor", defaultColor);',
                           'localStorage.setItem("brutalAccent", defaultColor);', 'accent reset storage')
    script = _replace_once(script,
                           'localStorage.setItem("valueColor", document.getElementById("valueColorPicker").value);',
                           'localStorage.setItem("brutalAccent", document.getElementById("valueColorPicker").value);',
                           'accent save storage')
    script = _replace_once(script, 'localStorage.getItem("callHeight") || "600"',
                           'localStorage.getItem("callHeight") || "320"', 'history height')
    script = _replace_once(script, 'document.getElementById("trackSubsToggle").checked = trackSubsToggle === "true";',
                           'document.getElementById("trackSubsToggle").checked = trackSubsToggle === null ? true : trackSubsToggle === "true";',
                           'affiliation default')
    script = _replace_once(script, 'document.getElementById("showBandPlan").checked = showBandPlan === "true";',
                           'document.getElementById("showBandPlan").checked = showBandPlan === null ? true : showBandPlan === "true";',
                           'band-plan default')
    # Upstream waits for a click before it even creates the AudioContext. A user who
    # only watches the dashboard sees traffic but hears nothing until touching a
    # control such as our volume slider. Try immediately; if the browser suspends
    # autoplay, retry resume on the first keyboard/pointer gesture.
    script = _replace_once(script,
                           "\tdocument.addEventListener('click', function initAudioCtx() {\n"
                           "\t\tif (!muteAudioAtStartup && !audioCtx) {\n"
                           "\t\t\taudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: WS_AUDIO_SAMPLE_RATE });\n"
                           "\t\t\tObject.keys(audioChannels).forEach(function(ch) { audio_play(ch); });\n"
                           "\t\t}\n"
                           "\t}, { once: true });",
                           "\tfunction startReceiverAudio() {\n"
                           "\t\tif (muteAudioAtStartup) return;\n"
                           "\t\tif (!audioCtx)\n"
                           "\t\t\taudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: WS_AUDIO_SAMPLE_RATE });\n"
                           "\t\tif (audioCtx.state === 'suspended')\n"
                           "\t\t\taudioCtx.resume().catch(function() { /* browser may require a gesture */ });\n"
                           "\t\tObject.keys(audioChannels).forEach(function(ch) { audio_play(ch); });\n"
                           "\t}\n"
                           "\tstartReceiverAudio();\n"
                           "\tdocument.addEventListener('pointerdown', startReceiverAudio);\n"
                           "\tdocument.addEventListener('keydown', startReceiverAudio);",
                           'automatic audio startup')
    script = _replace_once(script, 'localStorage.setItem("callHistorySource", document.getElementById("callHistorySource").value);',
                           'localStorage.setItem("callHistorySource", document.getElementById("callHistorySource").value);\n'
                           '  localStorage.setItem("callHistoryToggle", document.getElementById("callHistoryToggle").checked);',
                           'history setting save')
    script = _replace_once(script, 'const callHistorySource = localStorage.getItem("callHistorySource") || "frequency";',
                           'const callHistorySource = localStorage.getItem("callHistorySource") || "frequency";\n'
                           '  const callHistoryToggle = localStorage.getItem("callHistoryToggle");',
                           'history setting load')
    script = _replace_once(script, 'document.getElementById("callHistorySource").value = callHistorySource;',
                           'document.getElementById("callHistorySource").value = callHistorySource;\n'
                           '  const historyEnabled = callHistoryToggle === null ? true : callHistoryToggle === "true";\n'
                           '  document.getElementById("callHistoryToggle").checked = historyEnabled;\n'
                           '  document.getElementById("callHistoryContainer").style.display = historyEnabled ? "" : "none";',
                           'history setting restore')
    old_home = '''function showHome() {
  const settings = document.getElementById("settings-container");
  const about = document.getElementById("about-container");

  if (settings) settings.style.display = "none";
  if (about) about.style.display = "none";

  const btnSettings = document.getElementById("btn-settings");
  const btnAbout = document.getElementById("btn-about");

  if (btnSettings) btnSettings.style.color = "";
  if (btnAbout) btnAbout.style.color = "";
}'''
    new_home = '''function showHome() {
  for (const id of ["settingsPopupContainer", "aboutPopupContainer", "popupContainer"]) {
    togglePopup(id, false);
  }
  const plot = document.getElementById("plot-container");
  if (plot) plot.style.display = "";
  const plotButton = document.getElementById("btn-plot");
  if (plotButton) plotButton.style.color = "var(--brutal-green)";
}'''
    script = _replace_once(script, old_home, new_home, 'home navigation behavior')
    script = _replace_once(script, 'btn.style.color = "red";',
                           'btn.style.color = "var(--brutal-green)";', 'plot navigation accent')
    script = _replace_once(script,
                           '    else {\n        var img = document.getElementById("img0");\n'
                           '        img.style["display"] = "none";\n    }\n    \n    updatePlotButtonStyles();',
                           '    else {\n        for (var i=0; i<6; i++) {\n'
                           '            document.getElementById("img" + i).style["display"] = "none";\n'
                           '        }\n    }\n    \n    updatePlotButtonStyles();',
                           'empty plot update')
    script = _replace_once(script,
                           "    send_command('dump_tracking', 0, Number(channel_list[channel_index]));\n",
                           '', 'unsupported tracking dump command')
    script = _replace_once(script, "if (img['src'] != plotfiles[i]) {",
                           "if (img['src'] != plotfiles[i] && "
                           "(typeof brutalPlotsVisible !== \"function\" || brutalPlotsVisible())) {",
                           'plot refresh pausing')
    # Upstream's duplicate-suppression map only needs the last few seconds, but its cleanup is commented
    # out, so it grew for as long as the page stayed open. Drop expired entries once it gets large.
    script = _replace_once(script,
                           '    if (callHistorySeen.size > 5000) {\n'
                           '      // cheap prune: clear all (or implement better pruning)\n'
                           '      // callHistorySeen.clear();\n'
                           '    }',
                           '    if (callHistorySeen.size > 500) {\n'
                           '      var staleBefore = epochMs - ((Number(MAX_HISTORY_SECONDS) || 5) * 1000);\n'
                           '      callHistorySeen.forEach(function (seenAt, seenKey) {\n'
                           '        if (seenAt < staleBefore) callHistorySeen.delete(seenKey);\n'
                           '      });\n'
                           '    }', 'call history duplicate pruning')
    # The subscriber table is rebuilt from scratch every second. OP25 expires old registrations itself,
    # but never render more than the 500 most recent so a very busy system cannot make the page crawl.
    script = _replace_once(script,
                           '  // ---- optional sort (only if user clicked a header) ----',
                           '  if (rows.length > 500) {\n'
                           '    rows.sort(function (a, b) { return b.time - a.time; });\n'
                           '    rows = rows.slice(0, 500);\n'
                           '  }\n'
                           '  // ---- optional sort (only if user clicked a header) ----', 'subscriber render cap')
    # Route every audio chunk through one gain node so the dashboard can offer a volume control.
    script = _replace_once(script, '        source.connect(audioCtx.destination);',
                           '        source.connect(typeof brutalAudioOut === "function" ? brutalAudioOut(audioCtx) : audioCtx.destination);',
                           'audio volume hook')
    # Drop live audio while autoplay is suspended; otherwise Web Audio schedules
    # an ever-growing backlog that would all play after the user's first gesture.
    script = _replace_once(script, '    if (!audioCtx || state.muted || state.queue.length === 0) return;',
                           "    if (!audioCtx || state.muted || state.queue.length === 0) return;\n"
                           "    if (audioCtx.state !== 'running') { state.queue = []; return; }",
                           'suspended audio backlog')
    script = _replace_once(script, 'function full_config(config) {',
                           '''function full_config(config) {
    const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[char]);''', 'config HTML escaping')
    script = _replace_once(script, 'const displayKey = key; // no auto-capitalization for inner keys',
                           'const displayKey = escapeHtml(key); // no auto-capitalization for inner keys',
                           'config key escaping')
    script = _replace_once(script, '<td class="config-value">${value}</td>',
                           '<td class="config-value">${escapeHtml(value)}</td>',
                           'config value escaping')
    script = _replace_once(script, '<p><b>${sectionName}:</b> ${sectionContent}</p>',
                           '<p><b>${escapeHtml(sectionName)}:</b> ${escapeHtml(sectionContent)}</p>',
                           'config section escaping')
    if script.count('toggleIcon.textContent = "➕";') != 2 or script.count('toggleIcon.textContent = "➖";') != 1:
        raise ValueError('Unsupported upstream receiver UI: configuration toggles changed')
    script = script.replace('toggleIcon.textContent = "➕";', 'toggleIcon.textContent = "[+]";')
    script = script.replace('toggleIcon.textContent = "➖";', 'toggleIcon.textContent = "[-]";')
    theme = (asset_root / 'brutal-ui.css').read_bytes()
    systems_script = (asset_root / 'brutal-systems.js').read_bytes()
    tuning_script = (asset_root / 'brutal-tuning.js').read_bytes()
    # Validate before mutating the copied runtime tree.
    if not theme or b'--brutal-accent: #4c90f0' not in theme:
        raise ValueError('Brutal OP25 theme asset is missing or invalid')
    if b'window.brutalSystems' not in systems_script:
        raise ValueError('Brutal OP25 systems panel asset is missing or invalid')
    if b'brutalAudioOut' not in tuning_script or b'registerTab' not in tuning_script:
        raise ValueError('Brutal OP25 listening-controls asset is missing or invalid')
    logo = (asset_root / 'brutal-logo.png').read_bytes()
    if logo[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Brutal OP25 logo asset is missing or not a PNG')
    index.write_text(html, encoding='utf-8')
    js.write_text(script, encoding='utf-8')
    (static / 'brutal-ui.css').write_bytes(theme)
    (static / 'brutal-systems.js').write_bytes(systems_script)
    (static / 'brutal-tuning.js').write_bytes(tuning_script)
    # OP25's file server serves every .png from www/images, not www-static; the URL is still /brutal-logo.png.
    images = Path(www_root) / 'images'
    images.mkdir(exist_ok=True)
    (images / 'brutal-logo.png').write_bytes(logo)
    for filename in ('legacy-index.html', 'legacy-main.js', 'legacy-main.css'):
        (static / filename).unlink(missing_ok=True)
