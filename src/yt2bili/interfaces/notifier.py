"""Abstract notifier protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    """Protocol for sending notifications (webhook, email, etc.)."""

    async def notify(self, event: str, payload: dict[str, Any]) -> None:
        """Send a notification for *event* with *payload*."""
        ...
