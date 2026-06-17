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


def generate_deepseek_summary_on_demand(current_json: str, backtest_json: str, model: str, base_url: str, api_key: str) -> tuple[str, str]:
    """手动生成 DeepSeek 总结，并保存到下一次 UTC+8 早上 8 点。"""
    cache_key = make_deepseek_cache_key(current_json, backtest_json, model, base_url)
    current_summary = json.loads(current_json)
    backtest_summary = json.loads(backtest_json)
    messages = build_ai_prompt(current_summary, backtest_summary)
    summary = generate_deepseek_analysis(api_key, messages, model=model, base_url=base_url)
    expires_at_text = save_deepseek_file_cache(cache_key, summary)
    return summary, expires_at_text


def ask_deepseek_with_context(question: str, current_summary: dict, backtest_summary: dict, model: str, base_url: str, api_key: str) -> str:
    """带当前数据和回测结果上下文的手动问答。

    这里并不会在页面打开时提前调用 DeepSeek；只有用户点击“发送问题”时才会调用 API。
    """
    messages = [
        {
            "role": "system",
            "content": (
                "你是一名资管/信托FOF投后分析助手。当前宏观信号和回测结果已经作为上下文提供。"
                "请严格基于上下文回答用户问题，不要编造未提供的数据。"
                "如果数据为虚拟/演示数据，必须提醒不能用于正式投资判断。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "当前宏观信号": current_summary,
                    "回测摘要": backtest_summary,
                    "用户问题": question,
                },
                ensure_ascii=False,
            ),
        },
    ]
    return generate_deepseek_analysis(api_key, messages, model=model, base_url=base_url)


def render_deepseek_panel(api_key: str, model: str, base_url: str, current_summary: dict, backtest_summary: dict) -> None:
    """手动 DeepSeek 分析面板。

    不再页面打开自动调用 DeepSeek。
    - 没有有效缓存：显示“生成分析”按钮，点击后调用一次并缓存到次日 UTC+8 早 8 点。
    - 有有效缓存：展示旧报告，并隐藏“生成分析”按钮，直到缓存过期或管理员清除缓存。
    - 对话区：发送问题时才调用 DeepSeek，问题会携带当前数据和回测摘要。
    """
    st.caption("DeepSeek 不会在页面打开时自动调用。只有点击“生成分析”或“发送问题”时才会消耗 API。")

    current_json = json.dumps(current_summary, ensure_ascii=False, sort_keys=True)
    backtest_json = json.dumps(backtest_summary, ensure_ascii=False, sort_keys=True)
    cache_key = make_deepseek_cache_key(current_json, backtest_json, model, base_url)
    cached_text, expires_at = load_deepseek_file_cache(cache_key)

    if not api_key:
        st.warning("未配置 DeepSeek API Key。请在 Streamlit Secrets 中配置 DEEPSEEK_API_KEY，或在侧边栏开发者测试区临时输入。")
        with st.expander("查看已准备发送给 DeepSeek 的结构化摘要", expanded=False):
            st.json({"current_summary": current_summary, "backtest_summary": backtest_summary})
        return

    if cached_text:
        st.success(f"已存在 DeepSeek 分析报告，固定留存到：{expires_at}。在失效前隐藏“生成分析”按钮，避免重复调用。")
        with st.container(border=True):
            st.markdown(cached_text)
    else:
        st.info("当前没有有效 DeepSeek 分析报告。点击下方按钮后会调用一次 API，并把结果保存到下一次 UTC+8 早上 8 点。")
        if st.button("生成分析", type="secondary", use_container_width=True):
            with st.spinner("正在调用 DeepSeek 生成分析，并保存到下一次 UTC+8 早上 8 点..."):
                try:
                    summary, expires_at_text = generate_deepseek_summary_on_demand(current_json, backtest_json, model, base_url, api_key)
                    st.success(f"生成成功，已保存到：{expires_at_text}。页面将刷新并隐藏“生成分析”按钮。")
                    st.markdown(summary)
                    st.rerun()
                except Exception as exc:
                    st.error(f"DeepSeek 分析生成失败：{exc}")

    st.divider()
    st.markdown("### 与 DeepSeek 对话【数据和回测结果已上传】")
    st.caption("这里的“已上传”指当前数据摘要和回测结果已作为对话上下文预置；只有发送问题时才会真正调用 DeepSeek。")

    question = st.text_area(
        "输入你想追问的问题",
        placeholder="例如：为什么当前判断是中性偏防御？哪些指标贡献最大？如何写成月报口径？",
        height=90,
    )
    if st.button("发送问题", type="secondary", use_container_width=True):
        if not question.strip():
            st.warning("请先输入问题。")
        else:
            with st.spinner("正在基于当前数据和回测结果向 DeepSeek 提问..."):
                try:
                    answer = ask_deepseek_with_context(question.strip(), current_summary, backtest_summary, model, base_url, api_key)
                    st.markdown("**DeepSeek 回复：**")
                    st.markdown(answer)
                except Exception as exc:
                    st.error(f"DeepSeek 对话失败：{exc}")

    with st.expander("查看已准备发送给 DeepSeek 的结构化摘要", expanded=False):
        st.json({"current_summary": current_summary, "backtest_summary": backtest_summary})

    with st.expander("管理员操作：清除 DeepSeek 分析缓存", expanded=False):
        st.caption("清除后会重新显示“生成分析”按钮。普通同事不需要操作。")
        if st.button("清除 DeepSeek 分析缓存", use_container_width=True):
            try:
                if DEEPSEEK_CACHE_FILE.exists():
                    DEEPSEEK_CACHE_FILE.unlink()
                st.success("缓存已清除，页面将刷新。")
                st.rerun()
            except Exception as exc:
                st.error(f"缓存清除失败：{exc}")


