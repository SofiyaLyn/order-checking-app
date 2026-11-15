"""Run the engine and local HTML server regression suites."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from launch import configure
configure()
import unittest
root = Path(__file__).resolve().parent
suite = unittest.defaultTestLoader.discover(str(root / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

