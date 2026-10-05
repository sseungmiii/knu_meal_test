"""Compatibility entry point: both sites use the root crawler and menu.json."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'get_menu.py'), run_name='__main__')
