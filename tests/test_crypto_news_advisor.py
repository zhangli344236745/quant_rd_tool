from __future__ import annotations

from unittest.mock import patch

from quant_rd_tool.crypto_news_advisor import advise_items, template_advice


def test_template_fallback_without_api_key():
    items = [
        {
            "title": "Fed raises rates",
            "summary": "Rates up 25bps",
            "score": 55,
            "category": "macro",
            "impact_direction": "bearish",
            "symbols": ["BTC"],
        }
    ]
    with patch("quant_rd_tool.crypto_news_advisor.settings") as mock_settings:
        mock_settings.openai_api_key = None
        out = advise_items(items, top_n=1)
    assert len(out) == 1
    advice = out[0]["advice"]
    assert advice["impact"] in ("bullish", "bearish", "neutral", "mixed")
    assert advice.get("advice_template") or advice.get("advice")
    assert "仅供参考" in advice.get("risk_note", "") or "仅供参考" in advice.get("advice", "")


def test_template_advice_fields():
    item = {
        "title": "SEC enforcement action",
        "category": "regulation",
        "impact_direction": "bearish",
        "symbols": ["ETH"],
    }
    advice = template_advice(item)
    assert advice["headline"] == item["title"]
    assert advice["impact"] == "bearish"
    assert "ETH" in advice["affected_symbols"]


def test_mock_llm_merges_json_into_item():
    items = [
        {
            "title": "Bitcoin ETF inflows surge",
            "summary": "Institutional demand rises",
            "score": 60,
            "category": "crypto_native",
            "impact_direction": "bullish",
            "symbols": ["BTC"],
        }
    ]
    llm_json = {
        "headline": "Bitcoin ETF inflows surge",
        "impact": "bullish",
        "confidence": 0.85,
        "affected_symbols": ["BTC"],
        "horizon": "days",
        "advice": "资金流入支撑短期情绪，注意高位波动。仅供参考，不构成投资建议。",
        "risk_note": "流入可能放缓。",
    }

    def fake_call(_items):
        return [llm_json]

    with patch("quant_rd_tool.crypto_news_advisor.settings") as mock_settings:
        mock_settings.openai_api_key = "test-key"
        mock_settings.chat_model = "gpt-4o"
        mock_settings.openai_api_base = None
        with patch("quant_rd_tool.crypto_news_advisor._llm_advise_batch", side_effect=fake_call):
            out = advise_items(items, top_n=1)
    assert out[0]["advice"]["confidence"] == 0.85
    assert out[0]["advice"]["impact"] == "bullish"
    assert "BTC" in out[0]["advice"]["affected_symbols"]
