"""DeepSeek API 调用封装。

默认使用 OpenAI-compatible 的 chat completions 形式。
"""

from __future__ import annotations

import json
from typing import Any

import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def build_ai_prompt(current_summary: dict[str, Any], backtest_summary: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是一名资管/信托FOF投后分析助手。请基于用户给出的结构化数据生成中文投后解释。"
        "要求：1）不要编造未提供的数据；2）明确说明数据为演示/虚拟时不能用于正式投资判断；"
        "3）结论要审慎，避免绝对化；4）输出分为：当前信号、回测依据、配置含义、风险提示。"
    )
    user = {
        "当前宏观信号": current_summary,
        "回测摘要": backtest_summary,
        "输出要求": "生成约300-500字中文说明，适合放在看板或周报中。",
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def generate_deepseek_analysis(api_key: str, messages: list[dict[str, str]], model: str = DEFAULT_MODEL,
                               base_url: str = DEFAULT_BASE_URL, timeout: int = 60) -> str:
    if not api_key:
        raise ValueError("缺少 DeepSeek API Key。")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 1200}
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"DeepSeek API 调用失败：HTTP {resp.status_code} - {resp.text[:500]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        raise RuntimeError(f"DeepSeek API 返回格式异常：{data}") from exc
