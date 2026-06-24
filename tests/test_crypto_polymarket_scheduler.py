from __future__ import annotations

from quant_rd_tool.crypto_polymarket_scheduler import run_polymarket_scan_cycle, summarize_polymarket_cycle


def test_summarize_polymarket_cycle():
    result = {
        "scan": {
            "markets_scanned": 10,
            "opportunities_count": 2,
            "best_edge_bps": 45.0,
            "errors": 1,
        },
        "alerts_fired": 1,
    }
    s = summarize_polymarket_cycle(result)
    assert s["markets_scanned"] == 10
    assert s["opportunities_count"] == 2
    assert s["alerts_fired"] == 1


def test_run_polymarket_scan_cycle(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa
    from quant_rd_tool import crypto_polymarket_scheduler as ps

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    monkeypatch.setattr(
        ps,
        "scan_markets",
        lambda cfg, force=False, http_get=None: {
            "markets_scanned": 3,
            "opportunities_count": 1,
            "best_edge_bps": 12.0,
            "items": [{"opportunity": True, "condition_id": "x", "edge_bps": 12}],
        },
    )
    monkeypatch.setattr(ps, "evaluate_polymarket_alerts", lambda scan, config=None: [])
    out = run_polymarket_scan_cycle(force=True)
    assert out["markets_scanned"] == 3
