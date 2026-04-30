"""
Strategy Interpreter

Reads a StrategySpec and applies it against OHLCV data to generate
trade signals (entry/exit). This is the core logic that runs both
in the backtester and in the live execution engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .models import (
    ConditionType,
    ComparisonOp,
    ExitCondition,
    ExitType,
    StrategySpec,
)
from .indicators import compute_indicator

logger = logging.getLogger(__name__)


# ─── Data Classes ────────────────────────────────────────────────────────

@dataclass
class Trade:
    """A completed or open trade."""

    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp]
    entry_price: float
    exit_price: Optional[float]
    side: str
    symbol: str
    profit: Optional[float]
    reason: str


# ─── Interpreter ─────────────────────────────────────────────────────────

class StrategyInterpreter:
    """
    Interprets a StrategySpec against historical or real-time OHLCV data.

    Usage:
        interpreter = StrategyInterpreter(spec)
        signals = interpreter.run(dataframe)
    """

    def __init__(self, spec: StrategySpec):
        self.spec = spec
        self._indicator_cache: dict[str, dict[str, np.ndarray]] = {}
        self._open_trade_bar: int = 0

    def run(
        self,
        data: pd.DataFrame,
        initial_balance: float = 10_000.0,
    ) -> list[Trade]:
        """
        Run the strategy over a full DataFrame.

        Args:
            data: DataFrame with columns: open, high, low, close, volume, timestamp
            initial_balance: Starting balance for position sizing

        Returns:
            List of Trade objects (both open and closed)
        """
        if "timestamp" not in data.columns:
            data = data.copy()
            data["timestamp"] = pd.to_datetime(data.index)

        # Pre-compute all indicators
        self._compute_all_indicators(data)

        # Evaluate bar by bar
        trades: list[Trade] = []
        open_trade: Optional[Trade] = None
        self._open_trade_bar = 0
        current_balance = initial_balance

        for bar_idx in range(len(data)):
            row = data.iloc[bar_idx]
            ts = row["timestamp"]
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])

            # Check exit conditions for open trade
            if open_trade is not None:
                candles_elapsed = bar_idx - self._open_trade_bar
                exit_signal = self._check_exit(
                    bar_idx, data, high, low, close,
                    open_trade.entry_price, open_trade.side,
                    candles_elapsed,
                )
                if exit_signal:
                    exit_price = self._resolve_exit_price(
                        open_trade, bar_idx, data, exit_signal,
                        high, low, close,
                    )
                    open_trade.exit_time = ts
                    open_trade.exit_price = exit_price
                    open_trade.profit = self._calc_profit(
                        open_trade.side,
                        open_trade.entry_price,
                        exit_price,
                        current_balance,
                    )
                    trades.append(open_trade)
                    current_balance += open_trade.profit or 0
                    open_trade = None

            # Check entry conditions
            if open_trade is None:
                entry_signal = self._check_entry(bar_idx, data)
                if entry_signal:
                    self._open_trade_bar = bar_idx
                    open_trade = Trade(
                        entry_time=ts,
                        exit_time=None,
                        entry_price=close,
                        exit_price=None,
                        side=entry_signal["side"],
                        symbol=self.spec.symbol,
                        profit=None,
                        reason=entry_signal["reason"],
                    )

        # Close any remaining open trade at last bar
        if open_trade is not None:
            last_bar = data.iloc[-1]
            open_trade.exit_time = last_bar["timestamp"]
            last_close = float(last_bar["close"])
            open_trade.exit_price = last_close
            open_trade.profit = self._calc_profit(
                open_trade.side,
                open_trade.entry_price,
                last_close,
                current_balance,
            )
            trades.append(open_trade)

        return trades

    # ── Entry Evaluation ─────────────────────────────────────────────

    def _check_entry(
        self,
        idx: int,
        data: pd.DataFrame,
    ) -> Optional[dict]:
        """Check if ALL entry conditions are met at this bar."""
        reasons = []
        for cond in self.spec.entry_conditions:
            if not self._evaluate_condition(cond, idx, data):
                return None
            reasons.append(
                cond.description or f"{cond.condition_type.value}({cond.indicator.value})"
            )

        # Determine side: crossover = buy, crossunder = sell
        side = "buy"
        for cond in self.spec.entry_conditions:
            if cond.condition_type == ConditionType.CROSSUNDER:
                side = "sell"
                break

        return {
            "side": side,
            "reason": " AND ".join(reasons),
        }

    def _evaluate_condition(
        self,
        cond,
        idx: int,
        data: pd.DataFrame,
    ) -> bool:
        """Evaluate a single entry condition at index idx."""
        from .models import EntryCondition  # avoid circular
        fast_period = cond.params.get("fast_period")
        slow_period = cond.params.get("slow_period")

        val_a = self._get_indicator_value(
            cond.indicator, idx,
            fast_period=fast_period, slow_period=slow_period,
        )
        if val_a is None:
            return False

        if cond.condition_type in (ConditionType.CROSSEOVER, ConditionType.CROSSUNDER):
            # Special case: stochastic crossover (%K crosses %D)
            if cond.indicator.value == "stochastic":
                val_a = self._read_array(self._find_cache("stochastic"), idx, "stoch_k")
                val_b = self._read_array(self._find_cache("stochastic"), idx, "stoch_d")
                prev_a = self._read_array(self._find_cache("stochastic"), idx - 1, "stoch_k")
                prev_b = self._read_array(self._find_cache("stochastic"), idx - 1, "stoch_d")
            elif cond.indicator.value == "macd":
                # MACD crossover: MACD line crosses Signal line
                cache_key = self._find_cache("macd")
                val_a = self._read_array(cache_key, idx, "macd")
                val_b = self._read_array(cache_key, idx, "macd_signal")
                prev_a = self._read_array(cache_key, idx - 1, "macd")
                prev_b = self._read_array(cache_key, idx - 1, "macd_signal")
            elif cond.indicator_b and cond.indicator_b == cond.indicator:
                # Same type, different period
                val_b = self._get_indicator_value(
                    cond.indicator, idx,
                    fast_period=slow_period, slow_period=slow_period,
                )
                prev_a = self._get_indicator_value(
                    cond.indicator, idx - 1,
                    fast_period=fast_period, slow_period=slow_period,
                )
                prev_b = self._get_indicator_value(
                    cond.indicator, idx - 1,
                    fast_period=slow_period, slow_period=slow_period,
                )
            else:
                ind_b = cond.indicator_b or cond.indicator
                val_b = self._get_indicator_value(ind_b, idx)
                prev_a = self._get_indicator_value(
                    cond.indicator, idx - 1,
                    fast_period=fast_period, slow_period=slow_period,
                )
                prev_b = self._get_indicator_value(ind_b, idx - 1)

            if val_b is None or prev_a is None or prev_b is None:
                return False

            if cond.condition_type == ConditionType.CROSSEOVER:
                return prev_a <= prev_b and val_a > val_b
            else:  # CROSSUNDER
                return prev_a >= prev_b and val_a < val_b

        elif cond.condition_type == ConditionType.THRESHOLD:
            if cond.value is None:
                return False
            op = cond.operator or ComparisonOp.GT
            return self._compare(val_a, op, cond.value)

        elif cond.condition_type == ConditionType.CROSS_VALUE:
            if cond.value is None:
                return False
            prev_val = self._get_indicator_value(
                cond.indicator, idx - 1,
                fast_period=fast_period, slow_period=slow_period,
            )
            if prev_val is None:
                return False
            op = cond.operator or ComparisonOp.GT
            return self._compare(val_a, op, cond.value)

        return False

    # ── Exit Evaluation ──────────────────────────────────────────────

    def _check_exit(
        self,
        idx: int,
        data: pd.DataFrame,
        high: float,
        low: float,
        close: float,
        entry_price: float,
        side: str,
        candles_elapsed: int,
    ) -> Optional[str]:
        """Check if ANY exit condition is triggered."""
        for cond in self.spec.exit_conditions:
            if cond.exit_type in (ExitType.STOP_LOSS, ExitType.TAKE_PROFIT):
                if cond.pips is None:
                    continue
                pip_value = self._pips_to_price(cond.pips)

                if cond.exit_type == ExitType.STOP_LOSS:
                    sl_price = (
                        entry_price - pip_value if side == "buy"
                        else entry_price + pip_value
                    )
                    if (side == "buy" and low <= sl_price) or \
                       (side == "sell" and high >= sl_price):
                        return "stop_loss"

                elif cond.exit_type == ExitType.TAKE_PROFIT:
                    tp_price = (
                        entry_price + pip_value if side == "buy"
                        else entry_price - pip_value
                    )
                    if (side == "buy" and high >= tp_price) or \
                       (side == "sell" and low <= tp_price):
                        return "take_profit"

            elif cond.exit_type == ExitType.TRAILING_STOP:
                if cond.pips:
                    pip_value = self._pips_to_price(cond.pips)
                    sl_price = (
                        entry_price - pip_value if side == "buy"
                        else entry_price + pip_value
                    )
                    if (side == "buy" and low <= sl_price) or \
                       (side == "sell" and high >= sl_price):
                        return "trailing_stop"

            elif cond.exit_type == ExitType.ATR_STOP:
                atr_val = self._get_indicator_value("atr", idx)
                if atr_val and cond.atr_multiplier:
                    stop_distance = atr_val * cond.atr_multiplier
                    sl_price = (
                        entry_price - stop_distance if side == "buy"
                        else entry_price + stop_distance
                    )
                    if (side == "buy" and low <= sl_price) or \
                       (side == "sell" and high >= sl_price):
                        return "atr_stop"

            elif cond.exit_type == ExitType.TIME_BASED:
                if cond.candles and candles_elapsed >= cond.candles:
                    return "time_based"

            elif cond.exit_type == ExitType.CONDITION_BASED:
                if cond.condition:
                    if self._evaluate_condition(cond.condition, idx, data):
                        return f"condition: {cond.description}"

        return None

    # ── Helpers ──────────────────────────────────────────────────────

    def _compute_all_indicators(self, data: pd.DataFrame) -> None:
        """Pre-compute all indicators. Each gets a unique cache key
        based on type + period so SMA(10) and SMA(50) don't collide."""
        self._indicator_cache: dict[str, dict[str, np.ndarray]] = {}
        for ind_spec in self.spec.indicators:
            params = ind_spec.compute_params()
            result = compute_indicator(ind_spec.indicator_type.value, data, params)
            key = f"{ind_spec.indicator_type.value}_{params.get('period', 14)}"
            self._indicator_cache[key] = result

    def _get_indicator_value(
        self,
        indicator_ref,
        idx: int,
        fast_period: int | None = None,
        slow_period: int | None = None,
    ) -> Optional[float]:
        """Look up indicator value at index, optionally by period hint."""
        ind_name = (
            indicator_ref.value
            if hasattr(indicator_ref, "value")
            else indicator_ref
        )

        # 1. Try exact key (e.g. "rsi_14")
        for period_hint in [fast_period, slow_period]:
            if period_hint:
                key = f"{ind_name}_{period_hint}"
                if key in self._indicator_cache:
                    val = self._read_array(key, idx)
                    if val is not None:
                        return val

        # 2. Try any matching prefix
        for cache_key, cache in self._indicator_cache.items():
            if cache_key.startswith(f"{ind_name}_"):
                val = self._read_array(cache_key, idx)
                if val is not None:
                    return val

        return None

    def _find_cache(self, ind_name: str) -> str | None:
        """Find the cache key for an indicator type (e.g. 'stochastic_14')."""
        for key in self._indicator_cache:
            if key.startswith(f"{ind_name}_"):
                return key
        return None

    def _read_array(
        self, cache_key: str, idx: int, signal_name: str | None = None
    ) -> Optional[float]:
        """Read value from cached array at index. Optionally get specific signal."""
        cache = self._indicator_cache.get(cache_key)
        if cache is None:
            return None
        # If specific signal requested (e.g. "stoch_k", "stoch_d", "macd", "macd_signal")
        if signal_name and signal_name in cache:
            arr = cache[signal_name]
            if 0 <= idx < len(arr):
                val = arr[idx]
                if not np.isnan(val):
                    return float(val)
            return None
        # Otherwise return first non-NaN signal
        for arr_key in cache:
            arr = cache[arr_key]
            if 0 <= idx < len(arr):
                val = arr[idx]
                if not np.isnan(val):
                    return float(val)
        return None

    def _resolve_exit_price(
        self,
        trade: Trade,
        idx: int,
        data: pd.DataFrame,
        reason: str,
        high: float,
        low: float,
        close: float,
    ) -> float:
        """Determine the actual exit price."""
        if reason == "stop_loss":
            for cond in self.spec.exit_conditions:
                if cond.exit_type == ExitType.STOP_LOSS and cond.pips:
                    pip = self._pips_to_price(cond.pips)
                    if trade.side == "buy":
                        return trade.entry_price - pip
                    else:
                        return trade.entry_price + pip

        if reason == "take_profit":
            for cond in self.spec.exit_conditions:
                if cond.exit_type == ExitType.TAKE_PROFIT and cond.pips:
                    pip = self._pips_to_price(cond.pips)
                    if trade.side == "buy":
                        return trade.entry_price + pip
                    else:
                        return trade.entry_price - pip

        return close

    def _calc_profit(
        self, side: str, entry: float, exit_: float, balance: float
    ) -> float:
        """Calculate profit/loss in monetary terms."""
        position_size = balance * (self.spec.risk_management.position_size_pct / 100)
        price_change = (exit_ - entry) if side == "buy" else (entry - exit_)
        return price_change * position_size / entry * 100  # % return × position

    def _calc_position_size(self, balance: float) -> float:
        return balance * (self.spec.risk_management.position_size_pct / 100)

    def _pips_to_price(self, pips: float) -> float:
        """Convert pips to price units."""
        if self.spec.symbol.endswith("JPY"):
            return pips * 0.01
        return pips * 0.0001

    @staticmethod
    def _compare(a: float, op: ComparisonOp, b: float) -> bool:
        ops = {
            ">": lambda x, y: x > y,
            ">=": lambda x, y: x >= y,
            "<": lambda x, y: x < y,
            "<=": lambda x, y: x <= y,
            "==": lambda x, y: x == y,
        }
        fn = ops.get(op.value if hasattr(op, "value") else op)
        if fn is None:
            return False
        return fn(a, b)
