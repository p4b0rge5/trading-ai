"""
Live Engine — real-time bar builder + signal evaluation.

Pipeline:
  1. Receive ticks from MetaApi WebSocket (via SynchronizationListener)
  2. Accumulate ticks into OHLC bars matching the strategy timeframe
  3. On bar close, re-run StrategyInterpreter on accumulated history
  4. Forward new signals to OrderManager for execution
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

from engine.interpreter import StrategyInterpreter
from engine.models import StrategySpec

logger = logging.getLogger(__name__)


# Timeframe → seconds mapping
TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}


@dataclass
class LiveBar:
    """Single OHLC bar being accumulated from ticks."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    complete: bool = False


class LiveEngine:
    """
    Real-time trading engine.

    Receives ticks, builds bars, evaluates signals, executes orders.
    """

    def __init__(self, spec: StrategySpec, metaapi_client, order_manager,
                 session_id: int):
        self.spec = spec
        self.metaapi = metaapi_client
        self.order_manager = order_manager
        self.session_id = session_id

        self.interpreter = StrategyInterpreter(spec)

        # Bar state
        self._buffer: deque[LiveBar] = deque(maxlen=5000)
        self._current_bar: Optional[LiveBar] = None
        self._bar_seconds = TIMEFRAME_SECONDS.get(
            spec.timeframe.value if hasattr(spec.timeframe, 'value') else spec.timeframe, 3600
        )
        self._running = False
        self._last_signal_bar: int = -1
        self._tick_count = 0
        self._eval_lock = asyncio.Lock()
        self._stop_event: asyncio.Event | None = None

        # Signal callbacks (for frontend WebSocket)
        self._signal_callbacks: list = []

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        """Start the live engine: preload history, subscribe to candles."""
        if self._running:
            return
        self._running = True
        self._stop_event = asyncio.Event()

        # Preload historical bars for indicator warm-up
        await self._preload_history()

        # Subscribe to candle updates for real-time bar building
        tf = self.spec.timeframe.value if hasattr(self.spec.timeframe, 'value') else self.spec.timeframe
        await self.metaapi.subscribe_candles(self.spec.symbol, tf)

        # Also subscribe to tick for sub-timeframe resolution
        await self.metaapi.get_tick(self.spec.symbol)

        # Register event handlers on MetaApiClient
        self.metaapi.on("tick", self._on_tick)
        self.metaapi.on("candle", self._on_candle)
        self.metaapi.on("account_update", self._on_account_update)
        self.metaapi.on("deal", self._on_deal)
        self.metaapi.on("position", self._on_position)

        # Initial evaluation on preloaded data
        self._evaluate()

        logger.info(
            f"LiveEngine started: {self.spec.symbol} | {self.spec.timeframe} "
            f"| {len(self._buffer)} historical bars"
        )

    async def stop(self):
        """Stop engine, close all open trades."""
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        await self.order_manager.close_all()
        logger.info(f"LiveEngine stopped (session {self.session_id})")

    def on_signal(self, callback):
        """Register a callback for new signals: callback(signal_type, details)."""
        self._signal_callbacks.append(callback)

    # ── Historical Data ────────────────────────────────────────────────

    async def _preload_history(self):
        """Fetch historical data to warm up indicators.

        Strategy: use yfinance for OHLCV data (works for both paper and live modes).
        MetaApi is used as supplementary source when available.
        """
        # Primary: always load from yfinance (works in both modes)
        await self._preload_from_yfinance()

        # Secondary: try MetaApi deals for trade history reference
        try:
            history_deals = await self.metaapi.get_history_deals(
                symbol=self.spec.symbol, count=1000
            )
            if history_deals:
                logger.info(f"Preloaded {len(history_deals)} historical deals from MetaApi")
        except Exception:
            # Expected for paper mode — no MetaApi connection
            pass

    async def _preload_from_yfinance(self):
        """Load historical OHLCV data from yfinance."""
        try:
            from engine.data_fetcher import fetch_ohlcv, resolve_symbol

            tf = self.spec.timeframe.value if hasattr(self.spec.timeframe, 'value') else self.spec.timeframe

            # Map our timeframe to yfinance interval + period
            period_map = {
                "1m": "1d", "5m": "5d", "15m": "1mo", "30m": "1mo",
                "1h": "3mo", "4h": "6mo", "1d": "2y", "1w": "5y",
            }
            period = period_map.get(tf, "3mo")

            df = fetch_ohlcv(self.spec.symbol, tf, n_bars=500, use_real=True)

            if df.empty:
                logger.warning(f"No yfinance data for {self.spec.symbol}. Session will use live data only.")
                return

            for _, row in df.iterrows():
                ts = row['timestamp']
                if hasattr(ts, 'to_pydatetime'):
                    ts = ts.to_pydatetime()
                self._buffer.append(LiveBar(
                    timestamp=ts,
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=float(row.get('volume', 0)),
                    complete=True,
                ))

            logger.info(f"Preloaded {len(self._buffer)} bars from yfinance for {self.spec.symbol}")
        except Exception as e:
            logger.error(f"yfinance preload failed: {e}")

    # ── Tick Processing ────────────────────────────────────────────────

    def _on_tick(self, tick: dict):
        """Process incoming tick from MetaApi WebSocket."""
        if not self._running:
            return

        try:
            symbol = tick.get('symbol', '')
            if symbol != self.spec.symbol:
                return

            bid = tick.get('bid')
            ask = tick.get('ask')
            ts_raw = tick.get('time', 0)

            if bid is None:
                return

            # Handle timestamp: could be seconds or milliseconds
            if ts_raw > 1e12:
                ts = datetime.utcfromtimestamp(ts_raw / 1000)
            else:
                ts = datetime.utcfromtimestamp(ts_raw)

            self._process_tick(ts, float(bid), float(ask or bid))
        except Exception as e:
            logger.debug(f"Tick processing error: {e}")

    def _process_tick(self, ts: datetime, bid: float, ask: float):
        """Add tick to current bar, finalize if timeframe elapsed."""
        self._tick_count += 1

        if self._current_bar is None:
            # Start first bar
            self._current_bar = LiveBar(
                timestamp=ts, open=bid, high=ask, low=bid, close=bid,
            )
            return

        # Check if bar should finalize
        elapsed = (ts - self._current_bar.timestamp).total_seconds()

        if elapsed >= self._bar_seconds:
            # Finalize current bar
            self._current_bar.complete = True
            self._current_bar.close = bid
            self._buffer.append(self._current_bar)

            # Evaluate strategy
            self._evaluate()

            # Start new bar
            self._current_bar = LiveBar(timestamp=ts, open=bid, high=ask, low=bid, close=bid)
        else:
            # Update current bar
            self._current_bar.high = max(self._current_bar.high, ask)
            self._current_bar.low = min(self._current_bar.low, bid)
            self._current_bar.close = bid

    def _on_candle(self, candle: dict):
        """Process candle update from MetaApi — use as authoritative bar close."""
        if not self._running:
            return

        try:
            symbol = candle.get('symbol', '')
            if symbol != self.spec.symbol:
                return

            ts_raw = candle.get('time', 0)
            if ts_raw > 1e12:
                ts = datetime.utcfromtimestamp(ts_raw / 1000)
            else:
                ts = datetime.utcfromtimestamp(ts_raw)

            # Candle is authoritative — add as completed bar
            bar = LiveBar(
                timestamp=ts,
                open=float(candle.get('open', 0)),
                high=float(candle.get('high', 0)),
                low=float(candle.get('low', 0)),
                close=float(candle.get('close', 0)),
                volume=float(candle.get('volume', 0)),
                complete=True,
            )

            # If we have a forming bar, finalize it first
            if self._current_bar and not self._current_bar.complete:
                self._current_bar.complete = True
                self._current_bar.close = bar.open
                self._buffer.append(self._current_bar)

            self._buffer.append(bar)
            self._current_bar = None  # Next tick will start new bar

            # Evaluate
            self._evaluate()

        except Exception as e:
            logger.debug(f"Candle processing error: {e}")

    # ── Signal Evaluation ──────────────────────────────────────────────

    def _evaluate(self, force: bool = False):
        """Run StrategyInterpreter on accumulated bars and execute new signals.

        Args:
            force: If True, evaluate even without a new bar (e.g., when price
                   moved on the forming candle).
        """
        if len(self._buffer) < 50:
            return  # Not enough data

        # Build DataFrame from buffer
        df = pd.DataFrame([
            {
                'timestamp': b.timestamp,
                'open': b.open, 'high': b.high,
                'low': b.low, 'close': b.close,
                'volume': b.volume,
            }
            for b in self._buffer
        ])

        # Check if we have a new bar since last signal check
        current_len = len(df)
        if not force and current_len == self._last_signal_bar:
            return  # No new bar

        self._last_signal_bar = current_len

        try:
            # Use live_mode=True so the interpreter does NOT auto-close the
            # last open trade, and start_from to skip historical entries.
            # Only check the last 2 bars for new entry signals. This prevents
            # re-trading every historical signal on each re-evaluation.
            start_bar = len(df) - 2
            trades = self.interpreter.run(df, start_from=start_bar, live_mode=True)

            # Build set of existing sides that are open (prevents duplicates)
            existing_open_sides = {t.side for t in self.order_manager._open_trades.values()}

            # Filter: only trades from the most recent bars
            last_bar_ts = self._buffer[-1].timestamp

            for trade in trades:
                # Process closed trades — update order_manager
                if trade.exit_time is not None:
                    # This is a closed trade from the evaluation window.
                    # Check if we already have this trade open and need to close it.
                    for tid, ot in list(self.order_manager._open_trades.items()):
                        if ot.entry_time == trade.entry_time and ot.side == trade.side:
                            asyncio.create_task(
                                self.order_manager.close_trade(
                                    tid, trade.exit_price, trade.reason or "exit"
                                )
                            )
                            logger.info(
                                f"Trade {tid} closed via interpreter: "
                                f"{trade.side} {trade.reason} @ {trade.exit_price}"
                            )
                            existing_open_sides.discard(ot.side)
                            break
                    continue

                # Open trade — this is a new signal
                if trade.side not in existing_open_sides:
                    signal = {
                        'side': trade.side,
                        'price': trade.entry_price,
                        'reason': trade.reason,
                    }
                    asyncio.create_task(
                        self.order_manager.execute_signal(signal)
                    )
                    existing_open_sides.add(trade.side)
                    logger.info(
                        f"NEW SIGNAL: {trade.side.upper()} {self.spec.symbol} "
                        f"@ {trade.entry_price} ({trade.reason})"
                    )

                    # Notify callbacks
                    for cb in self._signal_callbacks:
                        try:
                            cb("signal", {
                                'type': trade.side,
                                'price': trade.entry_price,
                                'reason': trade.reason,
                                'time': trade.entry_time.isoformat() if trade.entry_time else None,
                            })
                        except Exception:
                            pass

        except Exception as e:
            logger.error(f"Signal evaluation error: {e}")

    # ── Continuous Candle Polling (Paper Mode Fallback) ─────────────────

    async def _poll_candles(self):
        """Periodically fetch new candles or update forming candle price.

        Two modes:
        1. If yfinance has a new completed bar → add to buffer + evaluate
        2. If no new bar → update the last bar's close with live price +
           force-evaluate (catches signals triggered by price movement on
           the forming candle)
        """
        import asyncio
        from engine.data_fetcher import resolve_symbol, get_current_price

        tf = self.spec.timeframe.value if hasattr(self.spec.timeframe, 'value') else self.spec.timeframe
        poll_interval = self._bar_seconds  # Check once per timeframe

        logger.info(f"Polling loop started: fetching new {tf} candles every {poll_interval}s")

        while self._running and not self._stop_event.is_set():
            try:
                # Sleep until stop signal or timeout
                stop_task = asyncio.create_task(self._stop_event.wait())
                sleep_task = asyncio.create_task(asyncio.sleep(poll_interval))

                done, pending = await asyncio.wait(
                    [stop_task, sleep_task], return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()

                if self._stop_event.is_set():
                    break

                new_bar = await self._fetch_latest_bar(tf)
                if new_bar:
                    # Check if it's actually newer than our last bar
                    if self._buffer and new_bar.timestamp == self._buffer[-1].timestamp:
                        # Same bar — update close price if changed
                        price_changed = abs(new_bar.close - self._buffer[-1].close) > 1e-8
                        if price_changed:
                            self._buffer[-1].close = new_bar.close
                            self._buffer[-1].high = max(self._buffer[-1].high, new_bar.close)
                            self._buffer[-1].low = min(self._buffer[-1].low, new_bar.close)
                            self._evaluate(force=True)
                            logger.info(f"Poll: updated close={new_bar.close:.5f}, buffer={len(self._buffer)}, trades={len(self.order_manager._open_trades)}")
                        else:
                            # yfinance bar same — but check if live price differs
                            # (yfinance may not have updated the forming candle yet)
                            live_price = get_current_price(self.spec.symbol)
                            if live_price:
                                live_changed = abs(live_price - self._buffer[-1].close) > 1e-8
                                if live_changed:
                                    self._buffer[-1].close = live_price
                                    self._buffer[-1].high = max(self._buffer[-1].high, live_price)
                                    self._buffer[-1].low = min(self._buffer[-1].low, live_price)
                                    self._evaluate(force=True)
                                    logger.info(f"Poll: live price update close={live_price:.5f}, trades={len(self.order_manager._open_trades)}")
                                else:
                                    logger.debug(f"Poll: no change, buffer={len(self._buffer)}")
                            else:
                                logger.debug(f"Poll: no change, buffer={len(self._buffer)}")
                    else:
                        self._add_bar_to_buffer(new_bar)
                        self._evaluate()
                        logger.info(f"Poll: NEW bar {new_bar.timestamp}, buffer={len(self._buffer)}, trades={len(self.order_manager._open_trades)}")
                else:
                    # No data from yfinance — try updating with live price
                    price = get_current_price(self.spec.symbol)
                    if price and self._buffer:
                        self._buffer[-1].close = price
                        self._buffer[-1].high = max(self._buffer[-1].high, price)
                        self._buffer[-1].low = min(self._buffer[-1].low, price)
                        self._evaluate(force=True)
                        logger.info(f"Poll: live price update close={price:.5f}, trades={len(self.order_manager._open_trades)}")
                    else:
                        logger.debug("Poll: no new data available")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poll candle error: {e}", exc_info=True)
                await asyncio.sleep(poll_interval)

    async def _fetch_latest_bar(self, timeframe: str) -> LiveBar | None:
        """Fetch the most recent completed bar from yfinance."""
        try:
            from engine.data_fetcher import fetch_ohlcv, resolve_symbol
            df = fetch_ohlcv(self.spec.symbol, timeframe, n_bars=3, use_real=True)
            if df.empty:
                return None

            row = df.iloc[-1]
            ts = row['timestamp']
            if hasattr(ts, 'to_pydatetime'):
                ts = ts.to_pydatetime()

            # Reject sample data: timestamps should be within last 24h
            from datetime import datetime, timedelta, timezone
            now = datetime.now(tz=timezone.utc)
            ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
            if abs((now - ts_naive).total_seconds()) > 86400:
                logger.debug(f"Poll: rejecting stale bar {ts} (older than 24h, likely sample data)")
                return None

            return LiveBar(
                timestamp=ts,
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row.get('volume', 0)),
                complete=True,
            )
        except Exception as e:
            logger.debug(f"Fetch latest bar error: {e}")
            return None

    def _add_bar_to_buffer(self, bar: LiveBar):
        """Add a new bar, avoiding duplicates."""
        if self._buffer and self._buffer[-1].timestamp == bar.timestamp:
            return  # Duplicate — skip

        # If we have a forming bar, finalize it first
        if self._current_bar and not self._current_bar.complete:
            self._current_bar.complete = True
            self._buffer.append(self._current_bar)

        self._buffer.append(bar)
        self._current_bar = None

    # ── MetaApi Event Handlers ─────────────────────────────────────────

    def _on_account_update(self, data: dict):
        """Update risk state from account info."""
        try:
            equity = data.get('equity', 0)
            balance = data.get('balance', 0)
            profit = data.get('profit', data.get('floatProfit', 0))
            self.order_manager.on_account_update(equity, balance, profit)
        except Exception:
            pass

    def _on_deal(self, data: dict):
        """Process deal (executed trade)."""
        try:
            ticket = str(data.get('dealTicket', data.get('ticket', '')))
            profit = data.get('profit', 0)
            if ticket:
                self.order_manager.on_trade_update(ticket, profit, 'closed')
        except Exception:
            pass

    def _on_position(self, data: dict):
        """Process position update."""
        try:
            pos_id = str(data.get('positionId', data.get('id', '')))
            profit = data.get('profit', 0)
            if pos_id:
                self.order_manager.on_trade_update(pos_id, profit, 'open')
        except Exception:
            pass

    def get_status(self) -> dict:
        """Return engine status for API response."""
        account_info = self.metaapi.account_info if self.metaapi else {}
        return {
            "running": self._running,
            "symbol": self.spec.symbol,
            "timeframe": self.spec.timeframe,
            "buffer_length": len(self._buffer),
            "tick_count": self._tick_count,
            "account_info": account_info,
            "open_trades": self.order_manager.get_open_trades() if self.order_manager else [],
            "stats": self.order_manager.get_stats() if self.order_manager else {},
        }
