"""Crypto market radar: Binance new listings, CoinGecko new coins, high volatility."""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from quant_rd_tool.time_util import now_iso

logger = logging.getLogger(__name__)

RADAR_DIR = Path("data/crypto/market_radar")
BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"
COINGECKO_API = "https://api.coingecko.com/api/v3"
HTTP_TIMEOUT = 15.0

HttpGet = Callable[[str, dict[str, Any] | None], Any]


@dataclass
class MarketRadarConfig:
    top_n_liquidity: int = 200
    vol_lookback_hours: int = 24
    vol_top_n_compute: int = 50
    min_24h_change_pct: float = 8.0
    min_realized_vol_pct: float = 5.0
    builtin_scan_enabled: bool = False
    builtin_interval_sec: int = 600
    scan_dedupe_sec: int = 60
    alert_cooldown_sec: int = 1800
    coingecko_per_page: int = 250
    last_scan_at: str | None = None


def _ensure_dirs() -> None:
    RADAR_DIR.mkdir(parents=True, exist_ok=True)
    (RADAR_DIR / "scans").mkdir(exist_ok=True)


def load_config() -> MarketRadarConfig:
    path = RADAR_DIR / "config.json"
    if not path.is_file():
        return MarketRadarConfig()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return MarketRadarConfig(
        top_n_liquidity=int(raw.get("top_n_liquidity", 200)),
        vol_lookback_hours=int(raw.get("vol_lookback_hours", 24)),
        vol_top_n_compute=int(raw.get("vol_top_n_compute", 50)),
        min_24h_change_pct=float(raw.get("min_24h_change_pct", 8.0)),
        min_realized_vol_pct=float(raw.get("min_realized_vol_pct", 5.0)),
        builtin_scan_enabled=bool(raw.get("builtin_scan_enabled", False)),
        builtin_interval_sec=int(raw.get("builtin_interval_sec", 600)),
        scan_dedupe_sec=int(raw.get("scan_dedupe_sec", 60)),
        alert_cooldown_sec=int(raw.get("alert_cooldown_sec", 1800)),
        coingecko_per_page=int(raw.get("coingecko_per_page", 250)),
        last_scan_at=raw.get("last_scan_at"),
    )


def save_config(cfg: MarketRadarConfig) -> MarketRadarConfig:
    _ensure_dirs()
    (RADAR_DIR / "config.json").write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cfg


