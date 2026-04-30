"""
Backtesting Engine

Runs a StrategySpec against historical data, computes performance metrics,
and generates a visual chart of the results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from .interpreter import StrategyInterpreter, Trade
from .models import StrategySpec

logger = logging.getLogger(__name__)


# ─── Metrics ─────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """Complete backtest output with metrics and chart."""

    strategy_name: str
    symbol: str
    timeframe: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    initial_balance: float
    final_balance: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_profit: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    avg_trade_duration_min: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)
    chart_path: Optional[str] = None

    @property
    def summary(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "symbol": self.symbol,
            "period": f"{self.start_date.date()} → {self.end_date.date()}",
            "total_trades": self.total_trades,
            "win_rate": f"{self.win_rate:.1%}",
            "net_profit": f"${self.net_profit:,.2f}",
            "total_return": f"{self.total_return_pct:.2f}%",
            "max_drawdown": f"{self.max_drawdown_pct:.2f}%",
            "sharpe_ratio": f"{self.sharpe_ratio:.2f}",
            "profit_factor": f"{self.profit_factor:.2f}",
        }


# ─── Backtester ──────────────────────────────────────────────────────────

class Backtester:
    """
    Run a strategy over historical data and produce metrics + chart.
    """

    def __init__(self, spec: StrategySpec):
        self.spec = spec
        self.interpreter = StrategyInterpreter(spec)

    def run(
        self,
        data: pd.DataFrame,
        initial_balance: float = 10_000.0,
        chart_output: Optional[str] = None,
    ) -> BacktestResult:
        """
        Execute backtest.

        Args:
            data: OHLCV DataFrame with columns: timestamp, open, high, low, close, volume
            initial_balance: Starting capital
            chart_output: File path to save chart PNG (optional)
        """
        logger.info(
            f"Backtesting: {self.spec.name} on {self.spec.symbol} "
            f"({len(data)} bars)"
        )

        # Run interpreter
        trades = self.interpreter.run(data, initial_balance)
        n_trades = len(trades)

        if n_trades == 0:
            logger.warning("No trades generated. Strategy may need adjustment.")
            return self._empty_result(data, initial_balance)

        # Build equity curve
        equity_curve = self._build_equity_curve(data, trades, initial_balance)

        # Compute metrics
        result = self._compute_metrics(
            trades, equity_curve, initial_balance, data
        )

        # Generate chart
        if chart_output:
            result.chart_path = self._generate_chart(
                data, trades, equity_curve, chart_output
            )

        logger.info(
            f"Backtest complete: {n_trades} trades, "
            f"win rate {result.win_rate:.1%}, "
            f"return {result.total_return_pct:.2f}%"
        )

        return result

    # ── Equity Curve ──────────────────────────────────────────────

    def _build_equity_curve(
        self,
        data: pd.DataFrame,
        trades: list[Trade],
        initial_balance: float,
    ) -> list[tuple[pd.Timestamp, float]]:
        """Build the equity curve from trades."""
        curve: list[tuple[pd.Timestamp, float]] = []
        balance = initial_balance

        # Sort trades by entry time
        sorted_trades = sorted(trades, key=lambda t: t.entry_time)

        trade_idx = 0
        for i in range(len(data)):
            ts = data.iloc[i]["timestamp"]
            # Apply completed trades at their exit time
            while (
                trade_idx < len(sorted_trades)
                and sorted_trades[trade_idx].exit_time is not None
                and sorted_trades[trade_idx].exit_time <= ts
            ):
                t = sorted_trades[trade_idx]
                if t.profit is not None:
                    balance += t.profit
                trade_idx += 1

            curve.append((ts, balance))

        return curve

    # ── Metrics ────────────────────────────────────────────────────

    def _compute_metrics(
        self,
        trades: list[Trade],
        equity_curve: list[tuple[pd.Timestamp, float]],
        initial_balance: float,
        data: pd.DataFrame,
    ) -> BacktestResult:
        """Calculate all performance metrics."""
        completed = [t for t in trades if t.exit_price is not None and t.profit is not None]
        n = len(completed)

        if n == 0:
            return self._empty_result(data, initial_balance)

        profits = [t.profit or 0 for t in completed]
        gross_profit = sum(p for p in profits if p > 0)
        gross_loss = abs(sum(p for p in profits if p <= 0))
        net_profit = sum(profits)
        final_balance = initial_balance + net_profit

        winning = sum(1 for p in profits if p > 0)
        losing = n - winning
        win_rate = winning / n if n > 0 else 0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Max drawdown
        peak = initial_balance
        max_dd = 0.0
        for _, equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (simplified, annualized)
        returns = pd.Series(profits)
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252 * 24 * 6)  # 1-min annualized
        else:
            sharpe = 0.0

        # Average trade duration
        durations = []
        for t in completed:
            if t.exit_time and t.entry_time:
                dur = (t.exit_time - t.entry_time).total_seconds() / 60
                durations.append(dur)
        avg_duration = sum(durations) / len(durations) if durations else 0

        return BacktestResult(
            strategy_name=self.spec.name,
            symbol=self.spec.symbol,
            timeframe=self.spec.timeframe.value,
            start_date=data.iloc[0]["timestamp"],
            end_date=data.iloc[-1]["timestamp"],
            initial_balance=initial_balance,
            final_balance=final_balance,
            total_return_pct=(net_profit / initial_balance) * 100,
            total_trades=n,
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_profit=net_profit,
            profit_factor=profit_factor,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            avg_trade_duration_min=avg_duration,
            trades=completed,
            equity_curve=equity_curve,
        )

    def _empty_result(
        self, data: pd.DataFrame, initial_balance: float
    ) -> BacktestResult:
        return BacktestResult(
            strategy_name=self.spec.name,
            symbol=self.spec.symbol,
            timeframe=self.spec.timeframe.value,
            start_date=data.iloc[0]["timestamp"],
            end_date=data.iloc[-1]["timestamp"],
            initial_balance=initial_balance,
            final_balance=initial_balance,
            total_return_pct=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            net_profit=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            avg_trade_duration_min=0.0,
        )

    # ── Chart Generation ───────────────────────────────────────────

    def _generate_chart(
        self,
        data: pd.DataFrame,
        trades: list[Trade],
        equity_curve: list[tuple[pd.Timestamp, float]],
        output_path: str,
    ) -> str:
        """Generate a backtest visualization chart."""
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 8),
            gridspec_kw={"height_ratios": [3, 1]},
            sharex=True,
        )
        fig.tight_layout()

        # ── Price chart with signals ──
        timestamps = pd.to_datetime(data["timestamp"])
        closes = data["close"].values

        ax1.plot(timestamps, closes, color="#1a1a2e", linewidth=0.8, label="Price")
        ax1.set_title(
            f"{self.spec.name} — {self.spec.symbol} Backtest\n"
            f"Win Rate: {self._win_rate(trades):.1%} | "
            f"Net Profit: ${self._net_profit(trades):,.2f} | "
            f"Trades: {len(trades)}",
            fontsize=12, fontweight="bold",
        )
        ax1.set_ylabel("Price")
        ax1.grid(True, alpha=0.3)

        # Plot trade signals
        for t in trades:
            if t.side == "buy":
                color = "#00c853"
                marker = "^"
            else:
                color = "#ff1744"
                marker = "v"

            ax1.scatter(
                t.entry_time, t.entry_price,
                color=color, marker=marker, s=60, zorder=5,
            )
            if t.exit_price:
                ax1.scatter(
                    t.exit_time, t.exit_price,
                    color=color, marker="x", s=60, zorder=5,
                )
                # Connect entry → exit
                ax1.plot(
                    [t.entry_time, t.exit_time],
                    [t.entry_price, t.exit_price],
                    color=color, alpha=0.3, linewidth=1,
                )

        # ── Equity curve ──
        if equity_curve:
            eq_times = [e[0] for e in equity_curve]
            eq_values = [e[1] for e in equity_curve]
            ax2.plot(eq_times, eq_values, color="#2962ff", linewidth=1.2)
            ax2.axhline(
                y=self._initial_from_curve(equity_curve),
                color="gray", linestyle="--", alpha=0.5,
                label="Initial Balance",
            )
        ax2.set_ylabel("Equity ($)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=8)

        # Format x-axis dates
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax1.xaxis.set_major_locator(mdates.MonthLocator())

        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"Chart saved to {output_path}")
        return output_path

    @staticmethod
    def _win_rate(trades: list[Trade]) -> float:
        completed = [t for t in trades if t.profit is not None]
        if not completed:
            return 0
        return sum(1 for t in completed if t.profit > 0) / len(completed)

    @staticmethod
    def _net_profit(trades: list[Trade]) -> float:
        return sum(t.profit or 0 for t in trades if t.profit is not None)

    @staticmethod
    def _initial_from_curve(curve: list) -> float:
        return curve[0][1] if curve else 0
