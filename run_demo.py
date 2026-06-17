from pathlib import Path

from src.data_loader import export_results, load_config, load_series
from src.signal_engine import MacroSignalEngine
from src.scoring import score_explanation

BASE_DIR = Path(__file__).resolve().parent
config_df = load_config(BASE_DIR / "data" / "indicator_config.xlsx")
series_df = load_series(BASE_DIR / "data" / "macro_series_template.csv")
result = MacroSignalEngine(config_df, series_df).run()
paths = export_results(result.detail, result.dimension_score, BASE_DIR / "output")
print(score_explanation(result.overall_score, result.trigger_count, result.valid_signal_count))
print("已导出：")
for name, path in paths.items():
    print(f"- {name}: {path}")
