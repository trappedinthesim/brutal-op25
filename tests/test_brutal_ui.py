from pathlib import Path
import shutil
import tempfile
import unittest

from brutal_ui import apply_branding


UPSTREAM_UI = Path('/opt/op25/op25/gr-op25_repeater/www')


@unittest.skipUnless(UPSTREAM_UI.is_dir(), 'Pinned boatbod UI exists only inside the image')
class ReceiverUiTests(unittest.TestCase):
    def test_every_tab_uses_brutal_runtime_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / 'www'
            shutil.copytree(UPSTREAM_UI, copy)
            apply_branding(copy)
            static = copy / 'www-static'
            html = (static / 'index.html').read_text(encoding='utf-8')
            script = (static / 'main.js').read_text(encoding='utf-8')
            css = (static / 'brutal-ui.css').read_text(encoding='utf-8')
            self.assertIn('Brutal OP25 // Live Receiver', html)
            self.assertNotIn('Legacy UI', html)
            self.assertNotIn('legacy-index.html', html)
            self.assertEqual(html.count('class="nav-item"'), 6)
            self.assertIn('id="btn-systems"', html)
            self.assertIn('<script src="brutal-systems.js" defer></script>', html)
            self.assertLess(html.index('src="main.js"'), html.index('src="brutal-systems.js"'))
            for ident in ('brutal-ctx-dot', 'brutal-ctx-session', 'brutal-ctx-system'):
                self.assertEqual(html.count(f'id="{ident}"'), 1)
            self.assertTrue((static / 'brutal-systems.js').read_text(encoding='utf-8').count('window.brutalSystems') >= 1)
            self.assertLess(html.index('class="top-nav-container"'), html.index('class="row"'))
            self.assertIn('class="ops-context"', html)
            self.assertIn('SIGNAL OPERATIONS', html)
            self.assertIn('PROJECT 25', html)
            self.assertIn('class="ops-panel-caption"', html)
            self.assertIn('ACTIVE MONITOR', html)
            self.assertIn('02 /', html)
            self.assertIn('SIGNAL ANALYSIS', html)
            from lxml import html as lxml_html
            page = lxml_html.fromstring(html)
            self.assertEqual(len(page.xpath('/html/body/div[@class="top-nav-container"]')), 1)
            self.assertEqual(len(page.xpath('/html/body/div[@class="ops-context"]')), 1)
            ids = page.xpath('//*[@id]/@id')
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(html.count('style="display:none" alt="plot"'), 6)
            self.assertIn('<table class="outer-table" id="plot-container">', html)
            self.assertIn('id="btn-plot" style="color: var(--brutal-green)"', html)
            self.assertIn('id="btn-settings"', html)
            self.assertIn('id="btn-about"', html)
            self.assertIn('value="#4c90f0"', html)
            self.assertIn('Receiver controls affect the live session', html)
            self.assertIn('function showHome()', script)
            self.assertIn('const escapeHtml = value', script)
            self.assertNotIn("send_command('dump_tracking'", script)
            import re
            from brutal_ui import BRUTAL_VERSION, UPSTREAM_COMMIT
            about = html[html.index('<div class="about-content">'):html.index('This program comes with')]
            self.assertIn('Brutal OP25', about)
            self.assertIn(BRUTAL_VERSION, about)
            self.assertIn('https://github.com/boatbod/op25', about)
            self.assertIn('Not affiliated with or endorsed', about)
            # Upstream's own copyright and licence text must survive, after our block.
            self.assertIn('Max H. Parke', about)
            self.assertLess(about.index('Brutal OP25'), about.index('Max H. Parke'))
            self.assertIn('GPLv3 License', html)
            dockerfile = (Path(__file__).resolve().parents[1] / 'build/Dockerfile').read_text()
            pinned = re.search(r'ARG OP25_COMMIT=([0-9a-f]{40})', dockerfile).group(1)
            self.assertTrue(pinned.startswith(UPSTREAM_COMMIT), 'About shows a different commit than the build uses')
            self.assertIn('<link rel="icon" type="image/png" href="brutal-logo.png">', html)
            # OP25 serves .png files only from www/images, so that is where the logo must live.
            self.assertEqual((copy / 'images' / 'brutal-logo.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            self.assertFalse((static / 'brutal-logo.png').exists())
            self.assertIn('url("brutal-logo.png")', css)
            self.assertIn('.nav-right { order: -1;', css)  # brand first, nav after it
            self.assertIn('justify-content: flex-start;', css)  # upstream's space-between must not split them
            self.assertIn('callHistoryToggle', script)
            self.assertIn('<script src="brutal-tuning.js" defer></script>', html)
            self.assertLess(html.index('src="brutal-systems.js"'), html.index('src="brutal-tuning.js"'))  # plugin loads second
            tuning_js = (static / 'brutal-tuning.js').read_text(encoding='utf-8')
            for name in ('registerTab', 'brutalAudioOut', "id: 'talkgroups'", "id: 'rids'", "id: 'advanced'"):
                self.assertIn(name, tuning_js)
            self.assertNotIn('innerHTML', tuning_js)  # names are inserted as text, never parsed
            self.assertIn('typeof brutalAudioOut === "function" ? brutalAudioOut(audioCtx) : audioCtx.destination', script)
            self.assertNotIn('source.connect(audioCtx.destination);', script)
            self.assertIn('callHistorySeen.forEach(function (seenAt, seenKey)', script)
            self.assertNotIn('// callHistorySeen.clear();', script)  # the dead commented-out prune is replaced
            self.assertIn('rows = rows.slice(0, 500);', script)
            self.assertLess(script.index('rows = rows.slice(0, 500);'),
                            script.index('// ---- optional sort (only if user clicked a header) ----'))
            self.assertIn('brutalPlotsVisible', script)
            self.assertIn('typeof brutalPlotsVisible !== "function"', script)  # safe if the helper is absent
            self.assertIn('window.brutalPlotsVisible', (static / 'brutal-systems.js').read_text(encoding='utf-8'))
            self.assertIn('localStorage.getItem("brutalAccent")', script)
            self.assertNotIn('localStorage.setItem("valueColor"', script)
            self.assertNotIn('localStorage.getItem("valueColor")', script)
            self.assertIn('--brutal-accent: #4c90f0', css)
            self.assertIn('.ops-context', css)
            self.assertIn('--brutal-bg: #0d1013', css)
            self.assertIn('#div_plot', css)
            self.assertIn('War-room treatment', css)
            self.assertEqual(css.count('{'), css.count('}'))
            self.assertIn('.config-section', css)
            self.assertIn('.settings-popup-content', css)
            self.assertIn('.about-popup-content', css)
            self.assertFalse((static / 'legacy-index.html').exists())


if __name__ == '__main__':
    unittest.main()
