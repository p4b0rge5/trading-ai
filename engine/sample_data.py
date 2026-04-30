"""
Sample data generator for backtesting without real market data.

Generates realistic OHLCV data with trends, volatility clustering,
and noise — sufficient for validating the engine logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_sample_data(
    symbol: str = "EURUSD",
    n_bars: int = 5000,
    start_date: str = "2024-01-01",
    timeframe: str = "1h",
    initial_price: float = 1.0800,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate realistic OHLCV data for backtesting.

    Uses a geometric Brownian motion with:
    - Trend regime changes
    - Volatility clustering (GARCH-like)
    - Realistic intrabar spread
    """
    rng = np.random.default_rng(seed)

    # Time index
    if timeframe == "1h":
        freq = "h"
    elif timeframe == "15m":
        freq = "15min"
    elif timeframe == "4h":
        freq = "4h"
    elif timeframe == "1d":
        freq = "D"
    else:
        freq = "h"

    timestamps = pd.date_range(start=start_date, periods=n_bars, freq=freq)

    # Parameters
    mu = 0.0001  # Drift (slight upward bias)
    sigma = 0.0005  # Base volatility
    trend_changes = rng.choice([-1, 0, 1], size=n_bars)
    trend_regime = np.cumsum(trend_changes * 0.00001)

    # Volatility clustering
    vol = np.zeros(n_bars)
    vol[0] = sigma
    for i in range(1, n_bars):
        vol[i] = 0.9 * vol[i - 1] + 0.1 * sigma + rng.exponential(0.0001)

    # Price generation
    prices = np.zeros(n_bars)
    prices[0] = initial_price
    for i in range(1, n_bars):
        returns = mu + trend_regime[i] + vol[i] * rng.standard_normal()
        prices[i] = prices[i - 1] * (1 + returns)

    # Generate OHLCV from close prices
    spread = prices * 0.0001  # ~1 pip spread for EURUSD

    opens = prices.copy()
    closes = prices.copy()
    high_pct = rng.uniform(0.0001, 0.002, n_bars)
    low_pct = rng.uniform(0.0001, 0.002, n_bars)

    highs = prices * (1 + high_pct)
    lows = prices * (1 - low_pct)

    # Ensure OHLC consistency
    for i in range(n_bars):
        o = prices[i - 1] if i > 0 else prices[i]
        opens[i] = o
        closes[i] = prices[i]
        highs[i] = max(opens[i], closes[i]) * (1 + high_pct[i] * 0.5)
        lows[i] = min(opens[i], closes[i]) * (1 - low_pct[i] * 0.5)

    volume = rng.lognormal(mean=10, sigma=2, size=n_bars).astype(int)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volume,
    })

    return df


def load_demo_strategy() -> dict:
    """
    Return a demo strategy spec as a dict (can be validated with Pydantic).

    Strategy: Golden Cross with RSI filter on EURUSD 1H.
    """
    return {
        "name": "Cruzamento de Médias com Filtro RSI",
        "description": (
            "Compra quando SMA rápida cruza acima da SMA lenta e RSI > 30. "
            "Vende quando SMA rápida cruza abaixo da SMA lenta e RSI < 70. "
            "Stop loss de 50 pips, take profit de 100 pips."
        ),
        "symbol": "EURUSD",
        "timeframe": "1h",
        "indicators": [
            {
                "indicator_type": "sma",
                "period": 10,
                "source": "close",
            },
            {
                "indicator_type": "sma",
                "period": 50,
                "source": "close",
                "params": {"alias": "sma_slow"},
            },
            {
                "indicator_type": "rsi",
                "period": 14,
                "source": "close",
            },
        ],
        "entry_conditions": [
            {
                "condition_type": "crossover",
                "indicator": "sma",
                "indicator_b": "sma",
                "params": {"fast_period": 10, "slow_period": 50},
                "description": "SMA 10 cruza acima SMA 50",
            },
            {
                "condition_type": "threshold",
                "indicator": "rsi",
                "operator": ">",
                "value": 30,
                "description": "RSI acima de 30 (momentum positivo)",
            },
        ],
        "exit_conditions": [
            {
                "exit_type": "stop_loss",
                "pips": 50,
                "description": "Stop loss de 50 pips",
            },
            {
                "exit_type": "take_profit",
                "pips": 100,
                "description": "Take profit de 100 pips",
            },
        ],
        "risk_management": {
            "position_size_pct": 2.0,
            "max_open_trades": 3,
            "max_daily_loss_pct": 5.0,
            "max_drawdown_pct": 15.0,
        },
    }
