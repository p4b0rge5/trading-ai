"""
MetaApi.cloud v29 SDK wrapper.

Provides:
  - REST account listing (metatrader_account_api)
  - WebSocket connection with SynchronizationListener for ticks, candles,
    positions, deals, account info updates
  - Order execution via ws.trade()
  - Historical data via REST (candles, ticks, history orders)
  - Auto-reconnect with exponential backoff
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Awaitable

from metaapi_cloud_sdk import MetaApi, SynchronizationListener
from metaapi_cloud_sdk.metaapi.models import (
    MetatraderTrade,
    MetatraderTick,
    MetatraderCandle,
    MetatraderPosition,
    MetatraderDeal,
    MetatraderOrder,
    MetatraderAccountInformation,
    MetatraderSymbolPrice,
    MarketDataSubscription,
)

logger = logging.getLogger(__name__)

# ── Trade action constants ──────────────────────────────────────────────
ACTION_BUY = "TRADE_ACTION_TYPE_BUY"
ACTION_SELL = "TRADE_ACTION_TYPE_SELL"
ACTION_CLOSE = "TRADE_ACTION_TYPE_CLOSE"

# ── Timeframe mapping ──────────────────────────────────────────────────
TIMEFRAME_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "2h": "H2", "4h": "H4", "1d": "D1", "1w": "W1",
}


# ── Synchronization Listener wrapper ────────────────────────────────────

class _SyncListener(SynchronizationListener):
    """Wraps SynchronizationListener to call our own callbacks."""

    def __init__(self, account_id: str, client: "MetaApiClient"):
        super().__init__()
        self.account_id = account_id
        self._client = client

    # Account info updates (equity, balance, margin)
    def on_account_information_updated(self, instance_index: str, account_information: MetatraderAccountInformation):
        self._client._dispatch("account_update", dict(account_information))

    def on_symbol_price_updated(self, instance_index: str, price: MetatraderSymbolPrice):
        self._client._dispatch("price_update", dict(price))

    def on_ticks_updated(self, instance_index: str, ticks, **kwargs):
        for t in ticks:
            self._client._dispatch("tick", dict(t))

    def on_candles_updated(self, instance_index: str, candles, **kwargs):
        for c in candles:
            self._client._dispatch("candle", dict(c))

    def on_deal_added(self, instance_index: str, deal: MetatraderDeal):
        self._client._dispatch("deal", dict(deal))

    def on_position_updated(self, instance_index: str, position: MetatraderPosition):
        self._client._dispatch("position", dict(position))

    def on_positions_updated(self, instance_index: str, positions, removed_positions_ids=None):
        for p in positions:
            self._client._dispatch("position", dict(p))
        if removed_positions_ids:
            for pid in removed_positions_ids:
                self._client._dispatch("position_removed", pid)

    def on_positions_synchronized(self, instance_index: str, synchronization_id: str):
        self._client._dispatch("positions_synced", synchronization_id)

    def on_pending_order_updated(self, instance_index: str, order: MetatraderOrder):
        self._client._dispatch("order", dict(order))

    def on_pending_order_completed(self, instance_index: str, order_id: str):
        self._client._dispatch("order_completed", order_id)

    def on_connected(self, instance_index: str, replicas: int):
        self._client._connected = True
        logger.info(f"✅ Connected to account {self.account_id} (instance {instance_index})")

    def on_disconnected(self, instance_index: str):
        self._client._connected = False
        logger.warning(f"⚠️ Disconnected from account {self.account_id}")

    def on_error(self, error):
        logger.error(f"❌ SyncListener error: {error}")


# ── Client ──────────────────────────────────────────────────────────────

class MetaApiClient:
    """
    Unified MetaApi.cloud v29 client.

    Manages WebSocket connection, data subscriptions, order execution,
    and account information retrieval.

    Usage:
        client = MetaApiClient(api_token="...")
        accounts = await client.get_accounts()   # REST list
        await client.connect(account_id)          # WebSocket + sync
        client.on("tick", lambda t: print(t["bid"]))
        await client.buy(account_id, "EURUSD", 0.01)
        await client.stop()
    """

    def __init__(self, api_token: str):
        self.api_token = api_token
        self._metaapi = MetaApi(token=api_token)
        self._ws = self._metaapi._metaapi_websocket_client
        self._sync_listener: _SyncListener | None = None
        self._connected = False
        self._account_id: str = ""
        self._instance_number: int = 0
        self._region: str = ""
        self._handlers: dict[str, list[Callable]] = {}
        self._reconnect_delay = 2
        self._reconnect_max = 60
        self._reconnect_task: asyncio.Task | None = None
        self._account_cache: dict = {}
        self._tick_cache: dict[str, dict] = {}   # symbol → latest tick

    # ── Event system ─────────────────────────────────────────────────

    def on(self, event: str, callback: Callable):
        """Register a callback for an event."""
        self._handlers.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable):
        """Remove a callback."""
        self._handlers.get(event, []).remove(callback)

    def _dispatch(self, event: str, data: dict):
        """Fire all callbacks for an event."""
        for cb in self._handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(data))
                else:
                    cb(data)
            except Exception as e:
                logger.error(f"Handler error for {event}: {e}")

    # ── REST: Account listing ────────────────────────────────────────

    async def get_accounts(self) -> list[dict]:
        """List all accounts via MetaApi REST API.

        Note: MetaApi dev/test tokens may return 401 on the accounts endpoint
        if no accounts have been deployed through the MetaApi dashboard yet.
        In that case, returns empty list with a warning logged.
        """
        try:
            accounts_list = await self._metaapi.metatrader_account_api.get_accounts_with_classic_scroll_pagination()
        except Exception as e:
            err_msg = str(e).lower()
            if '401' in err_msg or 'unauthorized' in err_msg:
                logger.warning(
                    "MetaApi returned 401 for account listing. "
                    "This usually means no MetaTrader accounts are deployed yet. "
                    "Visit https://metaapi.cloud to create a demo account first."
                )
                return []
            raise  # Re-raise unexpected errors

        result = []
        for a in accounts_list:
            info = await self.get_account_info(str(a.id))
            result.append({
                "id": a.id,
                "name": getattr(a, "name", "N/A"),
                "type": getattr(a, "type", "DEMO"),
                "server": getattr(a, "server", ""),
                "login": getattr(a, "login", ""),
                "balance": info.get("balance", 0),
                "equity": info.get("equity", 0),
                "margin": info.get("margin", 0),
                "freeMargin": info.get("freeMargin", 0),
                "marginLevel": info.get("marginLevel", 0),
            })
        return result

    async def get_account_info(self, account_id: str) -> dict:
        """Get current account information (balance, equity, margin)."""
        try:
            info = await self._ws.get_account_information(account_id)
            result = dict(info)
            self._account_cache = result
            return result
        except Exception as e:
            logger.error(f"get_account_info failed: {e}")
            return self._account_cache

    # ── Lifecycle ────────────────────────────────────────────────────

    async def connect(self, account_id: str) -> bool:
        """Connect WebSocket for a given account."""
        self._account_id = str(account_id)
        logger.info(f"Connecting to MetaApi — account {account_id}")

        try:
            # Get account region
            self._region = await self._ws.get_account_region(self._account_id)
            logger.info(f"Account region: {self._region}")

            # Connect WebSocket (instance 0 = primary)
            self._instance_number = 0
            await self._ws.connect(self._instance_number, self._region)

            # Subscribe to account
            await self._ws.ensure_subscribe(self._account_id, self._instance_number)

            # Register sync listener
            self._sync_listener = _SyncListener(self._account_id, self)
            self._ws.add_synchronization_listener(self._account_id, self._sync_listener)

            # Cache account info
            await self.get_account_info(self._account_id)

            logger.info(f"✅ Connected to account {self._account_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            self._start_reconnect()
            return False

    async def stop(self):
        """Disconnect and clean up."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        self._connected = False

        try:
            if self._sync_listener:
                self._ws.remove_all_listeners(self._account_id)
            await self._ws.close()
            await self._metaapi.close()
            logger.info("MetaApi connection closed")
        except Exception as e:
            logger.warning(f"Error during shutdown: {e}")

    def _start_reconnect(self):
        """Start exponential backoff reconnection loop."""
        if self._reconnect_task:
            return
        self._reconnect_delay = 2

        async def _reconnect_loop():
            while True:
                await asyncio.sleep(self._reconnect_delay)
                logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                try:
                    await self.connect(self._account_id)
                    self._reconnect_delay = 2
                    break
                except Exception:
                    self._reconnect_delay = min(self._reconnect_delay * 2, self._reconnect_max)

        self._reconnect_task = asyncio.create_task(_reconnect_loop())

    # ── Symbols ──────────────────────────────────────────────────────

    async def get_symbols(self) -> list[str]:
        """List available trading symbols."""
        if not self._account_id:
            return []
        try:
            return await self._ws.get_symbols(self._account_id)
        except Exception as e:
            logger.error(f"get_symbols failed: {e}")
            return []

    async def get_symbol_spec(self, symbol: str) -> dict:
        """Get symbol specification (spread, tick value, contract size)."""
        if not self._account_id:
            return {}
        try:
            spec = await self._ws.get_symbol_specification(self._account_id, symbol)
            return dict(spec)
        except Exception as e:
            logger.error(f"get_symbol_spec failed for {symbol}: {e}")
            return {}

    # ── Market data ──────────────────────────────────────────────────

    async def get_tick(self, symbol: str) -> dict | None:
        """Get latest tick for a symbol."""
        if not self._account_id:
            return self._tick_cache.get(symbol)
        try:
            tick = await self._ws.get_tick(self._account_id, symbol, keep_subscription=True)
            t_dict = dict(tick)
            self._tick_cache[symbol] = t_dict
            return t_dict
        except Exception as e:
            logger.error(f"get_tick failed for {symbol}: {e}")
            return self._tick_cache.get(symbol)

    async def get_candle(self, symbol: str, timeframe: str = "1h") -> dict | None:
        """Get current forming candle."""
        if not self._account_id:
            return None
        tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        try:
            candle = await self._ws.get_candle(self._account_id, symbol, tf, keep_subscription=True)
            return dict(candle)
        except Exception as e:
            logger.error(f"get_candle failed for {symbol} {timeframe}: {e}")
            return None

    async def subscribe_candles(self, symbol: str, timeframe: str = "1m") -> bool:
        """Subscribe to candle updates for real-time bar building."""
        if not self._account_id:
            return False
        tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        try:
            subs = [{"symbol": symbol, "timeframe": tf}]
            await self._ws.refresh_market_data_subscriptions(
                self._account_id, self._instance_number, subs
            )
            logger.info(f"Subscribed to {symbol} {tf} candles")
            return True
        except Exception as e:
            logger.error(f"subscribe_candles failed: {e}")
            return False

    async def get_price(self, symbol: str) -> dict | None:
        """Get current bid/ask price."""
        if not self._account_id:
            return None
        try:
            price = await self._ws.get_symbol_price(self._account_id, symbol, keep_subscription=True)
            return dict(price)
        except Exception as e:
            logger.error(f"get_price failed for {symbol}: {e}")
            return None

    # ── Positions & Orders ───────────────────────────────────────────

    async def get_positions(self) -> list[dict]:
        """Get all open positions."""
        if not self._account_id:
            return []
        try:
            positions = await self._ws.get_positions(self._account_id)
            return [dict(p) for p in positions]
        except Exception as e:
            logger.error(f"get_positions failed: {e}")
            return []

    async def get_orders(self) -> list[dict]:
        """Get all pending orders."""
        if not self._account_id:
            return []
        try:
            orders = await self._ws.get_orders(self._account_id)
            return [dict(o) for o in orders]
        except Exception as e:
            logger.error(f"get_orders failed: {e}")
            return []

    async def close_position(self, position_id: str) -> dict | None:
        """Close a position by its ID."""
        if not self._account_id:
            return None
        try:
            trade = MetatraderTrade({
                "action": ACTION_CLOSE,
                "positionId": str(position_id),
            })
            result = await self._ws.trade(self._account_id, trade)
            return dict(result)
        except Exception as e:
            logger.error(f"close_position failed for {position_id}: {e}")
            return None

    # ── Trading ──────────────────────────────────────────────────────

    async def buy(self, symbol: str, volume: float,
                  sl: float = 0, tp: float = 0,
                  comment: str = "") -> dict | None:
        """Place a market BUY order."""
        return await self._trade(
            symbol, volume, ACTION_BUY, sl=sl, tp=tp, comment=comment
        )

    async def sell(self, symbol: str, volume: float,
                   sl: float = 0, tp: float = 0,
                   comment: str = "") -> dict | None:
        """Place a market SELL order."""
        return await self._trade(
            symbol, volume, ACTION_SELL, sl=sl, tp=tp, comment=comment
        )

    async def _trade(self, symbol: str, volume: float,
                     action: str, sl: float = 0, tp: float = 0,
                     comment: str = "") -> dict | None:
        """Internal trade execution."""
        if not self._account_id:
            raise RuntimeError("Not connected. Call connect() first.")

        trade_data = {
            "action": action,
            "symbol": symbol,
            "volume": volume,
        }

        if sl > 0:
            trade_data["sl"] = sl
        if tp > 0:
            trade_data["tp"] = tp
        if comment:
            trade_data["comment"] = comment

        trade = MetatraderTrade(trade_data)
        try:
            result = await self._ws.trade(self._account_id, trade)
            logger.info(f"Trade executed: {action} {volume} {symbol} → {result}")
            return dict(result)
        except Exception as e:
            logger.error(f"Trade failed: {e}")
            return None

    async def close_all_positions(self) -> list[dict]:
        """Close all open positions."""
        results = []
        positions = await self.get_positions()
        for p in positions:
            r = await self.close_position(str(p.get("positionId", p.get("id"))))
            if r:
                results.append(r)
        return results

    # ── Historical data ──────────────────────────────────────────────

    async def get_history_deals(
        self, symbol: str = "", count: int = 1000
    ) -> list[dict]:
        """Get historical deals (closed trades)."""
        if not self._account_id:
            return []
        from datetime import datetime, timedelta
        end = datetime.utcnow()
        start = end - timedelta(days=365)  # Last year
        try:
            deals = self._ws.get_deals_by_time_range(
                self._account_id, start, end, offset=0, limit=count
            )
            result = []
            for d in deals:
                d_dict = dict(d)
                if symbol and d_dict.get("symbol") != symbol:
                    continue
                result.append(d_dict)
            return result
        except Exception as e:
            logger.error(f"get_history_deals failed: {e}")
            return []

    # ── Properties ───────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def account_info(self) -> dict:
        return self._account_cache

    # ── Tick cache ───────────────────────────────────────────────────

    def get_cached_tick(self, symbol: str) -> dict | None:
        """Get last known tick from cache (no network call)."""
        return self._tick_cache.get(symbol)
