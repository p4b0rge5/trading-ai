"""
Live trading engine — connects StrategySpec execution to live markets.

Two modes:
  - "live": Uses MetaApi.cloud WebSocket for real MT4/MT5 trading
  - "paper": Uses yfinance for real-time prices, simulates orders in memory

Modules:
  metaapi_client   — WebSocket connection to MetaApi.cloud (ticks, account, trades)
  paper_client     — Paper trading with real yfinance data (no real money)
  live_engine      — Bar builder + signal evaluation loop (ticks → bars → signals)
  order_manager    — Executes signals as orders (market, SL/TP, close)

Usage:
    from engine.live_trading import LiveSession

    # Paper trading (no MetaApi needed):
    session = LiveSession(strategy_spec, db, session_id, mode="paper")
    await session.start()

    # Live trading (MetaApi):
    session = LiveSession(api_token, account_id, strategy_spec, db, session_id, mode="live")
    await session.start()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional, Any

from sqlalchemy.orm import Session

from engine.models import StrategySpec

from .live_engine import LiveEngine
from .order_manager import OrderManager
from .session_registry import register as _register_session
from .session_registry import unregister as _unregister_session

logger = logging.getLogger(__name__)


class LiveSession:
    """
    Top-level live/paper trading session.

    Wires together: data client → bar builder → signal evaluation → orders.

    Manages the full lifecycle: connect → preload history → evaluate → execute → close.
    """

    def __init__(self, api_token: str, account_id: Any, strategy_spec: StrategySpec,
                 db: Session, session_id: int, mode: str = "paper",
                 webhook_url: str | None = None):
        self.api_token = api_token
        self.account_id = account_id
        self.strategy_spec = strategy_spec
        self.db = db
        self.session_id = session_id
        self.mode = mode  # "paper" or "live"

        self.client = None  # MetaApiClient or PaperTradingClient
        self.engine: Optional[LiveEngine] = None
        self.order_mgr: Optional[OrderManager] = None
        self._running = False

        # Notification service
        if webhook_url:
            from engine.notifications import NotificationService
            self.notifications = NotificationService(webhook_url=webhook_url)
        else:
            from engine.notifications import NotificationService
            self.notifications = NotificationService()

    async def start(self):
        """Start the session: connect to data source, init engine, begin trading."""
        if self._running:
            return

        if self.mode == "paper":
            await self._start_paper()
        else:
            await self._start_live()

    async def _start_paper(self):
        """Start paper trading mode with yfinance."""
        from .paper_client import PaperTradingClient

        # 1. Create paper trading client
        self.client = PaperTradingClient(self.api_token)

        # 2. Connect (initialize with yfinance)
        ok = await self.client.connect(self.account_id)
        if not ok:
            raise RuntimeError("Failed to initialize paper trading")

        # 3. Create order manager with notification service
        self.order_mgr = OrderManager(self.client, self.strategy_spec, self.session_id,
                                     notification_service=self.notifications)

        # 4. Create live engine
        self.engine = LiveEngine(
            spec=self.strategy_spec,
            metaapi_client=self.client,
            order_manager=self.order_mgr,
            session_id=self.session_id,
        )

        # 5. Start engine
        await self.engine.start()

        # 6. Fire session_started notification
        if self.notifications:
            asyncio.create_task(
                self.notifications.notify(
                    event_type="session_started",
                    session_id=self.session_id,
                    strategy_name=self.strategy_spec.name,
                    symbol=self.strategy_spec.symbol,
                    side="",
                    entry_price=0,
                    message=f"Session started: {self.strategy_spec.name} ({self.mode} mode)",
                )
            )

        self._running = True
        _register_session(self)
        logger.info(
            f"Paper Trading Session {self.session_id} started: "
            f"{self.strategy_spec.symbol} | mode=paper"
        )

        # 6. Keep running — continuous evaluation loop
        try:
            await self.engine._poll_candles()
        finally:
            self._running = False
            _unregister_session(self.session_id)

    async def _start_live(self):
        """Start live trading mode with MetaApi."""
        from .metaapi_client import MetaApiClient

        # 1. Create MetaApiClient
        self.client = MetaApiClient(self.api_token)

        # 2. Connect to specific account
        ok = await self.client.connect(self.account_id)
        if not ok:
            raise RuntimeError(f"Failed to connect to MetaApi account {self.account_id}")

        # 3. Create order manager with notification service
        self.order_mgr = OrderManager(self.client, self.strategy_spec, self.session_id,
                                     notification_service=self.notifications)

        # 4. Create live engine
        self.engine = LiveEngine(
            spec=self.strategy_spec,
            metaapi_client=self.client,
            order_manager=self.order_mgr,
            session_id=self.session_id,
        )

        # 5. Start engine
        await self.engine.start()

        # 6. Fire session_started notification
        if self.notifications:
            import asyncio
            asyncio.create_task(
                self.notifications.notify(
                    event_type="session_started",
                    session_id=self.session_id,
                    strategy_name=self.strategy_spec.name,
                    symbol=self.strategy_spec.symbol,
                    side="",
                    entry_price=0,
                    message=f"Session started: {self.strategy_spec.name} (live mode)",
                )
            )

        self._running = True
        _register_session(self)
        logger.info(
            f"Live Trading Session {self.session_id} started: "
            f"{self.strategy_spec.symbol} | mode=live"
        )

        # 6. Keep running — continuous evaluation loop
        try:
            await self.engine._poll_candles()
        finally:
            self._running = False
            _unregister_session(self.session_id)

    async def stop(self):
        """Stop the session, close trades, disconnect."""
        if not self._running:
            return

        self._running = False

        if self.engine:
            await self.engine.stop()

        if self.order_mgr:
            await self.order_mgr.close_all()

        if self.client:
            await self.client.stop()

        # Fire session_stopped notification
        if self.notifications:
            asyncio.create_task(
                self.notifications.notify(
                    event_type="session_stopped",
                    session_id=self.session_id,
                    strategy_name=self.strategy_spec.name,
                    symbol=self.strategy_spec.symbol,
                    side="",
                    entry_price=0,
                    message=f"Session stopped: {self.strategy_spec.name}",
                )
            )

        logger.info(f"LiveSession {self.session_id} stopped")

    def get_status(self) -> dict:
        """Session status for API response."""
        if not self.engine:
            return {"running": False, "error": "Not started"}

        engine_status = self.engine.get_status()
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "strategy_name": self.strategy_spec.name,
            **engine_status,
        }

    def get_trades_info(self) -> dict:
        """Get in-memory trade info (open trades, equity, P&L, counts)."""
        if not self.order_mgr:
            return {"open_trades": [], "total_trades": 0, "win_rate": 0.0,
                    "equity": 0.0, "balance": 0.0, "daily_pnl": 0.0}

        # Gather open trades
        open_trades = []
        for t in self.order_mgr._open_trades.values():
            open_trades.append({
                "id": t.trade_id,
                "metaapi_trade_id": t.trade_id,
                "side": t.side,
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                "entry_price": t.entry_price,
                "volume": t.volume,
                "sl": t.sl,
                "tp": t.tp,
                "profit": t.profit or 0.0,
                "pips": t.pips if hasattr(t, 'pips') else None,
            })

        # Calculate summary from order_manager
        all_trades = list(self.order_mgr._open_trades.values()) + self.order_mgr._closed_trades
        total = len(all_trades)
        wins = sum(1 for t in self.order_mgr._closed_trades if (t.profit or 0) > 0)
        win_rate = (wins / total * 100) if total > 0 else 0.0

        # Get equity from paper client
        equity = 0.0
        balance = 0.0
        if self.client and hasattr(self.client, '_equity'):
            equity = self.client._equity
            balance = self.client._balance

        daily_pnl = sum(t.profit or 0 for t in self.order_mgr._closed_trades)

        return {
            "open_trades": open_trades,
            "total_trades": total,
            "win_rate": win_rate,
            "equity": round(equity, 2),
            "balance": round(balance, 2),
            "daily_pnl": round(daily_pnl, 2),
        }
