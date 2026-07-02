"""Polymarket historical backtest, ROI distribution, and advisor calibration."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from quant_rd_tool.crypto_polymarket_arb import POLYMARKET_DIR, list_positions

_outcome_cache: dict[str, dict[str, Any]] = {}
_calibration_report_cache: dict[str, Any] | None = None
_calibration_report_key: tuple[float, float] | None = None


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_jsonl(path, *, hours: float | None = None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=hours) if hours is not None else None
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        if cutoff is not None:
            ts = _parse_ts(str(doc.get("ts") or ""))
            if ts is None or ts < cutoff:
                continue
        out.append(doc)
    return out


def load_opportunity_history(*, hours: float = 168.0) -> list[dict[str, Any]]:
    return _read_jsonl(POLYMARKET_DIR / "opportunities.jsonl", hours=hours)


def load_paper_outcomes(*, limit: int = 500) -> list[dict[str, Any]]:
    closed = list_positions(status="closed", limit=limit)
    for pos in closed:
        cost = float(pos.get("cost_usd") or 0) + float(pos.get("fee_usd") or 0)
        pnl = float(pos.get("realized_pnl_usd") or 0)
        pos["_roi_pct"] = round(pnl / cost * 100.0, 2) if cost > 0 else 0.0
        pos["_won"] = pnl > 0
    return closed


def _positions_dir_mtime() -> float:
    pos_dir = POLYMARKET_DIR / "positions"
    try:
        return pos_dir.stat().st_mtime if pos_dir.is_dir() else 0.0
    except OSError:
        return 0.0


def resolve_market_outcome(condition_id: str, *, http_get: Any = None) -> dict[str, Any]:
    """Fetch Gamma resolution status; cache per condition_id."""
    cid = str(condition_id or "").strip()
    if not cid:
        return {"condition_id": cid, "closed": False, "resolved": False, "error": "missing condition_id"}
    if cid in _outcome_cache:
        return _outcome_cache[cid]

    doc: dict[str, Any] = {
        "condition_id": cid,
        "closed": False,
        "resolved": False,
        "winning_outcome": None,
        "payout_per_share_yes": None,
        "payout_per_share_no": None,
    }
    try:
        getter = http_get
        if getter is None:
            from quant_rd_tool.crypto_polymarket_arb import GAMMA_API, _default_http_get

            getter = _default_http_get
        data = getter(f"{GAMMA_API}/markets", {"condition_ids": cid})
        gamma_rows = data if isinstance(data, list) else data.get("data") or data.get("markets") or []
        gamma = gamma_rows[0] if gamma_rows else {}
        if not gamma:
            doc["error"] = "market not found"
            _outcome_cache[cid] = doc
            return doc
        closed = bool(gamma.get("closed"))
        doc["closed"] = closed
        outcomes = gamma.get("outcomes")
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        prices = gamma.get("outcomePrices") or gamma.get("outcome_prices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        outcome_labels = [str(o) for o in outcomes] if outcomes else ["Yes", "No"]
        price_vals = [float(p) for p in prices] if prices else []
        if closed and len(price_vals) >= 2:
            doc["resolved"] = True
            winner_idx = max(range(len(price_vals)), key=lambda i: price_vals[i])
            doc["winning_outcome"] = outcome_labels[winner_idx] if winner_idx < len(outcome_labels) else None
            doc["payout_per_share_yes"] = round(price_vals[0], 4) if len(price_vals) > 0 else None
            doc["payout_per_share_no"] = round(price_vals[1], 4) if len(price_vals) > 1 else None
    except Exception as e:  # noqa: BLE001
        doc["error"] = str(e)

    _outcome_cache[cid] = doc
    return doc


def settlement_payout_for_position(
    position: dict[str, Any],
    *,
    http_get: Any = None,
) -> float | None:
    """Binary-ask paper holds YES+NO; resolved payout is size * (pay_yes + pay_no)."""
    cid = str(position.get("condition_id") or "")
    size = float(position.get("size_shares") or 0)
    if not cid or size <= 0:
        return None
    outcome = resolve_market_outcome(cid, http_get=http_get)
    if outcome.get("resolved"):
        pay_yes = float(outcome.get("payout_per_share_yes") or 0)
        pay_no = float(outcome.get("payout_per_share_no") or 0)
        return round(size * (pay_yes + pay_no), 4)
    # Unresolved arb: both legs settle to $1 total per share pair at resolution
    st = str(position.get("strategy_type") or "binary_ask")
    if st == "binary_ask":
        return round(size * 1.0, 4)
    return None


def build_strategy_backtest(*, hours: float = 168.0) -> dict[str, Any]:
    rows = [r for r in load_opportunity_history(hours=hours) if r.get("opportunity")]
    by_st: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        st = str(row.get("strategy_type") or "binary_ask")
        by_st[st].append(row)

    strategies: list[dict[str, Any]] = []
    for st, items in sorted(by_st.items()):
        edges = [float(x.get("edge_at_size_bps") or x.get("edge_bps") or 0) for x in items]
        profits = [float(x.get("profit_at_size_usd") or 0) for x in items]
        fillable = [float(x.get("fillable_shares") or 0) for x in items]
        target = float(items[0].get("depth_target_shares") or 100) if items else 100.0
        fill_rate = sum(1 for f in fillable if f >= target * 0.5) / len(fillable) if fillable else 0.0
        strategies.append(
            {
                "strategy_type": st,
                "hit_count": len(items),
                "avg_edge_bps": round(sum(edges) / len(edges), 2) if edges else None,
                "avg_edge_at_size_bps": round(
                    sum(float(x.get("edge_at_size_bps") or x.get("edge_bps") or 0) for x in items)
                    / len(items),
                    2,
                )
                if items
                else None,
                "avg_profit_at_size_usd": round(sum(profits) / len(profits), 4) if profits else None,
                "fill_rate": round(fill_rate, 4),
                "unique_markets": len({x.get("condition_id") for x in items}),
            }
        )

    closed = load_paper_outcomes()
    total_pnl = sum(float(p.get("realized_pnl_usd") or 0) for p in closed)
    wins = sum(1 for p in closed if p.get("_won"))

    return {
        "hours": hours,
        "opportunity_hits": len(rows),
        "strategies": strategies,
        "summary": {
            "closed_positions": len(closed),
            "paper_win_rate": round(wins / len(closed), 4) if closed else None,
            "total_realized_pnl_usd": round(total_pnl, 4),
        },
    }


def build_strategy_compare(*, hours: float = 168.0) -> dict[str, Any]:
    bt = build_strategy_backtest(hours=hours)
    return {
        "hours": hours,
        "items": bt["strategies"],
        "summary": bt["summary"],
    }


def _bucket_edge_bps(value: float) -> str:
    if value < 20:
        return "0-20"
    if value < 50:
        return "20-50"
    if value < 100:
        return "50-100"
    return "100+"


def _bucket_roi_pct(value: float) -> str:
    if value < 0:
        return "<0%"
    if value < 2:
        return "0-2%"
    if value < 5:
        return "2-5%"
    return "5%+"


def build_roi_distribution(
    *,
    hours: float = 168.0,
    strategy_type: str | None = None,
) -> dict[str, Any]:
    rows = load_opportunity_history(hours=hours)
    if strategy_type:
        rows = [r for r in rows if str(r.get("strategy_type") or "binary_ask") == strategy_type]

    edge_buckets: dict[str, int] = defaultdict(int)
    for row in rows:
        if not row.get("opportunity"):
            continue
        edge = float(row.get("edge_at_size_bps") or row.get("edge_bps") or 0)
        edge_buckets[_bucket_edge_bps(edge)] += 1

    pnl_buckets: dict[str, int] = defaultdict(int)
    closed = load_paper_outcomes()
    for pos in closed:
        pnl_buckets[_bucket_roi_pct(float(pos.get("_roi_pct") or 0))] += 1

    return {
        "hours": hours,
        "strategy_type": strategy_type,
        "edge_buckets": [{"bucket": k, "count": v} for k, v in sorted(edge_buckets.items())],
        "paper_pnl_buckets": [{"bucket": k, "count": v} for k, v in sorted(pnl_buckets.items())],
        "n_opportunities": sum(edge_buckets.values()),
        "n_closed_positions": len(closed),
    }


def build_advisor_calibration(*, hours: float = 720.0) -> dict[str, Any]:
    from quant_rd_tool.crypto_polymarket_advisor import AdvisorConfig, score_opportunity
    from quant_rd_tool.crypto_polymarket_arb import load_config

    cfg = load_config()
    adv = AdvisorConfig(history_hours=hours)
    closed = load_paper_outcomes()

    tier_stats: dict[str, dict[str, Any]] = {
        level: {"level": level, "predicted_wr": pred, "wins": 0, "n": 0}
        for level, pred in (
            ("strong_buy", adv.strong_buy_win_rate),
            ("buy", adv.buy_win_rate),
            ("watch", adv.watch_win_rate),
            ("pass", 0.25),
        )
    }

    for pos in closed:
        st = str(pos.get("strategy_type") or "binary_ask")
        row = {
            "condition_id": pos.get("condition_id"),
            "question": pos.get("question"),
            "strategy_type": st,
            "opportunity": True,
            "paper_tradable": st == "binary_ask",
            "ask_yes": pos.get("entry_ask_yes"),
            "ask_no": pos.get("entry_ask_no"),
            "vwap_yes": pos.get("entry_ask_yes"),
            "vwap_no": pos.get("entry_ask_no"),
            "fillable_shares": pos.get("size_shares"),
            "size_cap": pos.get("size_shares"),
            "edge_at_size_bps": pos.get("entry_edge_at_size_bps"),
            "edge_bps": pos.get("entry_edge_bps"),
            "profit_at_size_usd": pos.get("entry_profit_at_size_usd"),
        }
        scored = score_opportunity(row, config=cfg, advisor=adv, skip_calibration=True)
        level = str(scored.get("recommendation") or "pass")
        if level not in tier_stats:
            level = "pass"
        tier_stats[level]["n"] += 1
        if pos.get("_won"):
            tier_stats[level]["wins"] += 1

    tiers: list[dict[str, Any]] = []
    for level in ("strong_buy", "buy", "watch", "pass"):
        stat = tier_stats[level]
        n = int(stat["n"])
        actual = round(stat["wins"] / n, 4) if n else None
        tiers.append(
            {
                "level": level,
                "level_label": {
                    "strong_buy": "强烈推荐",
                    "buy": "建议参与",
                    "watch": "观望等待",
                    "pass": "暂不推荐",
                }.get(level, level),
                "predicted_wr": stat["predicted_wr"],
                "actual_wr": actual,
                "n": n,
            }
        )

    return {"hours": hours, "tiers": tiers, "sample_closed": len(closed)}


def get_advisor_calibration_report(*, hours: float = 720.0) -> dict[str, Any]:
    global _calibration_report_cache, _calibration_report_key
    key = (hours, _positions_dir_mtime())
    if _calibration_report_cache is None or _calibration_report_key != key:
        _calibration_report_cache = build_advisor_calibration(hours=hours)
        _calibration_report_key = key
    return _calibration_report_cache


def invalidate_calibration_cache() -> None:
    global _calibration_report_cache, _calibration_report_key
    _calibration_report_cache = None
    _calibration_report_key = None


def lookup_calibration_prior(report: dict[str, Any], recommendation: str) -> float | None:
    for tier in report.get("tiers") or []:
        if tier.get("level") != recommendation:
            continue
        n = int(tier.get("n") or 0)
        if n < 5:
            return None
        return float(tier["actual_wr"]) if tier.get("actual_wr") is not None else None
    return None


def calibration_prior(strategy_type: str, recommendation: str, *, hours: float = 720.0) -> float | None:
    """Return calibrated win rate for tier when sample n >= 5."""
    _ = strategy_type
    return lookup_calibration_prior(get_advisor_calibration_report(hours=hours), recommendation)
