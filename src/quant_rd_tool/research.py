"""Research memo generation (LLM optional, template fallback)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from quant_rd_tool.config import settings

REPORT_SECTIONS = (
    "投资摘要",
    "公司与行业概览",
    "财务与估值要点",
    "风险因素",
    "技术面与因子观察",
    "结论与跟踪清单",
)


async def build_research_memo(
    *,
    symbol: str,
    thesis: str,
    factor_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return structured 研报 JSON; call OpenAI-compatible API when key is set."""
    base = {
        "symbol": symbol,
        "thesis": thesis,
        "sections": {k: "" for k in REPORT_SECTIONS},
        "factor_snapshot": factor_snapshot,
        "model": None,
    }

    if not settings.openai_api_key:
        base["sections"] = _template_sections(symbol, thesis, factor_snapshot)
        base["note"] = "未配置 OPENAI_API_KEY，返回模板骨架。配置后可生成完整叙述。"
        return base

    payload = {
        "model": settings.chat_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是卖方风格的中文投资研究员。只输出一个 JSON 对象，键为："
                    + json.dumps(list(REPORT_SECTIONS), ensure_ascii=False)
                    + "；值为该章节正文（Markdown 段落）。不要代码块包裹。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"标的: {symbol}\n投资命题/关注点: {thesis}\n"
                    f"因子快照: {json.dumps(factor_snapshot, ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.4,
    }
    base_url = (settings.openai_api_base or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    text = data["choices"][0]["message"]["content"]
    base["model"] = settings.chat_model
    try:
        parsed = json.loads(text)
        base["sections"] = {k: str(parsed.get(k, "")) for k in REPORT_SECTIONS}
    except json.JSONDecodeError:
        base["sections"]["投资摘要"] = text
        base["note"] = "模型未返回严格 JSON，全文置于「投资摘要」。"
    return base


def _template_sections(
    symbol: str, thesis: str, factor_snapshot: dict[str, Any]
) -> dict[str, str]:
    snap = json.dumps(factor_snapshot, ensure_ascii=False, indent=2)
    intro = f"标的 {symbol}：围绕「{thesis}」展开跟踪。"
    intro += "以下为因子快照，供定量验证。"
    return {
        "投资摘要": f"{intro}\n\n{snap}",
        "公司与行业概览": "（模板）请补充主营业务、竞争格局与行业景气度。",
        "财务与估值要点": "（模板）请补充营收利润趋势、现金流与估值对比。",
        "风险因素": "（模板）宏观、行业、个股特异性风险。",
        "技术面与因子观察": "（模板）结合下方因子快照与价格走势解读。",
        "结论与跟踪清单": "（模板）列出未来 1–2 个季度的关键催化剂与数据验证点。",
    }
