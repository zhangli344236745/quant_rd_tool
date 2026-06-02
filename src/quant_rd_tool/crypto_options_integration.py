"""Combine spot/ML crypto analysis with Binance options IV context."""

from __future__ import annotations

import logging
from typing import Any

from quant_rd_tool.crypto_options_advisor import advise_item
from quant_rd_tool.crypto_options_data import fetch_atm_iv_snapshot
from quant_rd_tool.crypto_options_vol_scan import get_or_run_volatility_scan

logger = logging.getLogger(__name__)


def base_asset(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s.startswith("CRYPTO_"):
        return s.replace("CRYPTO_", "", 1)
    if "/" in s:
        return s.split("/")[0]
    if s.endswith("USDT"):
        return s[: -len("USDT")]
    return s


def fetch_options_context(
    symbol: str,
    *,
    data_dir: str = "data/crypto",
    persist_snapshot: bool = True,
    client: Any = None,
    peer_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Single-underlying options vol + cross-symbol rank from one EAPI scan."""
    from quant_rd_tool.crypto_options_vol_scan import get_scan_config

    base = base_asset(symbol)
    cfg = get_scan_config(data_dir)
    peers = [s.upper() for s in (peer_symbols or cfg.get("symbols") or [base])]
    if base not in peers:
        peers = [base, *peers]
    try:
        scan = get_or_run_volatility_scan(
            symbols=peers,
            data_dir=data_dir,
            persist_snapshot=persist_snapshot,
            client=client,
            use_cache=True,
        )
    except Exception as e:
        logger.warning("options vol scan failed for %s: %s", base, e)
        return {"enabled": False, "base": base, "error": str(e)}

    item = next((x for x in scan.get("items") or [] if x.get("base") == base), None)
    if not item or item.get("atm_iv") is None:
        return {
            "enabled": False,
            "base": base,
            "error": (item or {}).get("error", "no iv data"),
            "scan": scan,
        }
    advice = advise_item(item)
    ranked = [x for x in scan.get("items") or [] if x.get("rank") is not None]
    top = ranked[0] if ranked else None
    return {
        "enabled": True,
        "base": base,
        "scan_item": item,
        "advice": advice,
        "alert_level": item.get("alert_level"),
        "iv_percentile": item.get("iv_percentile"),
        "iv_change_24h_pct": item.get("iv_change_24h_pct"),
        "atm_iv": item.get("atm_iv"),
        "contract": item.get("contract"),
        "cold_start": item.get("cold_start"),
        "peer_rank": item.get("rank"),
        "peer_count": len(ranked),
        "hottest_peer": top.get("base") if top else None,
        "scanned_at": scan.get("scanned_at"),
    }


def synthesize_cross_market_view(
    *,
    spot_stance: str,
    spot_action: str,
    options_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Align spot technical stance with options vol regime."""
    if not options_ctx.get("enabled"):
        return {
            "alignment": "unavailable",
            "summary": "期权波动数据暂不可用，以下研判仅基于 K 线技术面与 ML。",
            "notes": [],
        }

    opt_stance = str(options_ctx.get("advice", {}).get("stance", ""))
    alert = options_ctx.get("alert_level", "normal")
    pct = options_ctx.get("iv_percentile")
    chg = options_ctx.get("iv_change_24h_pct")
    iv = options_ctx.get("atm_iv")

    notes: list[str] = []
    if iv is not None:
        notes.append(f"近月 ATM 隐含波动率约 {float(iv) * 100:.1f}%。")
    if pct is not None:
        notes.append(f"IV 历史分位约 {pct}%。")
    if chg is not None:
        notes.append(f"24h IV 变化约 {chg:+.1f}%。")
    pr = options_ctx.get("peer_rank")
    pc = options_ctx.get("peer_count")
    if pr is not None and pc:
        notes.append(f"横向波动排名 #{pr}/{pc}（含 BTC/ETH/SOL/BNB 等配置标的）。")
    hot = options_ctx.get("hottest_peer")
    if hot and hot != options_ctx.get("base") and alert in ("hot", "elevated"):
        notes.append(f"当前全市场 IV 综合最高：{hot}。")

    high_vol = alert in ("hot", "elevated") or (pct is not None and pct >= 80)
    vol_rising = chg is not None and chg >= 10

    alignment = "补充"
    summary_parts: list[str] = []

    if spot_stance == "看涨":
        if high_vol and vol_rising:
            alignment = "分歧"
            summary_parts.append(
                "现货/ML 偏多，但期权波动溢价同步抬升：追涨时买方期权成本高，"
                "更宜现货或永续顺势，买 Call 需控制久期与仓位。"
            )
        elif high_vol:
            alignment = "谨慎共振"
            summary_parts.append(
                "方向偏多而 IV 偏高：趋势与波动溢价并存，加仓宜分批并设止损，"
                "不宜重仓买方期权。"
            )
        else:
            alignment = "共振"
            summary_parts.append(
                "方向偏多且期权波动未极端：顺势参与性价比相对更好，"
                "仍须遵守杠杆与止损纪律。"
            )
    elif spot_stance == "看跌":
        if high_vol:
            alignment = "共振"
            summary_parts.append(
                "方向偏空且波动偏高：下行风险与期权溢价同向，"
                "不宜盲目抄底；卖 Put 需充足保证金与止损。"
            )
        else:
            alignment = "补充"
            summary_parts.append(
                "技术面偏空但 IV 未显著抬升：可关注反弹至压力位的减仓机会。"
            )
    else:
        if high_vol:
            alignment = "补充"
            summary_parts.append(
                f"现货方向中性而期权侧「{opt_stance}」："
                "更适合波动策略（宽跨/铁鹰等）或观望，等待方向与波动率结构明朗。"
            )
        else:
            summary_parts.append("现货与期权波动均未给出强方向，宜轻仓或观望。")

    if opt_stance and opt_stance not in ("中性", "不可用"):
        notes.append(f"期权维度：{opt_stance}。")

    return {
        "alignment": alignment,
        "summary": " ".join(summary_parts),
        "notes": notes,
        "options_stance": opt_stance,
        "spot_stance": spot_stance,
        "spot_action": spot_action,
    }


def _attach_strike_ladder_if_configured(
    options_ctx: dict[str, Any],
    *,
    report: dict[str, Any],
    data_dir: str,
    client: Any = None,
) -> None:
    if not options_ctx.get("enabled"):
        return
    from quant_rd_tool.crypto_options_strike_probs import (
        build_strike_probability_report,
        get_strike_prob_config,
    )

    cfg = get_strike_prob_config(data_dir)
    if not cfg.get("include_strike_ladder_in_analyze", True):
        return
    base = options_ctx.get("base") or ""
    combined = report.get("combined_signal") or {}
    scan_item = options_ctx.get("scan_item") or {}
    try:
        ladder = build_strike_probability_report(
            str(base),
            n=int(cfg.get("analyze_ladder_n") or 3),
            data_dir=data_dir,
            expiry_iso=scan_item.get("expiry"),
            client=client,
            spot_stance=str(combined.get("stance", "中性")),
            iv_alert_level=str(options_ctx.get("alert_level") or "normal"),
            iv_percentile=options_ctx.get("iv_percentile"),
            with_purchase_advice=True,
        )
        options_ctx["strike_ladder"] = ladder
    except Exception as e:
        logger.warning("strike ladder for analyze failed: %s", e)
        options_ctx["strike_ladder"] = {"enabled": False, "error": str(e)}


def attach_options_to_report(
    report: dict[str, Any],
    *,
    data_dir: str = "data/crypto",
    with_options_vol: bool = True,
    persist_snapshot: bool = True,
    client: Any = None,
) -> dict[str, Any]:
    """Mutate report: options_vol block, refreshed narrative & markdown."""
    if not with_options_vol:
        report["options_vol"] = {"enabled": False, "skipped": True}
        return report

    sym = report.get("symbol") or report.get("pair", "BTC")
    options_ctx = fetch_options_context(
        str(sym),
        data_dir=data_dir,
        persist_snapshot=persist_snapshot,
        client=client,
    )
    combined = report.get("combined_signal") or report.get("signal") or {}
    cross = synthesize_cross_market_view(
        spot_stance=str(combined.get("stance", "中性")),
        spot_action=str(combined.get("action", "hold")),
        options_ctx=options_ctx,
    )
    options_ctx["cross_view"] = cross
    _attach_strike_ladder_if_configured(
        options_ctx,
        report=report,
        data_dir=data_dir,
        client=client,
    )
    report["options_vol"] = options_ctx

    from quant_rd_tool.crypto_analysis import _render_markdown
    from quant_rd_tool.crypto_analyzer import build_crypto_narrative

    narrative = build_crypto_narrative(
        report["analysis"],
        report["technical_signal"],
        combined_signal=combined,
        ml_analysis=report.get("ml_analysis"),
        pair=str(report.get("pair", "")),
        timeframe=str(report.get("timeframe", "1d")),
        options_context=options_ctx,
    )
    report["narrative"] = narrative
    report["markdown"] = _render_markdown(report)
    return report