def _default_http_get(url: str, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _spot_usdt_symbols(exchange_info: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for sym in exchange_info.get("symbols") or []:
        if sym.get("status") != "TRADING":
            continue
        if sym.get("quoteAsset") != "USDT":
            continue
        if sym.get("isSpotTradingAllowed") is False:
            continue
        out.add(str(sym.get("symbol")))
    return out


def _perp_usdt_symbols(exchange_info: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for sym in exchange_info.get("symbols") or []:
        if sym.get("status") != "TRADING":
            continue
        if sym.get("contractType") != "PERPETUAL":
            continue
        if sym.get("quoteAsset") != "USDT":
            continue
        out.add(str(sym.get("symbol")))
    return out


def diff_binance_listings(
    *,
    http_get: HttpGet = _default_http_get,
    snapshot_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Return newly seen Binance symbols and updated snapshot."""
    snap_path = snapshot_path or (RADAR_DIR / "binance_snapshot.json")
    prev = _load_json(snap_path, {"spot": [], "perp": [], "bootstrapped": False})

    spot_info = http_get(f"{BINANCE_SPOT}/api/v3/exchangeInfo")
    perp_info = http_get(f"{BINANCE_FUTURES}/fapi/v1/exchangeInfo")
    spot_now = sorted(_spot_usdt_symbols(spot_info))
    perp_now = sorted(_perp_usdt_symbols(perp_info))

    prev_spot = set(prev.get("spot") or [])
    prev_perp = set(prev.get("perp") or [])
    bootstrapped = bool(prev.get("bootstrapped"))

    new_items: list[dict[str, Any]] = []
    if bootstrapped:
        for symbol in sorted(set(spot_now) - prev_spot):
            base = symbol.replace("USDT", "")
            new_items.append(
                {
                    "source": "binance",
                    "market_type": "spot",
                    "symbol": symbol,
                    "base": base,
                    "quote": "USDT",
                    "trade_url": f"https://www.binance.com/en/trade/{base}_USDT",
                }
            )
        for symbol in sorted(set(perp_now) - prev_perp):
            base = symbol.replace("USDT", "")
            new_items.append(
                {
                    "source": "binance",
                    "market_type": "perp",
                    "symbol": symbol,
                    "base": base,
                    "quote": "USDT",
                    "trade_url": f"https://www.binance.com/en/futures/{symbol}",
                }
            )

    snapshot = {"spot": spot_now, "perp": perp_now, "bootstrapped": True, "updated_at": now_iso()}
    _save_json(snap_path, snapshot)
    return new_items, snapshot


def diff_coingecko_new_coins(
    *,
    http_get: HttpGet = _default_http_get,
    snapshot_path: Path | None = None,
    per_page: int = 250,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Detect newly indexed CoinGecko coin ids via list snapshot diff."""
    snap_path = snapshot_path or (RADAR_DIR / "coingecko_snapshot.json")
    prev = _load_json(snap_path, {"coin_ids": [], "bootstrapped": False})

    coin_list = http_get(f"{COINGECKO_API}/coins/list", {"include_platform": "false"})
    all_ids = sorted({str(c.get("id")) for c in coin_list if c.get("id")})
    prev_ids = set(prev.get("coin_ids") or [])
    bootstrapped = bool(prev.get("bootstrapped"))

    new_ids = sorted(set(all_ids) - prev_ids) if bootstrapped else []
    markets_by_id: dict[str, dict[str, Any]] = {}
    if new_ids:
        # Fetch market metadata for new ids (batch via markets endpoint pages)
        markets = http_get(
            f"{COINGECKO_API}/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": min(per_page, 250),
                "page": 1,
                "sparkline": "false",
            },
        )
        for row in markets:
            cid = str(row.get("id") or "")
            if cid:
                markets_by_id[cid] = row

    new_items: list[dict[str, Any]] = []
    for cid in new_ids[:100]:
        row = markets_by_id.get(cid, {})
        symbol = str(row.get("symbol") or cid).upper()
        new_items.append(
            {
                "source": "coingecko",
                "coin_id": cid,
                "symbol": symbol,
                "name": row.get("name") or cid,
                "market_cap_usd": row.get("market_cap"),
                "price_change_pct_24h": row.get("price_change_percentage_24h"),
                "detail_url": f"https://www.coingecko.com/en/coins/{cid}",
            }
        )

    snapshot = {"coin_ids": all_ids, "bootstrapped": True, "updated_at": now_iso()}
    _save_json(snap_path, snapshot)
    return new_items, snapshot


def _realized_vol_pct(closes: list[float]) -> float | None:
    if len(closes) < 3:
        return None
    rets: list[float] = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a <= 0 or b <= 0:
            continue
        rets.append(math.log(b / a))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    hourly_std = math.sqrt(var)
    # Scale to daily-ish vol proxy (24 x 1h bars)
    daily = hourly_std * math.sqrt(24)
    return round(daily * 100, 2)


def scan_high_volatility(
    cfg: MarketRadarConfig,
    *,
    http_get: HttpGet = _default_http_get,
) -> list[dict[str, Any]]:
    tickers = http_get(f"{BINANCE_SPOT}/api/v3/ticker/24hr")
    usdt = [
        t
        for t in tickers
        if str(t.get("symbol", "")).endswith("USDT")
        and not str(t.get("symbol", "")).endswith("UPUSDT")
        and not str(t.get("symbol", "")).endswith("DOWNUSDT")
    ]
    usdt.sort(key=lambda t: float(t.get("quoteVolume") or 0), reverse=True)
    universe = usdt[: max(cfg.top_n_liquidity, 1)]

    rows: list[dict[str, Any]] = []
    vol_candidates = universe[: max(cfg.vol_top_n_compute, 1)]
    vol_map: dict[str, float | None] = {}

    for t in vol_candidates:
        symbol = str(t.get("symbol"))
        try:
            klines = http_get(
                f"{BINANCE_SPOT}/api/v3/klines",
                {"symbol": symbol, "interval": "1h", "limit": max(cfg.vol_lookback_hours, 3)},
            )
            closes = [float(k[4]) for k in klines if len(k) > 4]
            vol_map[symbol] = _realized_vol_pct(closes)
        except Exception as e:  # noqa: BLE001
            logger.debug("klines failed for %s: %s", symbol, e)
            vol_map[symbol] = None

    for t in universe:
        symbol = str(t.get("symbol"))
        base = symbol.replace("USDT", "")
        change_pct = float(t.get("priceChangePercent") or 0)
        vol_pct = vol_map.get(symbol)
        rows.append(
            {
                "symbol": symbol,
                "base": base,
                "price": float(t.get("lastPrice") or 0),
                "quote_volume_usdt": float(t.get("quoteVolume") or 0),
                "change_pct_24h": round(change_pct, 2),
                "abs_change_pct_24h": round(abs(change_pct), 2),
                "realized_vol_pct": vol_pct,
                "high_vol": abs(change_pct) >= cfg.min_24h_change_pct
                or (vol_pct is not None and vol_pct >= cfg.min_realized_vol_pct),
                "trade_url": f"https://www.binance.com/en/trade/{base}_USDT",
            }
        )

    rows.sort(key=lambda r: r["abs_change_pct_24h"], reverse=True)
    return rows


def empty_scan_result() -> dict[str, Any]:
    return {
        "scan_id": None,
        "scanned_at": None,
        "binance_new": [],
        "coingecko_new": [],
        "high_volatility": [],
        "duration_sec": 0,
        "alerts": [],
    }


def load_latest_scan() -> dict[str, Any] | None:
    scans_dir = RADAR_DIR / "scans"
    if not scans_dir.is_dir():
        return None
    files = sorted(scans_dir.glob("*.json"), reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text(encoding="utf-8"))


def _append_event(event: dict[str, Any]) -> None:
    _ensure_dirs()
    path = RADAR_DIR / "events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(*, limit: int = 100) -> list[dict[str, Any]]:
    path = RADAR_DIR / "events.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    items = [json.loads(line) for line in lines if line.strip()]
    return list(reversed(items[-limit:]))


def _load_alert_state() -> dict[str, Any]:
    return _load_json(RADAR_DIR / "alert_state.json", {})


def _save_alert_state(state: dict[str, Any]) -> None:
    _save_json(RADAR_DIR / "alert_state.json", state)


def evaluate_market_radar_alerts(
    scan: dict[str, Any],
    cfg: MarketRadarConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = cfg or load_config()
    state = _load_alert_state()
    now_ts = time.time()
    alerts: list[dict[str, Any]] = []

    def _cooldown_ok(key: str) -> bool:
        last = float(state.get(key) or 0)
        return now_ts - last >= cfg.alert_cooldown_sec

    def _mark(key: str) -> None:
        state[key] = now_ts

    for item in scan.get("binance_new") or []:
        key = f"binance:{item.get('market_type')}:{item.get('symbol')}"
        if _cooldown_ok(key):
            alert = {
                "type": "binance_new_listing",
                "title": f"Binance 新上币 {item.get('symbol')}",
                "body": f"{item.get('market_type')} {item.get('base')}/{item.get('quote')}",
                "payload": item,
            }
            alerts.append(alert)
            _mark(key)
            _append_event({**alert, "at": now_iso()})

    for item in scan.get("coingecko_new") or []:
        key = f"coingecko:{item.get('coin_id')}"
        if _cooldown_ok(key):
            alert = {
                "type": "coingecko_new_coin",
                "title": f"CoinGecko 新币 {item.get('symbol')}",
                "body": str(item.get("name") or item.get("coin_id")),
                "payload": item,
            }
            alerts.append(alert)
            _mark(key)
            _append_event({**alert, "at": now_iso()})

    for item in scan.get("high_volatility") or []:
        if not item.get("high_vol"):
            continue
        sym = item.get("symbol")
        key = f"vol:{sym}"
        if not _cooldown_ok(key):
            continue
        alert = {
            "type": "high_volatility",
            "title": f"高波动 {sym}",
            "body": (
                f"24h {item.get('change_pct_24h')}% | "
                f"波动率 {item.get('realized_vol_pct')}%"
            ),
            "payload": item,
        }
        alerts.append(alert)
        _mark(key)
        _append_event({**alert, "at": now_iso()})

    _save_alert_state(state)

    if alerts:
        try:
            from quant_rd_tool.bark_push import post_bark
            from quant_rd_tool.schedule_alerts import get_alert_rules

            rules = get_alert_rules()
            bark = rules.get("bark") or {}
            if bark.get("enabled") and bark.get("device_key"):
                for alert in alerts[:5]:
                    post_bark(
                        str(bark["device_key"]),
                        title=str(alert.get("title") or "市场雷达"),
                        body=str(alert.get("body") or ""),
                        group="market-radar",
                        server=str(bark.get("server") or ""),
                    )
        except Exception as e:  # noqa: BLE001
            logger.debug("market radar bark skipped: %s", e)

    return alerts


def scan_markets(
    cfg: MarketRadarConfig | None = None,
    *,
    force: bool = False,
    http_get: HttpGet = _default_http_get,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    _ensure_dirs()

    if not force and cfg.last_scan_at:
        try:
            from datetime import datetime

            last = datetime.fromisoformat(cfg.last_scan_at.replace("Z", "+00:00"))
            elapsed = (datetime.now(last.tzinfo) - last).total_seconds()
            if elapsed < cfg.scan_dedupe_sec:
                latest = load_latest_scan()
                if latest:
                    return latest
        except Exception:  # noqa: BLE001
            pass

    started = time.time()
    binance_new, _ = diff_binance_listings(http_get=http_get)
    coingecko_new, _ = diff_coingecko_new_coins(
        http_get=http_get,
        per_page=cfg.coingecko_per_page,
    )
    high_vol = scan_high_volatility(cfg, http_get=http_get)
    high_vol_flagged = [r for r in high_vol if r.get("high_vol")]

    scan_id = str(uuid.uuid4())
    scanned_at = now_iso()
    result = {
        "scan_id": scan_id,
        "scanned_at": scanned_at,
        "binance_new": binance_new,
        "coingecko_new": coingecko_new,
        "high_volatility": high_vol,
        "high_volatility_flagged_count": len(high_vol_flagged),
        "binance_new_count": len(binance_new),
        "coingecko_new_count": len(coingecko_new),
        "duration_sec": round(time.time() - started, 2),
    }
    result["alerts"] = evaluate_market_radar_alerts(result, cfg)

    scan_path = RADAR_DIR / "scans" / f"{scanned_at.replace(':', '-')}.json"
    scan_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg.last_scan_at = scanned_at
    save_config(cfg)
    return result


def build_stats(cfg: MarketRadarConfig | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    latest = load_latest_scan() or empty_scan_result()
    return {
        "last_scan_at": cfg.last_scan_at or latest.get("scanned_at"),
        "binance_new_count": latest.get("binance_new_count", len(latest.get("binance_new") or [])),
        "coingecko_new_count": latest.get("coingecko_new_count", len(latest.get("coingecko_new") or [])),
        "high_volatility_flagged_count": latest.get(
            "high_volatility_flagged_count",
            len([r for r in (latest.get("high_volatility") or []) if r.get("high_vol")]),
        ),
        "builtin_scan_enabled": cfg.builtin_scan_enabled,
        "builtin_interval_sec": cfg.builtin_interval_sec,
    }
