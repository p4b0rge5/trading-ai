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

import logging
from datetime import datetime
from typing import Optional, Any

from sqlalchemy.orm import Session

from engine.models import StrategySpec

from .live_engine import LiveEngine
from .order_manager import OrderManager

logger = logging.getLogger(__name__)


class LiveSession:
    """
    Top-level live/paper trading session.

    Wires together: data client → bar builder → signal evaluation → orders.

    Manages the full lifecycle: connect → preload history → evaluate → execute → close.
    """

    def __init__(self, api_token: str, account_id: Any, strategy_spec: StrategySpec,
                 db: Session, session_id: int, mode: str = "paper"):
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

        # 3. Create order manager
        self.order_mgr = OrderManager(self.client, self.strategy_spec, self.session_id)

        # 4. Create live engine
        self.engine = LiveEngine(
            spec=self.strategy_spec,
            metaapi_client=self.client,
            order_manager=self.order_mgr,
            session_id=self.session_id,
        )

        # 5. Start engine
        await self.engine.start()

        self._running = True
        logger.info(
            f"Paper Trading Session {self.session_id} started: "
            f"{self.strategy_spec.symbol} | mode=paper"
        )

    async def _start_live(self):
        """Start live trading mode with MetaApi."""
        from .metaapi_client import MetaApiClient

        # 1. Create MetaApiClient
        self.client = MetaApiClient(self.api_token)

        # 2. Connect to specific account
        ok = await self.client.connect(self.account_id)
        if not ok:
            raise RuntimeError(f"Failed to connect to MetaApi account {self.account_id}")

        # 3. Create order manager
        self.order_mgr = OrderManager(self.client, self.strategy_spec, self.session_id)

        # 4. Create live engine
        self.engine = LiveEngine(
            spec=self.strategy_spec,
            metaapi_client=self.client,
            order_manager=self.order_mgr,
            session_id=self.session_id,
        )

        # 5. Start engine
        await self.engine.start()

        self._running = True
        logger.info(
            f"Live Trading Session {self.session_id} started: "
            f"{self.strategy_spec.symbol} | mode=live"
        )

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
