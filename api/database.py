"""
SQLAlchemy database setup and models.

Tables:
  - users: registered users (email, hashed password, JWT auth)
  - strategies: saved strategy specs (linked to user)
  - backtests: backtest results (linked to strategy)
  - trades: individual trade records (linked to backtest)
  - live_sessions: live trading sessions (linked to user + strategy)
  - live_trades: individual trade records from live sessions
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, JSON,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.pool import StaticPool

from .config import settings

# ── Engine & Session ────────────────────────────────────────────────────

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    poolclass=StaticPool if "sqlite" in settings.database_url else None,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# ── Models ──────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    strategies = relationship("Strategy", back_populates="owner", cascade="all, delete-orphan")


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    symbol = Column(String(20), default="EURUSD")
    timeframe = Column(String(10), default="1h")

    # Stored as JSON — the full StrategySpec
    spec_json = Column(JSON, nullable=False)

    # Metadata
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="strategies")
    backtests = relationship("Backtest", back_populates="strategy", cascade="all, delete-orphan")
    live_sessions = relationship("LiveSession", back_populates="strategy", cascade="all, delete-orphan", foreign_keys="LiveSession.strategy_id")


class Backtest(Base):
    __tablename__ = "backtests"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    bars_count = Column(Integer, default=5000)
    total_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
    total_return_pct = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)

    # Full results as JSON
    results_json = Column(JSON, default=dict)
    chart_path = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    strategy = relationship("Strategy", back_populates="backtests")
    trades = relationship("Trade", back_populates="backtest", cascade="all, delete-orphan")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    backtest_id = Column(Integer, ForeignKey("backtests.id"), nullable=False)
    trade_number = Column(Integer, default=0)
    side = Column(String(4), default="BUY")  # BUY / SELL
    entry_time = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)
    profit_pct = Column(Float, nullable=True)
    pips = Column(Float, nullable=True)
    reason = Column(Text, default="")
    duration_minutes = Column(Integer, default=0)

    backtest = relationship("Backtest", back_populates="trades")


class LiveSession(Base):
    __tablename__ = "live_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    strategy_id = Column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, nullable=False)  # MetaApi account ID
    mode = Column(String(10), default="paper")  # "paper" or "live"
    status = Column(String(20), default="running")  # running/stopped/error

    # Performance tracking
    equity = Column(Float, default=0.0)
    balance = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)

    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    strategy = relationship("Strategy")
    trades = relationship("LiveTrade", back_populates="session", cascade="all, delete-orphan")


class LiveTrade(Base):
    __tablename__ = "live_trades"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("live_sessions.id"), nullable=False)
    metaapi_trade_id = Column(Integer, nullable=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)  # BUY/SELL
    entry_time = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    volume = Column(Float, default=0.01)
    sl = Column(Float, nullable=True)
    tp = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)
    profit_pct = Column(Float, nullable=True)
    pips = Column(Float, nullable=True)
    reason = Column(Text, default="")
    closed = Column(Boolean, default=False)

    session = relationship("LiveSession", back_populates="trades")


# ── Helpers ─────────────────────────────────────────────────────────────

def get_db() -> Session:
    """Dependency that yields a DB session and closes after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Call once at startup."""
    Base.metadata.create_all(bind=engine)
