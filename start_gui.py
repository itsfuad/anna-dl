#!/usr/bin/env python3
"""Launch from the source folder using its virtual environment when available."""
import os
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    app_dir = Path(__file__).resolve().parent
    python = app_dir / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    result = subprocess.run(
        [str(python) if python.is_file() else sys.executable, '-m', 'anna_dl', 'gui', *sys.argv[1:]],
        cwd=app_dir,
    )
    sys.exit(result.returncode)
