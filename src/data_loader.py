"""本地文件读取与结果导出。

注意：本文件有意不包含数据源获取逻辑。真实接入 Wind/Choice/数据库时，
只需要把取到的数据落成 date, indicator_id, value 三列即可复用后续模块。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


CONFIG_SHEET = "Indicator_Config"


def load_config(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到配置文件: {path}")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=CONFIG_SHEET)
    return pd.read_csv(path)


def load_series(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到指标历史文件: {path}")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def export_results(detail: pd.DataFrame, dimension_score: pd.DataFrame, output_dir: str | Path = "output") -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / "macro_signal_detail.csv"
    score_path = output_dir / "macro_signal_dimension_score.csv"
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    dimension_score.to_csv(score_path, index=False, encoding="utf-8-sig")
    return {"detail": detail_path, "dimension_score": score_path}
