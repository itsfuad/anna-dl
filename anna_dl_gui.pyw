"""Compatibility launcher for existing Windows shortcuts."""
import runpy
from pathlib import Path

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('start_gui.py')), run_name='__main__')
