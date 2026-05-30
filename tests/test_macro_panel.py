"""Tests for macro panel CLI helpers."""

from __future__ import annotations

from unittest.mock import patch

from quant_rd_tool.macro_panel import build_macro_panel, render_macro_markdown, save_macro_panel


@patch("quant_rd_tool.macro_panel.openbb_available", return_value=True)
@patch(
    "quant_rd_tool.openbb_settings.configure_openbb_credentials",
    return_value={"fred": False, "fmp": False},
)
@patch("quant_rd_tool.openbb_macro.fetch_macro_context")
@patch("quant_rd_tool.openbb_equity.fetch_economy_calendar_events", return_value=[])
def test_build_macro_panel(mock_events, mock_macro, _creds, _avail):
    mock_macro.return_value = {
        "available": True,
        "summary": "测试摘要。",
        "china": {"profile": {"gdp_yoy": 0.04}},
        "global": [],
    }
    panel = build_macro_panel(code=None, use_fred=False)
    assert panel["macro"]["summary"] == "测试摘要。"
    assert "markdown" in panel
    assert "## 宏观摘要" in panel["markdown"]


def test_save_macro_panel(tmp_path):
    panel = {
        "generated_at": "2026-01-01",
        "macro": {"available": True, "summary": "ok"},
        "markdown": render_macro_markdown(
            {"generated_at": "2026-01-01", "macro": {"available": True, "summary": "ok"}}
        ),
    }
    paths = save_macro_panel(panel, tmp_path)
    assert (tmp_path / "panel.json").exists()
    assert (tmp_path / "panel.md").exists()
    assert paths["json"].endswith("panel.json")
