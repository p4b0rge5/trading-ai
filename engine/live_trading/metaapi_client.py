"""
MetaApi.cloud connection wrapper.

Provides a unified interface to:
  - WebSocket: subscribe to ticks, account updates, trade/position updates
  - REST: fetch historical bars, submit orders, close trades, manage accounts
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from metaapi_cloud_sdk import MetaApi

logger = logging.getLogger(__name__)


class MetaApiClient:
    """
    Wraps the official metaapi-cloud-sdk MetaApi client.
    
    Manages the WebSocket lifecycle and exposes convenience methods for
    common trading operations.
    
    Usage:
        client = MetaApiClient(api_token="...", account_id=123456)
        client.on("tradeTickUpdate", lambda msg: print(msg.payload.bid))
        client.start()  # starts WebSocket listener
        # ... use client.buy(), client.close_trade(), etc.
        await client.stop()
    """

    WS_URL = "wss://sockc3.metaapi.cloud/api/ws"

    def __init__(self, api_token: str, account_id: int):
        self.api_token = api_token
        self.account_id = account_id
        self._metaapi = MetaApi(token=api_token, realTimeApiUrl=self.WS_URL)
        self._handlers: dict[str, list[Callable]] = {}
        self._task: asyncio.Task | None = None
        self._connected = False
        self._account_info: dict = {}

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        """Connect WebSocket and register for account events."""
        if self._connected:
            return

        logger.info(f"Connecting to MetaApi — account {self.account_id}")
        try:
            await self._metaapi.login()
            self._connected = True

            # Register for account
            await self._metaapi.register_for_account(self.account_id)

            # Store account info callback
            self.on("accountUpdate", self._on_account_update)

            # Start WebSocket listener in background
            self._task = asyncio.create_task(self._listen())
            logger.info("MetaApi WebSocket connected")
        except Exception as e:
            logger.error(f"MetaApi connection failed: {e}")
            self._connected = False
            raise

    async def stop(self):
        """Disconnect WebSocket and release resources."""
        self._connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        try:
            await self._metaapi.logout()
        except Exception:
            pass
        logger.info("MetaApi disconnected")

    async def _listen(self):
        """Main WebSocket listener loop with auto-reconnect."""
        max_backoff = 30
        backoff = 1

        while self._connected:
            try:
                await self._metaapi.stream(on_data=self._on_message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._connected:
                    break  # Intentional stop
                logger.warning(f"MetaApi WS error: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

                try:
                    await self._metaapi.reconnect()
                    await self._metaapi.register_for_account(self.account_id)
                    backoff = 1
                except Exception as e2:
                    logger.error(f"Reconnect failed: {e2}")

    def _on_message(self, message: Any):
        """Dispatch incoming WebSocket messages to registered handlers."""
        try:
            action = message.action if hasattr(message, 'action') else message.get('action', '')
            for handler in self._handlers.get(action, []):
                try:
                    handler(message)
                except Exception as e:
                    logger.error(f"Handler error for {action}: {e}")
        except Exception:
            pass

    def _on_account_update(self, message: Any):
        """Store account info for status queries."""
        try:
            payload = message.payload if hasattr(message, 'payload') else message
            if hasattr(payload, 'to_dict'):
                self._account_info = payload.to_dict()
            else:
                self._account_info = payload if isinstance(payload, dict) else {}
        except Exception:
            pass

    # ── Event Registration ────────────────────────────────────────────

    def on(self, event: str, handler: Callable):
        """Register a handler for a WebSocket event."""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    # ── Trading Operations ─────────────────────────────────────────────

    async def subscribe_symbol(self, symbol: str):
        """Subscribe to ticks for a specific symbol."""
        logger.info(f"Subscribing to symbol: {symbol}")
        await self._metaapi.register_for_symbol(self.account_id, symbol)

    async def buy(self, symbol: str, volume: float, price: float | None = None,
                  sl: float | None = None, tp: float | None = None, comment: str = "") -> int:
        """Open a BUY trade."""
        if price is None:
            price = await self._get_ask(symbol)

        position = await self._metaapi.open_long(
            accountId=self.account_id,
            symbol=symbol,
            volume=volume,
            price=price,
            sl=sl,
            tp=tp,
            comment=comment,
        )
        trade_id = position.tradeId if hasattr(position, 'tradeId') else position.get('tradeId', 0)
        logger.info(f"BUY {symbol} {volume}@{price} (id={trade_id})")
        return trade_id

    async def sell(self, symbol: str, volume: float, price: float | None = None,
                   sl: float | None = None, tp: float | None = None, comment: str = "") -> int:
        """Open a SELL trade."""
        if price is None:
            price = await self._get_bid(symbol)

        position = await self._metaapi.open_short(
            accountId=self.account_id,
            symbol=symbol,
            volume=volume,
            price=price,
            sl=sl,
            tp=tp,
            comment=comment,
        )
        trade_id = position.tradeId if hasattr(position, 'tradeId') else position.get('tradeId', 0)
        logger.info(f"SELL {symbol} {volume}@{price} (id={trade_id})")
        return trade_id

    async def close_trade(self, trade_id: int) -> bool:
        """Close an open trade by its MetaApi trade ID."""
        try:
            await self._metaapi.close_trade_by_trade_id(
                accountId=self.account_id, tradeId=trade_id
            )
            logger.info(f"Closed trade {trade_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to close trade {trade_id}: {e}")
            return False

    async def close_all_trades(self) -> int:
        """Close all open trades. Returns count of closed trades."""
        positions = await self._metaapi.get_positions(accountId=self.account_id)
        closed = 0
        for pos in (positions or []):
            pid = pos.positionId if hasattr(pos, 'positionId') else pos.get('positionId')
            tid = pos.tradeId if hasattr(pos, 'tradeId') else pos.get('tradeId')
            try:
                await self._metaapi.close_trade_by_trade_id(
                    accountId=self.account_id, tradeId=tid
                )
                closed += 1
            except Exception as e:
                logger.error(f"Failed to close position {pid}: {e}")
        return closed

    # ── Data Operations ────────────────────────────────────────────────

    async def get_historical_bars(self, symbol: str, timeframe: str, count: int = 500) -> list[dict]:
        """
        Fetch historical OHLCV bars from MetaApi REST API.
        
        Returns list of dicts: {time, open, high, low, close, volume}
        """
        try:
            history = await self._metaapi.get_bars(
                accountId=self.account_id, symbol=symbol, tf=timeframe, limit=count
            )
            if hasattr(history, 'bars'):
                bars = history.bars
            else:
                bars = history.get('bars', []) if isinstance(history, dict) else []

            result = []
            for bar in (bars or []):
                if hasattr(bar, 'to_dict'):
                    bar = bar.to_dict()
                result.append({
                    'time': bar.get('time', bar.get('openTime', 0)),
                    'open': bar.get('open', 0),
                    'high': bar.get('high', 0),
                    'low': bar.get('low', 0),
                    'close': bar.get('close', 0),
                    'volume': bar.get('volume', 0),
                })
            return result
        except Exception as e:
            logger.warning(f"Failed to fetch historical bars: {e}")
            return []

    async def get_open_positions(self) -> list[dict]:
        """Get all open positions."""
        try:
            positions = await self._metaapi.get_positions(accountId=self.account_id)
            if hasattr(positions, '__iter__'):
                result = []
                for pos in positions:
                    if hasattr(pos, 'to_dict'):
                        result.append(pos.to_dict())
                    elif isinstance(pos, dict):
                        result.append(pos)
                return result
            return []
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def get_account_info(self) -> dict:
        """Get current account balance, equity, etc."""
        try:
            info = await self._metaapi.get_account(accountId=self.account_id)
            if hasattr(info, 'to_dict'):
                return info.to_dict()
            return info if isinstance(info, dict) else {}
        except Exception:
            return self._account_info

    async def _get_ask(self, symbol: str) -> float:
        """Get current ask price for a symbol."""
        try:
            info = await self._metaapi.get_symbol_info(self.account_id, symbol)
            if hasattr(info, 'ask'):
                return float(info.ask)
            if isinstance(info, dict):
                return float(info.get('ask', 0))
        except Exception:
            pass
        return 0.0

    async def _get_bid(self, symbol: str) -> float:
        """Get current bid price for a symbol."""
        try:
            info = await self._metaapi.get_symbol_info(self.account_id, symbol)
            if hasattr(info, 'bid'):
                return float(info.bid)
            if isinstance(info, dict):
                return float(info.get('bid', 0))
        except Exception:
            pass
        return 0.0
