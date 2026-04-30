"""
Pydantic schemas for API request/response validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Auth ────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str = Field(..., example="trader@example.com")
    username: str = Field(..., min_length=3, example="trader1")
    password: str = Field(..., min_length=6, example="securepassword")
    full_name: str = Field(default="", example="John Trader")


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    """Placeholder — actual login uses OAuth2PasswordRequestForm dependency."""
    pass


# ── Strategy ────────────────────────────────────────────────────────────

class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    description: str = Field(default="", max_length=5000)
    symbol: str = Field(default="EURUSD")
    timeframe: str = Field(default="1h")
    spec_json: dict = Field(..., description="Full StrategySpec as JSON dict")


class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str
    symbol: str
    timeframe: str
    spec_json: dict
    user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Prompt-to-Strategy ─────────────────────────────────────────────────

class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=10, max_length=5000,
                         description="Natural language strategy description")
    run_backtest: bool = Field(default=True)
    bars: int = Field(default=5000, ge=500, le=20000)


class PromptResponse(BaseModel):
    strategy: StrategyResponse
    backtest: Optional[BacktestSummary] = None
    llm_calls: int = 0


# ── Backtest ────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    strategy_id: int = Field(..., description="Strategy to backtest")
    bars: int = Field(default=5000, ge=500, le=20000)


class BacktestSummary(BaseModel):
    id: Optional[int] = None
    strategy_id: int
    bars_count: int
    total_trades: int
    win_rate: float
    net_profit: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    chart_path: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Trade ───────────────────────────────────────────────────────────────

class TradeResponse(BaseModel):
    id: int
    backtest_id: int
    trade_number: int
    side: str
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit: Optional[float] = None
    profit_pct: Optional[float] = None
    pips: Optional[float] = None
    reason: str
    duration_minutes: int

    class Config:
        from_attributes = True


# ── Health ──────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"
    engine_indicators: int = 9
    strategies_supported: list[str] = [
        "sma", "ema", "wma", "rsi", "macd", "bollinger",
        "stochastic", "atr", "adx",
    ]
