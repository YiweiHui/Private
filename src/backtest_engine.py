"""宏观防御信号回测模块。

所有样例数据均为虚拟合成数据，回测结果只用于验证看板流程。
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from .signal_engine import MacroSignalEngine
from .scoring import score_bucket


@dataclass(frozen=True)
class BacktestResult:
    score_history: pd.DataFrame
    forward_stats: pd.DataFrame
    strategy_curve: pd.DataFrame
    strategy_metrics: pd.DataFrame
    latest_backtest_hint: str


def run_backtest(config_df: pd.DataFrame, macro_series_df: pd.DataFrame, asset_returns_df: pd.DataFrame) -> BacktestResult:
    engine = MacroSignalEngine(config_df, macro_series_df)
    macro_series = macro_series_df.copy()
    macro_series["date"] = pd.to_datetime(macro_series["date"])
    dates = sorted(macro_series["date"].dropna().unique())

    score_rows = []
    for d in dates:
        result = engine.run(as_of_date=d)
        score_rows.append({
            "date": pd.to_datetime(d),
            "defense_score": result.overall_score,
            "bucket": score_bucket(result.overall_score),
            "trigger_count": result.trigger_count,
            "valid_count": result.valid_signal_count,
        })
    score_history = pd.DataFrame(score_rows).sort_values("date")

    asset_wide = asset_returns_df.pivot_table(index="date", columns="asset_id", values="return", aggfunc="first").sort_index()
    asset_name_map = asset_returns_df.drop_duplicates("asset_id").set_index("asset_id")["asset_name"].to_dict()

    forward_stats = _forward_return_stats(score_history, asset_wide, asset_name_map)
    strategy_curve, strategy_metrics = _dynamic_allocation_backtest(score_history, asset_wide)
    latest_hint = _latest_backtest_hint(score_history, forward_stats)
    return BacktestResult(score_history, forward_stats, strategy_curve, strategy_metrics, latest_hint)


def _compound(values: pd.Series) -> float:
    values = values.dropna()
    if values.empty:
        return np.nan
    return float((1.0 + values).prod() - 1.0)


def _forward_return_stats(score_history: pd.DataFrame, asset_wide: pd.DataFrame, asset_name_map: dict[str, str]) -> pd.DataFrame:
    rows = []
    horizons = {"未来1个月": 1, "未来3个月": 3, "未来6个月": 6}
    merged = score_history.set_index("date").copy()

    for asset_id in asset_wide.columns:
        returns = asset_wide[asset_id]
        for horizon_label, months in horizons.items():
            fwd = []
            for dt in merged.index:
                pos = returns.index.searchsorted(dt)
                window = returns.iloc[pos + 1: pos + 1 + months]
                fwd.append(_compound(window) if len(window) == months else np.nan)
            tmp = merged.copy()
            tmp["forward_return"] = fwd
            for bucket, sub in tmp.groupby("bucket", sort=False):
                valid = sub["forward_return"].dropna()
                if valid.empty:
                    continue
                rows.append({
                    "资产代码": asset_id,
                    "资产名称": asset_name_map.get(asset_id, asset_id),
                    "观察窗口": horizon_label,
                    "防御分数区间": bucket,
                    "样本数": int(len(valid)),
                    "未来收益均值": float(valid.mean()),
                    "未来收益中位数": float(valid.median()),
                    "胜率": float((valid > 0).mean()),
                    "最差表现": float(valid.min()),
                    "最好表现": float(valid.max()),
                })
    return pd.DataFrame(rows)


def _allocation_for_score(score: float) -> dict[str, float]:
    """示例仓位规则：仅用于演示，不构成真实投资建议。"""
    if score < 0.25:
        return {"CSI300": 0.70, "CNI_BOND": 0.25, "CASH": 0.05}
    if score < 0.50:
        return {"CSI300": 0.60, "CNI_BOND": 0.35, "CASH": 0.05}
    if score < 0.75:
        return {"CSI300": 0.45, "CNI_BOND": 0.45, "CASH": 0.10}
    return {"CSI300": 0.30, "CNI_BOND": 0.55, "CASH": 0.15}


def _dynamic_allocation_backtest(score_history: pd.DataFrame, asset_wide: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    score_by_date = score_history.set_index("date")["defense_score"]
    dates = list(asset_wide.index)
    for i, dt in enumerate(dates):
        # 用上月信号指导本月仓位，避免未来函数。
        prev_score = score_by_date[score_by_date.index < dt].iloc[-1] if not score_by_date[score_by_date.index < dt].empty else 0.50
        alloc = _allocation_for_score(float(prev_score))
        row_ret = asset_wide.loc[dt]
        dynamic_ret = sum(weight * row_ret.get(asset_id, 0.0) for asset_id, weight in alloc.items())
        benchmark_ret = 0.60 * row_ret.get("CSI300", 0.0) + 0.35 * row_ret.get("CNI_BOND", 0.0) + 0.05 * row_ret.get("CASH", 0.0)
        records.append({"date": dt, "防御分数_上期": prev_score, "动态策略收益": dynamic_ret, "固定基准收益": benchmark_ret,
                        "权益仓位": alloc.get("CSI300", 0.0), "债券仓位": alloc.get("CNI_BOND", 0.0), "现金仓位": alloc.get("CASH", 0.0)})
    curve = pd.DataFrame(records).dropna(subset=["动态策略收益", "固定基准收益"])
    curve["动态策略净值"] = (1 + curve["动态策略收益"]).cumprod()
    curve["固定基准净值"] = (1 + curve["固定基准收益"]).cumprod()

    metrics = pd.DataFrame([
        _calc_metrics(curve["动态策略收益"], curve["动态策略净值"], "防御分数动态策略"),
        _calc_metrics(curve["固定基准收益"], curve["固定基准净值"], "固定60/35/5基准"),
    ])
    return curve, metrics


def _calc_metrics(ret: pd.Series, nav: pd.Series, name: str) -> dict[str, float | str]:
    ret = ret.dropna()
    nav = nav.loc[ret.index]
    if ret.empty:
        return {"策略": name}
    months = len(ret)
    total_ret = float((1 + ret).prod() - 1)
    annual_ret = float((1 + total_ret) ** (12 / months) - 1) if months > 0 else np.nan
    annual_vol = float(ret.std(ddof=0) * np.sqrt(12)) if months > 1 else np.nan
    sharpe = float(annual_ret / annual_vol) if annual_vol and annual_vol > 0 else np.nan
    drawdown = nav / nav.cummax() - 1
    max_dd = float(drawdown.min())
    calmar = float(annual_ret / abs(max_dd)) if max_dd < 0 else np.nan
    return {"策略": name, "样本月数": int(months), "累计收益": total_ret, "年化收益": annual_ret,
            "年化波动": annual_vol, "最大回撤": max_dd, "夏普比率": sharpe, "卡玛比率": calmar,
            "月度胜率": float((ret > 0).mean())}


def _latest_backtest_hint(score_history: pd.DataFrame, forward_stats: pd.DataFrame) -> str:
    if score_history.empty or forward_stats.empty:
        return ""
    latest_bucket = score_history.sort_values("date").iloc[-1]["bucket"]
    eq = forward_stats[(forward_stats["资产代码"] == "CSI300") & (forward_stats["观察窗口"] == "未来1个月") & (forward_stats["防御分数区间"] == latest_bucket)]
    bond = forward_stats[(forward_stats["资产代码"] == "CNI_BOND") & (forward_stats["观察窗口"] == "未来1个月") & (forward_stats["防御分数区间"] == latest_bucket)]
    if eq.empty or bond.empty:
        return ""
    eq_mean = float(eq.iloc[0]["未来收益均值"])
    eq_win = float(eq.iloc[0]["胜率"])
    bond_mean = float(bond.iloc[0]["未来收益均值"])
    bond_win = float(bond.iloc[0]["胜率"])
    return (f" 基于虚拟历史回测，在当前 {latest_bucket} 区间内，沪深300未来1个月平均收益为 {eq_mean:.2%}、胜率 {eq_win:.1%}；"
            f"中债综合财富未来1个月平均收益为 {bond_mean:.2%}、胜率 {bond_win:.1%}。")
