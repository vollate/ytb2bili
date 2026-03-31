"""Webhook notifier adapter – POSTs JSON to a configurable URL."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger()


class WebhookNotifier:
    """``Notifier`` implementation that POSTs JSON payloads to a webhook URL.

    Only events listed in *notify_on* are dispatched.  HTTP errors are logged
    but never propagated – the notifier must not crash the pipeline.
    """

    def __init__(self, webhook_url: str, notify_on: list[str], proxy: str | None = None) -> None:
        self._webhook_url = webhook_url
        self._notify_on = notify_on
        self._proxy = proxy

    async def notify(self, event: str, payload: dict[str, Any]) -> None:
        """POST *payload* as JSON to the configured webhook URL.

        The request is silently skipped when *event* is not in the allow-list.
        """
        if event not in self._notify_on:
            log.debug("webhook.skipped", event=event)
            return

        body: dict[str, Any] = {"event": event, "payload": payload}

        try:
            async with httpx.AsyncClient(proxy=self._proxy) as client:
                response = await client.post(
                    self._webhook_url,
                    json=body,
                    timeout=10.0,
                )
                response.raise_for_status()
            log.info(
                "webhook.sent",
                event=event,
                status=response.status_code,
            )
        except httpx.HTTPStatusError as exc:
            log.warning(
                "webhook.http_error",
                event=event,
                status=exc.response.status_code,
                detail=str(exc),
            )
        except httpx.RequestError as exc:
            log.warning(
                "webhook.request_error",
                event=event,
                detail=str(exc),
            )
        except Exception as exc:
            log.warning(
                "webhook.unexpected_error",
                event=event,
                detail=str(exc),
            )
