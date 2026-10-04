"""Minimal, fail-closed fixes to a private runtime copy of boatbod's receiver."""
from pathlib import Path


def _replace_once(source, old, new, label):
    if source.count(old) != 1:
        raise ValueError(f'Unsupported upstream receiver runtime: {label} changed')
    return source.replace(old, new, 1)


def patch_runtime_apps(apps):
    """Preserve enabled plots across UI watchdog timeouts, not across restarts."""
    target = Path(apps) / 'multi_rx.py'
    source = target.read_text(encoding='utf-8')
    source = _replace_once(
        source,
        "        if plot is None or plot not in self.sinks or self.tb.terminal_type is None:\n"
        "            return\n"
        "        if self.tb.terminal_type == \"http\":",
        "        if plot is None or plot not in self.sinks:\n"
        "            return\n"
        "        if self.tb.terminal_type is None:\n"
        "            # Channel plots are constructed before configure_terminal().\n"
        "            # Use the pending HTTP config now so gnuplot writes PNGs, not X11.\n"
        "            term = from_dict(self.tb.config, 'terminal', {})\n"
        "            if str(from_dict(term, 'terminal_type', '')).startswith('http:'):\n"
        "                gp = self.sinks[plot][0].gnuplot\n"
        "                gp.set_interval(float(from_dict(term, 'http_plot_interval', 1.0)))\n"
        "                gp.set_output_dir(str(from_dict(term, 'http_plot_directory', '../www/images')))\n"
        "            return\n"
        "        if self.tb.terminal_type == \"http\":",
        'early HTTP plot destination')
    source = _replace_once(
        source,
        "self.sinks['fll'] = (sink, self.toggle_mixer_plot)",
        "self.sinks['fll'] = (sink, self.toggle_fll_plot)",
        'FLL plot cleanup callback')
    source = _replace_once(
        source,
        "        elif s == 'update':                             # UI initiated update request\n"
        "            self.ui_last_update = time.time()",
        "        elif s == 'update':                             # UI initiated update request\n"
        "            self.ui_last_update = time.time()\n"
        "            pending_plots = getattr(self, '_brutal_resume_plots', None)\n"
        "            if pending_plots is not None:\n"
        "                self._brutal_resume_plots = None\n"
        "                plot_types = {'fft': 1, 'constellation': 2, 'symbol': 3,\n"
        "                              'eye': 4, 'mixer': 5, 'fll': 6}\n"
        "                for chan in self.channels:\n"
        "                    for plot in pending_plots.get(chan.msgq_id, ()):\n"
        "                        if plot in plot_types and plot not in chan.sinks:\n"
        "                            chan.toggle_plot(plot_types[plot])",
        'UI reconnection plot restore')
    source = _replace_once(
        source,
        "                for chan in self.channels:\n"
        "                    chan.close_plots()\n"
        "            # Experimental automatic fine tuning",
        "                self._brutal_resume_plots = {chan.msgq_id: tuple(chan.sinks)\n"
        "                                             for chan in self.channels}\n"
        "                for chan in self.channels:\n"
        "                    chan.close_plots()\n"
        "            # Experimental automatic fine tuning",
        'UI timeout plot snapshot')
    compile(source, str(target), 'exec')
    target.write_text(source, encoding='utf-8')
