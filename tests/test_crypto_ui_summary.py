from __future__ import annotations

from quant_rd_tool.crypto_analyzer import build_crypto_ui_summary


def test_build_crypto_ui_summary_plain_language():
    report = {
        "symbol": "CRYPTO_BTC",
        "pair": "BTC/USDT",
        "timeframe": "5m",
        "period": {"start": "2026-06-01", "end": "2026-06-03", "bars": 800},
        "analysis": {
            "symbol": "CRYPTO_BTC",
            "price": {
                "latest_close": 65000.0,
                "period_high": 68000.0,
                "period_low": 62000.0,
                "pct_from_high": -0.044,
            },
            "technical": {
                "ma_alignment": "震荡",
                "macd_trend": "空头",
                "rsi_14": 42.5,
                "rsi_zone": "中性",
                "bollinger_zone": "中轨附近",
            },
            "returns": {"5d": 0.01, "20d": -0.03},
            "risk": {"max_drawdown": -0.12},
        },
        "combined_signal": {
            "stance": "中性",
            "action": "hold",
            "confidence": 0.55,
            "agreement": "一致",
            "technical": {"stance": "中性"},
            "ml": {"stance": "看涨"},
        },
        "narrative": {
            "stance": "中性",
            "action": "hold",
            "summary": "BTC 最新价 65000，研判 **中性**。",
            "advice": "建议观望。",
            "observations": ["均线纠缠"],
            "risks": ["波动大"],
            "investment_brief": {
                "one_liner": "BTC/USDT：中性 — 价 65000，震荡。",
                "sections": [{"title": "结论", "paragraphs": ["综合中性。"]}],
            },
            "disclaimer": "不构成投资建议。",
        },
    }
    ui = build_crypto_ui_summary(report)
    assert ui["stance"] == "中性"
    assert ui["action_label"] == "观望"
    assert "65000" in ui["headline"]
    assert any("均线排列" in line for line in ui["technical_lines"])
    assert ui["brief_sections"][0]["title"] == "结论"
