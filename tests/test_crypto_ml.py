from __future__ import annotations

import numpy as np
import pandas as pd

from quant_rd_tool import crypto_ml
from quant_rd_tool.crypto_ml import merge_crypto_signals, run_crypto_ml_analysis
from quant_rd_tool.qlib_ml import _adaptive_signal_threshold, _signal_from_pred


def _tech(stance: str = "看涨", score: int = 1) -> dict:
    return {"stance": stance, "action": "buy", "score": score, "reasons": []}


def _ml(ic: float, acc: float, signal: str = "模型偏多") -> dict:
    return {
        "enabled": True,
        "algorithm": "xgb",
        "latest": {"signal": signal, "predicted_return": 0.01},
        "test_metrics": {"ic": ic, "direction_accuracy": acc},
    }


def test_adaptive_threshold_scales_with_volatility():
    rng = np.random.default_rng(0)
    daily = pd.Series(rng.normal(0, 0.03, 300))
    intraday = pd.Series(rng.normal(0, 0.001, 300))
    t_daily = _adaptive_signal_threshold(daily)
    t_intra = _adaptive_signal_threshold(intraday)
    assert t_intra < t_daily
    assert t_intra >= 1e-4
    # Intraday-scale prediction now fires instead of being stuck at 中性
    assert _signal_from_pred(0.0008, t_intra) == "模型偏多"
    assert _signal_from_pred(0.0008) == "中性"  # old fixed threshold


def test_adaptive_threshold_fallback_small_sample():
    from quant_rd_tool.qlib_ml import DEFAULT_SIGNAL_THRESHOLD

    assert _adaptive_signal_threshold(pd.Series([0.01] * 5)) == DEFAULT_SIGNAL_THRESHOLD


def test_merge_signals_ml_quality_gate_blocks_bad_model():
    good = merge_crypto_signals(_tech(), _ml(ic=0.05, acc=0.55))
    bad = merge_crypto_signals(_tech(), _ml(ic=-0.02, acc=0.55))
    assert good["score"] == 2
    assert good["ml"]["reliable"] is True
    assert bad["score"] == 1  # ML not counted
    assert bad["ml"]["reliable"] is False
    assert any("质量门控" in r for r in bad["reasons"])


def test_merge_signals_ml_quality_gate_low_accuracy():
    out = merge_crypto_signals(_tech(), _ml(ic=0.03, acc=0.40))
    assert out["ml"]["reliable"] is False
    assert out["score"] == 1


def test_run_crypto_ml_analysis_cache(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_run_ml(*a, **k):
        calls["n"] += 1
        return {"enabled": True, "algorithm": "xgb", "latest": {"signal": "中性"}}

    monkeypatch.setattr(crypto_ml, "run_ml_analysis", fake_run_ml)
    qlib_dir = str(tmp_path / "CRYPTO_BTC" / "qlib")
    kwargs = dict(
        start_date="2024-01-01",
        end_date="2026-01-01",
        num_bars=800,
        algorithm="xgb",
        timeframe="1d",
    )
    first = run_crypto_ml_analysis(qlib_dir, "CRYPTO_BTC", **kwargs)
    second = run_crypto_ml_analysis(qlib_dir, "CRYPTO_BTC", **kwargs)
    assert calls["n"] == 1
    assert first.get("cache_hit") is None
    assert second.get("cache_hit") is True

    # Different end_date (new bar) busts the cache
    run_crypto_ml_analysis(qlib_dir, "CRYPTO_BTC", **{**kwargs, "end_date": "2026-01-02"})
    assert calls["n"] == 2

    # use_cache=False forces retrain
    run_crypto_ml_analysis(qlib_dir, "CRYPTO_BTC", **kwargs, use_cache=False)
    assert calls["n"] == 3


def test_run_crypto_ml_analysis_skip_not_cached(monkeypatch, tmp_path):
    qlib_dir = str(tmp_path / "CRYPTO_BTC" / "qlib")
    out = run_crypto_ml_analysis(
        qlib_dir,
        "CRYPTO_BTC",
        start_date="2024-01-01",
        end_date="2026-01-01",
        num_bars=10,
        algorithm="xgb",
        timeframe="1d",
    )
    assert out["skipped"] is True
    assert not (tmp_path / "CRYPTO_BTC" / "ml_cache").exists()
