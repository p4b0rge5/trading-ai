"""
Market data endpoints.

Endpoints:
  GET  /api/v1/data/symbols       — List available symbols
  GET  /api/v1/data/ohlcv         — Fetch OHLCV data
  GET  /api/v1/data/price/{symbol} — Get current price
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from engine.data_fetcher import (
    fetch_ohlcv,
    get_available_symbols,
    get_current_price,
    resolve_symbol,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.get("/symbols")
def list_symbols():
    """Get list of available trading symbols."""
    return get_available_symbols()


@router.get("/price/{symbol}")
def get_price(symbol: str):
    """Get current price for a symbol."""
    price = get_current_price(symbol)
    return {"symbol": symbol, "price": price, "timestamp": datetime.utcnow().isoformat()}


@router.get("/ohlcv")
def get_ohlcv(
    symbol: str = Query(..., description="Trading symbol, e.g. EURUSD, BTCUSD"),
    timeframe: str = Query("1d", description="Timeframe: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1wk, 1mo"),
    bars: int = Query(500, ge=1, le=10000, description="Number of bars to fetch"),
    real: bool = Query(True, description="Use real market data. False = synthetic."),
):
    """
    Fetch OHLCV data for a symbol.

    Uses yfinance for real market data, falls back to synthetic generation.
    """
    df = fetch_ohlcv(symbol=symbol, timeframe=timeframe, n_bars=bars, use_real=real)

    # Convert to list of dicts for JSON
    data = []
    for _, row in df.iterrows():
        data.append({
            "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if row["volume"] else 0,
        })

    return {
        "symbol": symbol,
        "yf_symbol": resolve_symbol(symbol),
        "timeframe": timeframe,
        "bars": len(data),
        "data": data,
    }
