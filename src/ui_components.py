"""Streamlit 展示组件。"""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_kpis(overall_score: float, trigger_count: int, valid_count: int, label: str) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("总防御分数", f"{overall_score:.1%}")
    c2.metric("触发防御信号", f"{trigger_count}/{valid_count}")
    c3.metric("当前解释", label)


def render_dimension_score(dimension_score: pd.DataFrame) -> None:
    if dimension_score.empty:
        st.info("暂无维度得分。")
        return
    display = dimension_score.copy()
    display["dimension_score_pct"] = display["dimension_score"] * 100
    st.bar_chart(display.set_index("dimension")[["dimension_score_pct"]])
    st.dataframe(
        display[["dimension", "dimension_weight", "indicator_count", "valid_count", "trigger_count", "dimension_score", "weighted_score"]]
        .rename(
            columns={
                "dimension": "一级维度",
                "dimension_weight": "维度权重",
                "indicator_count": "二级指标数",
                "valid_count": "有效指标数",
                "trigger_count": "触发数",
                "dimension_score": "维度防御比例",
                "weighted_score": "加权贡献",
            }
        )
        .style.format({"维度权重": "{:.1%}", "维度防御比例": "{:.1%}", "加权贡献": "{:.1%}"}),
        use_container_width=True,
        hide_index=True,
    )


def render_signal_hierarchy(
    detail: pd.DataFrame,
    dimension_score: pd.DataFrame | None = None,
    dimension: str | None = None,
) -> None:
    """按“一级维度 -> 二级指标”展示信号，避免维度名称在每行重复。"""
    data = detail if dimension is None else detail[detail["dimension"] == dimension]
    if data.empty:
        st.info("暂无指标。")
        return

    score_map = {}
    if dimension_score is not None and not dimension_score.empty:
        score_map = {str(row.dimension): row for row in dimension_score.itertuples(index=False)}

    for dim, sub in data.groupby("dimension", sort=False):
        sub = sub.sort_values("display_order") if "display_order" in sub.columns else sub
        weight = float(sub["dimension_weight"].iloc[0])
        score_row = score_map.get(str(dim))
        if score_row is not None:
            valid_count = int(score_row.valid_count)
            trigger_count = int(score_row.trigger_count)
            dimension_score_value = float(score_row.dimension_score)
            weighted_score = float(score_row.weighted_score)
        else:
            valid = sub["signal_flag"].dropna()
            valid_count = int(len(valid))
            trigger_count = int(valid.sum()) if valid_count else 0
            dimension_score_value = trigger_count / valid_count if valid_count else 0.0
            weighted_score = dimension_score_value * weight

        title = (
            f"{dim}｜维度权重 {weight:.0%}｜"
            f"触发 {trigger_count}/{valid_count}｜"
            f"维度防御比例 {dimension_score_value:.1%}｜"
            f"加权贡献 {weighted_score:.1%}"
        )
        with st.expander(title, expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("一级维度权重", f"{weight:.0%}")
            c2.metric("二级指标数", f"{len(sub)}")
            c3.metric("触发防御", f"{trigger_count}/{valid_count}")
            c4.metric("加权贡献", f"{weighted_score:.1%}")
            _render_indicator_table(sub)


def _render_indicator_table(data: pd.DataFrame) -> None:
    table = data[
        [
            "indicator_name",
            "latest_value_display",
            "signal_text",
            "signal_flag_display",
            "signal_state",
            "latest_date",
            "reference_value_display",
            "data_status",
        ]
    ].rename(
        columns={
            "indicator_name": "二级指标",
            "latest_value_display": "最新数值",
            "signal_text": "择时信号（防御）",
            "signal_flag_display": "是否触发",
            "signal_state": "信号状态",
            "latest_date": "最新日期",
            "reference_value_display": "参考值",
            "data_status": "数据状态",
        }
    )
    table = table.copy()
    table["最新日期"] = pd.to_datetime(table["最新日期"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("—")

    def color_signal(val: str) -> str:
        if val == "1":
            return "background-color: #FEE2E2; color: #991B1B; font-weight: 700;"
        if val == "0":
            return "background-color: #DCFCE7; color: #166534;"
        return "background-color: #F3F4F6; color: #6B7280;"

    st.dataframe(
        table.style.map(color_signal, subset=["是否触发"]),
        use_container_width=True,
        hide_index=True,
    )


def render_signal_table(detail: pd.DataFrame, dimension: str | None = None) -> None:
    """保留平铺表，主要用于排查或导出核对。"""
    data = detail if dimension is None else detail[detail["dimension"] == dimension]
    if data.empty:
        st.info("该维度暂无指标。")
        return
    table = data[
        [
            "dimension_label",
            "indicator_name",
            "latest_value_display",
            "signal_text",
            "signal_flag_display",
            "signal_state",
            "latest_date",
            "reference_value_display",
            "data_status",
        ]
    ].rename(
        columns={
            "dimension_label": "维度(权重)",
            "indicator_name": "指标名称",
            "latest_value_display": "最新数值",
            "signal_text": "择时信号（防御）",
            "signal_flag_display": "是否满足择时信号",
            "signal_state": "信号状态",
            "latest_date": "最新日期",
            "reference_value_display": "参考值",
            "data_status": "数据状态",
        }
    )

    def color_signal(val: str) -> str:
        if val == "1":
            return "background-color: #FEE2E2; color: #991B1B; font-weight: 700;"
        if val == "0":
            return "background-color: #DCFCE7; color: #166534;"
        return "background-color: #F3F4F6; color: #6B7280;"

    st.dataframe(
        table.style.map(color_signal, subset=["是否满足择时信号"]),
        use_container_width=True,
        hide_index=True,
    )


def render_indicator_trend(series_df: pd.DataFrame, detail: pd.DataFrame) -> None:
    if detail.empty:
        return
    options = detail[["indicator_id", "indicator_name"]].drop_duplicates()
    label_map = {f"{row.indicator_name} ({row.indicator_id})": row.indicator_id for row in options.itertuples()}
    selected_label = st.selectbox("选择指标查看历史趋势", list(label_map.keys()))
    selected_id = label_map[selected_label]
    hist = series_df[series_df["indicator_id"].astype(str) == str(selected_id)].copy()
    if hist.empty:
        st.info("该指标暂无历史数据。")
        return
    hist["date"] = pd.to_datetime(hist["date"])
    st.line_chart(hist.sort_values("date").set_index("date")[["value"]])
