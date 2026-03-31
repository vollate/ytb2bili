"""Simple internationalization (i18n) system for yt2bili.

Supports Simplified Chinese (zh-CN) and English (en).
"""

from __future__ import annotations

# ── Module-level language state ──────────────────────────────────────────────

_current_lang: str = "en"


def get_lang() -> str:
    """Return the current language code."""
    return _current_lang


def set_lang(lang: str) -> None:
    """Set the current language code."""
    global _current_lang
    _current_lang = lang


def t(key: str, lang: str = "en", **kwargs: str) -> str:
    """Look up *key* in the translations dict for *lang*.

    Falls back to English if key is missing in *lang*, and falls back
    to *key* itself if not found in any language.  Supports
    ``.format(**kwargs)`` for variable substitution.
    """
    text = translations.get(lang, {}).get(key)
    if text is None and lang != "en":
        text = translations.get("en", {}).get(key)
    if text is None:
        text = key
    if kwargs:
        text = text.format(**kwargs)
    return text


def _(key: str, **kwargs: str) -> str:
    """Convenience wrapper: ``t(key, get_lang(), **kwargs)``."""
    return t(key, get_lang(), **kwargs)


# ── Translation dictionary ──────────────────────────────────────────────────

translations: dict[str, dict[str, str]] = {
    "en": {
        # ── Navigation ───────────────────────────────────────────────────
        "nav.dashboard": "Dashboard",
        "nav.channels": "Channels",
        "nav.tasks": "Tasks",
        "nav.settings": "Settings",
        "nav.auth": "Auth",
        "nav.videos": "Videos",
        "nav.navigation": "Navigation",

        # ── Dashboard ────────────────────────────────────────────────────
        "dashboard.title": "Dashboard",
        "dashboard.stats.channels": "Channels",
        "dashboard.stats.videos": "Videos",
        "dashboard.stats.active_tasks": "Active Tasks",
        "dashboard.stats.completed": "Completed",
        "dashboard.recent_activity": "Recent Activity",
        "dashboard.no_tasks": "No tasks yet.",
        "dashboard.check_all": "Check All Now",
        "dashboard.refresh": "Refresh",
        "dashboard.recent_channels": "Recent Channels",
        "dashboard.no_channels_checked": "No channels checked yet.",

        # ── Channels ─────────────────────────────────────────────────────
        "channels.title": "Channels",
        "channels.add": "Add Channel",
        "channels.refresh": "Refresh",
        "channels.search_placeholder": "Name or YouTube ID",
        "channels.sort_by": "Sort by",
        "channels.sort.name": "Name",
        "channels.sort.last_checked": "Last Checked",
        "channels.sort.video_count": "Video Count",
        "channels.enable_all": "Enable All",
        "channels.disable_all": "Disable All",
        "channels.no_channels": "No channels found.",
        "channels.stats": "{total} channels ({enabled} enabled, {disabled} disabled)",
        "channels.search_label": "Search channels...",

        "channels.add_dialog.title": "Add Channel",
        "channels.add_dialog.url_or_id": "YouTube Channel URL or ID",
        "channels.add_dialog.url_placeholder": "https://youtube.com/@handle, /channel/UCxxx, or bare UCxxx",
        "channels.add_dialog.name_optional": "Display Name (optional)",
        "channels.add_dialog.name_placeholder": "Auto-fetched from YouTube if empty",
        "channels.add_dialog.overrides": "Optional config overrides",
        "channels.add_dialog.quality": "Quality",
        "channels.add_dialog.tags": "Tags",
        "channels.add_dialog.tags_placeholder": "comma-separated",
        "channels.add_dialog.subtitle_langs": "Subtitle Languages",
        "channels.add_dialog.subtitle_langs_placeholder": "comma-separated, e.g. zh-Hans,en",
        "channels.add_dialog.resolving": "Resolving channel...",
        "channels.add_dialog.resolve_failed": "Could not resolve channel. Provide a valid YouTube URL or UCxxx ID.",
        "channels.add_dialog.already_exists": "Channel already exists: {name}",
        "channels.add_dialog.added": "Added: {name}",
        "channels.add_dialog.url_required": "Channel URL or ID is required",

        "channels.edit_dialog.title": "Edit: {name}",
        "channels.edit_dialog.overrides_label": "Channel config overrides",
        "channels.edit_dialog.quality": "Quality",
        "channels.edit_dialog.tags": "Tags",
        "channels.edit_dialog.subtitle_langs": "Subtitle Languages",
        "channels.edit_dialog.tid": "Bilibili TID",
        "channels.edit_dialog.title_template": "Title Template",
        "channels.edit_dialog.desc_template": "Description Template",
        "channels.edit_dialog.using_default": "Using default",
        "channels.edit_dialog.saved": "Config saved",
        "channels.edit_dialog.not_found": "Channel not found",

        "channels.card.videos": "{count} videos",
        "channels.card.never_checked": "Never",
        "channels.card.last_checked": "Last checked",
        "channels.card.enabled": "Enabled",
        "channels.card.disabled": "Disabled",
        "channels.card.check_now": "Check Now",
        "channels.card.recent_videos": "Recent Videos",
        "channels.card.edit": "Edit config",
        "channels.card.delete": "Delete channel",
        "channels.card.confirm_delete": "Confirm delete",
        "channels.card.enable_disable": "Enable / Disable",

        "channels.deleted": "Channel deleted",
        "channels.toggled": "All channels {state}",

        # ── Tasks ────────────────────────────────────────────────────────
        "tasks.title": "Tasks",
        "tasks.filter.all": "all",
        "tasks.filter.status": "Status filter",
        "tasks.filter.channel": "Channel",
        "tasks.no_tasks": "No tasks match the current filter.",
        "tasks.refresh": "Refresh",
        "tasks.retry": "Retry",
        "tasks.cancel": "Cancel",
        "tasks.header.id": "ID",
        "tasks.header.video": "Video",
        "tasks.header.status": "Status",
        "tasks.header.progress": "Progress",
        "tasks.header.attempt": "Attempt",
        "tasks.header.actions": "Actions",
        "tasks.retry_requested": "Task #{task_id} queued for retry",
        "tasks.cancel_requested": "Task #{task_id} cancelled",
        "tasks.attempt": "Attempt {attempt}",

        # ── Videos ───────────────────────────────────────────────────────
        "videos.title": "Videos",
        "videos.no_videos": "No videos found.",
        "videos.filter.all_channels": "Channel",
        "videos.filter.all_statuses": "Status",
        "videos.filter.all": "All",
        "videos.youtube_link": "Open on YouTube",
        "videos.create_task": "Create Task",
        "videos.details": "Details",
        "videos.tasks_label": "Tasks:",

        # ── Settings ─────────────────────────────────────────────────────
        "settings.title": "Settings",
        "settings.save": "Save",
        "settings.saved": "Settings saved to {path}",

        "settings.section.schedule": "Schedule",
        "settings.section.download": "Download",
        "settings.section.subtitle": "Subtitle",
        "settings.section.upload": "Upload",
        "settings.section.webui": "Web UI",
        "settings.section.notify": "Notifications",

        "settings.field.poll_interval_minutes": "Poll Interval (minutes)",
        "settings.field.max_concurrent_downloads": "Max Concurrent Downloads",
        "settings.field.max_concurrent_uploads": "Max Concurrent Uploads",
        "settings.field.max_retries": "Max Retries",
        "settings.field.retry_backoff_base": "Retry Backoff Base",
        "settings.field.quality": "Quality",
        "settings.field.subtitle_langs": "Subtitle Languages",
        "settings.field.download_dir": "Download Directory",
        "settings.field.subtitle_generator": "Subtitle Generator",
        "settings.field.whisper_model": "Whisper Model",
        "settings.field.whisper_device": "Whisper Device",
        "settings.field.subtitle_fallback_generate": "Subtitle Fallback Generate",
        "settings.field.bilibili_tid": "Bilibili TID",
        "settings.field.tags": "Tags",
        "settings.field.title_template": "Title Template",
        "settings.field.desc_template": "Description Template",
        "settings.field.copyright": "Copyright",
        "settings.field.delete_after_upload": "Delete After Upload",
        "settings.field.host": "Host",
        "settings.field.port": "Port",
        "settings.field.secret": "Secret",
        "settings.field.language": "Language",
        "settings.field.webhook_url": "Webhook URL",
        "settings.field.notify_on": "Notify On",

        # ── Auth ─────────────────────────────────────────────────────────
        "auth.title": "Bilibili Credentials",
        "auth.add": "Add Credential",
        "auth.no_credentials": "No credentials stored.",
        "auth.set_active": "Set Active",
        "auth.delete": "Delete",
        "auth.label": "Label",
        "auth.sessdata": "SESSDATA",
        "auth.bili_jct": "bili_jct",
        "auth.buvid3": "buvid3",
        "auth.expires_at": "Expires at (optional, ISO 8601)",
        "auth.added": "Credential added",
        "auth.deleted": "Credential deleted",
        "auth.activated": "Credential activated",
        "auth.add_dialog_title": "Add Bilibili Credential",
        "auth.active": "ACTIVE",
        "auth.inactive": "INACTIVE",
        "auth.sessdata_display": "SESSDATA: {masked}",
        "auth.expires_display": "Expires: {date}",
        "auth.added_display": "Added: {date}",
        "auth.fields_required": "All fields except expiry are required",
        "auth.invalid_date": "Invalid date format (use ISO 8601)",

        # ── Common ───────────────────────────────────────────────────────
        "common.cancel": "Cancel",
        "common.save": "Save",
        "common.add": "Add",
        "common.delete": "Delete",
        "common.confirm": "Confirm",
        "common.enabled": "enabled",
        "common.disabled": "disabled",
        "common.default": "default",
        "common.refresh": "Refresh",

        # ── App ──────────────────────────────────────────────────────────
        "app.title": "yt2bili — YouTube → Bilibili",
        "app.brand": "yt2bili",
        "app.language": "Language",

        # ── CLI ──────────────────────────────────────────────────────────
        "cli.error_loading_config": "Error loading config:",
        "cli.resolving_channel": "Resolving channel...",
        "cli.resolve_failed": "Could not resolve channel:",
        "cli.resolve_hint": "Please provide a valid YouTube channel URL or UCxxx ID.",
        "cli.channel_id": "  Channel ID: {channel_id}",
        "cli.channel_name": "  Name:       {name}",
        "cli.channel_exists": "Channel '{channel_id}' already exists as '{name}'.",
        "cli.channel_added": "Added channel: {name} ({channel_id})",
        "cli.no_channels": "No channels configured.",
        "cli.table_channels": "Monitored Channels",
        "cli.enabled_channels": "Found {count} enabled channel(s) to check.",
        "cli.scheduler_note": "Note: Full pipeline check requires the scheduler service to be running.",
        "cli.task_created": "Created upload task #{task_id} for video #{video_id}",
        "cli.no_tasks": "No tasks in queue.",
        "cli.table_tasks": "Task Queue",
    },
    "zh-CN": {
        # ── Navigation ───────────────────────────────────────────────────
        "nav.dashboard": "仪表盘",
        "nav.channels": "频道",
        "nav.tasks": "任务",
        "nav.settings": "设置",
        "nav.auth": "认证",
        "nav.videos": "视频",
        "nav.navigation": "导航",

        # ── Dashboard ────────────────────────────────────────────────────
        "dashboard.title": "仪表盘",
        "dashboard.stats.channels": "频道",
        "dashboard.stats.videos": "视频",
        "dashboard.stats.active_tasks": "活跃任务",
        "dashboard.stats.completed": "已完成",
        "dashboard.recent_activity": "近期活动",
        "dashboard.no_tasks": "暂无任务。",
        "dashboard.check_all": "立即全部检查",
        "dashboard.refresh": "刷新",
        "dashboard.recent_channels": "近期频道",
        "dashboard.no_channels_checked": "暂无已检查的频道。",

        # ── Channels ─────────────────────────────────────────────────────
        "channels.title": "频道",
        "channels.add": "添加频道",
        "channels.refresh": "刷新",
        "channels.search_placeholder": "名称或 YouTube ID",
        "channels.sort_by": "排序",
        "channels.sort.name": "名称",
        "channels.sort.last_checked": "最近检查",
        "channels.sort.video_count": "视频数量",
        "channels.enable_all": "全部启用",
        "channels.disable_all": "全部禁用",
        "channels.no_channels": "未找到频道。",
        "channels.stats": "{total} 个频道（{enabled} 个已启用，{disabled} 个已禁用）",
        "channels.search_label": "搜索频道...",

        "channels.add_dialog.title": "添加频道",
        "channels.add_dialog.url_or_id": "YouTube 频道 URL 或 ID",
        "channels.add_dialog.url_placeholder": "https://youtube.com/@handle、/channel/UCxxx 或直接输入 UCxxx",
        "channels.add_dialog.name_optional": "显示名称（可选）",
        "channels.add_dialog.name_placeholder": "留空则自动从 YouTube 获取",
        "channels.add_dialog.overrides": "可选配置覆盖",
        "channels.add_dialog.quality": "画质",
        "channels.add_dialog.tags": "标签",
        "channels.add_dialog.tags_placeholder": "逗号分隔",
        "channels.add_dialog.subtitle_langs": "字幕语言",
        "channels.add_dialog.subtitle_langs_placeholder": "逗号分隔，例如 zh-Hans,en",
        "channels.add_dialog.resolving": "正在解析频道...",
        "channels.add_dialog.resolve_failed": "无法解析频道。请提供有效的 YouTube URL 或 UCxxx ID。",
        "channels.add_dialog.already_exists": "频道已存在：{name}",
        "channels.add_dialog.added": "已添加：{name}",
        "channels.add_dialog.url_required": "频道 URL 或 ID 不能为空",

        "channels.edit_dialog.title": "编辑：{name}",
        "channels.edit_dialog.overrides_label": "频道配置覆盖",
        "channels.edit_dialog.quality": "画质",
        "channels.edit_dialog.tags": "标签",
        "channels.edit_dialog.subtitle_langs": "字幕语言",
        "channels.edit_dialog.tid": "B站分区 TID",
        "channels.edit_dialog.title_template": "标题模板",
        "channels.edit_dialog.desc_template": "描述模板",
        "channels.edit_dialog.using_default": "使用默认值",
        "channels.edit_dialog.saved": "配置已保存",
        "channels.edit_dialog.not_found": "频道未找到",

        "channels.card.videos": "{count} 个视频",
        "channels.card.never_checked": "从未检查",
        "channels.card.last_checked": "最近检查",
        "channels.card.enabled": "已启用",
        "channels.card.disabled": "已禁用",
        "channels.card.check_now": "立即检查",
        "channels.card.recent_videos": "近期视频",
        "channels.card.edit": "编辑配置",
        "channels.card.delete": "删除频道",
        "channels.card.confirm_delete": "确认删除",
        "channels.card.enable_disable": "启用/禁用",

        "channels.deleted": "频道已删除",
        "channels.toggled": "所有频道已{state}",

        # ── Tasks ────────────────────────────────────────────────────────
        "tasks.title": "任务",
        "tasks.filter.all": "全部",
        "tasks.filter.status": "状态筛选",
        "tasks.filter.channel": "频道",
        "tasks.no_tasks": "没有匹配当前筛选条件的任务。",
        "tasks.refresh": "刷新",
        "tasks.retry": "重试",
        "tasks.cancel": "取消",
        "tasks.header.id": "ID",
        "tasks.header.video": "视频",
        "tasks.header.status": "状态",
        "tasks.header.progress": "进度",
        "tasks.header.attempt": "尝试次数",
        "tasks.header.actions": "操作",
        "tasks.retry_requested": "任务 #{task_id} 已加入重试队列",
        "tasks.cancel_requested": "任务 #{task_id} 已取消",
        "tasks.attempt": "第 {attempt} 次",

        # ── Videos ───────────────────────────────────────────────────────
        "videos.title": "视频",
        "videos.no_videos": "未找到视频。",
        "videos.filter.all_channels": "频道",
        "videos.filter.all_statuses": "状态",
        "videos.filter.all": "全部",
        "videos.youtube_link": "在 YouTube 上打开",
        "videos.create_task": "创建任务",
        "videos.details": "详情",
        "videos.tasks_label": "任务：",

        # ── Settings ─────────────────────────────────────────────────────
        "settings.title": "设置",
        "settings.save": "保存",
        "settings.saved": "设置已保存到 {path}",

        "settings.section.schedule": "调度",
        "settings.section.download": "下载",
        "settings.section.subtitle": "字幕",
        "settings.section.upload": "上传",
        "settings.section.webui": "网页界面",
        "settings.section.notify": "通知",

        "settings.field.poll_interval_minutes": "轮询间隔（分钟）",
        "settings.field.max_concurrent_downloads": "最大并发下载数",
        "settings.field.max_concurrent_uploads": "最大并发上传数",
        "settings.field.max_retries": "最大重试次数",
        "settings.field.retry_backoff_base": "重试退避基数",
        "settings.field.quality": "画质",
        "settings.field.subtitle_langs": "字幕语言",
        "settings.field.download_dir": "下载目录",
        "settings.field.subtitle_generator": "字幕生成器",
        "settings.field.whisper_model": "Whisper 模型",
        "settings.field.whisper_device": "Whisper 设备",
        "settings.field.subtitle_fallback_generate": "字幕回退生成",
        "settings.field.bilibili_tid": "B站分区 TID",
        "settings.field.tags": "标签",
        "settings.field.title_template": "标题模板",
        "settings.field.desc_template": "描述模板",
        "settings.field.copyright": "版权类型",
        "settings.field.delete_after_upload": "上传后删除",
        "settings.field.host": "主机地址",
        "settings.field.port": "端口",
        "settings.field.secret": "密钥",
        "settings.field.language": "语言",
        "settings.field.webhook_url": "Webhook 地址",
        "settings.field.notify_on": "通知条件",

        # ── Auth ─────────────────────────────────────────────────────────
        "auth.title": "B站凭据",
        "auth.add": "添加凭据",
        "auth.no_credentials": "暂无存储的凭据。",
        "auth.set_active": "设为活跃",
        "auth.delete": "删除",
        "auth.label": "标签",
        "auth.sessdata": "SESSDATA",
        "auth.bili_jct": "bili_jct",
        "auth.buvid3": "buvid3",
        "auth.expires_at": "过期时间（可选，ISO 8601）",
        "auth.added": "凭据已添加",
        "auth.deleted": "凭据已删除",
        "auth.activated": "凭据已激活",
        "auth.add_dialog_title": "添加B站凭据",
        "auth.active": "活跃",
        "auth.inactive": "未激活",
        "auth.sessdata_display": "SESSDATA：{masked}",
        "auth.expires_display": "过期：{date}",
        "auth.added_display": "添加于：{date}",
        "auth.fields_required": "除过期时间外，所有字段均为必填",
        "auth.invalid_date": "日期格式无效（请使用 ISO 8601）",

        # ── Common ───────────────────────────────────────────────────────
        "common.cancel": "取消",
        "common.save": "保存",
        "common.add": "添加",
        "common.delete": "删除",
        "common.confirm": "确认",
        "common.enabled": "已启用",
        "common.disabled": "已禁用",
        "common.default": "默认",
        "common.refresh": "刷新",

        # ── App ──────────────────────────────────────────────────────────
        "app.title": "yt2bili — YouTube → Bilibili",
        "app.brand": "yt2bili",
        "app.language": "语言",

        # ── CLI ──────────────────────────────────────────────────────────
        "cli.error_loading_config": "加载配置出错：",
        "cli.resolving_channel": "正在解析频道...",
        "cli.resolve_failed": "无法解析频道：",
        "cli.resolve_hint": "请提供有效的 YouTube 频道 URL 或 UCxxx ID。",
        "cli.channel_id": "  频道 ID：{channel_id}",
        "cli.channel_name": "  名称：    {name}",
        "cli.channel_exists": "频道 '{channel_id}' 已存在，名称为 '{name}'。",
        "cli.channel_added": "已添加频道：{name}（{channel_id}）",
        "cli.no_channels": "未配置任何频道。",
        "cli.table_channels": "监控频道",
        "cli.enabled_channels": "找到 {count} 个已启用的频道待检查。",
        "cli.scheduler_note": "注意：完整的流水线检查需要调度服务运行中。",
        "cli.task_created": "已创建上传任务 #{task_id}，对应视频 #{video_id}",
        "cli.no_tasks": "队列中暂无任务。",
        "cli.table_tasks": "任务队列",
    },
}