st.set_page_config(page_title="宏观指标信号与回测", layout="wide")

st.markdown(
    """
<style>
/* Main DeepSeek trigger button: black background + white text. */
div[data-testid="stButton"] > button[kind="primary"] {
    background: #0b0b0b !important;
    color: #ffffff !important;
    border: 1px solid #0b0b0b !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #222222 !important;
    color: #ffffff !important;
    border-color: #222222 !important;
}
div[data-testid="stButton"] > button[kind="primary"]:focus {
    color: #ffffff !important;
    border-color: #111111 !important;
    box-shadow: 0 0 0 0.2rem rgba(0, 0, 0, 0.18) !important;
}
/* Make Streamlit dialog feel like a larger floating analysis panel. */
div[role="dialog"] {
    border-radius: 18px !important;
}
div[role="dialog"] div[data-testid="stVerticalBlock"] {
    gap: 0.85rem;
}
</style>
""",
    unsafe_allow_html=True,
)
st.title("宏观指标信号与回测看板")
st.caption("配置驱动的宏观防御信号 + 虚拟历史回测 + DeepSeek API 文字解释。")
st.warning("当前内置数据均为演示/虚拟数据，只用于验证方法、部署和展示流程，不代表真实宏观数据库，也不应用于正式投研判断。")

with st.sidebar:
    st.header("数据源状态")
    st.info("当前模式：GitHub 仓库内演示数据")
    st.caption("宏观历史数据格式：date, indicator_id, value。资产收益率格式：date, asset_id, asset_name, return。")
    st.divider()
    st.header("DeepSeek API")
    st.caption("团队版建议在 Streamlit Secrets 中配置 API Key；普通同事无需输入 Key。DeepSeek 仅在手动生成分析或发送问题时调用。")
    secret_key = safe_secret("DEEPSEEK_API_KEY", "")
    if secret_key:
        st.success("服务器端 API Key 已配置：可手动生成 DeepSeek 分析，并固定留存到下一次 UTC+8 早上 8 点。")
    else:
        st.warning("未配置服务器端 API Key：DeepSeek 手动分析不可用，但本地规则判断和回测模型仍可使用。")
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

    st.subheader("自动生成判断")
    st.info("由回测结果和本地语言模板自动生成的判断，非 AI 大模型判断。")
    st.write(explanation)

    if hasattr(st, "dialog"):
        @st.dialog("DeepSeek 分析助手", width="large")
        def _deepseek_dialog():
            render_deepseek_panel(api_key, model, base_url, current_summary, backtest_summary)

        left_col, right_col = st.columns([1.2, 4])
        with left_col:
            if st.button("DeepSeek 分析助手", type="primary", use_container_width=True):
                _deepseek_dialog()
        with right_col:
            st.caption("点击后弹出悬浮分析框；可手动生成分析，或与 DeepSeek 对话。默认不自动调用 DeepSeek，不会因同事打开页面而消耗 API。")
    else:
        st.warning("当前 Streamlit 版本不支持悬浮弹窗。请升级到较新版本，或临时使用页面内面板。")
        if st.button("DeepSeek 分析助手", type="primary", use_container_width=True):
            with st.container(border=True):
                render_deepseek_panel(api_key, model, base_url, current_summary, backtest_summary)

    st.subheader("核心指标明细")
    st.caption("同事优先看这张表：最新数值、参考值、触发状态和数据状态均在这里。")
    render_signal_table(result.detail)

    st.subheader("维度防御分数")
    render_dimension_score(result.dimension_score)

    with st.expander("查看分级明细（一级维度 → 二级指标）", expanded=False):
        dimensions = list(result.detail["dimension"].drop_duplicates())
        tabs = st.tabs(["全维度", *dimensions])
        with tabs[0]:
            render_signal_hierarchy(result.detail, result.dimension_score)
        for tab, dimension in zip(tabs[1:], dimensions):
            with tab:
                render_signal_hierarchy(result.detail, result.dimension_score, dimension)

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

页面中的“本地规则解释”是**由回测结果和本地语言模板自动生成的判断，非 AI 大模型判断。**
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
