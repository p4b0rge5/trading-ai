"""
Notification Service — lightweight async event dispatcher for live trading events.

Supports:
  - Local in-memory callbacks (callable functions)
  - Webhook callbacks (HTTP POST to a configured URL)

Events:
  - trade_opened
  - trade_closed
  - signal_triggered
  - session_started
  - session_stopped
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class NotificationPayload:
    """Standard payload sent with every notification."""
    session_id: int
    strategy_name: str
    symbol: str
    side: str
    entry_price: float
    timestamp: str
    message: str
    event_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class NotificationService:
    """
    Lightweight notification dispatcher.

    Registers callbacks (local or webhook) and fires them on trading events.
    All dispatch is async — callbacks are called concurrently without blocking.
    """

    VALID_EVENTS = frozenset({
        "trade_opened",
        "trade_closed",
        "signal_triggered",
        "session_started",
        "session_stopped",
    })

    def __init__(self, webhook_url: Optional[str] = None):
        self._webhook_url: Optional[str] = webhook_url
        self._local_callbacks: list[Callable] = []
        self._event_counts: dict[str, int] = {}
        self._errors: list[dict] = []

        # If webhook URL is given, register the webhook dispatcher
        if webhook_url:
            self._webhook_coroutine = self._fire_webhook
        else:
            self._webhook_coroutine = None

    # ── Callback Registration ───────────────────────────────────────────

    def register(self, callback: Callable) -> None:
        """Register a local in-memory callback.

        The callback will be called as: callback(event_type, payload_dict)
        Sync or async callables are both supported.
        """
        if not callable(callback):
            raise TypeError("Callback must be callable")
        self._local_callbacks.append(callback)

    def unregister(self, callback: Callable) -> bool:
        """Remove a previously registered callback. Returns True if found."""
        try:
            self._local_callbacks.remove(callback)
            return True
        except ValueError:
            return False

    @property
    def webhook_url(self) -> Optional[str]:
        return self._webhook_url

    @property
    def has_webhook(self) -> bool:
        return self._webhook_url is not None

    # ── Core Dispatch ───────────────────────────────────────────────────

    async def notify(
        self,
        event_type: str,
        session_id: int,
        strategy_name: str = "",
        symbol: str = "",
        side: str = "",
        entry_price: float = 0.0,
        message: str = "",
        **kwargs,
    ) -> None:
        """Fire a notification event to all registered listeners.

        Args:
            event_type: One of the VALID_EVENTS strings.
            session_id: Trading session ID.
            strategy_name: Name of the strategy.
            symbol: Trading symbol (e.g. "EURUSD").
            side: "buy" or "sell".
            entry_price: Entry price of the trade/signal.
            message: Human-readable description.
            **kwargs: Extra fields stored in metadata.
        """
        if event_type not in self.VALID_EVENTS:
            logger.warning(f"Unknown event type '{event_type}', skipping")
            return

        # Count events
        self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1

        # Build payload
        payload = NotificationPayload(
            session_id=session_id,
            strategy_name=strategy_name,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
            message=message,
            event_type=event_type,
            metadata=kwargs,
        )

        payload_dict = payload.to_dict()

        # Dispatch to all listeners concurrently
        tasks = []

        # Local callbacks
        for cb in self._local_callbacks:
            tasks.append(self._invoke_local(cb, event_type, payload_dict))

        # Webhook
        if self._webhook_coroutine:
            tasks.append(self._webhook_coroutine(payload_dict))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Log any exceptions (don't raise — we don't want one callback to break others)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.error(f"Notification callback {i} failed: {r}")

    # ── Local Callback Invocation ───────────────────────────────────────

    @staticmethod
    async def _invoke_local(
        callback: Callable, event_type: str, payload: dict
    ) -> Any:
        """Invoke a single callback, handling both sync and async callables."""
        try:
            result = callback(event_type, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Local callback error: {e}")
            raise  # Re-raise so gather(return_exceptions=True) captures it

    # ── Webhook Dispatch ────────────────────────────────────────────────

    async def _fire_webhook(self, payload: dict) -> None:
        """POST payload to the webhook URL using bare aiohttp if available,
        otherwise fall back to asyncio + urllib."""
        if not self._webhook_url:
            return

        body = json.dumps(payload).encode("utf-8")

        try:
            # Try aiohttp first (faster, native async)
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.post(
                    self._webhook_url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            f"Webhook returned status {resp.status}: "
                            f"{self._webhook_url}"
                        )
        except ImportError:
            # Fallback: asyncio + urllib
            await self._fire_webhook_urllib(payload, body)
        except Exception as e:
            logger.error(f"Webhook dispatch failed (aiohttp): {e}")
            # Fallback to urllib
            try:
                await self._fire_webhook_urllib(payload, body)
            except Exception as e2:
                logger.error(f"Webhook dispatch failed (urllib fallback): {e2}")

    async def _fire_webhook_urllib(self, payload: dict, body: bytes) -> None:
        """Fallback webhook using urllib in a thread executor."""
        import urllib.request
        import urllib.error

        loop = asyncio.get_event_loop()

        def _post():
            req = urllib.request.Request(
                self._webhook_url,  # type: ignore
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status
            except urllib.error.HTTPError as e:
                logger.warning(f"Webhook HTTP error {e.code}: {self._webhook_url}")
                return e.code

        try:
            status = await loop.run_in_executor(None, _post)
            if status and status >= 400:
                logger.warning(f"Webhook returned status {status}")
        except Exception as e:
            logger.error(f"Webhook urllib dispatch failed: {e}")

    # ── Helpers ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return notification service statistics."""
        return {
            "webhook_url": self._webhook_url,
            "local_callbacks_count": len(self._local_callbacks),
            "event_counts": dict(self._event_counts),
            "errors_count": len(self._errors),
        }

    def reset(self) -> None:
        """Clear all callbacks and stats (useful for tests)."""
        self._local_callbacks.clear()
        self._event_counts.clear()
        self._errors.clear()
