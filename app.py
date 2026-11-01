"""Compatibility entry point; the current UI lives in photostudio_app.py."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("photostudio_app.py")), run_name="__main__")
