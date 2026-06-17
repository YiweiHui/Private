"""宏观防御分数解释。"""

from __future__ import annotations


def score_bucket(score: float) -> str:
    if score < 0.25:
        return "0%–25%"
    if score < 0.50:
        return "25%–50%"
    if score < 0.75:
        return "50%–75%"
    return "75%–100%"


def score_label(score: float) -> str:
    """用于页面 KPI 的短标签，避免 Streamlit metric 文案被截断。"""
    if score < 0.25:
        return "偏友好"
    if score < 0.50:
        return "中性偏谨慎"
    if score < 0.75:
        return "中性偏防御"
    return "高防御"


def score_recommendation(score: float) -> str:
    """用于正文解释的配置提示。"""
    if score < 0.25:
        return "宏观环境整体偏友好，可维持权益配置。"
    if score < 0.50:
        return "宏观环境处于中性偏谨慎状态，权益仓位不宜过度激进。"
    if score < 0.75:
        return "宏观环境处于中性偏防御状态，建议权益仓位由积极转向中性或中性偏低。"
    return "宏观环境处于高防御状态，建议组合更偏债券、现金、红利低波等防御资产。"


def score_explanation(score: float, trigger_count: int, valid_signal_count: int, backtest_hint: str | None = None) -> str:
    if valid_signal_count == 0:
        return "当前没有足够有效数据生成信号。"
    base = (
        f"当前共有 {trigger_count}/{valid_signal_count} 个有效指标触发防御信号，"
        f"加权总防御分数为 {score:.1%}，处于 {score_bucket(score)} 区间。"
        f"{score_recommendation(score)}"
    )
    if backtest_hint:
        base += backtest_hint
    return base
