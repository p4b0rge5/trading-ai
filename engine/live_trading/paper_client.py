"""
Paper Trading Client — simulates live trading with real market data from yfinance.

Provides the same interface as MetaApiClient but:
  - Uses yfinance for real-time price data (polling)
  - Simulates order execution in memory (no real money)
  - Tracks P&L, positions, and trade history
  - Emits the same events (tick, candle, position, account_update) so the
    LiveEngine works unchanged

Usage:
    client = PaperTradingClient(initial_balance=10000)
    await client.connect("PAPER")       # connects to yfinance
    client.on("tick", lambda t: print(t["bid"]))
    await client.buy("EURUSD", 0.01)
    await client.stop()
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Awaitable, Optional

from engine.data_fetcher import resolve_symbol, fetch_ohlcv, get_current_price

logger = logging.getLogger(__name__)

# ── Trade action constants (compatible with MetaApiClient) ──────────────
ACTION_BUY = "TRADE_ACTION_TYPE_BUY"
ACTION_SELL = "TRADE_ACTION_TYPE_SELL"
ACTION_CLOSE = "TRADE_ACTION_TYPE_CLOSE"

# ── Timeframe mapping ──────────────────────────────────────────────────
TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
}


# ── Simulated Trade ────────────────────────────────────────────────────

@dataclass
class PaperPosition:
    """A paper trading position."""
    trade_id: str
    symbol: str
    side: str  # "buy" / "sell"
    entry_price: float
    volume: float
    sl: Optional[float]
    tp: Optional[float]
    entry_time: datetime
    reason: str = ""
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit: float = 0.0
    closed: bool = False


# ── Client ──────────────────────────────────────────────────────────────

class PaperTradingClient:
    """
    Paper trading client with real market data from yfinance.

    Simulates a MetaApi-connected MT5 account. Trades are tracked in memory
    with realistic fill prices, margin, and P&L calculations.
    """

    def __init__(self, api_token: str = "", initial_balance: float = 10000):
        self.api_token = api_token
        self._connected = False
        self._account_id = "PAPER"
        self._instance_number = 0
        self._region = "us-east-1"

        # Account state
        self._balance = initial_balance
        self._equity = initial_balance
        self._margin = 0.0
        self._free_margin = initial_balance
        self._margin_level = 0.0
        self._float_profit = 0.0

        # Positions
        self._positions: dict[str, PaperPosition] = {}
        self._closed_trades: list[PaperPosition] = []
        self._daily_deals: list[dict] = []

        # Tick cache per symbol
        self._tick_cache: dict[str, dict] = {}
        self._candle_cache: dict[str, dict] = {}

        # Event handlers
        self._handlers: dict[str, list[Callable]] = {}

        # Polling state
        self._poll_task: asyncio.Task | None = None
        self._poll_interval = 2.0  # seconds
        self._watched_symbols: set = set()

        # Spread simulation (typical forex spread in price units)
        self._spreads: dict[str, float] = {
            "EURUSD": 0.00012,
            "GBPUSD": 0.00018,
            "USDJPY": 0.015,
            "AUDUSD": 0.00016,
            "USDCAD": 0.00018,
            "NZDUSD": 0.00022,
            "EURGBP": 0.00014,
            "EURJPY": 0.018,
            "GBPJPY": 0.028,
            "BTCUSD": 5.0,
            "ETHUSD": 0.5,
        }

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

    # ── Lifecycle ────────────────────────────────────────────────────

    async def connect(self, account_id: str = "PAPER") -> bool:
        """Initialize paper trading."""
        self._account_id = str(account_id)
        self._connected = True

        logger.info(
            f"✅ Paper Trading initialized: balance=${self._balance:.2f} | "
            f"Real market data via yfinance | No real money at risk"
        )

        # Start background price polling
        self._start_polling()

        # Emit initial account info
        self._dispatch("account_update", self._account_info_dict())

        return True

    async def stop(self):
        """Stop price polling and clean up."""
        self._connected = False

        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

        logger.info("Paper Trading stopped")

    def _start_polling(self):
        """Start background task to poll prices for watched symbols."""
        if self._poll_task:
            return

        async def _poll_loop():
            while self._connected:
                for symbol in list(self._watched_symbols):
                    try:
                        await self._fetch_tick(symbol)
                    except Exception as e:
                        logger.debug(f"Poll error for {symbol}: {e}")
                await asyncio.sleep(self._poll_interval)

        self._poll_task = asyncio.create_task(_poll_loop())

    # ── REST: Account listing ────────────────────────────────────────

    async def get_accounts(self) -> list[dict]:
        """Return paper trading account info."""
        return [{
            "id": "PAPER",
            "name": "Paper Trading",
            "type": "DEMO",
            "server": "PaperTrade-Server",
            "login": "paper-001",
            "balance": self._balance,
            "equity": self._equity,
            "margin": self._margin,
            "freeMargin": self._free_margin,
            "marginLevel": self._margin_level,
        }]

    async def get_account_info(self, account_id: str = "PAPER") -> dict:
        """Get current account information."""
        info = self._account_info_dict()
        self._dispatch("account_update", info)
        return info

    def _account_info_dict(self) -> dict:
        """Build account info dict from current state."""
        return {
            "balance": self._balance,
            "equity": self._equity,
            "margin": self._margin,
            "freeMargin": self._free_margin,
            "marginLevel": self._margin_level,
            "floatProfit": self._float_profit,
            "leverage": 100,
            "currency": "USD",
            "server": "PaperTrade-Server",
        }

    # ── Symbols ──────────────────────────────────────────────────────

    async def get_symbols(self) -> list[str]:
        """List available trading symbols."""
        from engine.data_fetcher import KNOWN_SYMBOLS
        return KNOWN_SYMBOLS

    async def get_symbol_spec(self, symbol: str) -> dict:
        """Get symbol specification."""
        spread = self._spreads.get(symbol, 0.00015)
        return {
            "symbol": symbol,
            "tradeContractSize": 100000,
            "tradeCalcMode": "BY_PRICE",
            "tradeStopsLevel": 0,
            "tradeFreezeLevel": 0,
            "priceChange": 0.00001,
            "spread": spread,
            "digits": 5 if "=" in resolve_symbol(symbol) else 2,
        }

    # ── Market data ──────────────────────────────────────────────────

    async def get_tick(self, symbol: str) -> dict | None:
        """Get latest tick for a symbol. Starts watching if not already."""
        self._watched_symbols.add(symbol)
        return await self._fetch_tick(symbol)

    async def _fetch_tick(self, symbol: str) -> dict | None:
        """Fetch current price from yfinance."""
        yf_symbol = resolve_symbol(symbol)
        spread = self._spreads.get(symbol, 0.00015)

        try:
            import yfinance as yf
            ticker = yf.Ticker(yf_symbol)
            info = ticker.fast_info

            current = getattr(info, 'last_price', None) or \
                      getattr(info, 'regularMarketPrice', None) or \
                      get_current_price(symbol)

            if current is None:
                # Fallback: fetch last candle
                df = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: fetch_ohlcv(symbol, "1m", n_bars=1, use_real=True)
                )
                if not df.empty:
                    current = float(df.iloc[-1]["close"])
                else:
                    return None

            current = float(current)
            half_spread = spread / 2
            bid = current - half_spread
            ask = current + half_spread

            tick = {
                "symbol": symbol,
                "bid": round(bid, 8),
                "ask": round(ask, 8),
                "last": round(current, 8),
                "time": int(datetime.utcnow().timestamp() * 1000),
            }

            self._tick_cache[symbol] = tick
            self._dispatch("tick", tick)
            self._dispatch("price_update", {
                "symbol": symbol,
                "bid": tick["bid"],
                "ask": tick["ask"],
                "time": tick["time"],
            })

            # Update P&L for open positions in this symbol
            self._update_pnl()

            return tick

        except Exception as e:
            logger.debug(f"Tick fetch failed for {yf_symbol}: {e}")
            return self._tick_cache.get(symbol)

    async def get_candle(self, symbol: str, timeframe: str = "1h") -> dict | None:
        """Get current forming candle."""
        self._watched_symbols.add(symbol)

        try:
            df = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fetch_ohlcv(symbol, timeframe, n_bars=5, use_real=True)
            )
            if df.empty:
                return None

            row = df.iloc[-1]
            candle = {
                "symbol": symbol,
                "time": int(row["timestamp"].timestamp() * 1000) if hasattr(row["timestamp"], "timestamp") else int(pd.Timestamp(row["timestamp"]).timestamp() * 1000),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            }

            self._candle_cache[symbol] = candle
            self._dispatch("candle", candle)
            return candle

        except Exception as e:
            logger.debug(f"Candle fetch failed for {symbol}: {e}")
            return self._candle_cache.get(symbol)

    async def subscribe_candles(self, symbol: str, timeframe: str = "1m") -> bool:
        """Subscribe to candle updates (marks symbol for polling)."""
        self._watched_symbols.add(symbol)
        logger.info(f"Paper Trading: watching {symbol} {timeframe}")

        # Fetch initial candle
        await self.get_candle(symbol, timeframe)
        return True

    async def get_price(self, symbol: str) -> dict | None:
        """Get current bid/ask price."""
        return await self.get_tick(symbol)

    # ── Historical data ──────────────────────────────────────────────

    async def get_history_deals(
        self, symbol: str = "", count: int = 1000
    ) -> list[dict]:
        """Get historical deals (closed paper trades)."""
        if symbol:
            return [self._deal_dict(d) for d in self._daily_deals
                    if d.get("symbol") == symbol][:count]
        return [self._deal_dict(d) for d in self._daily_deals][:count]

    def _deal_dict(self, trade: PaperPosition) -> dict:
        return {
            "dealTicket": trade.trade_id,
            "symbol": trade.symbol,
            "type": trade.side.upper(),
            "volume": trade.volume,
            "price": trade.exit_price or trade.entry_price,
            "profit": trade.profit,
            "time": int(trade.exit_time.timestamp() * 1000) if trade.exit_time else 0,
        }

    # ── Positions & Orders ───────────────────────────────────────────

    async def get_positions(self) -> list[dict]:
        """Get all open positions."""
        return [self._position_dict(p) for p in self._positions.values()]

    def _position_dict(self, pos: PaperPosition) -> dict:
        current_price = self._tick_cache.get(pos.symbol, {})
        price = current_price.get("bid", pos.entry_price)
        unrealized = self._calc_unrealized_pnl(pos, price)

        return {
            "positionId": pos.trade_id,
            "symbol": pos.symbol,
            "type": pos.side.upper(),
            "volume": pos.volume,
            "openPrice": pos.entry_price,
            "currentPrice": price,
            "profit": round(unrealized, 2),
            "sl": pos.sl,
            "tp": pos.tp,
            "time": int(pos.entry_time.timestamp() * 1000),
            "comment": pos.reason,
        }

    async def get_orders(self) -> list[dict]:
        """Paper trading has no pending orders — returns empty."""
        return []

    async def close_position(self, position_id: str) -> dict | None:
        """Close a paper trading position."""
        if position_id not in self._positions:
            return None

        pos = self._positions[position_id]
        current = self._tick_cache.get(pos.symbol, {})
        exit_price = current.get("bid", pos.entry_price)

        pos.exit_price = exit_price
        pos.exit_time = datetime.utcnow()
        pos.profit = self._calc_unrealized_pnl(pos, exit_price)
        pos.closed = True

        # Return margin
        pos_margin = pos.volume * 10.0  # Simplified margin
        self._margin -= pos_margin
        self._balance += pos.profit
        self._free_margin = self._equity - self._margin
        self._update_margin_level()

        del self._positions[position_id]
        self._closed_trades.append(pos)
        self._daily_deals.append({
            "symbol": pos.symbol,
            "type": pos.side,
            "volume": pos.volume,
            "price": exit_price,
            "profit": pos.profit,
            "time": pos.exit_time,
        })

        self._update_pnl()
        self._dispatch("position", self._position_dict(pos))
        self._dispatch("position_removed", position_id)
        self._dispatch("deal", self._deal_dict(pos))

        logger.info(
            f"Paper Trade closed: {pos.symbol} {pos.side} "
            f"@ {exit_price:.5f} → P&L: ${pos.profit:.2f}"
        )

        return {
            "positionId": position_id,
            "price": exit_price,
            "profit": round(pos.profit, 2),
        }

    # ── Trading ──────────────────────────────────────────────────────

    async def buy(self, symbol: str, volume: float,
                  sl: float = 0, tp: float = 0,
                  comment: str = "") -> dict | None:
        """Place a paper BUY order."""
        return await self._trade(symbol, volume, "buy", sl, tp, comment)

    async def sell(self, symbol: str, volume: float,
                   sl: float = 0, tp: float = 0,
                   comment: str = "") -> dict | None:
        """Place a paper SELL order."""
        return await self._trade(symbol, volume, "sell", sl, tp, comment)

    async def _trade(
        self, symbol: str, volume: float, side: str,
        sl: float = 0, tp: float = 0, comment: str = ""
    ) -> dict | None:
        """Execute a paper trade."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Get current price
        tick = await self.get_tick(symbol)
        if not tick:
            logger.warning(f"Cannot trade {symbol}: no price data available")
            return None

        # Fill price: buy at ask, sell at bid
        fill_price = tick["ask"] if side == "buy" else tick["bid"]
        entry_time = datetime.utcnow()

        # Calculate margin (simplified: $10 per lot)
        margin = volume * 10.0
        if margin > self._free_margin:
            logger.warning(
                f"Insufficient margin for {volume} lots of {symbol}: "
                f"need ${margin:.2f}, have ${self._free_margin:.2f}"
            )
            return None

        # Create position
        trade_id = f"paper-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        pos = PaperPosition(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            volume=volume,
            sl=sl if sl and sl > 0 else None,
            tp=tp if tp and tp > 0 else None,
            entry_time=entry_time,
            reason=comment,
        )

        # Deduct margin
        self._margin += margin
        self._free_margin = self._equity - self._margin
        self._update_margin_level()

        self._positions[trade_id] = pos
        self._watched_symbols.add(symbol)

        self._dispatch("position", self._position_dict(pos))

        logger.info(
            f"Paper Trade opened: {side.upper()} {volume} {symbol} "
            f"@ {fill_price:.5f} (id={trade_id}, sl={sl}, tp={tp})"
        )

        return {
            "tradeId": trade_id,
            "positionId": trade_id,
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "price": fill_price,
        }

    async def close_all_positions(self) -> list[dict]:
        """Close all open positions."""
        results = []
        ids = list(self._positions.keys())
        for tid in ids:
            r = await self.close_position(tid)
            if r:
                results.append(r)
        return results

    # ── P&L Updates ──────────────────────────────────────────────────

    def _calc_unrealized_pnl(self, pos: PaperPosition, current_price: float) -> float:
        """Calculate unrealized P&L for a position."""
        diff = current_price - pos.entry_price
        contract_size = 100000  # Standard lot

        if pos.side == "buy":
            return diff * pos.volume * contract_size
        else:
            return -diff * pos.volume * contract_size

    def _update_pnl(self):
        """Recalculate floating P&L and equity."""
        total_float = 0.0
        for pos in self._positions.values():
            tick = self._tick_cache.get(pos.symbol, {})
            price = tick.get("bid", pos.entry_price)
            total_float += self._calc_unrealized_pnl(pos, price)

        self._float_profit = total_float
        self._equity = self._balance + total_float
        self._free_margin = self._equity - self._margin
        self._update_margin_level()

    def _update_margin_level(self):
        """Update margin level percentage."""
        if self._margin > 0:
            self._margin_level = (self._equity / self._margin) * 100
        else:
            self._margin_level = 0.0

    def _check_sl_tp(self):
        """Check if any open position hit SL or TP. Call from polling loop."""
        for pos in list(self._positions.values()):
            tick = self._tick_cache.get(pos.symbol, {})
            if not tick:
                continue
            price = tick["bid"]

            if pos.side == "buy":
                if pos.sl and price <= pos.sl:
                    asyncio.create_task(self.close_position(pos.trade_id))
                elif pos.tp and price >= pos.tp:
                    asyncio.create_task(self.close_position(pos.trade_id))
            else:  # sell
                if pos.sl and price >= pos.sl:
                    asyncio.create_task(self.close_position(pos.trade_id))
                elif pos.tp and price <= pos.tp:
                    asyncio.create_task(self.close_position(pos.trade_id))

    # ── Properties ───────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def account_info(self) -> dict:
        return self._account_info_dict()

    # ── Tick cache ───────────────────────────────────────────────────

    def get_cached_tick(self, symbol: str) -> dict | None:
        """Get last known tick from cache (no network call)."""
        return self._tick_cache.get(symbol)
