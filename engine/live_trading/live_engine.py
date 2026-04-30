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

        # Signal callbacks (for frontend WebSocket)
        self._signal_callbacks: list = []

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        """Start the live engine: preload history, subscribe to candles."""
        if self._running:
            return
        self._running = True

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

        logger.info(
            f"LiveEngine started: {self.spec.symbol} | {self.spec.timeframe} "
            f"| {len(self._buffer)} historical bars"
        )

    async def stop(self):
        """Stop engine, close all open trades."""
        self._running = False
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

    def _evaluate(self):
        """Run StrategyInterpreter on accumulated bars."""
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
        if current_len == self._last_signal_bar:
            return  # No new bar

        self._last_signal_bar = current_len

        try:
            trades = self.interpreter.run(df)

            # Find new trades not yet in order_manager
            existing_symbols = set(self.order_manager._open_trades.keys())
            for trade in trades:
                if trade.exit_time is None:  # Open trade signal
                    trade_key = f"{trade.side}_{self.spec.symbol}"
                    if trade_key not in existing_symbols:
                        signal = {
                            'side': trade.side,
                            'price': trade.entry_price,
                            'reason': trade.reason,
                        }
                        asyncio.create_task(
                            self.order_manager.execute_signal(signal)
                        )
                        existing_symbols.add(trade_key)

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
