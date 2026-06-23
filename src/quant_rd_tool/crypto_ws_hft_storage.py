"""Persistence for WebSocket crypto market-making bots."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

WS_HFT_DIR = Path("data/crypto/ws_hft")
CONFIG_PATH = WS_HFT_DIR / "config.json"
BOTS_INDEX_PATH = WS_HFT_DIR / "bots.json"

MarketType = Literal["spot", "future"]
TriggerMode = Literal["every_update", "throttle"]

_BOT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


@dataclass
class WsHftGlobalConfig:
    default_testnet: bool = True
    default_book_depth: int = 5
    default_price_tolerance_bps: float = 3.0
    default_throttle_ms: int = 20
    default_dry_run: bool = True
    max_daily_loss_usdt: float = 200.0


@dataclass
class WsHftBotConfig:
    bot_id: str
    symbol: str = "BTC"
    quote: str = "USDT"
    market_type: MarketType = "future"
    strategy_id: str = "classic_mm"
    strategy_params: dict[str, Any] = field(default_factory=dict)
    testnet: bool = True
    book_depth: int = 5
    price_tolerance_bps: float = 3.0
    post_only: bool = True
    max_order_size_usdt: float = 500.0
    max_open_orders: int = 20
    trigger_mode: TriggerMode = "throttle"
    throttle_ms: int = 20
    dry_run: bool = True
    maker_fee_bps: float = 2.0
    min_edge_bps: float = 1.0
    use_client_order_tags: bool = True
    batch_cancel: bool = True
    max_session_loss_usdt: float = 0.0
    max_inventory_usdt: float = 0.0


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def validate_bot_id(bot_id: str) -> str:
    bid = bot_id.strip()
    if not _BOT_ID_RE.match(bid):
        raise ValueError("invalid bot_id")
    return bid


def _ensure_dirs() -> None:
    WS_HFT_DIR.mkdir(parents=True, exist_ok=True)
    (WS_HFT_DIR / "state").mkdir(exist_ok=True)
    (WS_HFT_DIR / "events").mkdir(exist_ok=True)


def load_global_config() -> WsHftGlobalConfig:
    if not CONFIG_PATH.is_file():
        return WsHftGlobalConfig()
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return WsHftGlobalConfig(
        default_testnet=bool(raw.get("default_testnet", True)),
        default_book_depth=int(raw.get("default_book_depth", 5)),
        default_price_tolerance_bps=float(raw.get("default_price_tolerance_bps", 3.0)),
        default_throttle_ms=int(raw.get("default_throttle_ms", 20)),
        default_dry_run=bool(raw.get("default_dry_run", True)),
        max_daily_loss_usdt=float(raw.get("max_daily_loss_usdt", 200.0)),
    )


def save_global_config(cfg: WsHftGlobalConfig) -> dict[str, Any]:
    _ensure_dirs()
    doc = asdict(cfg)
    doc["updated_at"] = _iso_now()
    CONFIG_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def _load_bots_index() -> dict[str, Any]:
    if not BOTS_INDEX_PATH.is_file():
        return {"bots": []}
    return json.loads(BOTS_INDEX_PATH.read_text(encoding="utf-8"))


def _save_bots_index(data: dict[str, Any]) -> None:
    _ensure_dirs()
    data["updated_at"] = _iso_now()
    BOTS_INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_bot_ids() -> list[str]:
    return list(_load_bots_index().get("bots") or [])


def load_bot_config(bot_id: str) -> WsHftBotConfig:
    bid = validate_bot_id(bot_id)
    path = WS_HFT_DIR / "bots" / f"{bid}.json"
    if not path.is_file():
        raise ValueError(f"bot not found: {bid}; save bot config first")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return WsHftBotConfig(
        bot_id=bid,
        symbol=str(raw.get("symbol", "BTC")),
        quote=str(raw.get("quote", "USDT")),
        market_type=str(raw.get("market_type", "future")),  # type: ignore[arg-type]
        strategy_id=str(raw.get("strategy_id", "classic_mm")),
        strategy_params=dict(raw.get("strategy_params") or {}),
        testnet=bool(raw.get("testnet", True)),
        book_depth=int(raw.get("book_depth", 5)),
        price_tolerance_bps=float(raw.get("price_tolerance_bps", 3.0)),
        post_only=bool(raw.get("post_only", True)),
        max_order_size_usdt=float(raw.get("max_order_size_usdt", 500.0)),
        max_open_orders=int(raw.get("max_open_orders", 20)),
        trigger_mode=str(raw.get("trigger_mode", "throttle")),  # type: ignore[arg-type]
        throttle_ms=int(raw.get("throttle_ms", 20)),
        dry_run=bool(raw.get("dry_run", True)),
        maker_fee_bps=float(raw.get("maker_fee_bps", 2.0)),
        min_edge_bps=float(raw.get("min_edge_bps", 1.0)),
        use_client_order_tags=bool(raw.get("use_client_order_tags", True)),
        batch_cancel=bool(raw.get("batch_cancel", True)),
        max_session_loss_usdt=float(raw.get("max_session_loss_usdt", 0.0)),
        max_inventory_usdt=float(raw.get("max_inventory_usdt", 0.0)),
    )


def save_bot_config(cfg: WsHftBotConfig) -> dict[str, Any]:
    bid = validate_bot_id(cfg.bot_id)
    _ensure_dirs()
    (WS_HFT_DIR / "bots").mkdir(exist_ok=True)
    doc = asdict(cfg)
    doc["updated_at"] = _iso_now()
    (WS_HFT_DIR / "bots" / f"{bid}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    idx = _load_bots_index()
    bots: list[str] = list(idx.get("bots") or [])
    if bid not in bots:
        bots.append(bid)
    idx["bots"] = bots
    _save_bots_index(idx)
    return doc


def delete_bot_config(bot_id: str) -> bool:
    bid = validate_bot_id(bot_id)
    path = WS_HFT_DIR / "bots" / f"{bid}.json"
    if not path.is_file():
        return False
    path.unlink()
    idx = _load_bots_index()
    bots = [b for b in idx.get("bots") or [] if b != bid]
    idx["bots"] = bots
    _save_bots_index(idx)
    return True


def default_bot_state(bot_id: str) -> dict[str, Any]:
    return {
        "bot_id": bot_id,
        "status": "stopped",
        "inventory_base": 0.0,
        "inventory_usdt": 0.0,
        "last_mid": None,
        "last_reconcile_at": None,
        "last_error": None,
        "open_order_ids": [],
        "session_started_at": None,
        "book_updates_total": 0,
        "reconciles_total": 0,
        "throttled_skips": 0,
        "latency_us": {"last": None, "p50": None, "p95": None, "samples": []},
        "mid_history": [],
        "avg_entry_price": 0.0,
        "realized_pnl_usdt": 0.0,
        "pnl": {
            "realized_usdt": 0.0,
            "unrealized_usdt": 0.0,
            "total_usdt": 0.0,
            "session_usdt": 0.0,
            "daily_usdt": 0.0,
            "total_fees_usdt": 0.0,
            "fill_count": 0,
        },
        "risk": {
            "halted": False,
            "halt_reason": None,
            "allow_buy": True,
            "allow_sell": True,
        },
        "session_start_pnl_usdt": 0.0,
        "daily_date": None,
        "daily_start_pnl_usdt": 0.0,
        "last_fill_ts_ms": 0,
        "pnl_snapshots": [],
        "execution_stats": {
            "placed": 0,
            "canceled": 0,
            "rejected_cross": 0,
            "fee_adjusted": 0,
            "batch_cancel_used": 0,
            "reconnects": 0,
        },
    }


def load_bot_state(bot_id: str) -> dict[str, Any]:
    bid = validate_bot_id(bot_id)
    path = WS_HFT_DIR / "state" / f"{bid}.json"
    if not path.is_file():
        return default_bot_state(bid)
    return json.loads(path.read_text(encoding="utf-8"))


def save_bot_state(bot_id: str, state: dict[str, Any]) -> None:
    bid = validate_bot_id(bot_id)
    _ensure_dirs()
    state = {**state, "bot_id": bid, "updated_at": _iso_now()}
    (WS_HFT_DIR / "state" / f"{bid}.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def append_event(bot_id: str, event: dict[str, Any]) -> None:
    bid = validate_bot_id(bot_id)
    _ensure_dirs()
    row = {"ts": _iso_now(), **event}
    path = WS_HFT_DIR / "events" / f"{bid}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def tail_events(bot_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    bid = validate_bot_id(bot_id)
    path = WS_HFT_DIR / "events" / f"{bid}.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        if line.strip():
            out.append(json.loads(line))
    return out
