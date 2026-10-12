#!/usr/bin/env python3
"""Launch without activating an environment; ask before installing missing libraries."""
import os
import subprocess
import sys
from pathlib import Path


def main():
    app_dir = Path(__file__).resolve().parent
    environment = app_dir / '.venv'
    env_python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    current_python = Path(sys.executable)
    if current_python.name.lower() == 'pythonw.exe':
        current_python = current_python.with_name('python.exe')
    python = env_python if env_python.is_file() else current_python
    try:
        probe = subprocess.run(
            [str(python), '-c', 'import requests, bs4, urllib3'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if probe.returncode:
            print('Required libraries are missing. They can be installed into .venv beside the app.')
            try:
                consent = input('Install missing libraries now? [y/N] ').strip().lower()
            except (EOFError, OSError, RuntimeError):
                consent = ''
            if consent not in ('y', 'yes'):
                return 1
            if not env_python.is_file() and subprocess.run([str(current_python), '-m', 'venv', str(environment)], check=False).returncode:
                print('Could not create the environment. Install Python venv support and try again.', file=sys.stderr)
                return 1
            python = env_python
            pip = subprocess.run([str(python), '-m', 'pip', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if pip.returncode and subprocess.run([str(python), '-m', 'ensurepip', '--upgrade'], check=False).returncode:
                print('Could not prepare pip in the local environment.', file=sys.stderr)
                return 1
            if subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(app_dir / 'requirements.txt')], check=False).returncode:
                print('Library installation failed. Check your connection and try again.', file=sys.stderr)
                return 1
        return subprocess.run([str(python), '-m', 'anna_dl', 'gui', *sys.argv[1:]], cwd=app_dir, check=False).returncode
    except OSError as error:
        print(f'Could not launch Python: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
