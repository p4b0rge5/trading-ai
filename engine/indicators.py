"""
Technical indicator implementations.

Supports both TA-Lib (C library, fast) and pure NumPy fallbacks
so the engine runs even without TA-Lib installed (e.g. in testing).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Try to import TA-Lib; fall back to pure NumPy
try:
    import talib  # type: ignore
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False
    logger.warning("TA-Lib not installed. Using pure NumPy implementations.")


# ─── Core Indicators ─────────────────────────────────────────────────────

def sma(prices: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    if HAS_TALIB:
        return talib.SMA(prices, timeperiod=period)
    return _numpy_sma(prices, period)


def ema(prices: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    if HAS_TALIB:
        return talib.EMA(prices, timeperiod=period)
    return _numpy_ema(prices, period)


def wma(prices: np.ndarray, period: int) -> np.ndarray:
    """Weighted Moving Average."""
    if HAS_TALIB:
        return talib.WMA(prices, timeperiod=period)
    return _numpy_wma(prices, period)


def rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    if HAS_TALIB:
        return talib.RSI(prices, timeperiod=period)
    return _numpy_rsi(prices, period)


def macd(
    prices: np.ndarray,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD line, Signal line, Histogram."""
    if HAS_TALIB:
        macd_line, signal_line, histogram = talib.MACD(
            prices,
            fastperiod=fast_period,
            slowperiod=slow_period,
            signalperiod=signal_period,
        )
        return macd_line, signal_line, histogram
    return _numpy_macd(prices, fast_period, slow_period, signal_period)


