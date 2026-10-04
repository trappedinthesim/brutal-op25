import ast
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from brutal_runtime import patch_runtime_apps


UPSTREAM = Path('/opt/op25/op25/gr-op25_repeater/apps/multi_rx.py')


@unittest.skipUnless(UPSTREAM.is_file(), 'Pinned boatbod runtime exists only inside the image')
class ReceiverRuntimeTests(unittest.TestCase):
    def test_plot_cleanup_and_reconnection_patch_compiles(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'multi_rx.py'
            shutil.copy2(UPSTREAM, target)
            patch_runtime_apps(directory)
            text = target.read_text(encoding='utf-8')
            self.assertIn("if str(from_dict(term, 'terminal_type', '')).startswith('http:'):", text)
            self.assertIn("gp.set_output_dir(str(from_dict(term, 'http_plot_directory', '../www/images')))", text)
            self.assertIn("self.sinks['fll'] = (sink, self.toggle_fll_plot)", text)
            self.assertIn("self._brutal_resume_plots = {chan.msgq_id: tuple(chan.sinks)", text)
            self.assertIn("if plot in plot_types and plot not in chan.sinks:", text)
            self.assertIn("chan.toggle_plot(plot_types[plot])", text)
            compile(text, str(target), 'exec')

            # Exercise the patched method without starting an SDR or opening
            # GNU Radio: the terminal is still None at native plot startup.
            tree = ast.parse(text)
            method = next(node for cls in tree.body if isinstance(cls, ast.ClassDef)
                          for node in cls.body if isinstance(node, ast.FunctionDef)
                          and node.name == 'set_plot_destination')
            namespace = {'from_dict': lambda data, key, default: data.get(key, default)}
            exec(compile(ast.Module(body=[method], type_ignores=[]), str(target), 'exec'), namespace)
            calls = []
            gp = SimpleNamespace(set_interval=lambda value: calls.append(('interval', value)),
                                 set_output_dir=lambda value: calls.append(('directory', value)))
            channel = SimpleNamespace(sinks={'fft': (SimpleNamespace(gnuplot=gp), None)},
                                      tb=SimpleNamespace(terminal_type=None, config={'terminal': {
                                          'terminal_type': 'http:0.0.0.0:8080',
                                          'http_plot_interval': 1.5,
                                          'http_plot_directory': '/data/runtime/www/images'}}))
            namespace['set_plot_destination'](channel, 'fft')
            self.assertEqual(calls, [('interval', 1.5),
                                     ('directory', '/data/runtime/www/images')])


if __name__ == '__main__':
    unittest.main()
