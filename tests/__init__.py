"""Brutal OP25 regression tests against the checkout, not installed image copies."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / 'src', ROOT / 'build'):
    sys.path.insert(0, str(directory))
