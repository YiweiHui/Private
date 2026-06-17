from __future__ import annotations

from pathlib import Path
import json
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from src.backtest_engine import run_backtest
from src.data_loader import load_asset_returns, load_config, load_series
from src.deepseek_client import build_ai_prompt, generate_deepseek_analysis
from src.scoring import score_bucket, score_explanation, score_label
from src.signal_engine import MacroSignalEngine
from src.ui_components import (
    render_backtest_summary,
    render_dimension_score,
    render_indicator_trend,
    render_kpis,
    render_signal_hierarchy,
    render_signal_table,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "data" / "indicator_config.xlsx"
DEFAULT_SERIES = BASE_DIR / "data" / "macro_series_template.csv"
DEFAULT_ASSET_RETURNS = BASE_DIR / "data" / "asset_returns_template.csv"


def safe_secret(key: str, default: str = "") -> str:
    """读取 Streamlit Secrets；本地没有 secrets.toml 时返回默认值，不让页面报错。"""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def build_summaries(result, backtest, current_bucket: str) -> tuple[dict, dict]:
    """生成给 DeepSeek 的结构化摘要，避免把全量历史表传给 API。"""
    current_summary = {
        "overall_score": f"{result.overall_score:.1%}",
        "score_bucket": current_bucket,
        "score_label": score_label(result.overall_score),
        "trigger_count": result.trigger_count,
        "valid_signal_count": result.valid_signal_count,
        "dimension_scores": result.dimension_score.to_dict(orient="records"),
    }
    bt_focus = backtest.forward_stats[
        (backtest.forward_stats["观察窗口"] == "未来1个月")
        & (backtest.forward_stats["防御分数区间"] == current_bucket)
    ]
    backtest_summary = {
        "current_bucket_forward_1m": bt_focus.to_dict(orient="records"),
        "strategy_metrics": backtest.strategy_metrics.to_dict(orient="records"),
        "data_note": "所有数据为虚拟合成数据，仅演示模型和看板流程。",
    }
    return current_summary, backtest_summary


CACHE_DIR = BASE_DIR / ".runtime_cache"
DEEPSEEK_CACHE_FILE = CACHE_DIR / "deepseek_summary_cache.json"
CACHE_TZ = ZoneInfo("Asia/Shanghai")  # UTC+8；中国/新加坡团队都可按该口径理解


def next_morning_8(now: datetime | None = None) -> datetime:
    """返回下一次 UTC+8 早上 8 点。

    生成一次 DeepSeek 总结后，会固定留存到下一次早上 8 点。
    例如：今天 10:00 生成 -> 明早 8:00 过期；今天 07:30 生成 -> 今天 8:00 过期。
    """
    now = now.astimezone(CACHE_TZ) if now else datetime.now(CACHE_TZ)
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def make_deepseek_cache_key(current_json: str, backtest_json: str, model: str, base_url: str) -> str:
    """用数据摘要和模型参数生成缓存键；不包含 API Key。"""
    raw = "|".join([current_json, backtest_json, model, base_url])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_deepseek_file_cache(cache_key: str) -> tuple[str | None, str | None]:
    """读取文件缓存。返回 (summary_text, expires_at_text)。缓存不存在、过期或数据变化则返回 None。"""
    try:
        if not DEEPSEEK_CACHE_FILE.exists():
            return None, None
        payload = json.loads(DEEPSEEK_CACHE_FILE.read_text(encoding="utf-8"))
        expires_at = datetime.fromisoformat(payload.get("expires_at", ""))
        if payload.get("cache_key") == cache_key and datetime.now(CACHE_TZ) < expires_at:
            return payload.get("summary", ""), expires_at.strftime("%Y-%m-%d %H:%M UTC+8")
    except Exception:
        return None, None
    return None, None


def save_deepseek_file_cache(cache_key: str, summary: str) -> str:
    """保存 DeepSeek 总结到服务器本地文件，固定有效到下一次 UTC+8 早上 8 点。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    expires_at = next_morning_8()
    payload = {
        "cache_key": cache_key,
        "summary": summary,
        "generated_at": datetime.now(CACHE_TZ).isoformat(),
        "expires_at": expires_at.isoformat(),
        "timezone": "Asia/Shanghai / UTC+8",
    }
    DEEPSEEK_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return expires_at.strftime("%Y-%m-%d %H:%M UTC+8")


def get_or_create_deepseek_summary(current_json: str, backtest_json: str, model: str, base_url: str, api_key: str) -> tuple[str, str, bool]:
    """优先读取留存到早 8 点的团队缓存；没有缓存再调用 DeepSeek。

    返回：summary_text, expires_at_text, cache_hit
    """
    cache_key = make_deepseek_cache_key(current_json, backtest_json, model, base_url)
    cached_text, expires_at_text = load_deepseek_file_cache(cache_key)
    if cached_text:
        return cached_text, expires_at_text or "", True

    current_summary = json.loads(current_json)
    backtest_summary = json.loads(backtest_json)
    messages = build_ai_prompt(current_summary, backtest_summary)
    summary = generate_deepseek_analysis(api_key, messages, model=model, base_url=base_url)
    expires_at_text = save_deepseek_file_cache(cache_key, summary)
    return summary, expires_at_text, False


def render_deepseek_block(api_key: str, model: str, base_url: str, current_summary: dict, backtest_summary: dict, local_explanation: str) -> None:
    """在第一页自动展示 DeepSeek 总结；同事不需要点击按钮。"""
    st.subheader("DeepSeek总结（当前信号 + 回测模型）")
    st.caption("服务器端自动生成并固定留存到下一次 UTC+8 早上 8 点。团队成员打开网页即可看到同一份解释，不需要自己点击调用。")

    current_json = json.dumps(current_summary, ensure_ascii=False, sort_keys=True)
    backtest_json = json.dumps(backtest_summary, ensure_ascii=False, sort_keys=True)

    if api_key:
        with st.spinner("首次加载或数据变化后，正在生成/读取 DeepSeek 总结..."):
            try:
                ai_text, expires_at, cache_hit = get_or_create_deepseek_summary(current_json, backtest_json, model, base_url, api_key)
                st.markdown(ai_text)
                source_text = "读取服务器缓存" if cache_hit else "新调用 DeepSeek 生成"
                st.caption(f"说明：DeepSeek 只负责文字整理；信号、分数和回测统计均由本地程序计算。本次结果来源：{source_text}；固定留存到：{expires_at}。数据或模型参数变化后会重新生成。")
            except Exception as exc:
                st.error(f"DeepSeek API 自动总结失败：{exc}")
                st.info("已切换为本地模板解释。")
                st.write(local_explanation)
    else:
        st.info("当前未配置服务器端 DEEPSEEK_API_KEY，因此展示本地模板解释。配置 Streamlit Secrets 后，团队成员将自动看到 DeepSeek 总结。")
        st.write(local_explanation)

    with st.expander("查看发送给 DeepSeek 的结构化摘要", expanded=False):
        st.json({"current_summary": current_summary, "backtest_summary": backtest_summary})

    with st.expander("管理员操作：手动刷新 DeepSeek 缓存", expanded=False):
        st.caption("当你更新了数据但缓存尚未到次日早 8 点时，可以点击清除缓存，然后刷新页面。普通同事不需要操作。")
        if st.button("清除 DeepSeek 总结缓存", use_container_width=True):
            try:
                if DEEPSEEK_CACHE_FILE.exists():
                    DEEPSEEK_CACHE_FILE.unlink()
                st.success("缓存已清除，请刷新页面重新生成。")
            except Exception as exc:
                st.error(f"缓存清除失败：{exc}")


st.set_page_config(page_title="宏观指标信号与回测", layout="wide")
st.title("宏观指标信号与回测看板")
st.caption("配置驱动的宏观防御信号 + 虚拟历史回测 + DeepSeek API 文字解释。")
st.warning("当前内置数据均为演示/虚拟数据，只用于验证方法、部署和展示流程，不代表真实宏观数据库，也不应用于正式投研判断。")

with st.sidebar:
    st.header("数据源状态")
    st.info("当前模式：GitHub 仓库内演示数据")
    st.caption("宏观历史数据格式：date, indicator_id, value。资产收益率格式：date, asset_id, asset_name, return。")
    st.divider()
    st.header("DeepSeek API")
    st.caption("团队版建议在 Streamlit Secrets 中配置 API Key；普通同事无需输入或点击。")
    secret_key = safe_secret("DEEPSEEK_API_KEY", "")
    if secret_key:
        st.success("服务器端 API Key 已配置：DeepSeek 总结会自动生成，并固定留存到下一次 UTC+8 早上 8 点。")
    else:
        st.warning("未配置服务器端 API Key：页面将展示本地模板解释。")
    with st.expander("开发者临时测试 API Key", expanded=False):
        temp_key = st.text_input("临时 API Key（仅当前会话）", value="", type="password")
    api_key = temp_key or secret_key
    model = st.selectbox("模型", ["deepseek-chat", "deepseek-reasoner"], index=0)
    base_url = st.text_input("Base URL", safe_secret("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))

try:
    config_df = load_config(DEFAULT_CONFIG)
    series_df = load_series(DEFAULT_SERIES)
    asset_returns_df = load_asset_returns(DEFAULT_ASSET_RETURNS)
    result = MacroSignalEngine(config_df, series_df).run()
    backtest = run_backtest(config_df, series_df, asset_returns_df)
except Exception as exc:
    st.error(f"看板加载失败：{exc}")
    st.stop()

current_bucket = score_bucket(result.overall_score)
explanation = score_explanation(result.overall_score, result.trigger_count, result.valid_signal_count, backtest.latest_backtest_hint)
current_summary, backtest_summary = build_summaries(result, backtest, current_bucket)

main_tab, backtest_tab, logic_tab = st.tabs(["当前信号", "回测模型", "逻辑解释"])

with main_tab:
    render_kpis(result.overall_score, result.trigger_count, result.valid_signal_count, score_label(result.overall_score))
    st.info(explanation)

    render_deepseek_block(api_key, model, base_url, current_summary, backtest_summary, explanation)

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

with backtest_tab:
    st.subheader("回测模型结果")
    st.caption("回测使用虚拟宏观序列和虚拟资产收益率。信号在月末生成，组合收益使用下一月收益，避免直接用未来收益形成当期信号。")
    render_backtest_summary(backtest.forward_stats, backtest.strategy_curve, backtest.strategy_metrics, current_bucket)
    with st.expander("查看全部历史区间统计"):
        st.dataframe(
            backtest.forward_stats.style.format({
                "未来收益均值": "{:.2%}",
                "未来收益中位数": "{:.2%}",
                "胜率": "{:.1%}",
                "最差表现": "{:.2%}",
                "最好表现": "{:.2%}",
            }),
            use_container_width=True,
            hide_index=True,
        )
    with st.expander("查看防御分数历史"):
        score_hist = backtest.score_history.copy()
        st.line_chart(score_hist.set_index("date")[["defense_score"]])
        st.dataframe(score_hist, use_container_width=True, hide_index=True)

with logic_tab:
    st.subheader("结论生成逻辑")
    st.markdown(
        """
当前看板采用三层逻辑：

1. **信号层**：每个指标按配置表规则判断是否触发防御信号，触发记为 1，未触发记为 0。  
2. **评分层**：先计算每个一级维度的防御比例，再按维度权重汇总为总防御分数。  
3. **解释层**：回测模型提供历史相似区间表现，DeepSeek 只负责把结构化结果改写成投后语言。

因此，DeepSeek 不直接决定仓位，也不替代回测。真正的信号、分数和历史统计结果都由本地程序计算。
"""
    )
    st.subheader("项目内置文件")
    st.markdown(
        """
- `data/indicator_config.xlsx`：指标规则配置表。
- `data/macro_series_template.csv`：2015-01 至 2026-06 的虚拟宏观指标历史序列。
- `data/asset_returns_template.csv`：虚拟资产月度收益率，用于回测。
- `src/backtest_engine.py`：历史信号、分区统计、动态仓位策略回测。
- `src/deepseek_client.py`：DeepSeek API 调用封装。
"""
    )
    with st.expander("宏观指标原始数据"):
        st.dataframe(series_df, use_container_width=True, hide_index=True)
    with st.expander("资产收益率原始数据"):
        st.dataframe(asset_returns_df, use_container_width=True, hide_index=True)
