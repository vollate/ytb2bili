> **English Documentation / 英文文档**: [../README.md](../README.md)

# yt2bili — YouTube 频道订阅转载 Bilibili 自动化工具

自动监控 YouTube 频道新视频、下载、处理字幕、转载到 Bilibili —— 一条流水线搞定。

## 功能特性

- **频道监控** — 基于 RSS 轮询，几分钟内检测到新上传
- **视频下载** — yt-dlp 驱动，可配置画质（best/1080p/720p/480p）
- **智能字幕** — 三级兜底：YouTube 字幕 → 本地 Whisper 生成 → 跳过
- **B站上传** — 自动转载投稿（copyright=2），支持自定义标题/简介模板
- **Web 仪表盘** — 基于 NiceGUI 的管理界面，实时进度、频道管理、设置编辑
- **命令行工具** — Typer + Rich 打造的全功能 CLI
- **任务队列** — 异步优先级队列，并发控制 + 指数退避重试
- **频道级配置** — 每个频道可独立覆盖下载画质、字幕语言、标签、模板等

## 快速开始

### 安装

```bash
# 从源码安装
pip install -e .

# 附带 Whisper 字幕生成支持
pip install -e ".[whisper]"

# 附带开发工具
pip install -e ".[dev]"
```

### 最小化配置

1. **创建配置文件**（可选 —— 内置合理默认值）：

```bash
# Linux / macOS
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/yt2bili"
cp config/default.yaml "${XDG_CONFIG_HOME:-$HOME/.config}/yt2bili/config.yaml"

# Windows (PowerShell)
Copy-Item config/default.yaml "$env:APPDATA/yt2bili/config.yaml"
```

2. **添加频道并启动**：

```bash
# 通过 CLI
yt2bili add-channel UC_x5XG1OV2P6uZZ5FSM9Ttw "Google Developers"
yt2bili run

# 或直接启动 Web UI
yt2bili run  # 打开 http://127.0.0.1:8080
```

3. **添加 B站凭据** — 通过 Web UI（设置 → 凭据管理）或直接写入数据库。

## 架构设计

```
调度器（每 N 分钟）
  → ChannelMonitor.check_all_channels()  （RSS 订阅轮询）
  → 对每个新视频：插入 Video → 创建 Task(PENDING) → 入队

任务队列（async worker 池，并发控制）
  → Pipeline.process_task(task_id):
    1. DOWNLOADING  (0–40%)   通过 yt-dlp 下载视频 + 字幕
    2. SUBTITLING   (40–60%)  处理/生成字幕
    3. UPLOADING    (60–95%)  上传至 B站（转载投稿）
    4. COMPLETED    (95–100%) 清理 + 通知
    失败时：指数退避重试，超限则标记 FAILED
```

## 项目结构

```
src/yt2bili/
├── core/               # 领域层：ORM 模型、Pydantic Schema、配置、枚举、异常
├── interfaces/         # 协议接口：UploaderBackend、SubtitleGenerator、Notifier
├── services/           # 业务逻辑：monitor、downloader、subtitle、uploader、pipeline、scheduler、task_queue
├── adapters/           # 具体实现：bilibili_uploader、whisper_subtitle、webhook_notifier
├── db/                 # 数据库层：异步引擎、会话工厂、CRUD Repository
├── web/                # NiceGUI WebUI：应用工厂、页面（仪表盘/频道/任务/设置/凭据）、组件
└── cli/                # Typer CLI：run、add-channel、list-channels、check-now、upload、status
```

## 配置说明

配置文件从平台对应目录加载，通过 Pydantic 验证。所有字段均有合理默认值。

