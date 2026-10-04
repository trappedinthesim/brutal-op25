"""Read-only checks for the built-in-PowerShell WSL launcher."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsBootstrapTests(unittest.TestCase):
    def test_bootstrap_does_not_install_desktop_or_change_policy(self):
        text = (ROOT / 'Launch-Brutal-OP25.cmd').read_text()
        self.assertIn('powershell.exe -NoProfile -ExecutionPolicy Bypass', text)
        self.assertNotIn('Set-ExecutionPolicy', text)
        self.assertNotIn('Docker.DockerDesktop', text)
        self.assertNotIn('winget', text.lower())
        self.assertIn('install-brutal-wsl.ps1', text)
        source = (ROOT / 'install/install-brutal-wsl.ps1').read_text()
        self.assertIn('Assert-BrutalHostPortsFree', source)
        self.assertIn('Windows port $taskPort is already in use', source)

    @unittest.skipUnless(os.name == 'nt', 'Windows CMD integration')
    def test_check_is_read_only(self):
        result = subprocess.run(['cmd.exe', '/d', '/c', 'Launch-Brutal-OP25.cmd', '--check'],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('NoChangesMade', result.stdout)
        self.assertIn('DockerDesktopRequired', result.stdout)


if __name__ == '__main__':
    unittest.main()
