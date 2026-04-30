"""
Live trading engine — connects StrategySpec execution to live markets via MetaApi.

Modules:
  metaapi_client   — WebSocket connection to MetaApi.cloud (ticks, account, trades)
  live_engine      — Bar builder + signal evaluation loop (ticks → bars → signals)
  order_manager    — Executes signals as real orders (market, SL/TP, close)

Usage:
    from engine.live_trading import LiveSession

    session = LiveSession(api_token, account_id, strategy_id, db)
    await session.start()
    # ...
    await session.stop()
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from engine.models import StrategySpec

from .metaapi_client import MetaApiClient
from .order_manager import OrderManager
from .live_engine import LiveEngine

logger = logging.getLogger(__name__)


class LiveSession:
    """
    Top-level live trading session.
    
    Wires together: MetaApi connection → bar builder → signal evaluation → orders.
    
    Manages the full lifecycle: connect → preload history → evaluate → execute → close.
    """

    def __init__(self, api_token: str, account_id: int, strategy_spec: StrategySpec,
                 db: Session, session_id: int, mode: str = "paper"):
        self.api_token = api_token
        self.account_id = account_id
        self.strategy_spec = strategy_spec
        self.db = db
        self.session_id = session_id
        self.mode = mode  # "paper" or "live"

        self.metaapi: Optional[MetaApiClient] = None
        self.engine: Optional[LiveEngine] = None
        self.order_mgr: Optional[OrderManager] = None
        self._running = False

    async def start(self):
        """Start the live session: connect to MetaApi, init engine, begin trading."""
        if self._running:
            return

        # 1. Connect to MetaApi
        self.metaapi = MetaApiClient(self.api_token, self.account_id)
        await self.metaapi.start()

        # 2. Create order manager
        self.order_mgr = OrderManager(self.metaapi, self.strategy_spec, self.session_id)

        # 3. Create live engine
        self.engine = LiveEngine(
            spec=self.strategy_spec,
            metaapi_client=self.metaapi,
            order_manager=self.order_mgr,
            session_id=self.session_id,
            api_token=self.api_token,
        )

        # 4. Start engine (preloads history, subscribes to ticks)
        await self.engine.start()

        self._running = True
        logger.info(
            f"LiveSession {self.session_id} started: "
            f"{self.strategy_spec.symbol} | {self.mode} mode"
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

        if self.metaapi:
            await self.metaapi.stop()

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
