from __future__ import annotations

import json
from pathlib import Path

from quant_rd_tool.crypto_polymarket_arb import (
    PolymarketArbConfig,
    build_position_live_status,
    build_stats,
    clear_gamma_cache,
    compute_binary_edge,
    fetch_gamma_markets,
    list_scan_history,
    merge_market_universe,
    normalize_gamma_market,
    open_paper_position,
    close_paper_position,
    preview_close_paper_position,
    preview_paper_open,
    preview_paper_open_by_condition,
    scan_market_row,
    save_scan_snapshot,
)


def test_compute_binary_edge_positive():
    cfg = PolymarketArbConfig(taker_fee_bps=200, min_liquidity_usd=50.0)
    r = compute_binary_edge(
        ask_yes=0.45,
        ask_no=0.50,
        ask_yes_size=100,
        ask_no_size=80,
        config=cfg,
    )
    assert r["edge_bps"] > 0
    assert r["size_cap"] == 80
    assert r["ref_shares"] == 80
    assert r["profit_at_100_usd"] > 0
    assert r["profit_at_100_usd"] == round(r["edge"] * 80, 4)
    assert r["opportunity"]


def test_compute_binary_edge_ref_100_full_size():
    cfg = PolymarketArbConfig(taker_fee_bps=200, min_liquidity_usd=50.0)
    r = compute_binary_edge(
        ask_yes=0.45,
        ask_no=0.50,
        ask_yes_size=200,
        ask_no_size=200,
        config=cfg,
    )
    assert r["ref_shares"] == 100
    assert r["profit_at_100_usd"] == round(r["edge"] * 100, 4)


def test_normalize_gamma_market():
    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_gamma_markets.json").read_text()
    )
    norm = normalize_gamma_market(raw)
    assert norm is not None
    assert norm["condition_id"] == "0xabc123"
    assert norm["yes_token_id"] == "yes-token-1"


def test_merge_market_universe_dedupes():
    a = [{"condition_id": "1", "question": "A"}]
    b = [{"condition_id": "1", "question": "A2"}, {"condition_id": "2", "question": "B"}]
    merged = merge_market_universe(a, b)
    assert len(merged) == 2
    assert {m["condition_id"] for m in merged} == {"1", "2"}


def test_scan_market_row_from_fixtures(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    yes_book = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_clob_book_yes.json").read_text()
    )
    no_book = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_clob_book_no.json").read_text()
    )

    def fake_get(url: str, params: dict | None = None):
        token = (params or {}).get("token_id")
        if token == "yes-token-1":
            return yes_book
        if token == "no-token-2":
            return no_book
        raise ValueError(token)

    market = normalize_gamma_market(
        json.loads((Path(__file__).parent / "fixtures" / "polymarket_gamma_markets.json").read_text())
    )
    row = scan_market_row(market, PolymarketArbConfig(), http_get=fake_get)
    assert row.get("edge_bps") is not None
    assert row.get("error") is None


def test_scan_markets_persists(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    gamma = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_gamma_markets.json").read_text()
    )
    yes_book = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_clob_book_yes.json").read_text()
    )
    no_book = json.loads(
        (Path(__file__).parent / "fixtures" / "polymarket_clob_book_no.json").read_text()
    )

    def fake_get(url: str, params: dict | None = None):
        if "gamma-api" in url:
            return [gamma]
        token = (params or {}).get("token_id")
        if token == "yes-token-1":
            return yes_book
        if token == "no-token-2":
            return no_book
        return {"asks": []}

    cfg = PolymarketArbConfig(scan_dedupe_sec=0)
    result = pa.scan_markets(cfg, force=True, http_get=fake_get)
    assert result["markets_scanned"] == 1
    assert (tmp_path / "scans" / "latest.json").is_file()


def test_paper_open_close(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    opp = {
        "condition_id": "0xabc123",
        "question": "Test?",
        "ask_yes": 0.45,
        "ask_no": 0.50,
    }
    preview = preview_paper_open(opp, 10)
    assert preview["net_pnl_usd"] > 0
    pos = open_paper_position(opp, 10)
    closed = close_paper_position(pos["id"])
    assert closed["status"] == "closed"
    assert closed["realized_pnl_usd"] is not None


def test_build_position_live_status(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    pos = {
        "size_shares": 10,
        "cost_usd": 9.5,
        "fee_usd": 0.2,
        "entry_ask_yes": 0.45,
        "entry_ask_no": 0.50,
    }
    scan_row = {"ask_yes": 0.46, "ask_no": 0.51, "edge_bps": 20, "opportunity": False}
    live = build_position_live_status(pos, scan_row, PolymarketArbConfig())
    assert live is not None
    assert live["unrealized_pnl_usd"] > 0
    assert live["current_edge_bps"] == 20


def test_preview_by_condition(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    scan = {
        "items": [
            {"condition_id": "c1", "ask_yes": 0.4, "ask_no": 0.5, "question": "Q?"},
        ]
    }
    save_scan_snapshot({**scan, "scanned_at": "2026-06-23T12:00:00+00:00", "markets_scanned": 1})
    preview = preview_paper_open_by_condition("c1", 10, scan=scan)
    assert preview["net_pnl_usd"] > 0


def test_preview_close_paper(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    opp = {"condition_id": "c1", "question": "Q?", "ask_yes": 0.45, "ask_no": 0.50}
    pos = open_paper_position(opp, 10)
    close_prev = preview_close_paper_position(pos["id"])
    assert close_prev["net_pnl_usd"] is not None


def test_gamma_cache(monkeypatch):
    calls = {"n": 0}

    def fake_get(url: str, params: dict | None = None):
        calls["n"] += 1
        return []

    clear_gamma_cache()
    fetch_gamma_markets(limit=5, http_get=fake_get, use_cache=True)
    fetch_gamma_markets(limit=5, http_get=fake_get, use_cache=True)
    assert calls["n"] == 1


def test_list_scan_history(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    (tmp_path / "scans").mkdir(parents=True)
    doc = {
        "scanned_at": "2026-06-23T10:00:00+00:00",
        "markets_scanned": 5,
        "opportunities_count": 2,
        "best_edge_bps": 40,
        "duration_sec": 1.2,
    }
    (tmp_path / "scans" / "2026-06-23T10-00-00.json").write_text(
        __import__("json").dumps(doc), encoding="utf-8"
    )
    hist = list_scan_history(limit=5)
    assert len(hist) == 1
    assert hist[0]["opportunities_count"] == 2


def test_build_stats(monkeypatch, tmp_path):
    from quant_rd_tool import crypto_polymarket_arb as pa

    monkeypatch.setattr(pa, "POLYMARKET_DIR", tmp_path)
    today = __import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).date().isoformat()
    (tmp_path / "scans").mkdir(parents=True)
    doc = {
        "scanned_at": f"{today}T10:00:00+00:00",
        "markets_scanned": 3,
        "opportunities_count": 1,
        "best_edge_bps": 35,
    }
    (tmp_path / "scans" / "scan1.json").write_text(__import__("json").dumps(doc), encoding="utf-8")
    (tmp_path / "scans" / "latest.json").write_text(__import__("json").dumps(doc), encoding="utf-8")
    stats = build_stats()
    assert stats["scans_today"] >= 1
