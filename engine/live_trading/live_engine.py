"""
Live Engine — real-time bar builder + signal evaluation.

Pipeline:
  1. Receive ticks from MetaApi WebSocket
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
                 session_id: int, api_token: str):
        self.spec = spec
        self.metaapi = metaapi_client
        self.order_manager = order_manager
        self.session_id = session_id
        self.api_token = api_token

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

        # Signal callbacks (for frontend WebSocket)
        self._signal_callbacks: list = []

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        """Start the live engine: preload history, subscribe to ticks."""
        if self._running:
            return
        self._running = True

        # Preload historical bars for indicator warm-up
        await self._preload_history()

        # Subscribe to ticks
        await self.metaapi.subscribe_symbol(self.spec.symbol)

        # Register MetaApi event handlers
        self.metaapi.on("tradeTickUpdate", self._on_tick)
        self.metaapi.on("accountUpdate", self._on_account_update)
        self.metaapi.on("tradeUpdate", self._on_trade_update)

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
        """Fetch historical bars from MetaApi API to warm up indicators."""
        try:
            bars = await self.metaapi.get_historical_bars(
                symbol=self.spec.symbol,
                timeframe=self.spec.timeframe.value if hasattr(self.spec.timeframe, 'value') else self.spec.timeframe,
                count=1000,
            )
            for bar in bars:
                self._buffer.append(LiveBar(
                    timestamp=datetime.utcfromtimestamp(bar['time'] / 1000) if bar['time'] > 1e12 else datetime.utcfromtimestamp(bar['time']),
                    open=bar['open'],
                    high=bar['high'],
                    low=bar['low'],
                    close=bar['close'],
                    volume=bar.get('volume', 0),
                    complete=True,
                ))
            logger.info(f"Preloaded {len(self._buffer)} historical bars")
        except Exception as e:
            logger.error(f"Failed to preload history: {e}")

    # ── Tick Processing ────────────────────────────────────────────────

    def _on_tick(self, message):
        """Process incoming tick from MetaApi WebSocket."""
        if not self._running:
            return

        try:
            payload = message.payload if hasattr(message, 'payload') else message
            symbol = payload.get('symbol', '')

            if symbol != self.spec.symbol:
                return

            bid = payload.get('bid')
            ask = payload.get('ask')
            ts_ms = payload.get('time', 0)

            if bid is None:
                return

            ts = datetime.utcfromtimestamp(ts_ms / 1000)
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
            existing_ids = set(self.order_manager._open_trades.keys())
            for trade in trades:
                if trade.exit_time is None:  # Open trade signal
                    signal = {
                        'side': trade.side,
                        'price': trade.entry_price,
                        'reason': trade.reason,
                    }
                    asyncio.create_task(
                        self.order_manager.execute_signal(signal)
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

    # ── MetaApi Event Handlers ─────────────────────────────────────────

    def _on_account_update(self, message):
        """Update risk state from account info."""
        try:
            payload = message.payload if hasattr(message, 'payload') else message
            equity = payload.get('equity', 0)
            balance = payload.get('balance', 0)
            profit = payload.get('profit', 0)
            self.order_manager.on_account_update(equity, balance, profit)
        except Exception:
            pass

    def _on_trade_update(self, message):
        """Forward trade updates to order manager."""
        try:
            payload = message.payload if hasattr(message, 'payload') else message
            trade_id = payload.get('tradeId', 0)
            profit = payload.get('profit', 0)
            state = payload.get('state', '')
            if trade_id:
                self.order_manager.on_trade_update(trade_id, profit, state)
        except Exception:
            pass

    # ── Status ─────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Current engine status for API response."""
        stats = self.order_manager.get_stats()
        return {
            "running": self._running,
            "symbol": self.spec.symbol,
            "timeframe": self.spec.timeframe.value if hasattr(self.spec.timeframe, 'value') else self.spec.timeframe,
            "bars_loaded": len(self._buffer),
            "tick_count": self._tick_count,
            **stats,
        }
