"""LLM advice for top news items with template fallback."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from quant_rd_tool.config import settings

logger = logging.getLogger(__name__)

DISCLAIMER = "仅供参考，不构成投资建议。"

HORIZON_BY_CATEGORY = {
    "macro": "weeks",
    "regulation": "days",
    "security": "intraday",
    "market": "intraday",
    "crypto_native": "days",
}


def template_advice(item: dict[str, Any]) -> dict[str, Any]:
    category = item.get("category") or "market"
    impact = item.get("impact_direction") or "neutral"
    symbols = item.get("symbols") or []
    title = item.get("title") or "News item"
    cat_label = {
        "macro": "宏观",
        "regulation": "监管",
        "security": "安全",
        "market": "市场",
        "crypto_native": "加密原生",
    }.get(category, "市场")
    impact_label = {
        "bullish": "偏多",
        "bearish": "偏空",
        "neutral": "中性",
        "mixed": "分化",
    }.get(impact, "中性")
    sym_text = "、".join(symbols) if symbols else "主流加密资产"
    advice_text = (
        f"【{cat_label}】{title} — 规则判断{impact_label}，"
        f"可能波及 {sym_text}。请结合仓位与流动性自行评估。{DISCLAIMER}"
    )
    return {
        "headline": title,
        "impact": impact,
        "confidence": 0.45,
        "affected_symbols": symbols or ["BTC"],
        "horizon": HORIZON_BY_CATEGORY.get(category, "days"),
        "advice": advice_text,
        "advice_template": True,
        "risk_note": f"规则引擎输出，未调用 LLM。{DISCLAIMER}",
    }


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if len(lines) > 2 else lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _llm_advise_batch(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Call OpenAI-compatible API for a batch of items; one JSON object per item in array."""
    base_url = (settings.openai_api_base or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    schema_hint = (
        "每个元素键: headline, impact(bullish|bearish|neutral|mixed), confidence(0-1), "
        "affected_symbols(array), horizon(intraday|days|weeks), advice(中文1-3句), risk_note"
    )
    user_lines = []
    for i, item in enumerate(items, 1):
        source = item.get("source_id") or "rss"
        query_hint = ""
        if str(source).startswith("web_search:"):
            query_hint = f" search_query={item.get('search_query')}"
        user_lines.append(
            f"{i}. title={item.get('title')}\n   summary={item.get('summary')}\n"
            f"   category={item.get('category')} score={item.get('score')} "
            f"symbols={item.get('symbols')} source={source}{query_hint}"
        )
    payload = {
        "model": settings.chat_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是加密宏观舆情分析师。只输出 JSON 数组，"
                    f"与输入条目一一对应。{schema_hint}。"
                    f"advice 须注明非下单指令。{DISCLAIMER}"
                ),
            },
            {"role": "user", "content": "\n".join(user_lines)},
        ],
        "temperature": 0.3,
    }
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    text = data["choices"][0]["message"]["content"]
    parsed = _parse_llm_json(text)
    if not isinstance(parsed, list):
        raise ValueError("LLM did not return JSON array")
    results: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        advice = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else template_advice(item)
        advice.setdefault("headline", item.get("title"))
        advice["advice_template"] = False
        results.append(advice)
    return results


def advise_items(items: list[dict[str, Any]], *, top_n: int = 5) -> list[dict[str, Any]]:
    """Advise top items via LLM when API key set; otherwise template fallback."""
    batch = items[:top_n]
    if not batch:
        return []

    if not settings.openai_api_key:
        return [{**item, "advice": template_advice(item)} for item in batch]

    try:
        advices = _llm_advise_batch(batch)
    except Exception as exc:
        logger.warning("LLM advice failed, using templates: %s", exc)
        advices = [template_advice(item) for item in batch]

    out: list[dict[str, Any]] = []
    for item, advice in zip(batch, advices, strict=False):
        out.append({**item, "advice": advice})
    return out
