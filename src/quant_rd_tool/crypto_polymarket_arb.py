"""Polymarket binary YES+NO arbitrage scanner with paper positions."""

from __future__ import annotations

from quant_rd_tool.time_util import now_iso, today_beijing_date

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

import httpx

logger = logging.getLogger(__name__)

POLYMARKET_DIR = Path("data/crypto/polymarket")
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
HTTP_TIMEOUT = 10.0
BOOK_FETCH_WORKERS = 10
GAMMA_CACHE_TTL_SEC = 60.0
REFERENCE_PROFIT_SHARES = 100.0

PositionStatus = Literal["open", "closed"]
HttpGet = Callable[[str, dict[str, Any] | None], Any]


@dataclass
class PolymarketArbConfig:
    top_n_volume: int = 50
    watchlist_condition_ids: list[str] = field(default_factory=list)
    min_edge_bps: float = 30.0
    taker_fee_bps: float = 200.0
    min_size_shares: float = 10.0
    min_liquidity_usd: float = 100.0
    builtin_scan_enabled: bool = False
    builtin_interval_sec: int = 300
    scan_dedupe_sec: int = 30
    default_paper_size_shares: float = 100.0
    alert_cooldown_sec: int = 900
    last_scan_at: str | None = None


def _iso_now() -> str:
    return now_iso()


def _ensure_dirs() -> None:
    POLYMARKET_DIR.mkdir(parents=True, exist_ok=True)
    (POLYMARKET_DIR / "scans").mkdir(exist_ok=True)
    (POLYMARKET_DIR / "positions").mkdir(exist_ok=True)


def load_config() -> PolymarketArbConfig:
    path = POLYMARKET_DIR / "config.json"
    if not path.is_file():
        return PolymarketArbConfig()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return PolymarketArbConfig(
        top_n_volume=int(raw.get("top_n_volume", 50)),
        watchlist_condition_ids=[str(x) for x in raw.get("watchlist_condition_ids") or []],
        min_edge_bps=float(raw.get("min_edge_bps", 30.0)),
        taker_fee_bps=float(raw.get("taker_fee_bps", 200.0)),
        min_size_shares=float(raw.get("min_size_shares", 10.0)),
        min_liquidity_usd=float(raw.get("min_liquidity_usd", 100.0)),
        builtin_scan_enabled=bool(raw.get("builtin_scan_enabled", False)),
        builtin_interval_sec=int(raw.get("builtin_interval_sec", 300)),
        scan_dedupe_sec=int(raw.get("scan_dedupe_sec", 30)),
        default_paper_size_shares=float(raw.get("default_paper_size_shares", 100.0)),
        alert_cooldown_sec=int(raw.get("alert_cooldown_sec", 900)),
        last_scan_at=raw.get("last_scan_at"),
    )


