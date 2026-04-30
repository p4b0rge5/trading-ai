"""
Trading AI Engine — Demo Script

Run a complete backtest with a demo strategy to validate the engine.
Usage: python scripts/demo_backtest.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import json

from engine.models import StrategySpec
from engine.backtester import Backtester
from engine.sample_data import generate_sample_data, load_demo_strategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    print("=" * 60)
    print("  Trading AI — Engine Demo")
    print("=" * 60)
    print()

    # 1. Load demo strategy
    spec_dict = load_demo_strategy()
    print(f"Strategy: {spec_dict['name']}")
    print(f"Symbol:   {spec_dict['symbol']}")
    print(f"Timeframe: {spec_dict['timeframe']}")
    print()

    # 2. Validate with Pydantic
    spec = StrategySpec(**spec_dict)
    print(f"✓ Strategy validated: {spec.summary()}")
    print()

    # 3. Generate sample data
    print("Generating sample OHLCV data...")
    data = generate_sample_data(
        symbol=spec.symbol,
        n_bars=5000,
        timeframe="1h",
    )
    print(f"✓ {len(data)} bars from {data['timestamp'].min()} to {data['timestamp'].max()}")
    print()

    # 4. Run backtest
    print("Running backtest...")
    backtester = Backtester(spec)
    chart_path = "/opt/baal-agent/workspace/trading-ai/backtest_chart.png"
    result = backtester.run(data, initial_balance=10_000.0, chart_output=chart_path)

    # 5. Display results
    print()
    print("=" * 60)
    print("  Backtest Results")
    print("=" * 60)
    print(f"  Period:          {result.summary['period']}")
    print(f"  Total Trades:    {result.summary['total_trades']}")
    print(f"  Win Rate:        {result.summary['win_rate']}")
    print(f"  Net Profit:      {result.summary['net_profit']}")
    print(f"  Total Return:    {result.summary['total_return']}")
    print(f"  Max Drawdown:    {result.summary['max_drawdown']}")
    print(f"  Sharpe Ratio:    {result.summary['sharpe_ratio']}")
    print(f"  Profit Factor:   {result.summary['profit_factor']}")
    print(f"  Avg Duration:    {result.avg_trade_duration_min:.1f} min")
    print()

    if result.chart_path:
        print(f"  📊 Chart saved: {result.chart_path}")

    # 6. Show first few trades
    if result.trades:
        print()
        print("  First 5 trades:")
        print("  " + "-" * 56)
        for i, t in enumerate(result.trades[:5], 1):
            profit_str = f"${t.profit:,.2f}" if t.profit else "N/A"
            print(
                f"  {i}. {t.side.upper():4s} | "
                f"Entry: {t.entry_time:%Y-%m-%d %H:%M} @ {t.entry_price:.5f} | "
                f"Exit: {t.exit_time:%Y-%m-%d %H:%M} @ {t.exit_price:.5f} | "
                f"P/L: {profit_str}"
            )

    print()
    print("  Strategy spec (JSON):")
    print("  " + "-" * 56)
    print(json.dumps(spec.model_dump(), indent=2, default=str)[:500])
    print("  ...")
    print()
    print("=" * 60)
    print("  ✅ Engine demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
