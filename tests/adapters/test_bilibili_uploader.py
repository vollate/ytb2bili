"""Tests for the Bilibili uploader adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yt2bili.core.exceptions import UploadError
from yt2bili.adapters.bilibili_uploader import BilibiliUploaderBackend


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success() -> None:
    """authenticate() creates a Credential and calls check_valid."""
    backend = BilibiliUploaderBackend()

    mock_cred_instance = MagicMock()
    mock_cred_instance.check_valid = AsyncMock()

    with patch(
        "yt2bili.adapters.bilibili_uploader.BilibiliUploaderBackend.authenticate",
        new=BilibiliUploaderBackend.authenticate,  # keep original
    ):
        with patch(
            "bilibili_api.Credential", return_value=mock_cred_instance
        ) as mock_cred_cls:
            result = await backend.authenticate(
                {"sessdata": "abc", "bili_jct": "def", "buvid3": "ghi"}
            )

    assert result is True
    mock_cred_cls.assert_called_once_with(
        sessdata="abc", bili_jct="def", buvid3="ghi"
    )
    mock_cred_instance.check_valid.assert_awaited_once()
    assert backend._credential is mock_cred_instance


@pytest.mark.asyncio
async def test_authenticate_missing_keys() -> None:
    """authenticate() raises UploadError when required keys are absent."""
    backend = BilibiliUploaderBackend()

    with patch("bilibili_api.Credential"):
        with pytest.raises(UploadError, match="sessdata"):
            await backend.authenticate({"sessdata": "abc"})


@pytest.mark.asyncio
async def test_authenticate_api_failure() -> None:
    """authenticate() wraps bilibili_api exceptions in UploadError."""
    backend = BilibiliUploaderBackend()

    mock_cred_instance = MagicMock()
    mock_cred_instance.check_valid = AsyncMock(
        side_effect=RuntimeError("invalid token")
    )

    with patch(
        "bilibili_api.Credential", return_value=mock_cred_instance
    ):
        with pytest.raises(UploadError, match="verification failed"):
            await backend.authenticate(
                {"sessdata": "a", "bili_jct": "b", "buvid3": "c"}
            )


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_success() -> None:
    """upload() creates VideoMeta, calls VideoUploader.start(), returns bvid."""
    backend = BilibiliUploaderBackend()
    backend._credential = MagicMock()  # pretend authenticated

    mock_uploader_instance = MagicMock()
    mock_uploader_instance.start = AsyncMock(
        return_value={"bvid": "BV17x411w7KC"}
    )

    with patch(
        "bilibili_api.video_uploader.VideoUploader",
        return_value=mock_uploader_instance,
    ) as mock_uploader_cls, patch(
        "bilibili_api.video_uploader.VideoMeta",
    ) as mock_meta_cls:
        bvid = await backend.upload(
            video_path=Path("/tmp/video.mp4"),
            title="Test Title",
            description="Test Desc",
            tags=["tag1", "tag2"],
            partition_id=17,
            source_url="https://youtube.com/watch?v=abc",
        )

    assert bvid == "BV17x411w7KC"

    # Verify VideoMeta was constructed correctly
    mock_meta_cls.assert_called_once_with(
        tid=17,
        title="Test Title",
        desc="Test Desc",
        tag="tag1,tag2",
        copyright=2,
        source="https://youtube.com/watch?v=abc",
    )

    # Verify VideoUploader was constructed with the right arguments
    mock_uploader_cls.assert_called_once()
    call_kwargs = mock_uploader_cls.call_args.kwargs
    assert call_kwargs["video_file"] == "/tmp/video.mp4"
    assert call_kwargs["credential"] is backend._credential

    mock_uploader_instance.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_not_authenticated() -> None:
    """upload() raises UploadError when called before authenticate."""
    backend = BilibiliUploaderBackend()

    with pytest.raises(UploadError, match="Not authenticated"):
        await backend.upload(
            video_path=Path("/tmp/v.mp4"),
            title="t",
            description="d",
            tags=[],
            partition_id=17,
        )


@pytest.mark.asyncio
async def test_upload_no_bvid_in_response() -> None:
    """upload() raises UploadError when the API returns no bvid."""
    backend = BilibiliUploaderBackend()
    backend._credential = MagicMock()

    mock_uploader_instance = MagicMock()
    mock_uploader_instance.start = AsyncMock(return_value={})

    with patch(
        "bilibili_api.video_uploader.VideoUploader",
        return_value=mock_uploader_instance,
    ), patch("bilibili_api.video_uploader.VideoMeta"):
        with pytest.raises(UploadError, match="no bvid"):
            await backend.upload(
                video_path=Path("/tmp/v.mp4"),
                title="t",
                description="d",
                tags=[],
                partition_id=17,
            )


@pytest.mark.asyncio
async def test_upload_api_exception() -> None:
    """upload() wraps bilibili_api exceptions in UploadError."""
    backend = BilibiliUploaderBackend()
    backend._credential = MagicMock()

    mock_uploader_instance = MagicMock()
    mock_uploader_instance.start = AsyncMock(
        side_effect=RuntimeError("network error")
    )

    with patch(
        "bilibili_api.video_uploader.VideoUploader",
        return_value=mock_uploader_instance,
    ), patch("bilibili_api.video_uploader.VideoMeta"):
        with pytest.raises(UploadError, match="network error"):
            await backend.upload(
                video_path=Path("/tmp/v.mp4"),
                title="t",
                description="d",
                tags=[],
                partition_id=17,
            )


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_empty() -> None:
    """progress() yields nothing when no events are cached."""
    backend = BilibiliUploaderBackend()
    events = [ev async for ev in backend.progress()]
    assert events == []
