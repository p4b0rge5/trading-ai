"""
Backtest routes: run backtests, get results, get trades.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import get_current_user
from .config import settings
from .database import get_db, User, Strategy, Backtest, Trade
from .schemas import BacktestRequest, BacktestSummary, TradeResponse
from engine.backtester import Backtester
from engine.sample_data import generate_sample_data
from engine.data_fetcher import fetch_ohlcv

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])


@router.get("/summary", response_model=list[BacktestSummary])
def list_backtests(
    strategy_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List backtest summaries (for current user's strategies)."""
    query = (
        db.query(Backtest)
        .join(Strategy)
        .filter(Strategy.user_id == current_user.id)
    )
    if strategy_id:
        query = query.filter(Backtest.strategy_id == strategy_id)
    return query.order_by(Backtest.created_at.desc()).all()


@router.get("/{backtest_id}", response_model=dict)
def get_backtest(
    backtest_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full backtest result with trades."""
    bt = db.query(Backtest).filter(
        Backtest.id == backtest_id,
        Backtest.strategy_id.in_(
            db.query(Strategy.id).filter(Strategy.user_id == current_user.id)
        ),
    ).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")

    trades = db.query(Trade).filter(Trade.backtest_id == backtest_id).all()

    return {
        "backtest": BacktestSummary.model_validate(bt).model_dump(),
        "trades": [TradeResponse.model_validate(t).model_dump() for t in trades],
    }


@router.post("/", response_model=BacktestSummary)
def run_backtest(
    request: BacktestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run a backtest for a saved strategy.
    Generates sample data, runs the engine, saves results.
    """
    # Get strategy
    strategy = db.query(Strategy).filter(
        Strategy.id == request.strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    from engine.models import StrategySpec
    spec = StrategySpec(**strategy.spec_json)

    # Fetch data — real market data by default, fall back to sample
    try:
        data = fetch_ohlcv(
            symbol=spec.symbol,
            n_bars=request.bars,
            timeframe=spec.timeframe.value if hasattr(spec.timeframe, 'value') else str(spec.timeframe),
            use_real=True,
        )
    except Exception:
        data = generate_sample_data(
            symbol=spec.symbol,
            n_bars=request.bars,
            timeframe=spec.timeframe.value if hasattr(spec.timeframe, 'value') else str(spec.timeframe),
        )

    # Run backtest
    backtester = Backtester(spec)
    bt_result = backtester.run(data)

    # Save to DB
    bt = Backtest(
        strategy_id=strategy.id,
        bars_count=request.bars,
        total_trades=bt_result.total_trades,
        win_rate=bt_result.win_rate,
        net_profit=bt_result.net_profit,
        total_return_pct=bt_result.total_return_pct,
        max_drawdown_pct=bt_result.max_drawdown_pct,
        sharpe_ratio=bt_result.sharpe_ratio,
        profit_factor=bt_result.profit_factor,
        results_json=bt_result.model_dump() if hasattr(bt_result, 'model_dump') else {},
        chart_path=bt_result.chart_path,
    )
    db.add(bt)
    db.commit()
    db.refresh(bt)

    # Save individual trades
    for i, trade in enumerate(bt_result.trades[:200], 0):  # Cap at 200 per backtest
        db_trade = Trade(
            backtest_id=bt.id,
            trade_number=i + 1,
            side=trade.side.upper(),
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            exit_time=trade.exit_time,
            exit_price=trade.exit_price,
            profit=trade.profit,
            reason=trade.reason or "",
            duration_minutes=int(trade.duration_bars * 60) if hasattr(trade, 'duration_bars') else 0,
        )
        db.add(db_trade)
    db.commit()

    return BacktestSummary.model_validate(bt)
