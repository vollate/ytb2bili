#!/usr/bin/env python3
"""Convenience script to run yt2bili directly from the repo root without
installing.  Usage::

    python run.py run
    python run.py add-channel UC... "Name"
    python run.py --help
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from yt2bili.cli.main import app  # noqa: E402

if __name__ == "__main__":
    app()
