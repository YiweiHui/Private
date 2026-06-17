"""本地文件读取与结果导出。"""

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


def load_asset_returns(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到资产收益率文件: {path}")
    df = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_excel(path)
    required = {"date", "asset_id", "asset_name", "return"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"资产收益率表缺少字段: {sorted(missing)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["return"] = pd.to_numeric(df["return"], errors="coerce")
    df = df.dropna(subset=["date", "asset_id", "return"])
    return df.sort_values(["asset_id", "date"]).reset_index(drop=True)
