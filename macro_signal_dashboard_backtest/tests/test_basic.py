from pathlib import Path
from src.data_loader import load_config, load_series, load_asset_returns
from src.signal_engine import MacroSignalEngine
from src.backtest_engine import run_backtest


def test_signal_and_backtest_runs():
    base = Path(__file__).resolve().parents[1]
    config = load_config(base / "data" / "indicator_config.xlsx")
    series = load_series(base / "data" / "macro_series_template.csv")
    asset_returns = load_asset_returns(base / "data" / "asset_returns_template.csv")
    result = MacroSignalEngine(config, series).run()
    assert result.valid_signal_count == 12
    bt = run_backtest(config, series, asset_returns)
    assert not bt.forward_stats.empty
    assert not bt.strategy_metrics.empty
