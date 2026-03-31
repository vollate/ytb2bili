"""CRUD repository for all ORM models."""

from __future__ import annotations

import datetime
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yt2bili.core.enums import TaskStatus
from yt2bili.core.models import BilibiliCredential, Channel, Task, Video
from yt2bili.core.schemas import (
    BilibiliCredentialCreate,
    ChannelCreate,
    ChannelUpdate,
    VideoMeta,
)


class Repository:
    """Async CRUD repository backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Channel ──────────────────────────────────────────────────────────

    async def create_channel(self, data: ChannelCreate) -> Channel:
        import json

        channel = Channel(
            youtube_channel_id=data.youtube_channel_id,
            name=data.name,
            enabled=data.enabled,
            config_overrides=(
                json.dumps(data.config_overrides) if data.config_overrides else None
            ),
        )
        self._session.add(channel)
        await self._session.flush()
        return channel

    async def get_channel(self, channel_id: int) -> Channel | None:
        return await self._session.get(Channel, channel_id)

    async def get_channel_by_youtube_id(self, youtube_channel_id: str) -> Channel | None:
        stmt = select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_channels(self, *, enabled_only: bool = False) -> Sequence[Channel]:
        stmt = select(Channel).order_by(Channel.id)
        if enabled_only:
            stmt = stmt.where(Channel.enabled.is_(True))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def update_channel(self, channel_id: int, data: ChannelUpdate) -> Channel | None:
        import json

        channel = await self.get_channel(channel_id)
        if channel is None:
            return None
        if data.name is not None:
            channel.name = data.name
        if data.enabled is not None:
            channel.enabled = data.enabled
        if data.config_overrides is not None:
            channel.config_overrides = json.dumps(data.config_overrides)
        await self._session.flush()
        return channel

    async def delete_channel(self, channel_id: int) -> bool:
        channel = await self.get_channel(channel_id)
        if channel is None:
            return False
        await self._session.delete(channel)
        await self._session.flush()
        return True

    async def update_channel_checked(
        self, channel_id: int, checked_at: datetime.datetime
    ) -> None:
        stmt = (
            update(Channel)
            .where(Channel.id == channel_id)
            .values(last_checked_at=checked_at)
        )
        await self._session.execute(stmt)

    # ── Video ────────────────────────────────────────────────────────────

    async def create_video(self, channel_id: int, meta: VideoMeta) -> Video:
        video = Video(
            youtube_id=meta.youtube_id,
            channel_id=channel_id,
            title=meta.title,
            description=meta.description,
            duration=meta.duration,
            youtube_upload_date=meta.youtube_upload_date,
            thumbnail_url=meta.thumbnail_url,
        )
        self._session.add(video)
        await self._session.flush()
        return video

    async def get_video_by_youtube_id(self, youtube_id: str) -> Video | None:
        stmt = select(Video).where(Video.youtube_id == youtube_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_videos(
        self, channel_id: int | None = None, *, limit: int = 50
    ) -> Sequence[Video]:
        stmt = select(Video).order_by(Video.created_at.desc()).limit(limit)
        if channel_id is not None:
            stmt = stmt.where(Video.channel_id == channel_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    # ── Task ─────────────────────────────────────────────────────────────

    async def create_task(self, video_id: int, priority: int = 0) -> Task:
        task = Task(video_id=video_id, status=TaskStatus.PENDING, priority=priority)
        self._session.add(task)
        await self._session.flush()
        return task

    async def get_task(self, task_id: int) -> Task | None:
        return await self._session.get(Task, task_id)

    async def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> Sequence[Task]:
        stmt = select(Task).order_by(Task.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def update_task_status(
        self,
        task_id: int,
        status: TaskStatus,
        *,
        progress_pct: float | None = None,
        error_message: str | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status}
        if progress_pct is not None:
            values["progress_pct"] = progress_pct
        if error_message is not None:
            values["error_message"] = error_message
        stmt = update(Task).where(Task.id == task_id).values(**values)
        await self._session.execute(stmt)

    async def update_task_paths(
        self,
        task_id: int,
        *,
        video_path: str | None = None,
        subtitle_path: str | None = None,
        subtitle_source: str | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if video_path is not None:
            values["video_path"] = video_path
        if subtitle_path is not None:
            values["subtitle_path"] = subtitle_path
        if subtitle_source is not None:
            values["subtitle_source"] = subtitle_source
        if values:
            stmt = update(Task).where(Task.id == task_id).values(**values)
            await self._session.execute(stmt)

    async def update_task_bvid(self, task_id: int, bvid: str) -> None:
        stmt = update(Task).where(Task.id == task_id).values(bilibili_bvid=bvid)
        await self._session.execute(stmt)

    async def increment_task_attempt(self, task_id: int) -> None:
        task = await self.get_task(task_id)
        if task is not None:
            task.attempt += 1
            await self._session.flush()

    # ── BilibiliCredential ───────────────────────────────────────────────

    async def create_credential(self, data: BilibiliCredentialCreate) -> BilibiliCredential:
        cred = BilibiliCredential(
            label=data.label,
            sessdata=data.sessdata,
            bili_jct=data.bili_jct,
            buvid3=data.buvid3,
            expires_at=data.expires_at,
        )
        self._session.add(cred)
        await self._session.flush()
        return cred

    async def get_active_credential(self) -> BilibiliCredential | None:
        stmt = select(BilibiliCredential).where(BilibiliCredential.is_active.is_(True)).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_credentials(self) -> Sequence[BilibiliCredential]:
        stmt = select(BilibiliCredential).order_by(BilibiliCredential.id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def delete_credential(self, credential_id: int) -> bool:
        cred = await self._session.get(BilibiliCredential, credential_id)
        if cred is None:
            return False
        await self._session.delete(cred)
        await self._session.flush()
        return True

    # ── Aggregate queries ──────────────────────────────────────────────

    async def list_videos_with_tasks(
        self,
        channel_id: int | None = None,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> Sequence[Video]:
        """List videos with eagerly-loaded tasks, optionally filtered by channel and task status."""
        stmt = (
            select(Video)
            .options(selectinload(Video.tasks), selectinload(Video.channel))
            .order_by(Video.created_at.desc())
            .limit(limit)
        )
        if channel_id is not None:
            stmt = stmt.where(Video.channel_id == channel_id)
        if status is not None:
            stmt = stmt.join(Task, Task.video_id == Video.id).where(Task.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().unique().all()

    async def get_channel_stats(self, channel_id: int) -> dict[str, int]:
        """Return task status counts for a given channel."""
        stmt = (
            select(Task.status, func.count(Task.id))
            .join(Video, Video.id == Task.video_id)
            .where(Video.channel_id == channel_id)
            .group_by(Task.status)
        )
        result = await self._session.execute(stmt)
        counts: dict[str, int] = {s.value: 0 for s in TaskStatus}
        for row_status, count in result.all():
            counts[row_status.value] = count
        return counts

    async def commit(self) -> None:
        await self._session.commit()