| 平台 | 配置路径 | 数据路径（数据库、下载） |
|------|---------|----------------------|
| **Linux** | `$XDG_CONFIG_HOME/yt2bili/config.yaml`（默认 `~/.config/yt2bili/`） | `$XDG_DATA_HOME/yt2bili/`（默认 `~/.local/share/yt2bili/`） |
| **macOS** | `$XDG_CONFIG_HOME/yt2bili/config.yaml`（默认 `~/.config/yt2bili/`） | `$XDG_DATA_HOME/yt2bili/`（默认 `~/.local/share/yt2bili/`） |
| **Windows** | `%APPDATA%\yt2bili\config.yaml` | `%LOCALAPPDATA%\yt2bili\` |

| 分类 | 关键配置项 |
|------|-----------|
| **schedule（调度）** | `poll_interval_minutes`（轮询间隔）、`max_concurrent_downloads`、`max_concurrent_uploads`、`max_retries` |
| **download（下载）** | `quality`（best/1080/720/480）、`subtitle_langs`（字幕语言优先级）、`download_dir` |
| **subtitle（字幕）** | `subtitle_generator`（whisper/cloud/none）、`whisper_model`、`subtitle_fallback_generate` |
| **upload（上传）** | `bilibili_tid`（分区）、`tags`（标签）、`title_template`、`desc_template`、`copyright`（2=转载） |
| **webui** | `host`、`port`、`secret` |
| **notify（通知）** | `webhook_url`、`notify_on`（事件列表） |

### 模板变量

标题和简介模板支持以下占位符：

| 变量 | 说明 |
|------|------|
| `{original_title}` | YouTube 原始视频标题 |
| `{original_description}` | YouTube 原始视频简介 |
| `{youtube_url}` | YouTube 视频完整链接 |

### 频道级覆盖

每个频道可独立覆盖全局默认值（画质、字幕语言、标签、模板、分区），可通过 Web UI 操作或在数据库中设置 `config_overrides` JSON 字段。

## CLI 命令参考

```bash
yt2bili run                                    # 启动调度器 + Web UI
yt2bili add-channel <youtube_id> <name>        # 添加监控频道
yt2bili list-channels                          # 列出所有监控频道
yt2bili check-now                              # 立即触发所有频道检查
yt2bili upload <video_id>                      # 手动创建上传任务
yt2bili status                                 # 查看当前任务队列状态
```

## Web UI 界面

NiceGUI 仪表盘默认运行在 `http://127.0.0.1:8080`（可配置），包含五个页面：

| 页面 | 说明 |
|------|------|
| **Dashboard（仪表盘）** | 统计卡片、最近活动、快捷操作 |
| **Channels（频道）** | 添加/删除/启停频道，频道级配置 |
| **Tasks（任务）** | 可筛选的任务列表，进度条，重试/取消 |
| **Settings（设置）** | 编辑所有配置项 |
| **Auth（凭据）** | 管理 B站登录凭据 |

## 可扩展性

yt2bili 使用基于 Protocol 的抽象接口，便于扩展：

- **`UploaderBackend`** — 实现此接口可添加 B站以外的上传目标
- **`SubtitleGenerator`** — 实现此接口可接入任意 ASR 服务（本地或云端）
- **`Notifier`** — 实现此接口可自定义通知方式（邮件、Telegram 等）

## 技术栈

| 组件 | 技术选型 |
|------|---------|
| 下载 | yt-dlp（Python API） |
| 监控 | YouTube RSS + feedparser + httpx |
| 字幕 | pysubs2、srt、faster-whisper（可选） |
| 上传 | bilibili-api-python |
| 数据库 | SQLite + SQLAlchemy async ORM + aiosqlite |
| 配置 | YAML + Pydantic v2 |
| 调度 | APScheduler |
| Web UI | NiceGUI |
| CLI | Typer + Rich |
| 日志 | structlog |

## 开发指南

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 运行测试（含覆盖率）
pytest --cov=yt2bili

# 类型检查
mypy src/yt2bili

# 代码检查
ruff check src/
```

## 环境要求

- Python 3.11+
- 所有函数参数均有严格类型标注（mypy strict 模式）

## 许可证

MIT
