from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OrderRef:
    client_order_id: str = ""
    exchange_order_id: str = ""
    order_type: str = ""
    side: str = ""
    amount: float | None = None
    stop_price: float | None = None
    status: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionSnapshot:
    side: str = "flat"
    amount: float = 0.0
    entry_price: float | None = None


@dataclass
class PerpSymbolState:
    symbol: str = ""
    last_seen_bar_end: str = ""
    last_target_side: str = ""

    position: PositionSnapshot = field(default_factory=PositionSnapshot)

    # Protection
    sl_order: OrderRef = field(default_factory=OrderRef)
    tp_order: OrderRef = field(default_factory=OrderRef)
    protection_fail_streak: int = 0

    # Soft SL/TP (poll last price when native protection unavailable)
    soft_protection_active: bool = False
    soft_sl_price: float | None = None
    soft_tp_price: float | None = None
    soft_position_side: str = ""

    # Circuit breaker daily snapshot
    daily_date: str = ""
    daily_start_usdt_total: float = 0.0

    @staticmethod
    def load(path: str | Path) -> "PerpSymbolState":
        p = Path(path)
        if not p.exists():
            return PerpSymbolState()
        raw = p.read_text(encoding="utf-8").strip()
        data = json.loads(raw or "{}")
        pos = data.get("position") or {}
        sl = data.get("sl_order") or {}
        tp = data.get("tp_order") or {}
        return PerpSymbolState(
            symbol=str(data.get("symbol") or ""),
            last_seen_bar_end=str(data.get("last_seen_bar_end") or ""),
            last_target_side=str(data.get("last_target_side") or ""),
            position=PositionSnapshot(
                side=str(pos.get("side") or "flat"),
                amount=float(pos.get("amount") or 0.0),
                entry_price=(float(pos["entry_price"]) if pos.get("entry_price") is not None else None),
            ),
            sl_order=OrderRef(
                client_order_id=str(sl.get("client_order_id") or ""),
                exchange_order_id=str(sl.get("exchange_order_id") or ""),
                order_type=str(sl.get("order_type") or ""),
                side=str(sl.get("side") or ""),
                amount=(float(sl["amount"]) if sl.get("amount") is not None else None),
                stop_price=(float(sl["stop_price"]) if sl.get("stop_price") is not None else None),
                status=str(sl.get("status") or ""),
                extra=dict(sl.get("extra") or {}),
            ),
            tp_order=OrderRef(
                client_order_id=str(tp.get("client_order_id") or ""),
                exchange_order_id=str(tp.get("exchange_order_id") or ""),
                order_type=str(tp.get("order_type") or ""),
                side=str(tp.get("side") or ""),
                amount=(float(tp["amount"]) if tp.get("amount") is not None else None),
                stop_price=(float(tp["stop_price"]) if tp.get("stop_price") is not None else None),
                status=str(tp.get("status") or ""),
                extra=dict(tp.get("extra") or {}),
            ),
            protection_fail_streak=int(data.get("protection_fail_streak") or 0),
            soft_protection_active=bool(data.get("soft_protection_active") or False),
            soft_sl_price=(
                float(data["soft_sl_price"]) if data.get("soft_sl_price") is not None else None
            ),
            soft_tp_price=(
                float(data["soft_tp_price"]) if data.get("soft_tp_price") is not None else None
            ),
            soft_position_side=str(data.get("soft_position_side") or ""),
            daily_date=str(data.get("daily_date") or ""),
            daily_start_usdt_total=float(data.get("daily_start_usdt_total") or 0.0),
        )

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

