"""Utilities for resolving YouTube channel identifiers.

Supports YouTube channel URLs (``/channel/UCxxx``, ``/@handle``, ``/c/name``,
``/user/name``) and bare channel IDs.  Can also auto-fetch the channel display
name via the RSS feed.
"""

from __future__ import annotations

import re

import feedparser
import httpx
import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ── URL patterns ─────────────────────────────────────────────────────────────

# /channel/UCxxxxxxxx
_RE_CHANNEL_ID = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/channel/(UC[\w-]{22})"
)
# /@handle  /c/custom  /user/legacy
_RE_HANDLE = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/(@[\w.-]+|c/[\w.-]+|user/[\w.-]+)"
)
# bare UC id
_RE_BARE_ID = re.compile(r"^UC[\w-]{22}$")

_RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def extract_channel_id(value: str) -> str | None:
    """Try to extract a ``UCxxx`` channel ID from *value*.

    Returns the ID string if *value* is a bare channel ID or a
    ``/channel/UCxxx`` URL.  Returns ``None`` for handle/custom URLs
    (those need an HTTP resolve step).
    """
    value = value.strip()
    m = _RE_CHANNEL_ID.search(value)
    if m:
        return m.group(1)
    if _RE_BARE_ID.match(value):
        return value
    return None


def extract_handle(value: str) -> str | None:
    """Try to extract a handle/custom path from *value*.

    Returns the path segment (e.g. ``@handle``, ``c/name``, ``user/name``)
    or ``None``.
    """
    value = value.strip()
    m = _RE_HANDLE.search(value)
    return m.group(1) if m else None


async def resolve_channel(
    value: str,
    *,
    proxy: str | None = None,
) -> tuple[str, str] | None:
    """Resolve *value* (URL, handle, or bare ID) to ``(channel_id, display_name)``.

    Returns ``None`` when the channel cannot be resolved.
    """
    # 1. Direct channel ID
    channel_id = extract_channel_id(value)
    if channel_id is not None:
        name = await _fetch_channel_name(channel_id, proxy=proxy)
        return (channel_id, name or channel_id)

    # 2. Handle / custom URL → need to fetch the page to discover the channel ID
    handle = extract_handle(value)
    if handle is not None:
        result = await _resolve_handle(handle, proxy=proxy)
        if result is not None:
            return result
        return None

    # 3. Maybe it's a full URL we didn't match, or just garbage
    if "youtube.com" in value or "youtu.be" in value:
        result = await _resolve_by_page(value, proxy=proxy)
        if result is not None:
            return result

    return None


async def _fetch_channel_name(
    channel_id: str,
    *,
    proxy: str | None = None,
) -> str | None:
    """Fetch the channel display name from the RSS feed."""
    url = _RSS_URL_TEMPLATE.format(channel_id=channel_id)
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        title: str | None = feed.feed.get("title")
        return title if title else None
    except Exception as exc:
        log.warning("channel_name_fetch_failed", channel_id=channel_id, error=str(exc))
        return None


async def _resolve_handle(
    handle: str,
    *,
    proxy: str | None = None,
) -> tuple[str, str] | None:
    """Resolve a YouTube handle (``@xxx``, ``c/xxx``, ``user/xxx``) to (id, name)."""
    page_url = f"https://www.youtube.com/{handle}"
    return await _resolve_by_page(page_url, proxy=proxy)


async def _resolve_by_page(
    url: str,
    *,
    proxy: str | None = None,
) -> tuple[str, str] | None:
    """Fetch a YouTube page and extract channel ID + name from meta tags."""
    try:
        async with httpx.AsyncClient(
            proxy=proxy, timeout=15.0, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        html = resp.text

        # Extract channel ID from <meta> or <link rel="canonical">
        # <meta itemprop="channelId" content="UCxxx">
        # <link rel="canonical" href="https://www.youtube.com/channel/UCxxx">
        channel_id: str | None = None
        m = re.search(r'itemprop="channelId"\s+content="(UC[\w-]{22})"', html)
        if m:
            channel_id = m.group(1)
        else:
            m = re.search(r'youtube\.com/channel/(UC[\w-]{22})', html)
            if m:
                channel_id = m.group(1)

        if channel_id is None:
            log.warning("channel_id_not_found_in_page", url=url)
            return None

        # Extract display name from <meta property="og:title"> or <title>
        name: str | None = None
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if m:
            name = m.group(1)
            # og:title often has " - YouTube" suffix
            if name.endswith(" - YouTube"):
                name = name[: -len(" - YouTube")]
        if not name:
            m = re.search(r"<title>(.+?)</title>", html)
            if m:
                name = m.group(1).replace(" - YouTube", "").strip()

        return (channel_id, name or channel_id)
    except Exception as exc:
        log.warning("channel_page_resolve_failed", url=url, error=str(exc))
        return None
