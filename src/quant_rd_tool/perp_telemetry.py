"""Structured JSONL telemetry for perp bot cycles."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

PerpDecision = Literal[
    "skipped_dedup",
    "blocked_circuit_breaker",
    "opened",
    "flipped",
    "closed",
    "no_op",
    "error",
]

ErrorCategory = Literal["transient", "exchange_reject", "config", "unknown"]

Notifier = Callable[[dict[str, Any]], None]


def noop_notifier(_: dict[str, Any]) -> None:
    return None


def daily_log_path(log_dir: str | Path, *, day: date | None = None) -> Path:
    d = day or date.today()
    return Path(log_dir) / f"{d.strftime('%Y%m%d')}.jsonl"


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def classify_error_category(exc: BaseException | None) -> ErrorCategory | None:
    if exc is None:
        return None
    try:
        import ccxt  # type: ignore[import-untyped]
    except ImportError:
        ccxt = None  # type: ignore[assignment]

    if isinstance(exc, ValueError):
        return "config"
    if ccxt is not None:
        if isinstance(exc, ccxt.AuthenticationError):
            return "config"
        if isinstance(exc, (ccxt.NetworkError, ccxt.RequestTimeout)):
            return "transient"
        if isinstance(exc, ccxt.ExchangeError):
            return "exchange_reject"
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name:
        return "transient"
    return "unknown"


def classify_decision(result: dict[str, Any], *, explicit: str | None = None) -> PerpDecision:
    if explicit:
        return explicit  # type: ignore[return-value]
    if result.get("decision"):
        return result["decision"]  # type: ignore[return-value]

    msg = str(result.get("message") or "")
    if "bar_end 去重" in msg or result.get("skipped_dedup"):
        return "skipped_dedup"

    cb = result.get("circuit_breaker") or {}
    perp_action = result.get("perp_action")
    if cb.get("blocked") and perp_action in ("long", "short") and not result.get("open_order"):
        if not result.get("close_order"):
            return "blocked_circuit_breaker"

    sp = result.get("soft_protection") or {}
    if sp.get("triggered"):
        return "closed"

    close_o = _effective_order(result.get("close_order"))
    open_o = _effective_order(result.get("open_order"))
    if result.get("dry_run") and not close_o and not open_o:
        return "no_op"
    if close_o and open_o:
        return "flipped"
    if open_o:
        return "opened"
    if close_o:
        return "closed"
    return "no_op"


def _effective_order(order: Any) -> dict[str, Any] | None:
    if not order or not isinstance(order, dict):
        return order if order else None
    if order.get("side") == "hold" or order.get("status") == "skipped":
        return None
    if order.get("status") == "planned":
        return None
    return order


def build_cycle_record(
    *,
    result: dict[str, Any],
    base: str,
    decision: PerpDecision | None = None,
    error: BaseException | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    dec = decision or classify_decision(result)
    signal = result.get("signal") if isinstance(result.get("signal"), dict) else {}
    pos = result.get("position_before") if isinstance(result.get("position_before"), dict) else {}
    err_cat = classify_error_category(error)

    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "cycle",
        "symbol": result.get("pair") or "",
        "base": base.upper(),
        "decision": dec,
        "error_category": err_cat,
        "error_message": (str(error)[:500] if error else None),
        "dry_run": bool(result.get("dry_run")),
        "testnet": bool(result.get("testnet")),
        "bar_end": result.get("bar_end") or "",
        "perp_action": result.get("perp_action"),
        "target_side": result.get("target_side"),
        "message": result.get("message"),
        "circuit_breaker": result.get("circuit_breaker"),
        "soft_protection": result.get("soft_protection"),
        "position_side_before": pos.get("side"),
        "position_amount_before": pos.get("amount"),
        "had_close_order": bool(result.get("close_order")),
        "had_open_order": bool(result.get("open_order")),
        "signal_action": signal.get("action"),
        "signal_score": signal.get("score"),
        "signal_confidence": signal.get("confidence"),
    }
    sizing = result.get("sizing")
    if isinstance(sizing, dict):
        record["sizing_mode"] = sizing.get("mode")
        record["notional_usdt"] = sizing.get("notional_usdt")
        record["atr_notional_usdt"] = sizing.get("atr_notional_usdt")
        record["leverage_cap_usdt"] = sizing.get("leverage_cap_usdt")
        record["atr"] = sizing.get("atr")
    if duration_ms is not None:
        record["duration_ms"] = round(float(duration_ms), 2)
    bal = result.get("balance_before")
    if isinstance(bal, dict):
        record["usdt_free"] = bal.get("USDT_free")
        record["usdt_total"] = bal.get("USDT_total")
    return record


def build_portfolio_record(summary: dict[str, Any]) -> dict[str, Any]:
    results = summary.get("results") or []
    decisions: list[dict[str, str]] = []
    for row in results:
        sym = str(row.get("symbol") or "")
        inner = row.get("result") if isinstance(row.get("result"), dict) else {}
        decisions.append(
            {
                "symbol": sym,
                "decision": classify_decision(inner) if inner else "no_op",
            }
        )
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "portfolio",
        "count": summary.get("count"),
        "allocation": summary.get("allocation"),
        "decisions": decisions,
    }


@dataclass
class TelemetryConfig:
    enabled: bool = True
    log_dir: str = "data/crypto/perp_logs"
    notifier: Notifier = field(default=noop_notifier)


class PerpTelemetry:
    def __init__(self, config: TelemetryConfig | None = None) -> None:
        self.config = config or TelemetryConfig()

    def log_path(self, *, day: date | None = None) -> Path:
        return daily_log_path(self.config.log_dir, day=day)

    def emit(self, record: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        append_jsonl(self.log_path(), record)
        try:
            self.config.notifier(record)
        except Exception:
            pass

    def log_cycle(
        self,
        *,
        result: dict[str, Any],
        base: str,
        decision: PerpDecision | None = None,
        error: BaseException | None = None,
        duration_ms: float | None = None,
    ) -> dict[str, Any]:
        record = build_cycle_record(
            result=result,
            base=base,
            decision=decision,
            error=error,
            duration_ms=duration_ms,
        )
        result["decision"] = record["decision"]
        if record.get("error_category"):
            result["error_category"] = record["error_category"]
        self.emit(record)
        return record

    def log_portfolio(self, summary: dict[str, Any]) -> dict[str, Any]:
        record = build_portfolio_record(summary)
        self.emit(record)
        return record
