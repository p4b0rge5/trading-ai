"""
LLM Client — OpenAI integration with retry, validation, and auto-refinement.

Handles the conversation loop:
  1. Send user prompt + system prompt + JSON schema → LLM
  2. Parse response as JSON
  3. Validate against StrategySpec (Pydantic)
  4. If invalid, send error back to LLM for correction (up to N retries)
  5. Return valid StrategySpec or raise after max retries
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import ValidationError

from engine.models import (
    ConditionType, ComparisonOp, ExitType, IndicatorType, StrategySpec,
    IndicatorSpec, EntryCondition, ExitCondition, RiskManagement, Timeframe,
)
from prompt_system.schema import get_json_schema
from prompt_system.prompts import build_system_prompt

logger = logging.getLogger(__name__)

# ─── Timeframe mapping ──────────────────────────────────────────────────

TIMEFRAME_ALIASES = {
    "1 minuto": "1m", "1m": "1m", "1min": "1m",
    "5 minutos": "5m", "5m": "5m", "5min": "5m",
    "15 minutos": "15m", "15m": "15m", "15min": "15m",
    "30 minutos": "30m", "30m": "30m", "30min": "30m",
    "1 hora": "1h", "1h": "1h", "hora": "1h", "horário": "1h",
    "4 horas": "4h", "4h": "4h",
    "diário": "1d", "1 dia": "1d", "1d": "1d", "daily": "1d",
    "semanal": "1w", "1w": "1w", "weekly": "1w",
}

TIMEFRAME_VALUES = [t.value for t in Timeframe]


def _parse_timeframe(text: str) -> str:
    text_lower = text.lower()
    for alias, tf in TIMEFRAME_ALIASES.items():
        if alias in text_lower:
            return tf
    return "1h"  # default


def _parse_symbol(text: str) -> str:
    # Match patterns like EURUSD, GBP/USD, BTC-USD, etc.
    pairs = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
        "GBPCAD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY",
        "BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT",
    ]
    text_upper = text.upper().replace("/", "").replace(" ", "")
    for pair in pairs:
        if pair in text_upper:
            return pair
    return "EURUSD"


def _extract_periods(text: str) -> tuple[int, int]:
    """Extract two numbers from text like 'SMA 10 e SMA 50' or '50 e 200'."""
    numbers = [int(x) for x in re.findall(r'(\d+)', text) if int(x) < 500]
    if len(numbers) >= 2:
        return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
    return 10, 50


def _extract_pips(text: str) -> tuple[float, float]:
    """Extract SL and TP pips from text."""
    sl = tp = 50.0
    sl_match = re.search(r'stop\s*(?:loss\s*)?(\d+)', text, re.I)
    tp_match = re.search(r'take\s*(?:profit\s*)?(\d+)', text, re.I)
    if sl_match:
        sl = float(sl_match.group(1))
    if tp_match:
        tp = float(tp_match.group(1))
    return sl, tp


# ─── Smart Mock LLM ─────────────────────────────────────────────────────

class MockLLMClient:
    """
    Simulates LLM behavior by parsing Portuguese/English prompts and
    building appropriate StrategySpec objects. Much smarter than returning
    the same spec for everything — actually reads the prompt.
    """

    def __init__(self):
        self.call_count = 0

    def generate(self, user_prompt: str, max_retries: int = 3) -> StrategySpec:
        self.call_count += 1
        logger.info(f"Mock LLM: generating from: {user_prompt[:80]}...")

        text = user_prompt.lower()
        symbol = _parse_symbol(user_prompt)
        timeframe = _parse_timeframe(user_prompt)

        # Detect strategy type
        spec = self._classify_and_build(user_prompt, symbol, timeframe)
        return spec

    def _classify_and_build(self, text: str, symbol: str, timeframe: str) -> StrategySpec:
        indicators = []
        entry_conditions = []
        exit_conditions = []

        sl, tp = _extract_pips(text)
        fast, slow = _extract_periods(text)
        if fast == slow:
            fast, slow = 10, 50

        # ── MACD ──
        if "macd" in text:
            indicators.append({"indicator_type": "macd", "period": 26,
                               "fast_period": 12, "slow_period": 26, "source": "close"})
            entry_conditions.append({
                "condition_type": "crossover",
                "indicator": "macd", "indicator_b": "macd",
                "params": {"fast_period": 12, "slow_period": 26},
                "description": "MACD cruza acima do Signal",
            })

        # ── RSI ──
        elif "rsi" in text:
            rsi_period = 14
            for m in re.findall(r'rsi\s*(\d+)', text):
                rsi_period = int(m)
                break
            indicators.append({"indicator_type": "rsi", "period": rsi_period, "source": "close"})

            if any(w in text for w in ["sobrevendido", "abaixo de 30", "abaixo de 20", "acumulaçã"]):
                entry_conditions.append({
                    "condition_type": "threshold",
                    "indicator": "rsi", "operator": "<", "value": 30,
                    "description": f"RSI abaixo de 30 (sobrevendido)",
                })
            elif any(w in text for w in ["sobrecomprado", "acima de 70", "vender"]):
                entry_conditions.append({
                    "condition_type": "threshold",
                    "indicator": "rsi", "operator": ">", "value": 70,
                    "description": f"RSI acima de 70 (sobrecomprado)",
                })
            else:
                entry_conditions.append({
                    "condition_type": "threshold",
                    "indicator": "rsi", "operator": ">", "value": 50,
                    "description": "RSI acima de 50",
                })

        # ── Bollinger ──
        elif "bollinger" in text or "banda" in text:
            indicators.append({"indicator_type": "bollinger", "period": 20, "source": "close"})
            indicators.append({"indicator_type": "rsi", "period": 14, "source": "close"})
            entry_conditions.append({
                "condition_type": "threshold",
                "indicator": "rsi", "operator": ">", "value": 30,
                "description": "RSI > 30 como confirmação",
            })

        # ── Stochastic ──
        elif "estocástic" in text or "stochastic" in text or "%k" in text:
            indicators.append({"indicator_type": "stochastic", "period": 14, "source": "close"})
            indicators.append({"indicator_type": "rsi", "period": 14, "source": "close"})
            entry_conditions.append({
                "condition_type": "crossover",
                "indicator": "stochastic",
                "params": {"fast_period": 14, "slow_period": 3},
                "description": "%K cruza acima %D na zona de sobrevenda",
            })

        # ── ADX ──
        elif "adx" in text:
            indicators.append({"indicator_type": "adx", "period": 14, "source": "close"})
            indicators.append({"indicator_type": "sma", "period": slow, "source": "close"})
            entry_conditions.append({
                "condition_type": "threshold",
                "indicator": "adx", "operator": ">", "value": 25,
                "description": "ADX > 25 (tendência forte)",
            })

        # ── ATR ──
        elif "atr" in text and "breakout" in text:
            indicators.append({"indicator_type": "atr", "period": 14, "source": "close"})
            indicators.append({"indicator_type": "sma", "period": slow, "source": "close"})
            entry_conditions.append({
                "condition_type": "threshold",
                "indicator": "atr", "operator": ">", "value": 0.001,
                "description": "ATR acima da média (volatilidade crescendo)",
            })

        # ── Default: SMA crossover ──
        else:
            indicators.append({"indicator_type": "sma", "period": fast, "source": "close"})
            indicators.append({"indicator_type": "sma", "period": slow, "source": "close"})
            entry_conditions.append({
                "condition_type": "crossover",
                "indicator": "sma", "indicator_b": "sma",
                "params": {"fast_period": fast, "slow_period": slow},
                "description": f"SMA {fast} cruza acima SMA {slow}",
            })

        # Always ensure at least RSI if not already present
        has_rsi = any(ind.get("indicator_type") == "rsi" for ind in indicators)
        if not has_rsi:
            indicators.append({"indicator_type": "rsi", "period": 14, "source": "close"})
            if not entry_conditions:
                entry_conditions.append({
                    "condition_type": "threshold",
                    "indicator": "rsi", "operator": ">", "value": 30,
                    "description": "RSI acima de 30",
                })

        # Exit conditions
        exit_conditions.append({"exit_type": "stop_loss", "pips": sl})
        exit_conditions.append({"exit_type": "take_profit", "pips": tp})

        name = f"Auto: {text[:50]}"
        if len(entry_conditions) == 0:
            entry_conditions.append({
                "condition_type": "threshold",
                "indicator": "rsi", "operator": ">", "value": 50,
                "description": "RSI > 50",
            })

        return StrategySpec(
            name=name,
            description=text[:200],
            symbol=symbol,
            timeframe=timeframe,
            indicators=indicators,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            risk_management={
                "position_size_pct": 2.0,
                "max_open_trades": 3,
                "max_daily_loss_pct": 5.0,
                "max_drawdown_pct": 15.0,
            },
        )


# ─── Real OpenAI Client ──────────────────────────────────────────────────

class OpenAIClient:
    """Production client using OpenAI API with JSON schema constraints."""

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        self.model = model
        self._client = None
        self._api_key = api_key
        self.call_count = 0

    def _ensure_client(self):
        if self._client is None:
            try:
                from openai import OpenAI as _OpenAI
                kwargs = {}
                if self._api_key:
                    kwargs["api_key"] = self._api_key
                self._client = _OpenAI(**kwargs)
            except ImportError:
                raise ImportError("OpenAI SDK not installed. pip install openai")

    def generate(self, user_prompt: str, max_retries: int = 3) -> StrategySpec:
        self._ensure_client()
        schema = get_json_schema()
        system = build_system_prompt()

        for attempt in range(1, max_retries + 1):
            self.call_count += 1
            logger.info(f"LLM call attempt {attempt}/{max_retries}")

            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "StrategySpec",
                            "schema": schema,
                            "strict": True,
                        },
                    },
                    temperature=0.1,
                )

                raw_json = response.choices[0].message.content
                data = json.loads(raw_json)
                spec = StrategySpec(**data)
                logger.info(f"✅ Strategy validated on attempt {attempt}")
                return spec

            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning(f"Validation error: {e}")
                system += f"\n\n⚠️ ERROR: {e}. Fix and return corrected JSON only."
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                if attempt == max_retries:
                    raise

        raise RuntimeError(f"Failed after {max_retries} attempts")


# ─── Factory ──────────────────────────────────────────────────────────────

def create_client(use_mock: bool = False, **kwargs):
    if use_mock:
        return MockLLMClient()
    return OpenAIClient(**kwargs)
