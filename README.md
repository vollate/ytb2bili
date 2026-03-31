> **中文文档 / Chinese Documentation**: [doc/README_zh.md](doc/README_zh.md)

# yt2bili — YouTube → Bilibili Auto-Repost Tool

Automatically monitor YouTube channels, download new videos, process subtitles, and repost them to Bilibili — all in one pipeline.

## Features

- **Channel Monitoring** — RSS-based polling detects new uploads within minutes
- **Video Download** — yt-dlp powered, configurable quality (best/1080p/720p/480p)
- **Smart Subtitles** — 3-tier fallback: YouTube captions → local Whisper generation → skip
- **Bilibili Upload** — Automated repost (copyright=2) with customizable title/description templates
- **Web Dashboard** — NiceGUI-based UI with real-time progress, channel management, and settings
- **CLI** — Full-featured command-line interface via Typer + Rich
- **Task Queue** — Async priority queue with concurrency control and exponential-backoff retry
- **Per-Channel Config** — Override download quality, subtitle languages, tags, and templates per channel

## Quick Start

### Installation

```bash
# From source
pip install -e .

# With Whisper subtitle generation support
pip install -e ".[whisper]"

# With development tools
pip install -e ".[dev]"
```

### Minimal Setup

1. **Create configuration** (optional — sensible defaults are built-in):

```bash
# Linux / macOS
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/yt2bili"
cp config/default.yaml "${XDG_CONFIG_HOME:-$HOME/.config}/yt2bili/config.yaml"

# Windows (PowerShell)
Copy-Item config/default.yaml "$env:APPDATA/yt2bili/config.yaml"
```

2. **Add a channel and start**:

```bash
# Via CLI
yt2bili add-channel UC_x5XG1OV2P6uZZ5FSM9Ttw "Google Developers"
yt2bili run

# Or start the Web UI directly
yt2bili run  # opens http://127.0.0.1:8080
```

3. **Add Bilibili credentials** — via the Web UI (Settings → Auth) or configure in the database.

## Architecture

```
Scheduler (every N minutes)
  → ChannelMonitor.check_all_channels()  (RSS feed polling)
  → For each new video: insert Video → create Task(PENDING) → enqueue

TaskQueue (async worker pool with concurrency control)
  → Pipeline.process_task(task_id):
    1. DOWNLOADING  (0–40%)   Download video + subtitles via yt-dlp
    2. SUBTITLING   (40–60%)  Process/generate subtitles
    3. UPLOADING    (60–95%)  Upload to Bilibili as repost
    4. COMPLETED    (95–100%) Cleanup + notify
    On failure: retry with exponential backoff, or mark FAILED
```

## Project Structure

```
src/yt2bili/
├── core/               # Domain layer: models, schemas, config, enums, exceptions
├── interfaces/         # Protocol classes: UploaderBackend, SubtitleGenerator, Notifier
├── services/           # Business logic: monitor, downloader, subtitle, uploader, pipeline, scheduler, task_queue
├── adapters/           # Concrete implementations: bilibili_uploader, whisper_subtitle, webhook_notifier
├── db/                 # Database: async engine, session factory, CRUD repository
├── web/                # NiceGUI WebUI: app factory, pages (dashboard/channels/tasks/settings/auth), components
└── cli/                # Typer CLI: run, add-channel, list-channels, check-now, upload, status
```

## Configuration

Configuration is loaded from the platform-specific config directory with Pydantic validation. All fields have sensible defaults.

| Platform | Config path | Data path (DB, downloads) |
|----------|------------|--------------------------|
| **Linux** | `$XDG_CONFIG_HOME/yt2bili/config.yaml` (default `~/.config/yt2bili/`) | `$XDG_DATA_HOME/yt2bili/` (default `~/.local/share/yt2bili/`) |
| **macOS** | `$XDG_CONFIG_HOME/yt2bili/config.yaml` (default `~/.config/yt2bili/`) | `$XDG_DATA_HOME/yt2bili/` (default `~/.local/share/yt2bili/`) |
| **Windows** | `%APPDATA%\yt2bili\config.yaml` | `%LOCALAPPDATA%\yt2bili\` |

| Section | Key Settings |
|---------|-------------|
| **schedule** | `poll_interval_minutes`, `max_concurrent_downloads`, `max_concurrent_uploads`, `max_retries` |
| **download** | `quality` (best/1080/720/480), `subtitle_langs` priority list, `download_dir` |
| **subtitle** | `subtitle_generator` (whisper/cloud/none), `whisper_model`, `subtitle_fallback_generate` |
| **upload** | `bilibili_tid` (partition), `tags`, `title_template`, `desc_template`, `copyright` (2=repost) |
| **webui** | `host`, `port`, `secret` |
| **notify** | `webhook_url`, `notify_on` event list |

### Template Variables

Title and description templates support the following placeholders:

| Variable | Description |
|----------|-------------|
| `{original_title}` | Original YouTube video title |
| `{original_description}` | Original YouTube video description |
| `{youtube_url}` | Full YouTube video URL |

### Per-Channel Overrides

Each channel can override global defaults (quality, subtitle languages, tags, templates, tid) via the Web UI or by setting `config_overrides` JSON in the database.

## CLI Reference

```bash
yt2bili run                                    # Start scheduler + Web UI
yt2bili add-channel <youtube_id> <name>        # Add a channel to monitor
yt2bili list-channels                          # List all monitored channels
yt2bili check-now                              # Trigger immediate check of all channels
yt2bili upload <video_id>                      # Manually create an upload task
yt2bili status                                 # Show current task queue status
```

## Web UI

The NiceGUI dashboard is accessible at `http://127.0.0.1:8080` (configurable) with five pages:

| Page | Description |
|------|-------------|
| **Dashboard** | Stats cards, recent activity, quick actions |
| **Channels** | Add/remove/toggle channels, per-channel config |
| **Tasks** | Filterable task list with progress bars, retry/cancel |
| **Settings** | Edit all configuration sections |
| **Auth** | Manage Bilibili credentials |

## Extensibility

yt2bili uses Protocol-based interfaces for key components:

- **`UploaderBackend`** — Implement to add new upload targets beyond Bilibili
- **`SubtitleGenerator`** — Implement to plug in any ASR service (local or cloud)
- **`Notifier`** — Implement for custom notification channels (email, Telegram, etc.)

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Download | yt-dlp (Python API) |
| Monitoring | YouTube RSS + feedparser + httpx |
| Subtitles | pysubs2, srt, faster-whisper (optional) |
| Upload | bilibili-api-python |
| Database | SQLite + SQLAlchemy async ORM + aiosqlite |
| Config | YAML + Pydantic v2 |
| Scheduling | APScheduler |
| Web UI | NiceGUI |
| CLI | Typer + Rich |
| Logging | structlog |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=yt2bili

# Type checking
mypy src/yt2bili

# Lint
ruff check src/
```

## Requirements

- Python 3.11+
- All function parameters are strictly type-annotated (mypy strict mode)

## License

MIT
