"""Streamlit 展示组件。"""

from __future__ import annotations

from html import escape
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
        display[
            [
                "dimension",
                "dimension_weight",
                "indicator_count",
                "valid_count",
                "trigger_count",
                "dimension_score",
                "weighted_score",
            ]
        ]
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
        .style.format(
            {
                "维度权重": "{:.1%}",
                "维度防御比例": "{:.1%}",
                "加权贡献": "{:.1%}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_signal_hierarchy(
    detail: pd.DataFrame,
    dimension_score: pd.DataFrame | None = None,
    dimension: str | None = None,
) -> None:
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
            f"{dim}｜维度权重 {weight:.0%}｜触发 {trigger_count}/{valid_count}"
            f"｜维度防御比例 {dimension_score_value:.1%}｜加权贡献 {weighted_score:.1%}"
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

    st.dataframe(
        table.style.map(_color_signal, subset=["是否触发"]),
        use_container_width=True,
        hide_index=True,
    )


def _color_signal(val: str) -> str:
    if str(val) == "1":
        return "background-color: #FEE2E2; color: #991B1B; font-weight: 700;"
    if str(val) == "0":
        return "background-color: #DCFCE7; color: #166534;"
    return "background-color: #F3F4F6; color: #6B7280;"


def _format_change(latest, base, unit: str, digits: int = 2) -> str:
    """展示最新值较上期/参考值的变化。"""
    if pd.isna(latest) or pd.isna(base):
        return "—"

    latest = float(latest)
    base = float(base)
    diff = latest - base

    if abs(diff) < 1e-12:
        return "持平"

    arrow = "↑" if diff > 0 else "↓"
    unit = "" if pd.isna(unit) else str(unit).strip()

    if unit == "%":
        diff_text = f"{abs(diff):.{digits}f}pp"
    elif unit.lower() in {"pp", "pctpt", "百分点"}:
        diff_text = f"{abs(diff):.{digits}f}pp"
    elif unit:
        diff_text = f"{abs(diff):.{digits}f}{unit}"
    else:
        diff_text = f"{abs(diff):.{digits}f}"

    if abs(base) > 1e-12:
        rel_change = diff / abs(base)
        return f"{arrow} {diff_text}（{rel_change:+.1%}）"

    return f"{arrow} {diff_text}"


def _signal_badge(value: object) -> str:
    text = "—" if pd.isna(value) else str(value)
    if text == "1":
        return '<span class="signal-badge signal-on">1</span>'
    if text == "0":
        return '<span class="signal-badge signal-off">0</span>'
    return '<span class="signal-badge signal-na">—</span>'


def _latest_data_date_text(data: pd.DataFrame) -> str:
    if "latest_date" not in data.columns:
        return "—"
    dates = pd.to_datetime(data["latest_date"], errors="coerce").dropna()
    if dates.empty:
        return "—"
    return dates.max().strftime("%Y-%m-%d")


def _safe_text(value: object) -> str:
    if value is None or pd.isna(value):
        return "—"
    text = str(value)
    return escape(text)


def render_signal_table(detail: pd.DataFrame, dimension: str | None = None) -> None:
    """核心指标主表：一级维度行 + 二级指标明细行。主表不展示权重。"""
    data = detail if dimension is None else detail[detail["dimension"] == dimension]
    if data.empty:
        st.info("该维度暂无指标。")
        return

    data = data.copy()
    if "display_order" in data.columns:
        data = data.sort_values(["display_order", "dimension", "indicator_name"])

    latest_date = _latest_data_date_text(data)
    st.caption(f"截至最新数据日：{latest_date}")

    st.markdown(
        """
<style>
.compact-signal-wrap {
    width: 100%;
    overflow-x: hidden;
}
.compact-signal-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 12.5px;
    line-height: 1.35;
}
.compact-signal-table th {
    background: #f3f4f6;
    color: #111827;
    font-weight: 700;
    padding: 6px 7px;
    border: 1px solid #e5e7eb;
    text-align: left;
    vertical-align: middle;
}
.compact-signal-table td {
    padding: 6px 7px;
    border: 1px solid #e5e7eb;
    vertical-align: middle;
    color: #111827;
    word-break: break-word;
    overflow-wrap: anywhere;
}
.compact-signal-table .dim-row td {
    background: #111827;
    color: #ffffff;
    font-weight: 700;
    padding: 4px 8px;
    border-color: #111827;
    font-size: 12.5px;
}
.compact-signal-table .indicator-name {
    padding-left: 18px;
    font-weight: 600;
}
.compact-signal-table .signal-badge {
    display: inline-block;
    min-width: 22px;
    padding: 1px 6px;
    border-radius: 999px;
    text-align: center;
    font-weight: 700;
    font-size: 12px;
}
.compact-signal-table .signal-on {
    background: #fee2e2;
    color: #991b1b;
}
.compact-signal-table .signal-off {
    background: #dcfce7;
    color: #166534;
}
.compact-signal-table .signal-na {
    background: #f3f4f6;
    color: #6b7280;
}
.compact-signal-table .state-text {
    font-size: 12px;
    color: #374151;
}
</style>
""",
        unsafe_allow_html=True,
    )

    colgroup = """
<colgroup>
  <col style="width: 23%;">
  <col style="width: 10%;">
  <col style="width: 13%;">
  <col style="width: 14%;">
  <col style="width: 22%;">
  <col style="width: 7%;">
  <col style="width: 11%;">
</colgroup>
"""

    html_rows: list[str] = []
    for dim, sub in data.groupby("dimension", sort=False):
        dim_text = _safe_text(dim)
        html_rows.append(f'<tr class="dim-row"><td colspan="7">{dim_text}</td></tr>')

        for _, r in sub.iterrows():
            digits_raw = r.get("digits", 2)
            digits = int(digits_raw) if pd.notna(digits_raw) else 2

            indicator_name = _safe_text(r.get("indicator_name", ""))
            latest_value = _safe_text(r.get("latest_value_display", "—"))
            previous_change = _safe_text(
                _format_change(r.get("latest_value"), r.get("previous_value"), r.get("unit"), digits)
            )
            reference_change = _safe_text(
                _format_change(r.get("latest_value"), r.get("reference_value"), r.get("unit"), digits)
            )
            signal_text = _safe_text(r.get("signal_text", ""))
            signal_flag = _signal_badge(r.get("signal_flag_display", "—"))
            signal_state = _safe_text(r.get("signal_state", ""))

            html_rows.append(
                "<tr>"
                f'<td class="indicator-name">{indicator_name}</td>'
                f"<td>{latest_value}</td>"
                f"<td>{previous_change}</td>"
                f"<td>{reference_change}</td>"
                f"<td>{signal_text}</td>"
                f"<td>{signal_flag}</td>"
                f'<td class="state-text">{signal_state}</td>'
                "</tr>"
            )

    table_html = f"""
<div class="compact-signal-wrap">
<table class="compact-signal-table">
{colgroup}
<thead>
<tr>
  <th>指标结构</th>
  <th>最新值</th>
  <th>较上期</th>
  <th>较参考均值</th>
  <th>防御规则</th>
  <th>触发</th>
  <th>状态</th>
</tr>
</thead>
<tbody>
{''.join(html_rows)}
</tbody>
</table>
</div>
"""
    st.markdown(table_html, unsafe_allow_html=True)


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


def render_backtest_summary(
    forward_stats: pd.DataFrame,
    strategy_curve: pd.DataFrame,
    strategy_metrics: pd.DataFrame,
    current_bucket: str,
) -> None:
    st.markdown(f"当前防御分数对应历史区间：**{current_bucket}**")
    focus = forward_stats[
        (forward_stats["观察窗口"] == "未来1个月")
        & (forward_stats["防御分数区间"] == current_bucket)
    ]
    if not focus.empty:
        st.dataframe(
            focus[["资产名称", "样本数", "未来收益均值", "胜率", "最差表现", "最好表现"]].style.format(
                {
                    "未来收益均值": "{:.2%}",
                    "胜率": "{:.1%}",
                    "最差表现": "{:.2%}",
                    "最好表现": "{:.2%}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("动态策略 vs 固定基准净值")
        st.line_chart(strategy_curve.set_index("date")[["动态策略净值", "固定基准净值"]])
    with c2:
        st.subheader("策略回测指标")
        st.dataframe(
            strategy_metrics.style.format(
                {
                    "累计收益": "{:.2%}",
                    "年化收益": "{:.2%}",
                    "年化波动": "{:.2%}",
                    "最大回撤": "{:.2%}",
                    "夏普比率": "{:.2f}",
                    "卡玛比率": "{:.2f}",
                    "月度胜率": "{:.1%}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


