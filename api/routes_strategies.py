"""
Strategy routes: CRUD for saved strategies.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import get_current_user
from .config import settings
from .database import get_db, User, Strategy
from .schemas import StrategyCreate, StrategyResponse

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


@router.get("/", response_model=list[StrategyResponse])
def list_strategies(
    skip: int = 0,
    limit: int = 50,
    symbol: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all strategies (filtered by current user)."""
    query = db.query(Strategy).filter(Strategy.user_id == current_user.id)
    if symbol:
        query = query.filter(Strategy.symbol.ilike(f"%{symbol}%"))
    return query.order_by(Strategy.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{strategy_id}", response_model=StrategyResponse)
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific strategy by ID."""
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.post("/", response_model=StrategyResponse, status_code=201)
def create_strategy(
    data: StrategyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a new strategy spec to the database."""
    strategy = Strategy(
        name=data.name,
        description=data.description,
        symbol=data.symbol,
        timeframe=data.timeframe,
        spec_json=data.spec_json,
        user_id=current_user.id,
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


@router.put("/{strategy_id}", response_model=StrategyResponse)
def update_strategy(
    strategy_id: int,
    data: StrategyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing strategy."""
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    for field, value in data.model_dump().items():
        setattr(strategy, field, value)

    db.commit()
    db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}", status_code=204)
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a strategy and all its backtests."""
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    db.delete(strategy)
    db.commit()


@router.post("/from-prompt", response_model=dict)
def create_from_prompt(
    data: dict,  # {"prompt": str, "run_backtest": bool, "bars": int}
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a strategy from a natural language prompt.
    Uses the Prompt System (LLM -> StrategySpec -> save -> backtest).
    """
    from prompt_system.orchestrator import PromptOrchestrator

    prompt_text = data.get("prompt", "")
    run_bt = data.get("run_backtest", True)
    bars = data.get("bars", 5000)

    if not prompt_text or len(prompt_text) < 10:
        raise HTTPException(status_code=400, detail="Prompt too short")

    orchestrator = PromptOrchestrator(
        use_mock_llm=settings.use_mock_llm,
        openai_api_key=settings.openai_api_key or None,
    )

    result = orchestrator.create_strategy(
        user_prompt=prompt_text,
        run_backtest=run_bt,
        backtest_bars=bars,
    )

    # Save to DB
    strategy = Strategy(
        name=result.strategy.name,
        description=result.strategy.description,
        symbol=result.strategy.symbol,
        timeframe=result.strategy.timeframe.value if hasattr(result.strategy.timeframe, 'value') else result.strategy.timeframe,
        spec_json=result.strategy.model_dump(),
        user_id=current_user.id,
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)

    response = {
        "strategy": StrategyResponse.model_validate(strategy).model_dump(),
        "llm_calls": result.llm_calls,
    }
    if result.backtest:
        response["backtest"] = {
            "total_trades": result.backtest.total_trades,
            "win_rate": result.backtest.win_rate,
            "net_profit": result.backtest.net_profit,
            "total_return_pct": result.backtest.total_return_pct,
            "max_drawdown_pct": result.backtest.max_drawdown_pct,
            "sharpe_ratio": result.backtest.sharpe_ratio,
            "profit_factor": result.backtest.profit_factor,
        }

    return response


@router.get("/{strategy_id}/export/mql5")
def export_mql5(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export a strategy as MQL5 EA source code."""
    from engine.models import StrategySpec
    from engine.mql5_generator import generate_mql5, generate_mql5_filename
    from fastapi.responses import Response

    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id,
    ).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    spec = StrategySpec(**strategy.spec_json)
    code = generate_mql5(spec)
    filename = generate_mql5_filename(spec)

    return Response(
        content=code,
        media_type="text/x-mql5",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
