from pathlib import Path

from src.backtest_engine import run_backtest
from src.data_loader import load_asset_returns, load_config, load_series
from src.scoring import score_explanation
from src.signal_engine import MacroSignalEngine

BASE_DIR = Path(__file__).resolve().parent
config = load_config(BASE_DIR / "data" / "indicator_config.xlsx")
series = load_series(BASE_DIR / "data" / "macro_series_template.csv")
asset_returns = load_asset_returns(BASE_DIR / "data" / "asset_returns_template.csv")

result = MacroSignalEngine(config, series).run()
backtest = run_backtest(config, series, asset_returns)
print(score_explanation(result.overall_score, result.trigger_count, result.valid_signal_count, backtest.latest_backtest_hint))
print("\n策略指标：")
print(backtest.strategy_metrics.to_string(index=False))
