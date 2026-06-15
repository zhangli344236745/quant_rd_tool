from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from quant_rd_tool.main import app
from quant_rd_tool.stock_announcement_radar import (
    append_items,
    save_digest,
    score_text,
    tail_items,
)
from quant_rd_tool.stock_screener import run_screener
from quant_rd_tool.stock_workflow import normalize_template_steps, run_workflow, synthesize_advice
from quant_rd_tool.stock_workflow_storage import list_templates

client = TestClient(app)


def _fake_stock_df(n: int = 300) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = pd.Series(100 * (1 + np.random.default_rng(1).normal(0, 0.01, n)).cumprod(), index=dates)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0,
        }
    )


def test_normalize_template_steps_adds_advice():
    steps = normalize_template_steps([{"id": "technical", "enabled": True, "order": 0}])
    ids = [s["id"] for s in steps]
    assert "advice_synth" in ids


def test_synthesize_advice_var_gate():
    ctx = {
        "symbol": "600519",
        "timeframe": "1d",
        "steps": {
            "technical": {
                "status": "ok",
                "output": {"stance": "偏多", "score": 3, "technical_signal": {"stance": "偏多"}},
            },
            "zipline_strategy": {
                "status": "ok",
                "output": {"strategy_id": "ma_crossover", "target_pct": 0.6},
            },
            "var_symbol": {
                "status": "ok",
                "output": {"var_ratio": 0.12, "var_99_pct": 0.12, "var_99_cny": 12000},
            },
        },
    }
    advice = synthesize_advice(ctx, {"var_gate_pct": 0.08})
    assert advice["var_gate_triggered"] is True
    assert advice["suggested_position_pct"] <= 0.1


def test_run_workflow_mocked(monkeypatch, tmp_path):
    from quant_rd_tool import stock_workflow as sw

    df = _fake_stock_df(300)
    monkeypatch.setattr(sw, "_load_ohlcv", lambda *a, **k: df)
    monkeypatch.setattr(
        sw,
        "_step_technical",
        lambda ctx, p: {"stance": "中性", "score": 0, "technical_signal": {"stance": "中性", "action": "hold"}},
    )
    monkeypatch.setattr(
        sw,
        "_step_qlib_ml",
        lambda ctx, p: {"combined_signal": {"stance": "中性", "agreement": "仅技术面"}, "ml_analysis": {}},
    )
    monkeypatch.setattr(
        sw,
        "_step_zipline_strategy",
        lambda ctx, p: {"strategy_id": "ma_crossover", "target_pct": 0.0, "final_signal": {}},
    )
    monkeypatch.setattr(
        sw,
        "_step_var_symbol",
        lambda ctx, p: {"var_ratio": 0.03, "var_99_pct": 0.03, "var_99_cny": 3000},
    )

    template = {
        "id": "t1",
        "name": "test",
        "symbol_default": "600519",
        "timeframe": "1d",
        "steps": normalize_template_steps(
            [
                {"id": "technical", "enabled": True, "order": 0},
                {"id": "qlib_ml", "enabled": True, "order": 1},
                {"id": "zipline_strategy", "enabled": True, "order": 2},
                {"id": "var_symbol", "enabled": True, "order": 3},
                {"id": "advice_synth", "enabled": True, "order": 4},
            ]
        ),
    }
    data_dir = str(tmp_path / "stocks")
    result = run_workflow(symbol="600519", template=template, data_dir=data_dir, refresh_ohlcv=False, save=True)
    assert result["symbol"] in ("600519", "SH600519")
    assert result.get("advice")
    assert result["advice"]["stance"] in ("偏多", "谨慎", "中性")
    assert len(result["steps"]) >= 5
    assert result.get("audit_record", {}).get("run_id")


def test_workflow_qlib_oos_compact():
    from quant_rd_tool.stock_workflow import _compact_output, summarize_step

    output = {
        "skipped": False,
        "combined_signal": {"stance": "偏多", "agreement": "一致"},
        "ml_analysis": {"enabled": True},
        "oos_summary": {
            "protocol_type": "fixed_split",
            "gate_passed": True,
            "test_ic": 0.03,
            "headline": "OOS 通过",
            "markdown": "## OOS",
        },
    }
    compact = _compact_output("qlib_ml", output)
    assert compact["oos_summary"]["gate_passed"] is True
    assert compact["oos_markdown"] == "## OOS"
    summary = summarize_step("qlib_ml", output, status="ok")
    assert "OOS✓" in summary


def test_oos_protocol_route_missing_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/v1/stocks/600519/oos-protocol?data_dir=data/stocks")
    assert r.status_code == 404


def test_workflow_steps_route():
    r = client.get("/api/v1/stocks/workflow/steps")
    assert r.status_code == 200, r.text
    ids = {s["id"] for s in r.json()["steps"]}
    assert "technical" in ids
    assert "advice_synth" in ids
    assert "options_vol" not in ids


def test_workflow_templates_route(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/v1/stocks/workflow/templates?data_dir=data/stocks")
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1
    tpls = list_templates("data/stocks")
    assert tpls[0]["symbol_default"] == "600519"


def test_announcements_digest_route(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/v1/stocks/announcements/digest?data_dir=data/stocks")
    assert r.status_code == 200, r.text
    assert "digest" in r.json()


def test_score_text():
    score, hits = score_text("关于公司收到立案告知书的公告")
    assert score >= 80
    assert "立案" in hits


def test_screener_high_impact_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = "data/stocks"
    save_digest(
        data_dir,
        {
            "generated_at": "2026-06-15T00:00:00+00:00",
            "top_items": [
                {
                    "code": "600519",
                    "title": "股东减持计划公告",
                    "score": 72,
                    "keywords": ["减持"],
                }
            ],
        },
    )

    out = run_screener(codes=["600519", "000001"], high_impact_only=True, page_size=10, data_dir=data_dir)
    assert out["total"] == 1
    assert out["items"][0]["code"] == "600519"


def test_screener_notice_keyword(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = "data/stocks"
    append_items(
        data_dir,
        [
            {
                "ts": datetime.now(UTC).isoformat(),
                "code": "600519",
                "title": "业绩预增公告",
                "published": "2026-06-15",
                "score": 80,
                "keywords": ["业绩预增"],
                "source": "notice",
            }
        ],
    )
    out = run_screener(codes=["600519", "000001"], notice_keyword="业绩预增", page_size=10, data_dir=data_dir)
    assert out["total"] == 1
    assert out["items"][0]["code"] == "600519"


def test_announcement_scan_mocked(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from quant_rd_tool import stock_announcement_radar as radar

    monkeypatch.setattr(
        radar,
        "_resolve_symbols",
        lambda symbols, use_watchlist=True: ["600519"],
    )
    monkeypatch.setattr(
        radar.astk,
        "fetch_stock_notices",
        lambda code, limit=15: [{"公告标题": "收到立案告知书", "公告日期": "2026-06-12"}],
    )
    out = radar.run_announcement_scan(data_dir="data/stocks", use_watchlist=True, min_score=40)
    assert out["items_new"] >= 1
    items = tail_items(data_dir="data/stocks", limit=5)
    assert items
    assert items[0]["score"] >= 80
