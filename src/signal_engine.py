"""宏观择时/防御信号计算引擎。

只负责配置驱动的信号计算，不包含 Wind/Choice/AKShare 等数据获取逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


REQUIRED_CONFIG_COLUMNS = {
    "dimension",
    "dimension_weight",
    "indicator_id",
    "indicator_name",
    "unit",
    "rule_type",
    "direction",
    "ma_window",
    "signal_text",
    "display_order",
    "enabled",
}

REQUIRED_SERIES_COLUMNS = {"date", "indicator_id", "value"}


@dataclass(frozen=True)
class EngineResult:
    detail: pd.DataFrame
    dimension_score: pd.DataFrame
    overall_score: float
    valid_signal_count: int
    trigger_count: int


class MacroSignalEngine:
    """配置驱动的宏观防御信号引擎。

    支持的规则：
    - moving_avg + below/above：最新值低于/高于移动平均；
    - mom + down/up：最新值较上期下降/上升；
    - fixed + below/above：最新值低于/高于固定阈值 threshold。

    默认移动平均参考值使用「最新一期之前的 N 期均值」，避免把本期数值本身放入比较基准。
    """

    def __init__(self, config_df: pd.DataFrame, series_df: pd.DataFrame):
        self.config_df = self._prepare_config(config_df)
        self.series_df = self._prepare_series(series_df)

    @staticmethod
    def _prepare_config(config_df: pd.DataFrame) -> pd.DataFrame:
        config = config_df.copy()
        missing = REQUIRED_CONFIG_COLUMNS - set(config.columns)
        if missing:
            raise ValueError(f"配置表缺少字段: {sorted(missing)}")

        config["enabled"] = config["enabled"].map(_to_bool)
        config = config[config["enabled"]].copy()
        config["dimension_weight"] = pd.to_numeric(config["dimension_weight"], errors="coerce")
        config.loc[config["dimension_weight"] > 1, "dimension_weight"] /= 100.0
        config["ma_window"] = pd.to_numeric(config["ma_window"], errors="coerce")
        config["display_order"] = pd.to_numeric(config["display_order"], errors="coerce").fillna(9999)
        if "threshold" not in config.columns:
            config["threshold"] = pd.NA
        if "ma_include_latest" not in config.columns:
            config["ma_include_latest"] = False
        config["ma_include_latest"] = config["ma_include_latest"].map(_to_bool)
        if "digits" not in config.columns:
            config["digits"] = 2
        config["digits"] = pd.to_numeric(config["digits"], errors="coerce").fillna(2).astype(int)
        if "remark" not in config.columns:
            config["remark"] = ""
        return config.sort_values(["display_order", "dimension", "indicator_name"]).reset_index(drop=True)

    @staticmethod
    def _prepare_series(series_df: pd.DataFrame) -> pd.DataFrame:
        series = series_df.copy()
        missing = REQUIRED_SERIES_COLUMNS - set(series.columns)
        if missing:
            raise ValueError(f"指标历史表缺少字段: {sorted(missing)}")
        series["date"] = pd.to_datetime(series["date"], errors="coerce")
        series["value"] = pd.to_numeric(series["value"], errors="coerce")
        series = series.dropna(subset=["date", "indicator_id", "value"]).copy()
        series["indicator_id"] = series["indicator_id"].astype(str)
        return series.sort_values(["indicator_id", "date"]).reset_index(drop=True)

    def run(self, as_of_date: str | pd.Timestamp | None = None) -> EngineResult:
        series = self.series_df
        if as_of_date is not None:
            as_of = pd.to_datetime(as_of_date)
            series = series[series["date"] <= as_of].copy()
        rows = []
        for _, cfg in self.config_df.iterrows():
            rows.append(self._compute_one_indicator(cfg, series))
        detail = pd.DataFrame(rows)
        detail = self._add_display_columns(detail)
        dimension_score = self._compute_dimension_score(detail)
        overall_score = float(dimension_score["weighted_score"].sum()) if not dimension_score.empty else 0.0
        signal_numeric = pd.to_numeric(detail["signal_flag"], errors="coerce") if not detail.empty else pd.Series(dtype=float)
        valid_signal_count = int(signal_numeric.notna().sum()) if not detail.empty else 0
        trigger_count = int(signal_numeric.fillna(0).sum()) if not detail.empty else 0
        return EngineResult(detail, dimension_score, overall_score, valid_signal_count, trigger_count)

    def _compute_one_indicator(self, cfg: pd.Series, series_df: pd.DataFrame) -> dict:
        indicator_id = str(cfg["indicator_id"])
        hist = series_df[series_df["indicator_id"] == indicator_id].sort_values("date")

        base = cfg.to_dict()
        base.update({"latest_date": pd.NaT, "latest_value": pd.NA, "previous_value": pd.NA, "reference_value": pd.NA,
                     "signal_flag": pd.NA, "data_status": "缺少数据"})
        if hist.empty:
            return base

        latest = hist.iloc[-1]
        previous_value = hist.iloc[-2]["value"] if len(hist) >= 2 else pd.NA
        base["latest_date"] = latest["date"]
        base["latest_value"] = latest["value"]
        base["previous_value"] = previous_value

        rule_type = str(cfg["rule_type"]).strip().lower()
        direction = str(cfg["direction"]).strip().lower()
        try:
            if rule_type == "moving_avg":
                ref = self._moving_average(hist, cfg)
                base["reference_value"] = ref
                base["signal_flag"] = _compare(latest["value"], ref, direction)
                base["data_status"] = "正常" if pd.notna(ref) else "移动平均样本不足"
            elif rule_type == "mom":
                ref = previous_value
                base["reference_value"] = ref
                base["signal_flag"] = _compare(latest["value"], ref, direction)
                base["data_status"] = "正常" if pd.notna(ref) else "缺少上期数据"
            elif rule_type == "fixed":
                ref = pd.to_numeric(cfg.get("threshold"), errors="coerce")
                base["reference_value"] = ref
                base["signal_flag"] = _compare(latest["value"], ref, direction)
                base["data_status"] = "正常" if pd.notna(ref) else "缺少阈值"
            else:
                base["data_status"] = f"未知规则: {rule_type}"
        except Exception as exc:
            base["data_status"] = f"计算失败: {exc}"
        return base

    @staticmethod
    def _moving_average(hist: pd.DataFrame, cfg: pd.Series) -> Optional[float]:
        window = int(cfg["ma_window"]) if pd.notna(cfg["ma_window"]) else 6
        include_latest = bool(cfg.get("ma_include_latest", False))
        ref_series = hist["value"] if include_latest else hist["value"].iloc[:-1]
        if len(ref_series) < window:
            return pd.NA
        return float(ref_series.tail(window).mean())

    @staticmethod
    def _add_display_columns(detail: pd.DataFrame) -> pd.DataFrame:
        if detail.empty:
            return detail
        detail = detail.copy()
        detail["dimension_label"] = detail.apply(lambda r: f"{r['dimension']}\n({r['dimension_weight']:.0%})", axis=1)
        detail["latest_value_display"] = detail.apply(lambda r: _format_value(r.get("latest_value"), r.get("unit"), int(r.get("digits", 2))), axis=1)
        detail["reference_value_display"] = detail.apply(lambda r: _format_value(r.get("reference_value"), r.get("unit"), int(r.get("digits", 2))), axis=1)
        detail["signal_flag_display"] = detail["signal_flag"].map({1: "1", 0: "0"}).fillna("—")
        detail["signal_state"] = detail["signal_flag"].map({1: "触发防御", 0: "未触发"}).fillna("数据不足")
        return detail

    @staticmethod
    def _compute_dimension_score(detail: pd.DataFrame) -> pd.DataFrame:
        if detail.empty:
            return pd.DataFrame(columns=["dimension", "dimension_weight", "indicator_count", "valid_count", "trigger_count", "dimension_score", "weighted_score"])
        grouped = []
        for dim, sub in detail.groupby("dimension", sort=False):
            weight = float(sub["dimension_weight"].iloc[0])
            valid = sub["signal_flag"].dropna()
            valid_count = int(len(valid))
            trigger_count = int(valid.sum()) if valid_count else 0
            dimension_score = trigger_count / valid_count if valid_count else 0.0
            grouped.append({"dimension": dim, "dimension_weight": weight, "indicator_count": int(len(sub)),
                            "valid_count": valid_count, "trigger_count": trigger_count,
                            "dimension_score": dimension_score, "weighted_score": dimension_score * weight})
        return pd.DataFrame(grouped)


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "启用", "是"}


def _compare(value, reference, direction: str):
    if pd.isna(value) or pd.isna(reference):
        return pd.NA
    direction = direction.lower()
    if direction in {"below", "down", "less", "lt", "低于", "下降"}:
        return int(value < reference)
    if direction in {"above", "up", "greater", "gt", "高于", "上升"}:
        return int(value > reference)
    if direction in {"equal", "eq", "等于"}:
        return int(value == reference)
    raise ValueError(f"未知方向: {direction}")


def _format_value(value, unit: str, digits: int = 2) -> str:
    if pd.isna(value):
        return "—"
    unit = "" if pd.isna(unit) else str(unit).strip()
    if unit == "%":
        return f"{float(value):.{digits}f}%"
    if unit.lower() in {"pp", "pctpt", "百分点"}:
        return f"{float(value):.{digits}f}pp"
    if unit:
        return f"{float(value):.{digits}f}{unit}"
    return f"{float(value):.{digits}f}"
