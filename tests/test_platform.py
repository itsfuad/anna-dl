import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anna_dl.cli import main


class PlatformTests(unittest.TestCase):
    def test_gui_command_explains_missing_tkinter_without_traceback(self):
        error_output = io.StringIO()
        with patch.object(sys, 'argv', ['anna-dl', 'gui']), patch.dict(sys.modules, {'tkinter': None}), contextlib.redirect_stderr(error_output):
            try:
                main()
            except SystemExit as error:
                result = error.code
            else:
                result = 0
        self.assertEqual(result, 1)
        self.assertIn('Tkinter', error_output.getvalue())
        self.assertIn('python3-tkinter', error_output.getvalue())
        self.assertNotIn('Traceback', error_output.getvalue())

    def test_portable_launcher_works_from_another_directory(self):
        script = Path(__file__).resolve().parents[1] / 'start_gui.py'
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(script), '--help'], cwd=folder, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('anna-dl', result.stdout)
