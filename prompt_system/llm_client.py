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
    # Sort aliases by length descending so longer matches are checked first
    # (prevents "5 minutos" matching before "15 minutos")
    for alias, tf in sorted(TIMEFRAME_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in text_lower:
            return tf
    return "1h"  # default


def _parse_symbol(text: str) -> str:
    """Extract a known symbol from user prompt text.
    
    Checks against our full KNOWN_SYMBOLS list (B3, forex, crypto).
    Returns best match or 'EURUSD' as fallback.
    """
    from engine.data_fetcher import KNOWN_SYMBOLS

    text_upper = text.upper().replace("/", "").replace("-", "").replace(" ", "")

    # Also try the raw prompt with separators preserved (for B3 like PETR4, VALE3)
    text_raw_upper = text.upper()

    # 1) Check full KNOWN_SYMBOLS against cleaned text
    for sym in KNOWN_SYMBOLS:
        sym_clean = sym.replace("/", "").replace("-", "").replace(" ", "")
        if sym_clean in text_upper or sym in text_raw_upper:
            return sym

    # 2) Common forex/crypto without cleaning (handles GBP/USD etc.)
    pairs = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
        "GBPCAD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY",
        "BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT",
        "BNBUSD", "SOLUSD", "XRPUSD", "ADAUSD", "DOGEUSD",
    ]
    for pair in pairs:
        if pair in text_upper:
            return pair

    return "EURUSD"


def _generate_strategy_name(text: str, symbol: str, timeframe: str, indicators: list) -> str:
    """Generate a clear, concise strategy name instead of truncating the prompt.

    Examples:
      'PETR4 · SMA 10/50 Cross · 1D'
      'EURUSD · RSI Oversold · 1H'
      'BTCUSD · MACD Signal · 4H'
    """
    import re

    # Determine primary strategy type — prioritize non-RSI indicators
    primary_type = None
    primary_period = None
    sma_periods = []

    for ind in indicators:
        if not isinstance(ind, dict):
            continue
        itype = ind.get("indicator_type", "")
        period = ind.get("period", "")

        if itype in ("macd", "bollinger", "stochastic", "adx", "atr"):
            # These always take priority over SMA/RSI
            if itype == "macd":
                primary_type = "MACD"
            elif itype == "bollinger":
                primary_type = "Bollinger"
            elif itype == "stochastic":
                primary_type = "Stochastic"
            elif itype == "adx":
                primary_type = "ADX"
            elif itype == "atr":
                primary_type = "ATR Breakout"
            primary_period = period
        elif itype == "sma":
            sma_periods.append(period)
            if primary_type is None:
                primary_type = "SMA"
        # RSI is ignored for primary type (it's often added as confirmation)

    # Build strategy label
    if primary_type == "SMA":
        if len(sma_periods) >= 2:
            strategy_type = f"SMA {sma_periods[0]}/{sma_periods[1]} Cross"
        elif sma_periods:
            strategy_type = f"SMA Cross"
        else:
            strategy_type = "SMA Cross"
    elif primary_type == "RSI" or (primary_type is None and any(i.get("indicator_type") == "rsi" for i in indicators if isinstance(i, dict))):
        # Get RSI period from indicators list
        rsi_period = None
        for i in indicators:
            if isinstance(i, dict) and i.get("indicator_type") == "rsi":
                rsi_period = i.get("period", 14)
                break
        # Fallback: extract from text
        if rsi_period is None:
            rsi_nums = re.findall(r'rsi\s*(\d+)', text, re.I)
            if rsi_nums:
                rsi_period = int(rsi_nums[0])
        if rsi_period and rsi_period != 14:
            strategy_type = f"RSI ({rsi_period})"
        else:
            strategy_type = "RSI"
    else:
        strategy_type = primary_type or "SMA Cross"

    # Timeframe label
    tf_labels = {
        "1m": "1M", "5m": "5M", "15m": "15M", "30m": "30M",
        "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W", "1mo": "1Mês",
    }
    tf_label = tf_labels.get(timeframe, timeframe)

    return f"{symbol} · {strategy_type} · {tf_label}"


