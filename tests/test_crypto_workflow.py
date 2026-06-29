from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_rd_tool.crypto_workflow import (
    normalize_template_steps,
    run_workflow,
    summarize_step,
    synthesize_advice,
)
from quant_rd_tool.crypto_workflow_storage import duplicate_template, list_templates
from quant_rd_tool.main import app

client = TestClient(app)


def _fake_df(n: int = 500) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = pd.Series(100 * (1 + np.random.default_rng(0).normal(0, 0.002, n)).cumprod(), index=dates)
    return pd.DataFrame(
        {
            "date": dates,
            "timestamp": (dates.astype("int64") // 10**6).astype(int),
            "symbol": "CRYPTO_BTC",
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_normalize_template_steps_adds_advice():
    steps = normalize_template_steps([{"id": "technical", "enabled": True, "order": 0}])
    ids = [s["id"] for s in steps]
    assert "advice_synth" in ids


def test_synthesize_advice_var_gate():
    ctx = {
        "symbol": "BTC",
        "timeframe": "1d",
        "steps": {
            "technical": {
                "status": "ok",
                "output": {"stance": "看涨", "score": 3, "technical_signal": {"stance": "看涨"}},
            },
            "zipline_strategy": {
                "status": "ok",
                "output": {"strategy_id": "ma_crossover", "target_pct": 0.6},
            },
            "var_symbol": {
                "status": "ok",
                "output": {"var_ratio": 0.12, "var_99_pct": 0.12, "var_99_usdt": 1200},
            },
        },
    }
    advice = synthesize_advice(ctx, {"var_gate_pct": 0.08})
    assert advice["var_gate_triggered"] is True
    assert advice["suggested_position_pct"] <= 0.1
    segs = advice.get("segments") or {}
    assert segs["spot"]["label"] == "现货"
    assert segs["perp"]["label"] == "合约"
    assert segs["perp"]["var_gate_triggered"] is True
    assert segs["options"]["label"] == "期权"


def test_synthesize_advice_segments_spot_perp_options():
    ctx = {
        "symbol": "BTC",
        "timeframe": "1d",
        "steps": {
            "technical": {
                "status": "ok",
                "output": {"stance": "看涨", "score": 3},
            },
            "qlib_ml": {
                "status": "ok",
                "output": {
                    "combined_signal": {
                        "stance": "看涨",
                        "agreement": "一致",
                        "ml": {"stance": "看涨"},
                    },
                },
            },
            "volume_analysis": {
                "status": "ok",
                "output": {
                    "advice": {
                        "level": "buy",
                        "stance": "看涨",
                        "scheme_label": "放量突破",
                        "level_label": "建议参与",
                    },
                },
            },
            "zipline_strategy": {
                "status": "ok",
                "output": {"strategy_id": "ma_crossover", "target_pct": 0.5},
            },
            "var_symbol": {
                "status": "ok",
                "output": {"var_ratio": 0.03, "var_99_pct": 0.03, "var_99_usdt": 300},
            },
            "options_vol": {
                "status": "ok",
                "output": {
                    "enabled": True,
                    "cross_view": {
                        "summary": "方向偏多且 IV 未极端",
                        "alignment": "共振",
                        "notes": ["IV 历史分位约 55%。"],
                        "options_stance": "中性",
                    },
                    "scan_item": {"atm_iv": 0.45, "iv_percentile": 55},
                    "options_vol": {
                        "advice": {
                            "stance": "中性",
                            "summary": "BTC：中性。",
                            "actions": ["维持常规仓位管理。"],
                            "confidence": 0.45,
                        },
                    },
                },
            },
        },
    }
    advice = synthesize_advice(ctx, {})
    segs = advice["segments"]
    assert segs["spot"]["stance"] == "看涨"
    assert segs["spot"]["available"] is True
    assert segs["perp"]["stance"] == "看涨"
    assert segs["perp"]["suggested_position_pct"] >= 0.4
    assert segs["options"]["available"] is True
    assert segs["options"]["alignment"] == "共振"
    assert "### 现货" in advice["markdown"]
    assert "### 合约" in advice["markdown"]
    assert "### 期权" in advice["markdown"]


def test_run_workflow_mocked(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_workflow as cw

    df = _fake_df(500)
    monkeypatch.setattr(cw, "_load_ohlcv", lambda *a, **k: df)
    monkeypatch.setattr(
        cw,
        "_step_technical",
        lambda ctx, p: {"stance": "中性", "score": 0, "technical_signal": {"stance": "中性", "action": "hold"}},
    )
    monkeypatch.setattr(
        cw,
        "_step_qlib_ml",
        lambda ctx, p: {"combined_signal": {"stance": "中性", "agreement": "仅技术面"}, "ml_analysis": {}},
    )
    monkeypatch.setattr(
        cw,
        "_step_zipline_strategy",
        lambda ctx, p: {"strategy_id": "ma_crossover", "target_pct": 0.0, "final_signal": {}},
    )
    monkeypatch.setattr(
        cw,
        "_step_var_symbol",
        lambda ctx, p: {"var_ratio": 0.03, "var_99_pct": 0.03, "var_99_usdt": 300},
    )
    monkeypatch.setattr(
        cw,
        "_step_options_vol",
        lambda ctx, p: {"enabled": False, "options_vol": {}},
    )

    template = {
        "id": "t1",
        "name": "test",
        "symbol_default": "BTC",
        "timeframe": "1d",
        "steps": normalize_template_steps(
            [
                {"id": "technical", "enabled": True, "order": 0},
                {"id": "qlib_ml", "enabled": True, "order": 1},
                {"id": "zipline_strategy", "enabled": True, "order": 2},
                {"id": "var_symbol", "enabled": True, "order": 3},
                {"id": "options_vol", "enabled": False, "order": 4},
                {"id": "advice_synth", "enabled": True, "order": 5},
            ]
        ),
    }
    data_dir = str(tmp_path / "crypto")
    result = run_workflow(symbol="BTC", template=template, data_dir=data_dir, refresh_ohlcv=False, save=True)
    assert result["symbol"] == "BTC"
    assert result.get("advice")
    assert result["advice"]["stance"] in ("看涨", "看跌", "中性")
    assert len(result["steps"]) >= 5


def test_workflow_steps_route():
    r = client.get("/api/v1/crypto/workflow/steps")
    assert r.status_code == 200, r.text
    ids = {s["id"] for s in r.json()["steps"]}
    assert "technical" in ids
    assert "advice_synth" in ids


def test_workflow_templates_route(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/v1/crypto/workflow/templates?data_dir=data/crypto")
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1


def test_summarize_step_qlib_skipped():
    out = {"skipped": True, "reason": "样本不足", "combined_signal": {"stance": "中性"}}
    assert "样本不足" in summarize_step("qlib_ml", out, status="skipped")


def test_run_workflow_qlib_skipped_status(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_workflow as cw

    df = _fake_df(500)
    monkeypatch.setattr(cw, "_load_ohlcv", lambda *a, **k: df)
    monkeypatch.setattr(
        cw,
        "_step_technical",
        lambda ctx, p: {"stance": "中性", "score": 0, "technical_signal": {"stance": "中性"}},
    )
    monkeypatch.setitem(
        cw._STEP_HANDLERS,
        "qlib_ml",
        lambda ctx, p: {
            "skipped": True,
            "reason": "样本不足",
            "combined_signal": {"stance": "中性", "agreement": "仅技术面"},
        },
    )
    monkeypatch.setitem(
        cw._STEP_HANDLERS,
        "zipline_strategy",
        lambda ctx, p: {"strategy_id": "ma", "target_pct": 0.0},
    )
    monkeypatch.setitem(
        cw._STEP_HANDLERS,
        "var_symbol",
        lambda ctx, p: {"var_ratio": 0.02, "var_99_usdt": 200, "var_99_pct": 0.02},
    )

    template = {
        "name": "skip-ml",
        "timeframe": "1d",
        "steps": normalize_template_steps(
            [
                {"id": "technical", "enabled": True, "order": 0},
                {"id": "qlib_ml", "enabled": True, "order": 1},
                {"id": "var_symbol", "enabled": True, "order": 2},
                {"id": "options_vol", "enabled": False, "order": 3},
            ]
        ),
    }
    result = run_workflow(symbol="BTC", template=template, data_dir=str(tmp_path / "crypto"), refresh_ohlcv=False, save=False)
    qlib = next(s for s in result["steps"] if s["id"] == "qlib_ml")
    assert qlib["status"] == "skipped"
    assert qlib.get("elapsed_s") is not None


def test_duplicate_template(tmp_path):
    data_dir = str(tmp_path / "crypto")
    templates = list_templates(data_dir)
    src_id = templates[0]["id"]
    dup = duplicate_template(data_dir, src_id)
    assert dup
    assert dup["id"] != src_id
    assert "副本" in dup["name"]


def test_workflow_duplicate_route(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.post("/api/v1/crypto/workflow/templates/default-btc-1d/duplicate?data_dir=data/crypto")
    assert r.status_code == 200, r.text
    assert r.json()["template"]["id"] != "default-btc-1d"


def test_resolve_template_for_run_overrides(tmp_path):
    from quant_rd_tool.crypto_workflow import resolve_template_for_run

    data_dir = str(tmp_path / "crypto")
    list_templates(data_dir)
    tpl = resolve_template_for_run(
        data_dir=data_dir,
        template_id="default-btc-1d",
        timeframe="4h",
        steps=[{"id": "technical", "enabled": True, "order": 0}],
    )
    assert tpl["timeframe"] == "4h"
    ids = [s["id"] for s in tpl["steps"]]
    assert "advice_synth" in ids


def test_resolve_template_for_run_missing(tmp_path):
    from quant_rd_tool.crypto_workflow import resolve_template_for_run

    data_dir = str(tmp_path / "crypto")
    list_templates(data_dir)
    with pytest.raises(LookupError):
        resolve_template_for_run(data_dir=data_dir, template_id="nope")


def test_run_workflow_progress_cb(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_workflow as cw

    df = _fake_df(500)
    monkeypatch.setattr(cw, "_load_ohlcv", lambda *a, **k: df)
    monkeypatch.setitem(
        cw._STEP_HANDLERS,
        "technical",
        lambda ctx, p: {"stance": "中性", "score": 0, "technical_signal": {"stance": "中性"}},
    )
    monkeypatch.setitem(
        cw._STEP_HANDLERS,
        "var_symbol",
        lambda ctx, p: {"var_ratio": 0.02, "var_99_usdt": 200, "var_99_pct": 0.02},
    )
    messages: list[tuple[float, str]] = []
    template = {
        "name": "progress",
        "timeframe": "1d",
        "steps": normalize_template_steps(
            [
                {"id": "technical", "enabled": True, "order": 0},
                {"id": "var_symbol", "enabled": True, "order": 1},
            ]
        ),
    }
    run_workflow(
        symbol="BTC",
        template=template,
        data_dir=str(tmp_path / "crypto"),
        refresh_ohlcv=False,
        save=False,
        progress_cb=lambda p, m: messages.append((p, m)),
    )
    assert messages
    assert any("OHLCV" in m for _, m in messages)
    assert any("建议" in m for _, m in messages)
    probs = [p for p, _ in messages]
    assert probs == sorted(probs)


def test_job_runner_crypto_workflow(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_workflow as cw
    from quant_rd_tool.job_runner import JobRunner
    from quant_rd_tool.job_store import JobStore

    monkeypatch.chdir(tmp_path)
    df = _fake_df(500)
    monkeypatch.setattr(cw, "_load_ohlcv", lambda *a, **k: df)
    monkeypatch.setitem(
        cw._STEP_HANDLERS,
        "technical",
        lambda ctx, p: {"stance": "中性", "score": 0, "technical_signal": {"stance": "中性"}},
    )
    for sid in ("qlib_ml", "zipline_strategy", "var_symbol", "options_vol"):
        monkeypatch.setitem(cw._STEP_HANDLERS, sid, lambda ctx, p: {"skipped": True, "reason": "test"})

    store = JobStore(tmp_path / "jobs.db")
    job = store.create(
        type="crypto_workflow",
        code="BTC",
        payload={
            "symbol": "BTC",
            "template_id": "default-btc-1d",
            "data_dir": "data/crypto",
            "refresh_ohlcv": False,
        },
    )
    runner = JobRunner(store, data_dir="data/stocks")
    runner.run_once()
    got = store.get(job["id"])
    assert got["status"] == "done", got.get("error")

    from quant_rd_tool.job_results import load_job_result

    snap = load_job_result(got["result_path"])
    assert snap["kind"] == "crypto_workflow"
    assert snap["run_id"]
    assert snap["symbol"] == "BTC"


def test_workflow_run_steps_override(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_workflow as cw

    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"symbol": kwargs["symbol"], "timeframe": kwargs["template"]["timeframe"], "steps": [], "advice": {}}

    monkeypatch.setattr(cw, "run_workflow", fake_run)
    r = client.post(
        "/api/v1/crypto/workflow/run",
        json={
            "symbol": "ETH",
            "timeframe": "4h",
            "template_id": "default-btc-1d",
            "data_dir": "data/crypto",
            "steps": [{"id": "technical", "enabled": True, "order": 0, "params": {}}],
        },
    )
    assert r.status_code == 200, r.text
    assert captured["symbol"] == "ETH"
    tpl = captured["template"]
    assert tpl["timeframe"] == "4h"
    assert len(tpl["steps"]) >= 2


def test_workflow_run_route(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_workflow as cw

    monkeypatch.chdir(tmp_path)
    df = _fake_df(500)
    monkeypatch.setattr(cw, "_load_ohlcv", lambda *a, **k: df)
    monkeypatch.setattr(
        cw,
        "_step_technical",
        lambda ctx, p: {"stance": "中性", "score": 0, "technical_signal": {"stance": "中性"}},
    )
    monkeypatch.setattr(cw, "_step_qlib_ml", lambda ctx, p: {"combined_signal": {"stance": "中性"}})
    monkeypatch.setattr(cw, "_step_zipline_strategy", lambda ctx, p: {"target_pct": 0.0, "strategy_id": "ma"})
    monkeypatch.setattr(cw, "_step_var_symbol", lambda ctx, p: {"var_ratio": 0.02, "var_99_usdt": 200})
    monkeypatch.setattr(cw, "_step_options_vol", lambda ctx, p: {"enabled": False})

    r = client.post(
        "/api/v1/crypto/workflow/run",
        json={"symbol": "BTC", "template_id": "default-btc-1d", "data_dir": "data/crypto"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("advice")
