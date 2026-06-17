"""宏观防御分数解释。"""

from __future__ import annotations


def score_label(score: float) -> str:
    """把 0~1 的总防御分数翻译成组合语言。"""
    if score < 0.25:
        return "宏观环境偏友好，可维持权益配置"
    if score < 0.50:
        return "中性偏谨慎，权益不宜过度激进"
    if score < 0.75:
        return "防御信号较强，建议降低权益仓位"
    return "高防御状态，偏债券、现金、红利、低波"


def score_explanation(score: float, trigger_count: int, valid_signal_count: int) -> str:
    if valid_signal_count == 0:
        return "当前没有足够有效数据生成信号。"
    return (
        f"当前共有 {trigger_count}/{valid_signal_count} 个有效指标触发防御信号，"
        f"加权总防御分数为 {score:.1%}。{score_label(score)}。"
    )
