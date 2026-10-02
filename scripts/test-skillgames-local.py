"""Network harness safety and real-HTTP smoke, separate from fixture UI tests."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'scripts' / 'run-skillgames-local.py'

class LocalHarnessTests(unittest.TestCase):
    def test_explicit_local_only_harness_is_required(self):
        self.assertTrue(RUNNER.exists(), 'Missing real-HTTP local skillgame runner; fixture preview is not integration')
        rejected = subprocess.run([sys.executable, str(RUNNER)],capture_output=True,text=True)
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn('--allow-local-demo',rejected.stderr)

    def test_no_production_database_or_public_bind_arguments(self):
        self.assertTrue(RUNNER.exists(), 'Missing local integration harness')
        help_result = subprocess.run([sys.executable,str(RUNNER),'--help'],capture_output=True,text=True)
        self.assertEqual(help_result.returncode,0)
        self.assertNotIn('--host',help_result.stdout)
        self.assertNotIn('--db',help_result.stdout)
        self.assertIn('--port',help_result.stdout)

if __name__ == '__main__': unittest.main()
