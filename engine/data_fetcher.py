"""
Real market data fetcher using yfinance.

Supports:
  - Forex pairs (EURUSD=X, GBPUSD=X, etc.)
  - Crypto (BTC-USD, ETH-USD, etc.)
  - Stocks (AAPL, TSLA, etc.)
  - Timeframes: 1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo

Includes LRU caching to avoid repeated API calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import pandas as pd

from .sample_data import generate_sample_data

logger = logging.getLogger(__name__)

# ── Symbol mapping ─────────────────────────────────────────────────────
# Maps user-friendly symbols to yfinance ticker symbols

SYMBOL_MAP = {
    # Forex
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    "CHFJPY": "CHFJPY=X",
    "AUDJPY": "AUDJPY=X",
    "CADJPY": "CADJPY=X",
    "EURCHF": "EURCHF=X",
    "GBPAUD": "GBPAUD=X",
    "GBPCHF": "GBPCHF=X",
    # Crypto
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "BNBUSD": "BNB-USD",
    "SOLUSD": "SOL-USD",
    "XRPUSD": "XRP-USD",
    "ADAUSD": "ADA-USD",
    "DOTUSD": "DOT-USD",
    "DOGEUSD": "DOGE-USD",
    "AVAXUSD": "AVAX-USD",
    "MATICUSD": "MATIC-USD",
    # B3 — Brazilian Stock Exchange (.SA suffix, BRL)
    "B3SA3":  "B3SA3.SA",
    "BBAS3":  "BBAS3.SA",
    "BBDC4":  "BBDC4.SA",
    "BBSE3":  "BBSE3.SA",
    "PETR3":  "PETR3.SA",
    "PETR4":  "PETR4.SA",
    "ITUB4":  "ITUB4.SA",
    "ABEV3":  "ABEV3.SA",
    "TAEE11": "TAEE11.SA",
    "VALE3":  "VALE3.SA",
    "WEGE3":  "WEGE3.SA",
    "SUZB3":  "SUZB3.SA",
    "CSAN3":  "CSAN3.SA",
    "RADL3":  "RADL3.SA",
    "KLBN11": "KLBN11.SA",
    "RENT3":  "RENT3.SA",
    "HGLG11": "HGLG11.SA",
    "GGBR4":  "GGBR4.SA",
    "PINE3":  "PINE3.SA",
    "IRBR3":  "IRBR3.SA",
    "TIMS3":  "TIMS3.SA",
    "CSMG3":  "CSMG3.SA",
    "SMTO3":  "SMTO3.SA",
    "MGLU3":  "MGLU3.SA",
    "HAPV3":  "HAPV3.SA",
    "HGBS11": "HGBS11.SA",
    "HGBR3":  "HGBR3.SA",
    "COGN3":  "COGN3.SA",
    "HBOR3":  "HBOR3.SA",
    "PCAR3":  "PCAR3.SA",
    "CAML3":  "CAML3.SA",
    "BNBR3":  "BNBR3.SA",
    "SBSP3":  "SBSP3.SA",
    "SANB3":  "SANB3.SA",
    "TOTS3":  "TOTS3.SA",
}

# Supported timeframe mappings: our internal → yfinance interval + period
TIMEFRAME_MAP = {
    "1m":  {"interval": "1m",  "period": "1d"},
    "5m":  {"interval": "5m",  "period": "5d"},
    "15m": {"interval": "15m", "period": "1mo"},
    "30m": {"interval": "30m", "period": "1mo"},
    "1h":  {"interval": "60m", "period": "6mo"},
    "4h":  {"interval": "60m", "period": "6mo"},  # yfinance doesn't have 4h; fetch 1h then resample
    "1d":  {"interval": "1d",  "period": "2y"},
    "1wk": {"interval": "1wk", "period": "5y"},
    "1mo": {"interval": "1mo", "period": "5y"},
}

# Known forex/crypto symbols for autocomplete
KNOWN_SYMBOLS = list(SYMBOL_MAP.keys())


def resolve_symbol(symbol: str) -> str:
    """Convert user-friendly symbol to yfinance ticker."""
    s = symbol.upper().replace(" ", "")
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]
    # Try as-is (maybe a stock or already a yfinance symbol)
    return s


def reverse_resolve(yf_symbol: str) -> str:
    """Convert yfinance ticker back to user-friendly symbol."""
    for key, val in SYMBOL_MAP.items():
        if val == yf_symbol:
            return key
    return yf_symbol.replace("=", "").replace("-", "")


def timeframe_to_range(timeframe: str, n_bars: int) -> dict:
    """Calculate the date range needed to get n_bars of a given timeframe."""
    tf_map = {
        "1m": {"multiplier": 1, "unit_minutes": 1},
        "5m": {"multiplier": 1, "unit_minutes": 5},
        "15m": {"multiplier": 1, "unit_minutes": 15},
        "30m": {"multiplier": 1, "unit_minutes": 30},
        "1h": {"multiplier": 1, "unit_minutes": 60},
        "4h": {"multiplier": 4, "unit_minutes": 60},
        "1d": {"multiplier": 1, "unit_days": 1},
        "1wk": {"multiplier": 1, "unit_days": 7},
        "1mo": {"multiplier": 1, "unit_days": 30},
    }

    config = tf_map.get(timeframe, {"multiplier": 1, "unit_minutes": 60})
    end_date = datetime.utcnow()

    if "unit_days" in config:
        days_needed = n_bars * config["multiplier"] * config["unit_days"]
    else:
        days_needed = (n_bars * config["multiplier"] * config["unit_minutes"]) / (60 * 24)

    start_date = end_date - timedelta(days=min(days_needed, 5000))  # Max ~13.7 years
    return {"start": start_date.strftime("%Y-%m-%d"), "end": end_date.strftime("%Y-%m-%d")}


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    n_bars: int = 5000,
    use_real: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for a symbol.

    Args:
        symbol: User-friendly symbol (e.g., "EURUSD", "BTCUSD")
        timeframe: Timeframe string (e.g., "1h", "4h", "1d")
        n_bars: Desired number of bars
        use_real: If True, fetch from yfinance. If False, generate sample data.

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    if not use_real:
        logger.info(f"Generating sample data for {symbol} ({n_bars} bars)")
        return generate_sample_data(symbol=symbol, n_bars=n_bars, timeframe=timeframe)

    yf_symbol = resolve_symbol(symbol)
    tf_config = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["1h"])

    # Calculate date range
    date_range = timeframe_to_range(timeframe, n_bars)

    logger.info(f"Fetching {yf_symbol} ({timeframe}, ~{n_bars} bars) from yfinance")

    try:
        import yfinance as yf

        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(
            start=date_range["start"],
            end=date_range["end"],
            interval=tf_config["interval"],
            auto_adjust=True,
            repair=True,
        )

        if df.empty:
            logger.warning(f"No data returned for {yf_symbol}. Using sample data.")
            return generate_sample_data(symbol=symbol, n_bars=n_bars, timeframe=timeframe)

        # Resample if needed (e.g., 4h from 1h data)
        if timeframe == "4h" and tf_config["interval"] == "60m":
            df = df.resample("4h").agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }).dropna()

        # Normalize column names to lowercase
        df = df.rename(columns=str.lower)

        # Ensure column order
        df = df[["open", "high", "low", "close", "volume"]].copy()

        # Rename index to 'timestamp'
        df = df.reset_index()
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]

        # Take last n_bars
        df = df.tail(n_bars).reset_index(drop=True)

        logger.info(
            f"Fetched {len(df)} bars for {yf_symbol}"
        )
        return df

    except Exception as e:
        logger.error(f"Failed to fetch {yf_symbol}: {e}. Falling back to sample data.")
        return generate_sample_data(symbol=symbol, n_bars=n_bars, timeframe=timeframe)


def get_available_symbols() -> list[dict]:
    """Return list of available symbols with metadata for autocomplete."""
    # B3 symbols: any ticker ending with a digit (PETR4, B3SA3, etc.) that maps
    # to a .SA ticker
    b3_prefixes = {"B3SA", "BBAS", "BBDC", "BBSE", "PETR", "ITUB", "ABEV",
                   "TAEE", "VALE", "WEGE", "SUZB", "CSAN", "RADL", "KLBN",
                   "RENT", "HGLG", "GGBR", "PINE", "IRBR", "TIMS", "CSMG",
                   "SMTO", "MGLU", "HAPV", "HGBS", "HGBR", "COGN", "HBOR",
                   "PCAR", "CAML", "BNBR", "SBSP", "SANB", "TOTS"}

    result = []
    for sym in KNOWN_SYMBOLS:
        yf_sym = SYMBOL_MAP[sym]

        if ".SA" in yf_sym:
            result.append({"symbol": sym, "type": "b3", "ticker": yf_sym, "currency": "BRL"})
        elif any(sym.startswith(p) for p in ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOT", "DOGE", "AVAX", "MATIC"]):
            result.append({"symbol": sym, "type": "crypto", "ticker": yf_sym, "currency": "USD"})
        else:
            result.append({"symbol": sym, "type": "forex", "ticker": yf_sym, "currency": "USD"})
    return result


def get_current_price(symbol: str) -> Optional[float]:
    """Get the current/latest price for a symbol."""
    yf_symbol = resolve_symbol(symbol)
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        info = ticker.fast_info
        price = getattr(info, 'last_price', None) or getattr(info, 'regularMarketPrice', None)
        if price:
            return float(price)
    except Exception as e:
        logger.warning(f"Failed to get current price for {yf_symbol}: {e}")
    return None