def bollinger(
    prices: np.ndarray,
    period: int = 20,
    nb_dev: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Upper band, Middle band (SMA), Lower band."""
    if HAS_TALIB:
        upper, middle, lower = talib.BBANDS(
            prices, timeperiod=period, nbdev=nb_dev
        )
        return upper, middle, lower
    middle = sma(prices, period)
    std = np.nanstd(prices)  # simplified; rolling std in NumPy fallback
    upper = middle + nb_dev * std
    lower = middle - nb_dev * std
    return upper, middle, lower


def stochastic(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """%K and %D lines."""
    if HAS_TALIB:
        percent_k, percent_d = talib.STOCH(
            highs, lows, closes,
            fastk_period=k_period,
            slowk_period=d_period,
            slowd_period=d_period,
        )
        return percent_k, percent_d
    return _numpy_stochastic(highs, lows, closes, k_period, d_period)


def atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average True Range."""
    if HAS_TALIB:
        return talib.ATR(highs, lows, closes, timeperiod=period)
    return _numpy_atr(highs, lows, closes, period)


def adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average Directional Index."""
    if HAS_TALIB:
        return talib.ADX(highs, lows, closes, timeperiod=period)
    return _numpy_adx(highs, lows, closes, period)


# ─── Indicator Dispatcher ────────────────────────────────────────────────

INDICATOR_FUNCS = {
    "sma": sma,
    "ema": ema,
    "wma": wma,
    "rsi": rsi,
    "macd": macd,
    "bollinger": bollinger,
    "stochastic": stochastic,
    "atr": atr,
    "adx": adx,
}


def compute_indicator(
    name: str,
    data: pd.DataFrame,
    params: dict,
) -> dict[str, np.ndarray]:
    """
    Compute an indicator given a name and OHLCV DataFrame.

    Returns a dict of signal_name → numpy array, e.g.:
      {"sma_10": [...], "sma_50": [...]} for crossover
      {"rsi": [...]} for threshold
      {"macd": [...], "macd_signal": [...], "macd_hist": [...]}
    """
    func = INDICATOR_FUNCS.get(name.lower())
    if func is None:
        raise ValueError(f"Unknown indicator: {name}")

    source_col = params.get("source", "close")
    prices = data[source_col].values.astype(float)
    period = params.get("period", 14)

    if name == "macd":
        fast = params.get("fast_period", 12)
        slow = params.get("slow_period", 26)
        sig = params.get("signal_period", 9)
        m, s, h = macd(prices, fast, slow, sig)
        return {"macd": m, "macd_signal": s, "macd_hist": h}

    if name == "bollinger":
        nb_dev = params.get("nb_dev", 2.0)
        upper, mid, lower = bollinger(prices, period, nb_dev)
        return {"bb_upper": upper, "bb_middle": mid, "bb_lower": lower}

    if name == "stochastic":
        highs = data["high"].values.astype(float)
        lows = data["low"].values.astype(float)
        closes = data["close"].values.astype(float)
        k, d = stochastic(highs, lows, closes, period, params.get("d_period", 3))
        return {"stoch_k": k, "stoch_d": d}

    if name in ("atr", "adx"):
        highs = data["high"].values.astype(float)
        lows = data["low"].values.astype(float)
        closes = data["close"].values.astype(float)
        result = func(highs, lows, closes, period)
        return {name: result}

    # Simple single-output indicators (sma, ema, wma, rsi)
    result = func(prices, period) if name != "rsi" else rsi(prices, period)
    return {name: result}


# ─── Pure NumPy Fallbacks ────────────────────────────────────────────────

def _numpy_sma(prices: np.ndarray, period: int) -> np.ndarray:
    return pd.Series(prices).rolling(window=period).mean().values


def _numpy_ema(prices: np.ndarray, period: int) -> np.ndarray:
    return pd.Series(prices).ewm(span=period, adjust=False).mean().values


def _numpy_wma(prices: np.ndarray, period: int) -> np.ndarray:
    weights = np.arange(1, period + 1)
    result = np.full_like(prices, np.nan, dtype=float)
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1: i + 1]
        result[i] = np.dot(window, weights) / weights.sum()
    return result


def _numpy_rsi(prices: np.ndarray, period: int) -> np.ndarray:
    delta = np.diff(prices)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = pd.Series(gain).rolling(window=period).mean().values.copy()
    avg_loss = pd.Series(loss).rolling(window=period).mean().values.copy()

    # Exponential smoothing after first period
    for i in range(period, len(avg_gain)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period

    rs = np.where(avg_loss == 0, 100, avg_gain / avg_loss)
    rsi = 100 - (100 / (1 + rs))
    rsi[:period] = np.nan
    return rsi


def _numpy_macd(
    prices: np.ndarray,
    fast: int,
    slow: int,
    signal: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fast_ema = _numpy_ema(prices, fast)
    slow_ema = _numpy_ema(prices, slow)
    macd_line = fast_ema - slow_ema
    signal_line = _numpy_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _numpy_stochastic(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    k_period: int,
    d_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    rolling_min = pd.Series(lows).rolling(k_period).min().values
    rolling_max = pd.Series(highs).rolling(k_period).max().values
    denom = rolling_max - rolling_min
    percent_k = np.where(
        denom == 0, 50, 100 * (closes - rolling_min) / denom
    )
    percent_d = pd.Series(percent_k).rolling(d_period).mean().values
    return percent_k, percent_d


def _numpy_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
) -> np.ndarray:
    prev_closes = np.concatenate([[closes[0]], closes[:-1]])
    tr = np.maximum(
        highs - lows,
        np.maximum(
            np.abs(highs - prev_closes),
            np.abs(lows - prev_closes)
        )
    )
    return pd.Series(tr).ewm(span=period, adjust=False).mean().values


def _numpy_adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
) -> np.ndarray:
    plus_dm = np.maximum(highs[1:] - highs[:-1], 0)
    minus_dm = np.maximum(lows[:-1] - lows[1:], 0)
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    plus_di = 100 * pd.Series(plus_dm).ewm(period).mean().values
    minus_di = 100 * pd.Series(minus_dm).ewm(period).mean().values
    tr_smooth = pd.Series(tr).ewm(period).mean().values

    di_sum = plus_di + minus_di
    dx = 100 * np.where(di_sum == 0, 0, np.abs(plus_di - minus_di) / di_sum)
    adx = pd.Series(dx).ewm(period).mean().values
    return np.concatenate([[np.nan]], adx)
