"""
Prompt System Orchestrator

The main entry point for the prompt-to-strategy pipeline:

    user text → LLM → JSON → Pydantic validate → StrategySpec → backtest preview

Also provides the "refinement loop" where the user can adjust the strategy
based on backtest results.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.models import StrategySpec
from engine.backtester import Backtester, BacktestResult
from engine.sample_data import generate_sample_data
from engine.data_fetcher import fetch_ohlcv
from prompt_system.llm_client import create_client, MockLLMClient, OpenAIClient

logger = logging.getLogger(__name__)


@dataclass
class StrategyResult:
    """Complete output of the prompt-to-strategy pipeline."""

    user_prompt: str
    strategy: StrategySpec
    llm_calls: int
    validation_attempts: int
    backtest: BacktestResult | None = None
    raw_json: str | None = None
    chart_path: str | None = None


class PromptOrchestrator:
    """
    Main orchestrator: natural language → validated strategy → backtest.

    Usage:
        orchestrator = PromptOrchestrator()
        result = orchestrator.create_strategy("Quero operar golden cross...")
    """

    def __init__(
        self,
        use_mock_llm: bool = True,
        llm_model: str = "gpt-4o",
        openai_api_key: str | None = None,
    ):
        self.llm = create_client(
            use_mock=use_mock_llm,
            model=llm_model,
            api_key=openai_api_key,
        )
        self._history: list[dict[str, Any]] = []

    def create_strategy(
        self,
        user_prompt: str,
        run_backtest: bool = True,
        backtest_bars: int = 5000,
        chart_output: str | None = None,
    ) -> StrategyResult:
        """
        Complete pipeline: prompt → LLM → validate → backtest → result.

        Args:
            user_prompt: Natural language strategy description
            run_backtest: If True, immediately run backtest on sample data
            backtest_bars: Number of bars to generate for backtest
            chart_output: Path to save backtest chart PNG
        """
        logger.info(f"Creating strategy from prompt: {user_prompt[:100]}...")

        # Step 1: LLM generation with auto-refinement
        spec = self.llm.generate(user_prompt)
        llm_calls = self.llm.call_count

        # Step 2: Generate raw JSON for record
        raw_json = json.dumps(spec.model_dump(), indent=2, default=str)

        result = StrategyResult(
            user_prompt=user_prompt,
            strategy=spec,
            llm_calls=llm_calls,
            validation_attempts=llm_calls,
        )

        # Step 3: Backtest (optional) — use real data if possible
        if run_backtest:
            logger.info(f"Running backtest with {backtest_bars} bars...")
            try:
                data = fetch_ohlcv(
                    symbol=spec.symbol,
                    n_bars=backtest_bars,
                    timeframe=spec.timeframe.value,
                    use_real=True,
                )
            except Exception:
                logger.info("Falling back to sample data")
                data = generate_sample_data(
                    symbol=spec.symbol,
                    n_bars=backtest_bars,
                    timeframe=spec.timeframe.value,
                )
            backtester = Backtester(spec)
            bt_result = backtester.run(data, chart_output=chart_output)
            result.backtest = bt_result
            result.chart_path = bt_result.chart_path

        # Store in history
        self._history.append({
            "prompt": user_prompt,
            "strategy_id": spec.name,
            "spec": spec.model_dump(),
        })

        logger.info(f"✅ Strategy created: {spec.summary()}")
        return result

    def refine(
        self,
        existing_spec: StrategySpec,
        feedback: str,
        run_backtest: bool = True,
    ) -> StrategyResult:
        """
        Refine an existing strategy based on user feedback.

        Args:
            existing_spec: Current strategy spec
            feedback: What the user wants to change
        """
        refined_prompt = (
            f"MODIFY the following strategy based on this feedback:\n\n"
            f"Current strategy:\n{json.dumps(existing_spec.model_dump(), indent=2, default=str)}\n\n"
            f"Feedback: {feedback}\n\n"
            f"Return the COMPLETE modified strategy JSON."
        )

        new_spec = self.llm.generate(refined_prompt)
        llm_calls = self.llm.call_count

        result = StrategyResult(
            user_prompt=f"[REFINE] {feedback}",
            strategy=new_spec,
            llm_calls=llm_calls,
            validation_attempts=llm_calls,
        )

        if run_backtest:
            try:
                data = fetch_ohlcv(
                    symbol=new_spec.symbol,
                    n_bars=5000,
                    timeframe=new_spec.timeframe.value,
                    use_real=True,
                )
            except Exception:
                data = generate_sample_data(
                    symbol=new_spec.symbol,
                    n_bars=5000,
                    timeframe=new_spec.timeframe.value,
                )
            backtester = Backtester(new_spec)
            bt_result = backtester.run(data)
            result.backtest = bt_result

        return result

    def export_spec(
        self,
        spec: StrategySpec,
        output_path: str,
    ) -> str:
        """Save strategy spec to a JSON file."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec.model_dump(), indent=2, default=str))
        logger.info(f"Strategy exported to {path}")
        return str(path)

    @classmethod
    def load_spec(cls, path: str) -> StrategySpec:
        """Load a strategy spec from a JSON file."""
        data = json.loads(Path(path).read_text())
        return StrategySpec(**data)
