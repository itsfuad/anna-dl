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

    def test_launcher_asks_before_installing_missing_libraries(self):
        import shutil
        import venv
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = Path(__file__).resolve().parents[1] / 'start_gui.py'
            shutil.copyfile(source, root / 'start_gui.py')
            venv.EnvBuilder(with_pip=False).create(root / '.venv')
            for answer in ('n\n', ''):
                with self.subTest(answer=answer):
                    result = subprocess.run([sys.executable, str(root/'start_gui.py')], input=answer, capture_output=True, text=True, cwd=root)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn('Install', result.stdout)
                    self.assertNotIn('Traceback', result.stderr)
            self.assertFalse((root / '.venv' / ('Scripts/pip.exe' if sys.platform == 'win32' else 'bin/pip')).exists())
