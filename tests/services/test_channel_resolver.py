"""Tests for yt2bili.services.channel_resolver."""

from __future__ import annotations

import pytest

from yt2bili.services.channel_resolver import (
    extract_channel_id,
    extract_handle,
)


class TestExtractChannelId:
    """Test bare ID and /channel/ URL extraction."""

    def test_bare_id(self) -> None:
        assert extract_channel_id("UC_x5XG1OV2P6uZZ5FSM9Ttw") == "UC_x5XG1OV2P6uZZ5FSM9Ttw"

    def test_channel_url(self) -> None:
        url = "https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw"
        assert extract_channel_id(url) == "UC_x5XG1OV2P6uZZ5FSM9Ttw"

    def test_channel_url_no_scheme(self) -> None:
        url = "youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw"
        assert extract_channel_id(url) == "UC_x5XG1OV2P6uZZ5FSM9Ttw"

    def test_handle_url_returns_none(self) -> None:
        # Handle URLs can't give a UC ID without HTTP fetch
        assert extract_channel_id("https://youtube.com/@handle") is None

    def test_random_string_returns_none(self) -> None:
        assert extract_channel_id("not a channel") is None

    def test_with_whitespace(self) -> None:
        assert extract_channel_id("  UC_x5XG1OV2P6uZZ5FSM9Ttw  ") == "UC_x5XG1OV2P6uZZ5FSM9Ttw"


class TestExtractHandle:
    """Test handle / custom URL extraction."""

    def test_at_handle(self) -> None:
        assert extract_handle("https://youtube.com/@LinusTechTips") == "@LinusTechTips"

    def test_c_custom(self) -> None:
        assert extract_handle("https://youtube.com/c/GoogleDevelopers") == "c/GoogleDevelopers"

    def test_user_legacy(self) -> None:
        assert extract_handle("https://www.youtube.com/user/Google") == "user/Google"

    def test_bare_id_returns_none(self) -> None:
        assert extract_handle("UC_x5XG1OV2P6uZZ5FSM9Ttw") is None

    def test_channel_url_returns_none(self) -> None:
        assert extract_handle("https://youtube.com/channel/UCxxx") is None