def save_config(cfg: PolymarketArbConfig) -> PolymarketArbConfig:
    _ensure_dirs()
    doc = asdict(cfg)
    doc["updated_at"] = _iso_now()
    (POLYMARKET_DIR / "config.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg


def _default_http_get(url: str, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        r = client.get(url, params=params or {})
        r.raise_for_status()
        return r.json()


_gamma_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _gamma_cache_key(limit: int, condition_ids: list[str] | None) -> str:
    ids = ",".join(sorted(str(x) for x in (condition_ids or []) if str(x).strip()))
    return f"{limit}|{ids}"


def clear_gamma_cache() -> None:
    _gamma_cache.clear()


def _parse_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def normalize_gamma_market(raw: dict[str, Any]) -> dict[str, Any] | None:
    condition_id = str(raw.get("conditionId") or raw.get("condition_id") or "").strip()
    if not condition_id:
        return None
    token_ids = _parse_json_list(raw.get("clobTokenIds") or raw.get("clob_token_ids"))
    outcomes = _parse_json_list(raw.get("outcomes"))
    if len(token_ids) < 2:
        return None
    yes_token = str(token_ids[0])
    no_token = str(token_ids[1])
    question = str(raw.get("question") or raw.get("title") or condition_id)
    vol = raw.get("volume24hr")
    if vol is None:
        vol = raw.get("volume24hrClob") or raw.get("volume") or 0
    try:
        volume24hr = float(vol or 0)
    except (TypeError, ValueError):
        volume24hr = 0.0
    slug = str(raw.get("slug") or "")
    return {
        "condition_id": condition_id,
        "question": question,
        "yes_token_id": yes_token,
        "no_token_id": no_token,
        "outcomes": [str(o) for o in outcomes] if outcomes else ["Yes", "No"],
        "volume24hr": volume24hr,
        "slug": slug,
        "market_url": f"https://polymarket.com/event/{slug}" if slug else None,
    }


def merge_market_universe(
    top_markets: list[dict[str, Any]],
    watchlist_markets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for m in top_markets + watchlist_markets:
        cid = str(m.get("condition_id") or "")
        if cid:
            merged[cid] = m
    return list(merged.values())


def compute_binary_edge(
    *,
    ask_yes: float,
    ask_no: float,
    ask_yes_size: float,
    ask_no_size: float,
    config: PolymarketArbConfig,
) -> dict[str, Any]:
    fee_yes = ask_yes * config.taker_fee_bps / 10_000.0
    fee_no = ask_no * config.taker_fee_bps / 10_000.0
    raw_edge = 1.0 - ask_yes - ask_no
    edge = raw_edge - fee_yes - fee_no
    size_cap = min(float(ask_yes_size), float(ask_no_size))
    edge_bps = edge * 10_000.0
    liquidity_usd = ask_yes * ask_yes_size + ask_no * ask_no_size
    profit_usd = edge * size_cap if edge > 0 else 0.0
    ref_shares = min(REFERENCE_PROFIT_SHARES, size_cap)
    cost_at_100_usd = ref_shares * (ask_yes + ask_no)
    profit_at_100_usd = edge * ref_shares if edge > 0 else 0.0
    roi_at_100_pct = (
        (profit_at_100_usd / cost_at_100_usd * 100.0) if cost_at_100_usd > 0 and edge > 0 else 0.0
    )
    opportunity = (
        edge_bps >= config.min_edge_bps
        and size_cap >= config.min_size_shares
        and liquidity_usd >= config.min_liquidity_usd
    )
    return {
        "ask_yes": round(ask_yes, 6),
        "ask_no": round(ask_no, 6),
        "ask_yes_size": round(ask_yes_size, 4),
        "ask_no_size": round(ask_no_size, 4),
        "raw_edge": round(raw_edge, 6),
        "fee_yes": round(fee_yes, 6),
        "fee_no": round(fee_no, 6),
        "edge": round(edge, 6),
        "edge_bps": round(edge_bps, 2),
        "size_cap": round(size_cap, 4),
        "liquidity_usd": round(liquidity_usd, 2),
        "profit_usd": round(profit_usd, 4),
        "ref_shares": round(ref_shares, 4),
        "cost_at_100_usd": round(cost_at_100_usd, 4),
        "profit_at_100_usd": round(profit_at_100_usd, 4),
        "roi_at_100_pct": round(roi_at_100_pct, 2),
        "opportunity": opportunity,
    }


def _best_ask(book: dict[str, Any]) -> tuple[float, float]:
    asks = book.get("asks") or []
    if not asks:
        return 0.0, 0.0
    row = asks[0]
    if isinstance(row, dict):
        return float(row.get("price") or 0), float(row.get("size") or 0)
    return float(row[0]), float(row[1])


def fetch_gamma_markets(
    *,
    limit: int = 50,
    condition_ids: list[str] | None = None,
    http_get: HttpGet | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    cache_key = _gamma_cache_key(limit, condition_ids)
    if use_cache:
        cached = _gamma_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < GAMMA_CACHE_TTL_SEC:
            return list(cached[1])

    getter = http_get or _default_http_get
    out: list[dict[str, Any]] = []
    if condition_ids:
        for cid in condition_ids:
            if not cid.strip():
                continue
            try:
                data = getter(f"{GAMMA_API}/markets", {"condition_ids": cid.strip()})
                rows = data if isinstance(data, list) else data.get("data") or data.get("markets") or []
                for raw in rows:
                    norm = normalize_gamma_market(raw if isinstance(raw, dict) else {})
                    if norm:
                        out.append(norm)
            except Exception as e:  # noqa: BLE001
                logger.warning("gamma watchlist fetch %s: %s", cid, e)
    if not condition_ids:
        try:
            data = getter(
                f"{GAMMA_API}/markets",
                {
                    "active": "true",
                    "closed": "false",
                    "limit": max(limit, 1),
                    "order": "volume24hr",
                },
            )
            rows = data if isinstance(data, list) else data.get("data") or data.get("markets") or []
            for raw in rows[:limit]:
                norm = normalize_gamma_market(raw if isinstance(raw, dict) else {})
                if norm:
                    out.append(norm)
        except Exception as e:  # noqa: BLE001
            logger.warning("gamma top markets fetch: %s", e)

    if use_cache:
        _gamma_cache[cache_key] = (time.time(), list(out))
    return out


def fetch_clob_book(token_id: str, *, http_get: HttpGet | None = None) -> dict[str, Any]:
    getter = http_get or _default_http_get
    return getter(f"{CLOB_API}/book", {"token_id": token_id})


def scan_market_row(
    market: dict[str, Any],
    config: PolymarketArbConfig,
    *,
    http_get: HttpGet | None = None,
) -> dict[str, Any]:
    getter = http_get or _default_http_get
    base = {**market}
    try:
        yes_book = fetch_clob_book(market["yes_token_id"], http_get=getter)
        no_book = fetch_clob_book(market["no_token_id"], http_get=getter)
        ask_yes, ask_yes_size = _best_ask(yes_book)
        ask_no, ask_no_size = _best_ask(no_book)
        if ask_yes <= 0 or ask_no <= 0:
            base["error"] = "incomplete_book"
            return base
        metrics = compute_binary_edge(
            ask_yes=ask_yes,
            ask_no=ask_no,
            ask_yes_size=ask_yes_size,
            ask_no_size=ask_no_size,
            config=config,
        )
        base.update(metrics)
        return base
    except Exception as e:  # noqa: BLE001
        base["error"] = str(e)
        return base


def scan_markets(
    config: PolymarketArbConfig | None = None,
    *,
    force: bool = False,
    http_get: HttpGet | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    if not force and cfg.last_scan_at and cfg.scan_dedupe_sec > 0:
        try:
            last = datetime.fromisoformat(cfg.last_scan_at.replace("Z", "+00:00"))
            age = (datetime.now(UTC) - last).total_seconds()
            if age < cfg.scan_dedupe_sec:
                cached = load_latest_scan()
                if cached:
                    return cached
        except ValueError:
            pass

    top = fetch_gamma_markets(limit=cfg.top_n_volume, http_get=http_get)
    watchlist = fetch_gamma_markets(
        condition_ids=cfg.watchlist_condition_ids,
        limit=len(cfg.watchlist_condition_ids) or 1,
        http_get=http_get,
    )
    universe = merge_market_universe(top, watchlist)
    items: list[dict[str, Any]] = []
    errors = 0
    books_fetched = 0
    t0 = time.perf_counter()

    def _scan_one(m: dict[str, Any]) -> dict[str, Any]:
        return scan_market_row(m, cfg, http_get=http_get)

    workers = min(BOOK_FETCH_WORKERS, max(len(universe), 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_scan_one, m): m for m in universe}
        for fut in as_completed(futures):
            row = fut.result()
            if row.get("error"):
                errors += 1
            else:
                books_fetched += 2
            items.append(row)

    duration_sec = round(time.perf_counter() - t0, 3)

    items.sort(key=lambda r: float(r.get("edge_bps") or -1e9), reverse=True)
    opportunities = [r for r in items if r.get("opportunity")]
    ts = _iso_now()
    payload = {
        "scanned_at": ts,
        "markets_scanned": len(items),
        "opportunities_count": len(opportunities),
        "best_edge_bps": float(opportunities[0]["edge_bps"]) if opportunities else None,
        "errors": errors,
        "books_fetched": books_fetched,
        "books_failed": errors * 2,
        "duration_sec": duration_sec,
        "items": items,
        "config": asdict(cfg),
    }
    save_scan_snapshot(payload)
    cfg.last_scan_at = ts
    save_config(cfg)
    for opp in opportunities:
        append_opportunity(opp)
    return payload


def save_scan_snapshot(payload: dict[str, Any]) -> Path:
    _ensure_dirs()
    safe_ts = payload.get("scanned_at", _iso_now()).replace(":", "-")
    path = POLYMARKET_DIR / "scans" / f"{safe_ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = POLYMARKET_DIR / "scans" / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_latest_scan() -> dict[str, Any] | None:
    path = POLYMARKET_DIR / "scans" / "latest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def empty_scan_result() -> dict[str, Any]:
    return {
        "scanned_at": None,
        "markets_scanned": 0,
        "opportunities_count": 0,
        "best_edge_bps": None,
        "errors": 0,
        "books_fetched": 0,
        "books_failed": 0,
        "duration_sec": None,
        "items": [],
    }


def append_opportunity(row: dict[str, Any]) -> None:
    _ensure_dirs()
    path = POLYMARKET_DIR / "opportunities.jsonl"
    doc = {"ts": _iso_now(), **{k: row.get(k) for k in row if k != "config"}}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")


def append_event(event: dict[str, Any]) -> None:
    _ensure_dirs()
    row = {"ts": _iso_now(), **event}
    path = POLYMARKET_DIR / "events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_events(*, limit: int = 100) -> list[dict[str, Any]]:
    path = POLYMARKET_DIR / "events.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        if line.strip():
            out.append(json.loads(line))
    return out


def list_positions(*, status: PositionStatus | None = None, limit: int = 50) -> list[dict[str, Any]]:
    _ensure_dirs()
    items: list[dict[str, Any]] = []
    for path in sorted((POLYMARKET_DIR / "positions").glob("*.json"), reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if status and doc.get("status") != status:
            continue
        items.append(doc)
        if len(items) >= limit:
            break
    return items


def _scan_row_by_condition(scan: dict[str, Any] | None, condition_id: str) -> dict[str, Any] | None:
    if not scan:
        return None
    for row in scan.get("items") or []:
        if str(row.get("condition_id") or "") == condition_id:
            return row
    return None


def build_position_live_status(
    position: dict[str, Any],
    scan_row: dict[str, Any] | None,
    config: PolymarketArbConfig | None = None,
) -> dict[str, Any] | None:
    if not scan_row or scan_row.get("error"):
        return None
    cfg = config or load_config()
    size = float(position.get("size_shares") or 0)
    cost = float(position.get("cost_usd") or 0)
    fee = float(position.get("fee_usd") or 0)
    entry_yes = float(position.get("entry_ask_yes") or 0)
    entry_no = float(position.get("entry_ask_no") or 0)
    entry_metrics = compute_binary_edge(
        ask_yes=entry_yes,
        ask_no=entry_no,
        ask_yes_size=size,
        ask_no_size=size,
        config=cfg,
    )
    current_yes = float(scan_row.get("ask_yes") or 0)
    current_no = float(scan_row.get("ask_no") or 0)
    payout = size * 1.0
    unrealized = payout - cost - fee
    return {
        "current_ask_yes": round(current_yes, 6),
        "current_ask_no": round(current_no, 6),
        "current_edge_bps": scan_row.get("edge_bps"),
        "entry_edge_bps": entry_metrics.get("edge_bps"),
        "edge_delta_bps": round(
            float(scan_row.get("edge_bps") or 0) - float(entry_metrics.get("edge_bps") or 0),
            2,
        ),
        "opportunity_active": bool(scan_row.get("opportunity")),
        "unrealized_pnl_usd": round(unrealized, 4),
    }


def list_positions_with_live(
    *,
    status: PositionStatus | None = None,
    limit: int = 50,
    scan: dict[str, Any] | None = None,
    config: PolymarketArbConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = config or load_config()
    latest = scan if scan is not None else load_latest_scan()
    items = list_positions(status=status, limit=limit)
    out: list[dict[str, Any]] = []
    for doc in items:
        row = doc.copy()
        if doc.get("status") == "open":
            scan_row = _scan_row_by_condition(latest, str(doc.get("condition_id") or ""))
            live = build_position_live_status(doc, scan_row, cfg)
            if live:
                row["live_status"] = live
        out.append(row)
    return out


def preview_paper_open_by_condition(
    condition_id: str,
    size_shares: float | None = None,
    config: PolymarketArbConfig | None = None,
    scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest = scan if scan is not None else load_latest_scan()
    row = _scan_row_by_condition(latest, condition_id)
    if not row:
        raise ValueError(f"market not found in latest scan: {condition_id}")
    if row.get("error"):
        raise ValueError(f"market scan error: {row.get('error')}")
    return preview_paper_open(row, size_shares, config)


def preview_close_paper_position(
    position_id: str,
    *,
    config: PolymarketArbConfig | None = None,
    scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = config
    path = POLYMARKET_DIR / "positions" / f"{position_id}.json"
    if not path.is_file():
        raise ValueError("position not found")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("status") != "open":
        raise ValueError("position not open")
    size = float(doc.get("size_shares") or 0)
    cost = float(doc.get("cost_usd") or 0)
    fee = float(doc.get("fee_usd") or 0)
    payout = size * 1.0
    net_pnl = payout - cost - fee
    latest = scan if scan is not None else load_latest_scan()
    scan_row = _scan_row_by_condition(latest, str(doc.get("condition_id") or ""))
    live = build_position_live_status(doc, scan_row, config)
    return {
        "position_id": position_id,
        "condition_id": doc.get("condition_id"),
        "question": doc.get("question"),
        "size_shares": size,
        "cost_usd": round(cost, 4),
        "fee_usd": round(fee, 4),
        "payout_usd": round(payout, 4),
        "net_pnl_usd": round(net_pnl, 4),
        "live_status": live,
    }


def list_scan_history(*, limit: int = 20) -> list[dict[str, Any]]:
    scans_dir = POLYMARKET_DIR / "scans"
    if not scans_dir.is_dir():
        return []
    paths = sorted(scans_dir.glob("*.json"), reverse=True)
    out: list[dict[str, Any]] = []
    for path in paths:
        if path.name == "latest.json":
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append(
            {
                "scanned_at": doc.get("scanned_at"),
                "markets_scanned": doc.get("markets_scanned", 0),
                "opportunities_count": doc.get("opportunities_count", 0),
                "best_edge_bps": doc.get("best_edge_bps"),
                "errors": doc.get("errors", 0),
                "duration_sec": doc.get("duration_sec"),
            }
        )
        if len(out) >= limit:
            break
    return out


def build_stats(config: PolymarketArbConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    summary = build_summary(cfg)
    today = today_beijing_date()
    scans_today = 0
    opp_today = 0
    edge_sum = 0.0
    edge_count = 0
    best_edge: float | None = None
    scans_dir = POLYMARKET_DIR / "scans"
    if scans_dir.is_dir():
        for path in scans_dir.glob("*.json"):
            if path.name == "latest.json":
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            scanned_at = str(doc.get("scanned_at") or "")
            if not scanned_at.startswith(today):
                continue
            scans_today += 1
            opp_today += int(doc.get("opportunities_count") or 0)
            be = doc.get("best_edge_bps")
            if be is not None:
                edge_sum += float(be)
                edge_count += 1
                if best_edge is None or float(be) > best_edge:
                    best_edge = float(be)
    latest = load_latest_scan()
    if latest and str(latest.get("scanned_at") or "").startswith(today):
        pass  # already counted from files
    hit_rate = round(opp_today / scans_today, 4) if scans_today else None
    return {
        **summary,
        "scans_today": scans_today,
        "opportunities_today": opp_today,
        "hit_rate_today": hit_rate,
        "avg_best_edge_bps_today": round(edge_sum / edge_count, 2) if edge_count else None,
        "best_edge_bps_today": best_edge,
        "last_duration_sec": latest.get("duration_sec") if latest else None,
    }


def _has_open_position(condition_id: str) -> bool:
    for p in list_positions(status="open", limit=200):
        if str(p.get("condition_id")) == condition_id:
            return True
    return False


def preview_paper_open(
    opportunity: dict[str, Any],
    size_shares: float | None,
    config: PolymarketArbConfig | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    size = float(size_shares or cfg.default_paper_size_shares)
    ask_yes = float(opportunity.get("ask_yes") or 0)
    ask_no = float(opportunity.get("ask_no") or 0)
    if ask_yes <= 0 or ask_no <= 0:
        raise ValueError("invalid opportunity prices")
    cost = size * (ask_yes + ask_no)
    fee = size * (ask_yes + ask_no) * cfg.taker_fee_bps / 10_000.0
    payout = size * 1.0
    gross_edge = payout - cost
    net_pnl = gross_edge - fee
    return {
        "condition_id": opportunity.get("condition_id"),
        "question": opportunity.get("question"),
        "size_shares": size,
        "ask_yes": ask_yes,
        "ask_no": ask_no,
        "cost_usd": round(cost, 4),
        "fee_usd": round(fee, 4),
        "payout_usd": round(payout, 4),
        "gross_edge_usd": round(gross_edge, 4),
        "net_pnl_usd": round(net_pnl, 4),
    }


def open_paper_position(
    opportunity: dict[str, Any],
    size_shares: float | None = None,
    config: PolymarketArbConfig | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    cid = str(opportunity.get("condition_id") or "")
    if not cid:
        raise ValueError("condition_id required")
    if _has_open_position(cid):
        raise ValueError(f"open position already exists for {cid}")
    preview = preview_paper_open(opportunity, size_shares, cfg)
    pos_id = str(uuid.uuid4())
    doc = {
        "id": pos_id,
        "status": "open",
        "condition_id": cid,
        "question": opportunity.get("question"),
        "size_shares": preview["size_shares"],
        "entry_ask_yes": preview["ask_yes"],
        "entry_ask_no": preview["ask_no"],
        "cost_usd": preview["cost_usd"],
        "fee_usd": preview["fee_usd"],
        "opened_at": _iso_now(),
        "closed_at": None,
        "realized_pnl_usd": None,
    }
    path = POLYMARKET_DIR / "positions" / f"{pos_id}.json"
    _ensure_dirs()
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event({"type": "position_opened", "position_id": pos_id, "condition_id": cid})
    return doc


def close_paper_position(
    position_id: str,
    *,
    config: PolymarketArbConfig | None = None,
    settlement_payout_usd: float | None = None,
) -> dict[str, Any]:
    _ = config
    path = POLYMARKET_DIR / "positions" / f"{position_id}.json"
    if not path.is_file():
        raise ValueError("position not found")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("status") != "open":
        raise ValueError("position not open")
    size = float(doc.get("size_shares") or 0)
    cost = float(doc.get("cost_usd") or 0)
    fee = float(doc.get("fee_usd") or 0)
    payout = float(settlement_payout_usd if settlement_payout_usd is not None else size * 1.0)
    pnl = payout - cost - fee
    doc.update(
        {
            "status": "closed",
            "closed_at": _iso_now(),
            "settlement_payout_usd": round(payout, 4),
            "realized_pnl_usd": round(pnl, 4),
        }
    )
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event({"type": "position_closed", "position_id": position_id, "pnl_usd": pnl})
    return doc


def build_summary(config: PolymarketArbConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    latest = load_latest_scan()
    open_pos = list_positions(status="open", limit=200)
    closed = list_positions(status="closed", limit=500)
    realized = sum(float(p.get("realized_pnl_usd") or 0) for p in closed)
    return {
        "last_scan_at": latest.get("scanned_at") if latest else cfg.last_scan_at,
        "markets_scanned": latest.get("markets_scanned") if latest else 0,
        "opportunities_count": latest.get("opportunities_count") if latest else 0,
        "best_edge_bps": latest.get("best_edge_bps") if latest else None,
        "open_positions": len(open_pos),
        "closed_positions": len(closed),
        "total_realized_pnl_usd": round(realized, 4),
        "builtin_scan_enabled": cfg.builtin_scan_enabled,
    }


_alert_last: dict[str, float] = {}


def evaluate_polymarket_alerts(scan: dict[str, Any], config: PolymarketArbConfig | None = None) -> list[dict[str, Any]]:
    cfg = config or load_config()
    fired: list[dict[str, Any]] = []
    now = time.time()
    for row in scan.get("items") or []:
        if not row.get("opportunity"):
            continue
        cid = str(row.get("condition_id") or "")
        last = _alert_last.get(cid, 0.0)
        if now - last < cfg.alert_cooldown_sec:
            continue
        _alert_last[cid] = now
        alert = {
            "type": "polymarket_arb",
            "condition_id": cid,
            "question": row.get("question"),
            "edge_bps": row.get("edge_bps"),
            "profit_usd": row.get("profit_usd"),
            "profit_at_100_usd": row.get("profit_at_100_usd"),
        }
        fired.append(alert)
        append_event({"type": "alert", **alert})
        try:
            from quant_rd_tool.bark_push import post_bark
            from quant_rd_tool.schedule_alerts import get_alert_rules

            rules = get_alert_rules()
            bark = rules.get("bark") or {}
            if bark.get("enabled") and bark.get("device_key"):
                post_bark(
                    str(bark["device_key"]),
                    title="Polymarket 套利",
                    body=(
                        f"{row.get('question')} edge {row.get('edge_bps')} bps "
                        f"@100份 +{row.get('profit_at_100_usd')} USDC"
                    ),
                    server=str(bark.get("server") or ""),
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("polymarket alert delivery skipped: %s", e)
    return fired
