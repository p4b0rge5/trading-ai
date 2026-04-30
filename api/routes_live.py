"""
Live trading routes: manage live trading sessions.
"""

import asyncio
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import get_current_user
from .config import settings
from .database import get_db, User, Strategy, LiveSession, LiveTrade
from .schemas import LiveSessionCreate, LiveSessionResponse, LiveTradeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/live", tags=["live-trading"])

# Global registry of running live sessions
_active_sessions: dict[int, object] = {}


@router.get("/sessions")
def list_live_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all live trading sessions for the current user."""
    sessions = (
        db.query(LiveSession)
        .filter(LiveSession.user_id == current_user.id)
        .order_by(LiveSession.start_time.desc())
        .all()
    )
    result = []
    for s in sessions:
        s_dict = {
            "id": s.id,
            "strategy_id": s.strategy_id,
            "account_id": s.account_id,
            "mode": s.mode,
            "status": s.status,
            "equity": s.equity,
            "balance": s.balance,
            "daily_pnl": s.daily_pnl,
            "total_trades": s.total_trades,
            "win_rate": s.win_rate,
            "start_time": s.start_time.isoformat() if s.start_time else None,
            "end_time": s.end_time.isoformat() if s.end_time else None,
        }
        # Attach strategy name
        if s.strategy:
            s_dict["strategy_name"] = s.strategy.name
            s_dict["symbol"] = s.strategy.symbol
        result.append(s_dict)
    return result


@router.post("/sessions", status_code=201)
def create_live_session(
    request: LiveSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a new live trading session (paper or live mode)."""
    # Validate strategy exists and belongs to user
    strategy = db.query(Strategy).filter(
        Strategy.id == request.strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if not strategy:
        raise HTTPException(404, "Strategy not found")

    # For live mode, check MetaApi key is configured
    if request.mode == "live" and not settings.metaapi_api_key:
        raise HTTPException(
            status_code=503,
            detail="MetaApi API key not configured. Set METAAPI_API_KEY in .env or use mode='paper'",
        )

    # For paper mode, no account_id needed
    account_id = request.account_id or "PAPER"

    # Create DB session record
    session = LiveSession(
        strategy_id=strategy.id,
        user_id=current_user.id,
        account_id=account_id,
        mode=request.mode,
        status="running",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # Start live engine in background
    from engine.live_trading import LiveSession as LiveTradingSession
    from engine.models import StrategySpec

    spec = StrategySpec(**strategy.spec_json)

    api_token = settings.metaapi_api_key or ""
    live = LiveTradingSession(
        api_token=api_token,
        account_id=account_id,
        strategy_spec=spec,
        db=db,
        session_id=session.id,
        mode=request.mode,
    )

    # Store in registry and start in background thread
    _active_sessions[session.id] = live
    def _run_session():
        try:
            asyncio.run(live.start())
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Live session {session.id} crashed: {e}", exc_info=True)
    threading.Thread(target=_run_session, daemon=True).start()

    mode_label = "Paper Trading (yfinance)" if request.mode == "paper" else "Live (MetaApi)"
    return {
        "id": session.id,
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
        "mode": request.mode,
        "status": "running",
        "message": f"{mode_label} session created for {strategy.symbol}...",
    }


@router.get("/sessions/{session_id}")
def get_live_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get live session status, equity, open trades."""
    session = db.query(LiveSession).filter(
        LiveSession.id == session_id,
        LiveSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "Session not found")

    trades = (
        db.query(LiveTrade)
        .filter(LiveTrade.session_id == session_id, LiveTrade.closed == False)
        .order_by(LiveTrade.entry_time.desc())
        .all()
    )

    return {
        "session": {
            "id": session.id,
            "strategy_id": session.strategy_id,
            "account_id": session.account_id,
            "mode": session.mode,
            "status": session.status,
            "equity": session.equity,
            "balance": session.balance,
            "daily_pnl": session.daily_pnl,
            "total_trades": session.total_trades,
            "win_rate": session.win_rate,
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
        },
        "open_trades": [
            {
                "id": t.id,
                "metaapi_trade_id": t.metaapi_trade_id,
                "side": t.side,
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                "entry_price": t.entry_price,
                "volume": t.volume,
                "sl": t.sl,
                "tp": t.tp,
                "profit": t.profit,
                "pips": t.pips,
            }
            for t in trades
        ],
    }


@router.post("/sessions/{session_id}/stop")
def stop_live_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop a live trading session and close all trades."""
    session = db.query(LiveSession).filter(
        LiveSession.id == session_id,
        LiveSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "Session not found")

    # Stop engine and close trades
    live = _active_sessions.pop(session_id, None)
    if live:
        def _stop_session():
            asyncio.run(live.stop())
        threading.Thread(target=_stop_session, daemon=True).start()

    session.status = "stopped"
    session.end_time = __import__("datetime").datetime.utcnow()
    db.commit()

    return {"status": "stopped", "message": "Session stopped, all trades closed"}


@router.get("/sessions/{session_id}/trades")
def get_session_trades(
    session_id: int,
    closed_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get trades for a session."""
    session = db.query(LiveSession).filter(
        LiveSession.id == session_id,
        LiveSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "Session not found")

    query = db.query(LiveTrade).filter(
        LiveTrade.session_id == session_id
    )
    if closed_only:
        query = query.filter(LiveTrade.closed == True)
    else:
        query = query.filter(LiveTrade.closed == False)

    trades = query.order_by(LiveTrade.entry_time.desc()).all()
    return [
        {
            "id": t.id,
            "metaapi_trade_id": t.metaapi_trade_id,
            "side": t.side,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "entry_price": t.entry_price,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "exit_price": t.exit_price,
            "volume": t.volume,
            "sl": t.sl,
            "tp": t.tp,
            "profit": t.profit,
            "profit_pct": t.profit_pct,
            "pips": t.pips,
            "reason": t.reason,
            "closed": t.closed,
        }
        for t in trades
    ]
