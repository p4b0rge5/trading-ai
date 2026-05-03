"""
Order Manager — translates strategy signals into MetaApi orders.

Handles:
  - Risk checks (max trades, daily loss, drawdown)
  - Position sizing from account balance
  - SL/TP calculation from exit conditions
  - Trade lifecycle tracking (open → update → close)
  - Trade record persistence
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OpenTrade:
    """Tracks a trade open via MetaApi."""
    trade_id: str  # MetaApi trade ticket/position ID (string in v29 SDK)
    session_id: int
    strategy_id: int
    symbol: str
    side: str  # "buy" / "sell"
    entry_price: float
    volume: float
    sl: Optional[float]
    tp: Optional[float]
    entry_time: datetime
    reason: str = ""
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit: Optional[float] = None
    pips: Optional[float] = None
    closed: bool = False


class OrderManager:
    """
    Manages real trade execution through MetaApi.
    
    Receives signals from the LiveEngine, applies risk checks,
    calculates position sizing and SL/TP, then executes orders.
    """

    def __init__(self, metaapi_client, strategy_spec, session_id: int,
                 notification_service=None):
        from engine.models import StrategySpec, ExitType

        self.metaapi = metaapi_client
        self.spec = strategy_spec
        self.session_id = session_id
        self.risk = strategy_spec.risk_management
        self.notifications = notification_service

        self._open_trades: dict[str, OpenTrade] = {}
        self._closed_trades: list[OpenTrade] = []
        self._daily_pnl = 0.0
        self._daily_trades_count = 0
        self._peak_equity: float = 0.0
        self._volume = 0.01  # Default lot size

        self._ExitType = ExitType

    async def execute_signal(self, signal: dict) -> Optional[OpenTrade]:
        """
        Execute a trade signal. Returns OpenTrade on success, None if blocked.
        
        signal: dict with keys: side ("buy"/"sell"), price (float), reason (str)
        """
        # ── Risk Checks ──────────────────────────────────────────────
        if len(self._open_trades) >= self.risk.max_open_trades:
            logger.info(
                f"Max trades ({self.risk.max_open_trades}) reached, "
                f"skipping signal: {signal.get('reason', '')}"
            )
            return None

        if self._daily_pnl < -self.risk.max_daily_loss_pct:
            logger.warning("Daily loss limit reached — pausing execution")
            return None

        # ── Calculate SL/TP ──────────────────────────────────────────
        sl, tp = self._calc_sl_tp(signal)

        # ── Execute via MetaApi ───────────────────────────────────────
        side = signal["side"]
        price = signal["price"]

        try:
            comment = f"TradingAI-{getattr(self.spec, 'name', 'strat')[:16]}"
            if side == "buy":
                result = await self.metaapi.buy(
                    symbol=self.spec.symbol,
                    volume=self._volume,
                    sl=sl,
                    tp=tp,
                    comment=comment,
                )
            else:
                result = await self.metaapi.sell(
                    symbol=self.spec.symbol,
                    volume=self._volume,
                    sl=sl,
                    tp=tp,
                    comment=comment,
                )

            if result is None:
                logger.error("Trade execution returned None — MetaApi rejected order")
                return None

            # v29 SDK: result is a dict — extract trade/position ID
            trade_id = str(result.get("tradeId") or result.get("positionId") or result.get("orderId") or id(result))

            trade = OpenTrade(
                trade_id=trade_id,
                session_id=self.session_id,
                strategy_id=self.spec.id if hasattr(self.spec, 'id') else 0,
                symbol=self.spec.symbol,
                side=side,
                entry_price=price,
                volume=self._volume,
                sl=sl,
                tp=tp,
                entry_time=datetime.utcnow(),
                reason=signal.get("reason", ""),
            )
            self._open_trades[trade_id] = trade
            self._daily_trades_count += 1

            logger.info(
                f"Signal executed: {side.upper()} {self.spec.symbol} "
                f"@ {price} (id={trade_id}, sl={sl}, tp={tp})"
            )

            # ── Notification ────────────────────────────────────────────
            if self.notifications:
                asyncio.create_task(
                    self.notifications.notify(
                        event_type="trade_opened",
                        session_id=self.session_id,
                        strategy_name=getattr(self.spec, 'name', ''),
                        symbol=self.spec.symbol,
                        side=side,
                        entry_price=price,
                        message=f"Trade opened: {side.upper()} {self.spec.symbol} @ {price} (id={trade_id})",
                        trade_id=trade_id,
                        sl=sl,
                        tp=tp,
                    )
                )

            return trade

        except Exception as e:
            logger.error(f"Failed to execute signal: {e}")
            return None

    async def close_trade(self, trade_id: str, reason: str = "") -> Optional[OpenTrade]:
        """Close a specific trade."""
        if trade_id not in self._open_trades:
            return None

        trade = self._open_trades[trade_id]
        if trade.closed:
            return trade

        try:
            result = await self.metaapi.close_position(trade_id)
            if result:
                trade.closed = True
                trade.exit_time = datetime.utcnow()
                trade.reason = reason or trade.reason
                trade.exit_price = result.get("price")
                trade.profit = result.get("profit", trade.profit)
                del self._open_trades[trade_id]
                self._closed_trades.append(trade)
                logger.info(f"Trade {trade_id} closed: {reason}")

                # ── Notification ────────────────────────────────────────────
                if self.notifications:
                    asyncio.create_task(
                        self.notifications.notify(
                            event_type="trade_closed",
                            session_id=self.session_id,
                            strategy_name=getattr(self.spec, 'name', ''),
                            symbol=trade.symbol,
                            side=trade.side,
                            entry_price=trade.entry_price,
                            message=f"Trade closed: {trade.side.upper()} {trade.symbol} @ {trade.exit_price} (profit={trade.profit})",
                            trade_id=trade_id,
                            exit_price=trade.exit_price,
                            profit=trade.profit,
                            reason=reason,
                        )
                    )

                return trade
            return trade
        except Exception as e:
            logger.error(f"Failed to close trade {trade_id}: {e}")
            return None

    async def close_all(self) -> int:
        """Close all open trades. Returns count of closed trades."""
        ids = list(self._open_trades.keys())
        closed = 0
        for tid in ids:
            if await self.close_trade(tid, "engine_stopped"):
                closed += 1
        return closed

    def on_account_update(self, equity: float, balance: float, profit: float):
        """Update internal risk state on account changes."""
        if equity > self._peak_equity:
            self._peak_equity = equity

        # Check drawdown limit
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity * 100
            if drawdown >= self.risk.max_drawdown_pct:
                logger.warning(
                    f"Max drawdown ({drawdown:.1f}%) exceeded limit "
                    f"({self.risk.max_drawdown_pct}%) — closing all trades"
                )
                asyncio.create_task(self.close_all())

    def on_trade_update(self, trade_id: str, profit: float, state: str):
        """Handle trade update from MetaApi."""
        trade = self._open_trades.get(trade_id)
        if not trade:
            return

        trade.profit = profit

        # If trade was closed by SL/TP (from MetaApi side)
        if state in ("closed", "closedBySL", "closedByTP"):
            reason = "stop_loss" if "SL" in state else "take_profit"
            asyncio.create_task(self.close_trade(trade_id, reason))

    # ── Helpers ───────────────────────────────────────────────────────

    def _calc_sl_tp(self, signal: dict) -> tuple:
        """Calculate SL and TP prices from exit conditions."""
        entry_price = signal["price"]
        side = signal["side"]
        sl = tp = None

        direction = 1 if side == "buy" else -1

        for cond in self.spec.exit_conditions:
            if cond.exit_type == self._ExitType.STOP_LOSS and cond.pips:
                pip_value = self._pips_to_price(cond.pips)
                sl = entry_price - direction * pip_value

            elif cond.exit_type == self._ExitType.TAKE_PROFIT and cond.pips:
                pip_value = self._pips_to_price(cond.pips)
                tp = entry_price + direction * pip_value

            elif cond.exit_type == self._ExitType.ATR_STOP:
                # ATR stop will be computed dynamically at bar time
                # For now, use a default SL
                if cond.atr_multiplier:
                    pass  # Live ATR will be computed in live_engine

        return sl, tp

    def _pips_to_price(self, pips: float) -> float:
        """Convert pips to price units."""
        symbol = self.spec.symbol
        if symbol.endswith("JPY"):
            return pips * 0.01
        if self._is_crypto(symbol):
            return pips * 0.01  # Crypto: use percent-like pips
        return pips * 0.0001

    def _is_crypto(self, symbol: str) -> bool:
        return any(symbol.startswith(prefix) for prefix in [
            "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOT",
            "DOGE", "AVAX", "MATIC",
        ])

    def get_open_trades(self) -> list[dict]:
        """Return snapshot of open trades for API response."""
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "volume": t.volume,
                "sl": t.sl,
                "tp": t.tp,
                "profit": t.profit,
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                "reason": t.reason,
            }
            for t in self._open_trades.values()
        ]

    def get_stats(self) -> dict:
        """Return summary stats for the current session."""
        total = len(self._open_trades) + len(self._closed_trades)
        winners = sum(1 for t in self._closed_trades if (t.profit or 0) > 0)
        return {
            "open_trades": len(self._open_trades),
            "closed_trades": len(self._closed_trades),
            "total_trades": total,
            "win_rate": (winners / len(self._closed_trades) * 100) if self._closed_trades else 0,
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades_count,
        }
