from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.data_loader import load_config, load_series
from src.scoring import score_explanation, score_label
from src.signal_engine import MacroSignalEngine
from src.ui_components import render_dimension_score, render_indicator_trend, render_kpis, render_signal_hierarchy, render_signal_table


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "data" / "indicator_config.xlsx"
DEFAULT_SERIES = BASE_DIR / "data" / "macro_series_template.csv"

st.set_page_config(page_title="宏观指标信号", layout="wide")
st.title("宏观指标信号")
st.caption("配置驱动的宏观防御信号看板：已完成信号计算、维度汇总和分级展示；数据获取模块暂未接入。")
st.warning("当前页面默认读取演示/占位数据，仅用于验证部署和看板逻辑，不代表真实宏观数据库，也不应用于正式投研判断。")

with st.sidebar:
    st.header("数据源状态")
    st.info("当前模式：本地文件 / GitHub 仓库内演示数据")
    st.caption("历史数据格式：date, indicator_id, value。真实数据接入后只需替换数据文件，或在 data_loader 前增加取数落地逻辑。")
    with st.expander("高级：修改本地文件路径", expanded=False):
        config_path = st.text_input("指标配置表路径", str(DEFAULT_CONFIG))
        series_path = st.text_input("指标历史数据路径", str(DEFAULT_SERIES))

try:
    config_df = load_config(config_path)
    series_df = load_series(series_path)
    result = MacroSignalEngine(config_df, series_df).run()
except Exception as exc:  # noqa: BLE001 - Streamlit 顶层展示错误
    st.error(f"看板加载失败：{exc}")
    st.stop()

explanation = score_explanation(result.overall_score, result.trigger_count, result.valid_signal_count)
render_kpis(result.overall_score, result.trigger_count, result.valid_signal_count, score_label(result.overall_score))
st.info(explanation)

st.subheader("维度防御分数")
render_dimension_score(result.dimension_score)

st.subheader("信号明细（分级视图）")
dimensions = list(result.detail["dimension"].drop_duplicates())
tabs = st.tabs(["全维度", *dimensions])
with tabs[0]:
    render_signal_hierarchy(result.detail, result.dimension_score)
for tab, dimension in zip(tabs[1:], dimensions):
    with tab:
        render_signal_hierarchy(result.detail, result.dimension_score, dimension)

with st.expander("查看平铺明细表（用于核对/导出）"):
    render_signal_table(result.detail)

st.subheader("指标历史趋势")
render_indicator_trend(series_df, result.detail)

with st.expander("查看原始计算表"):
    st.dataframe(result.detail, use_container_width=True, hide_index=True)