def _extract_periods(text: str) -> tuple[int, int]:
    """Extract two meaningful periods from text like 'SMA 10 e SMA 50' or '50 e 200'.

    Filters out timeframe numbers (like '4h' → 4, '15m' → 15) and SL/TP pips.
    Requires at least one explicit indicator keyword (sma, média, period) nearby
    to avoid false matches.
    """
    # First try: look for SMA/EMA/média context patterns
    sma_matches = re.findall(r'(?:sma|ema|média)\s*(\d+)', text, re.I)
    if len(sma_matches) >= 2:
        a, b = int(sma_matches[0]), int(sma_matches[1])
        return min(a, b), max(a, b)
    if len(sma_matches) == 1:
        return int(sma_matches[0]), 50  # default second

    # Second try: "periodo" or "período" followed by number
    period_matches = re.findall(r'período\s*(\d+)', text, re.I)
    if period_matches:
        return int(period_matches[0]), int(period_matches[1]) if len(period_matches) > 1 else 50

    # Fallback: extract numbers but skip common false positives
    timeframe_pattern = re.findall(r'\b(\d+)\s*(?:h|minuto|dia|week|d|m|mo)\b', text, re.I)
    sl_tp_pattern = re.findall(r'(?:stop|loss|take|profit|stop loss|take profit)\s*(\d+)', text, re.I)
    excluded = set(int(x) for x in timeframe_pattern + sl_tp_pattern)

    numbers = [int(x) for x in re.findall(r'(\d+)', text)
               if 5 <= int(x) <= 500 and int(x) not in excluded]
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

        # Work with lowercase for keyword detection
        text_lower = text.lower()

        sl, tp = _extract_pips(text_lower)
        fast, slow = _extract_periods(text_lower)
        if fast == slow:
            fast, slow = 10, 50

        # ── MACD ──
        if "macd" in text_lower:
            indicators.append({"indicator_type": "macd", "period": 26,
                               "fast_period": 12, "slow_period": 26, "source": "close"})
            entry_conditions.append({
                "condition_type": "crossover",
                "indicator": "macd", "indicator_b": "macd",
                "params": {"fast_period": 12, "slow_period": 26},
                "description": "MACD cruza acima do Signal",
            })

        # ── RSI ──
        elif "rsi" in text_lower:
            rsi_period = 14
            for m in re.findall(r'rsi\s*(\d+)', text_lower):
                rsi_period = int(m)
                break
            indicators.append({"indicator_type": "rsi", "period": rsi_period, "source": "close"})

            if any(w in text_lower for w in ["sobrevendido", "abaixo de 30", "abaixo de 20", "acumulaçã"]):
                entry_conditions.append({
                    "condition_type": "threshold",
                    "indicator": "rsi", "operator": "<", "value": 30,
                    "description": f"RSI abaixo de 30 (sobrevendido)",
                })
            elif any(w in text_lower for w in ["sobrecomprado", "acima de 70", "vender"]):
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
        elif "bollinger" in text_lower or "banda" in text_lower:
            indicators.append({"indicator_type": "bollinger", "period": 20, "source": "close"})
            indicators.append({"indicator_type": "rsi", "period": 14, "source": "close"})
            entry_conditions.append({
                "condition_type": "threshold",
                "indicator": "rsi", "operator": ">", "value": 30,
                "description": "RSI > 30 como confirmação",
            })

        # ── Stochastic ──
        elif "estocástic" in text_lower or "stochastic" in text_lower or "%k" in text_lower:
            indicators.append({"indicator_type": "stochastic", "period": 14, "source": "close"})
            indicators.append({"indicator_type": "rsi", "period": 14, "source": "close"})
            entry_conditions.append({
                "condition_type": "crossover",
                "indicator": "stochastic",
                "params": {"fast_period": 14, "slow_period": 3},
                "description": "%K cruza acima %D na zona de sobrevenda",
            })

        # ── ADX ──
        elif "adx" in text_lower.replace(" ", "") or "adx" in text_lower:
            indicators.append({"indicator_type": "adx", "period": 14, "source": "close"})
            indicators.append({"indicator_type": "sma", "period": slow, "source": "close"})
            entry_conditions.append({
                "condition_type": "threshold",
                "indicator": "adx", "operator": ">", "value": 25,
                "description": "ADX > 25 (tendência forte)",
            })

        # ── ATR ──
        elif "atr" in text_lower and "breakout" in text_lower:
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

        name = _generate_strategy_name(text, symbol, timeframe, indicators)
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
