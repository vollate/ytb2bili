"""Platform-aware application directories following XDG on Unix and standard
conventions on Windows.

- **Linux / macOS (XDG)**:
  - Config : ``$XDG_CONFIG_HOME/yt2bili``  (default ``~/.config/yt2bili``)
  - Data   : ``$XDG_DATA_HOME/yt2bili``    (default ``~/.local/share/yt2bili``)
  - Cache  : ``$XDG_CACHE_HOME/yt2bili``   (default ``~/.cache/yt2bili``)

- **Windows**:
  - Config : ``%APPDATA%/yt2bili``
  - Data   : ``%LOCALAPPDATA%/yt2bili``
  - Cache  : ``%LOCALAPPDATA%/yt2bili/cache``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_NAME = "yt2bili"


def _is_windows() -> bool:
    return sys.platform == "win32"


def config_dir() -> Path:
    """Return the directory for configuration files."""
    if _is_windows():
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / _APP_NAME


def data_dir() -> Path:
    """Return the directory for persistent application data (DB, downloads)."""
    if _is_windows():
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / _APP_NAME


def cache_dir() -> Path:
    """Return the directory for cache / temporary files."""
    if _is_windows():
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / _APP_NAME / "cache"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        return base / _APP_NAME


def default_config_path() -> Path:
    """Return the default path for ``config.yaml``."""
    return config_dir() / "config.yaml"


def default_db_url() -> str:
    """Return the default SQLite database URL."""
    return f"sqlite+aiosqlite:///{data_dir() / 'yt2bili.db'}"


def default_download_dir() -> Path:
    """Return the default video download directory."""
    return data_dir() / "downloads"
