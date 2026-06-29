"""VaR enrichment for crypto schedule cycles and alert evaluation."""

from __future__ import annotations

from typing import Any

from quant_rd_tool.network_settings import load_settings
from quant_rd_tool.schedule_alerts import get_alert_rules

_SETTINGS_PATH = "data/settings.json"

_VAR_NUMERIC_FIELDS = frozenset(
    {
        "var_pct",
        "var_usdt",
        "cvar_pct",
        "cvar_usdt",
        "var_95_pct",
        "var_99_pct",
        "var_95_usdt",
        "var_99_usdt",
        "parametric_var_pct",
        "mc_gbm_var_pct",
        "mc_t_var_pct",
    }
)


def get_var_schedule_config(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or get_alert_rules()
    vc = raw.get("var") if isinstance(raw.get("var"), dict) else {}
    return {
        "enabled": vc.get("enabled", False) is not False,
        "on_symbol_var_breach": vc.get("on_symbol_var_breach", False) is not False,
        "on_portfolio_var_breach": vc.get("on_portfolio_var_breach", False) is not False,
        "on_rolling_var_breach": vc.get("on_rolling_var_breach", False) is not False,
        "max_var_pct": float(vc.get("max_var_pct", 0.05)),
        "max_portfolio_var_pct_of_equity": float(vc.get("max_portfolio_var_pct_of_equity", 0.10)),
        "confidence": float(vc.get("confidence", 0.99)),
        "notional_usdt": float(vc.get("notional_usdt", 10_000)),
        "lookback_bars": int(vc.get("lookback_bars", 252)),
        "horizon_days": int(vc.get("horizon_days", 1)),
        "horizon_bars": int(vc.get("horizon_bars", 1)),
        "timeframe": str(vc.get("timeframe", "1d")),
        "mc_n_sims": int(vc.get("mc_n_sims", 3000)),
        "mc_seed": int(vc.get("mc_seed", 42)),
    }


def _rule_uses_var_field(rule: dict[str, Any]) -> bool:
    for c in rule.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        field = str(c.get("field") or "").strip().lower()
        if field in _VAR_NUMERIC_FIELDS or field.startswith("var_"):
            return True
    return False


def var_cycle_needed(raw: dict[str, Any] | None = None) -> bool:
    raw = raw or get_alert_rules()
    cfg = get_var_schedule_config(raw)
    if cfg["enabled"]:
        return True
    if cfg["on_symbol_var_breach"] or cfg["on_portfolio_var_breach"] or cfg["on_rolling_var_breach"]:
        return True
    for rule in raw.get("custom_rules") or []:
        if isinstance(rule, dict) and rule.get("enabled", True) and _rule_uses_var_field(rule):
            return True
    return False


def build_var_cycle_fields(symbol: str, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute VaR metrics for one symbol (schedule cycle row enrichment)."""
    from quant_rd_tool.crypto_var import (
        build_symbol_var_breach,
        build_symbol_var_report,
        confidence_key,
        default_lookback_bars,
        normalize_var_timeframe,
    )

    cfg = config or get_var_schedule_config()
    conf_primary = float(cfg["confidence"])
    levels = sorted(set([0.95, 0.99, conf_primary]))
    tf = normalize_var_timeframe(str(cfg["timeframe"]))
    lb = default_lookback_bars(tf, int(cfg["lookback_bars"]))
    horizon_bars = int(cfg.get("horizon_bars") or 0) or None
    try:
        report = build_symbol_var_report(
            symbol,
            notional_usdt=cfg["notional_usdt"],
            lookback_bars=lb,
            horizon_days=cfg["horizon_days"],
            horizon_bars=horizon_bars,
            timeframe=tf,
            confidence_levels=levels,
            mc_n_sims=cfg["mc_n_sims"],
            mc_seed=cfg["mc_seed"],
        )
        metrics = report.get("metrics") or {}
        primary = metrics.get(confidence_key(conf_primary)) or metrics.get("0.99") or {}
        m95 = metrics.get("0.95") or {}
        mc = primary.get("monte_carlo") or {}
        gbm = mc.get("gbm") or {}
        st = mc.get("student_t") or {}

        breach_fields: dict[str, Any] = {}
        try:
            breach = build_symbol_var_breach(
                symbol,
                confidence=conf_primary,
                lookback_bars=lb,
                horizon_days=cfg["horizon_days"],
                horizon_bars=horizon_bars,
                timeframe=tf,
                notional_usdt=cfg["notional_usdt"],
            )
            breach_fields = {
                "var_breach": breach.get("breached"),
                "var_actual_return": breach.get("actual_return"),
                "var_exceedance_pct": breach.get("exceedance_pct"),
                "var_breach_severity": breach.get("severity"),
                "var_bar_time": breach.get("bar_time"),
            }
        except Exception as be:
            breach_fields = {"var_breach_error": str(be)}

        return {
            "var_enabled": True,
            "var_timeframe": tf,
            "var_horizon_bars": horizon_bars,
            "var_horizon_bars": horizon_bars,
            "var_pct": primary.get("var_pct"),
            "var_usdt": primary.get("var_usdt"),
            "cvar_pct": primary.get("cvar_pct"),
            "cvar_usdt": primary.get("cvar_usdt"),
            "var_95_pct": m95.get("var_pct"),
            "var_95_usdt": m95.get("var_usdt"),
            "var_99_pct": (metrics.get("0.99") or {}).get("var_pct"),
            "var_99_usdt": (metrics.get("0.99") or {}).get("var_usdt"),
            "parametric_var_pct": primary.get("parametric_var_pct"),
            "mc_gbm_var_pct": gbm.get("var_pct"),
            "mc_t_var_pct": st.get("var_pct"),
            "var_confidence": conf_primary,
            "var_notional_usdt": report.get("notional_usdt"),
            **breach_fields,
        }
    except Exception as e:
        return {"var_enabled": False, "var_error": str(e)}


def merge_var_into_summary_row(row: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    sym = row.get("symbol") or row.get("pair")
    if not sym or row.get("error"):
        return row
    fields = build_var_cycle_fields(str(sym), config=config)
    return {**row, **fields}
