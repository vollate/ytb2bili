"""Entry point for ``python -m yt2bili``.

Also ensures ``src/`` is on ``sys.path`` so the project can be run directly
from the repository without ``pip install -e .``::

    python -m yt2bili run
    # or from the repo root:
    python src/yt2bili run
"""

import sys
from pathlib import Path

# When running as ``python -m yt2bili`` from the repo root, the package lives
# under ``src/``.  Add it to sys.path so imports resolve without installation.
_src = Path(__file__).resolve().parent.parent  # src/
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from yt2bili.cli.main import app  # noqa: E402

if __name__ == "__main__":
    app()
