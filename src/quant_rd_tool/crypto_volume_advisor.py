"""Spot volume / turnover analysis and investment advice for single symbols (BTC/ETH focus)."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from quant_rd_tool import ccxt_data as cxt
from quant_rd_tool.crypto_analyzer import analyze_crypto_ohlcv, derive_trading_signal
from quant_rd_tool.time_util import now_iso

DISCLAIMER = (
    "以下为基于成交量与成交额规则的研究性提示，不构成投资建议。"
    "Crypto 7×24 交易，量价关系易受新闻与杠杆清算干扰，请结合风控自行决策。"
)

RecommendationLevel = Literal["strong_buy", "buy", "watch", "pass"]
VolumeScheme = Literal[
    "breakout_confirmed",
    "accumulation",
    "distribution_risk",
    "low_liquidity_warn",
    "neutral",
]

_LEVEL_LABEL: dict[str, str] = {
    "strong_buy": "强烈推荐",
    "buy": "建议参与",
    "watch": "观望等待",
    "pass": "暂不推荐",
}

_SCHEME_LABEL: dict[str, str] = {
    "breakout_confirmed": "放量突破确认",
    "accumulation": "缩量整理 / 吸筹",
    "distribution_risk": "量价背离 / 派发风险",
    "low_liquidity_warn": "流动性偏低",
    "neutral": "量价中性",
}

FOCUS_SYMBOLS = frozenset({"BTC", "ETH"})


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _period_return(close: pd.Series, bars: int) -> float | None:
    if len(close) <= bars:
        return None
    base = float(close.iloc[-1 - bars])
    if base <= 0:
        return None
    return float(close.iloc[-1] / base - 1.0)


def compute_volume_metrics(df: pd.DataFrame, *, timeframe: str = "1d") -> dict[str, Any]:
    """Derive volume, turnover and price-volume alignment from OHLCV."""
    work = df.copy()
    if "date" in work.columns:
        work["date"] = pd.to_datetime(work["date"])
        work = work.sort_values("date")
    vol = work["volume"].astype(float)
    close = work["close"].astype(float)
    turnover = vol * close

    vol_ratio: float | None = None
    turnover_ratio: float | None = None
    if len(vol) >= 25:
        base_vol = float(vol.iloc[-25:-5].mean())
        base_turn = float(turnover.iloc[-25:-5].mean())
        if base_vol > 0:
            vol_ratio = round(float(vol.iloc[-5:].mean() / base_vol), 4)
        if base_turn > 0:
            turnover_ratio = round(float(turnover.iloc[-5:].mean() / base_turn), 4)
    elif len(vol) >= 10:
        base_vol = float(vol.iloc[-10:-3].mean())
        if base_vol > 0:
            vol_ratio = round(float(vol.iloc[-3:].mean() / base_vol), 4)

    lookback = min(60, len(turnover))
    turnover_pctile: float | None = None
    if lookback >= 10:
        window = turnover.iloc[-lookback:]
        last_turn = float(turnover.iloc[-1])
        turnover_pctile = round(float((window <= last_turn).mean() * 100), 1)

    ret_1 = _period_return(close, 1)
    ret_5 = _period_return(close, 5)
    ret_20 = _period_return(close, 20)

    latest_vol = float(vol.iloc[-1])
    latest_turnover = float(turnover.iloc[-1])
    avg_turnover_20 = float(turnover.iloc[-20:].mean()) if len(turnover) >= 20 else None

    pv_alignment = "neutral"
    if vol_ratio is not None and ret_5 is not None:
        if ret_5 > 0.02 and vol_ratio >= 1.15:
            pv_alignment = "bullish_confirm"
        elif ret_5 > 0.02 and vol_ratio < 0.9:
            pv_alignment = "bearish_divergence"
        elif ret_5 < -0.02 and vol_ratio >= 1.3:
            pv_alignment = "distribution"
        elif abs(ret_5) < 0.03 and vol_ratio >= 1.15:
            pv_alignment = "accumulation"

    return {
        "timeframe": timeframe,
        "bars": int(len(work)),
        "latest_volume": round(latest_vol, 6),
        "latest_turnover_usdt": round(latest_turnover, 2),
        "avg_turnover_20_usdt": round(avg_turnover_20, 2) if avg_turnover_20 is not None else None,
        "volume_ratio_5d_vs_20d": vol_ratio,
        "turnover_ratio_5d_vs_20d": turnover_ratio,
        "turnover_percentile_60": turnover_pctile,
        "return_1bar": round(ret_1, 6) if ret_1 is not None else None,
        "return_5bar": round(ret_5, 6) if ret_5 is not None else None,
        "return_20bar": round(ret_20, 6) if ret_20 is not None else None,
        "price_volume_alignment": pv_alignment,
    }


def classify_volume_scheme(metrics: dict[str, Any]) -> VolumeScheme:
    vol_ratio = metrics.get("volume_ratio_5d_vs_20d")
    turn_pct = metrics.get("turnover_percentile_60")
    ret_5 = metrics.get("return_5bar")
    align = metrics.get("price_volume_alignment")

    if turn_pct is not None and turn_pct < 20:
        return "low_liquidity_warn"
    if vol_ratio is not None and vol_ratio < 0.55:
        return "low_liquidity_warn"

    if align == "distribution" or (
        ret_5 is not None and ret_5 > 0.03 and vol_ratio is not None and vol_ratio < 0.85
    ):
        return "distribution_risk"

    if align == "bullish_confirm" or (
        ret_5 is not None and ret_5 > 0.02 and vol_ratio is not None and vol_ratio >= 1.25
    ):
        return "breakout_confirmed"

    if align == "accumulation" or (
        vol_ratio is not None
        and vol_ratio >= 1.15
        and ret_5 is not None
        and abs(ret_5) < 0.04
    ):
        return "accumulation"

    return "neutral"


def build_volume_advice(
    metrics: dict[str, Any],
    *,
    scheme: VolumeScheme,
    technical_stance: str | None = None,
    ticker_24h: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    actions: list[str] = []
    risks: list[str] = [DISCLAIMER]

    vr = metrics.get("volume_ratio_5d_vs_20d")
    tr = metrics.get("turnover_ratio_5d_vs_20d")
    tp = metrics.get("turnover_percentile_60")
    r5 = metrics.get("return_5bar")

    if vr is not None:
        word = "放大" if vr >= 1.05 else "萎缩" if vr <= 0.95 else "持平"
        reasons.append(f"近 5 根 K 线成交量较此前 20 根均值{word}（量比 {vr:.2f}）。")
    if tr is not None:
        reasons.append(f"同期成交额（≈量×价）比 {tr:.2f}。")
    if tp is not None:
        reasons.append(f"最新 bar 成交额处于近 60 根 {tp:.0f}% 分位。")
    if r5 is not None:
        reasons.append(f"近 5 根价格变动 {r5 * 100:+.2f}%。")
    if ticker_24h and ticker_24h.get("quote_volume_usdt"):
        reasons.append(f"Binance 24h 成交额约 {ticker_24h['quote_volume_usdt']:,.0f} USDT。")

    scheme_label = _SCHEME_LABEL[scheme]
    reasons.insert(0, f"量价形态：{scheme_label}。")

    level: RecommendationLevel = "watch"
    stance = "中性"
    confidence = 0.45
    max_position_pct = 0.15

    if scheme == "breakout_confirmed":
        level = "buy"
        stance = "看涨"
        confidence = 0.62
        max_position_pct = 0.35
        actions.append("放量上行：可考虑分批建仓，止损设于近期整理区下沿。")
        if technical_stance == "看涨":
            level = "strong_buy"
            confidence = 0.72
            max_position_pct = 0.45
            actions.append("技术面同为看涨，量价共振提高置信度。")
    elif scheme == "accumulation":
        level = "watch"
        stance = "中性"
        confidence = 0.52
        max_position_pct = 0.2
        actions.append("价平量增：可列入观察，等待方向突破后再加仓。")
        if technical_stance == "看涨":
            level = "buy"
            stance = "看涨"
            confidence = 0.58
            actions.append("技术面偏多，吸筹形态下可小仓试多。")
    elif scheme == "distribution_risk":
        level = "pass"
        stance = "看跌"
        confidence = 0.58
        max_position_pct = 0.0
        actions.append("价涨量缩或下跌放量：建议减仓或观望，勿追高。")
    elif scheme == "low_liquidity_warn":
        level = "pass"
        stance = "中性"
        confidence = 0.4
        max_position_pct = 0.05
        actions.append("成交清淡：大单易滑点，不建议重仓；若交易请缩小规模。")
        risks.append("低流动性环境下量价信号噪声更大。")
    else:
        actions.append("量价未给出强信号：以技术面 / 风控为主，暂不因成交量单独加仓。")

    if technical_stance == "看跌" and level in {"strong_buy", "buy"}:
        level = "watch"
        stance = "中性"
        confidence *= 0.85
        actions.append("技术面偏空，量价看多信号已降级为观望。")

    headline = f"{_LEVEL_LABEL[level]} · {scheme_label}"
    advice_text = " ".join(actions[:2])

    return {
        "level": level,
        "level_label": _LEVEL_LABEL[level],
        "stance": stance,
        "scheme": scheme,
        "scheme_label": scheme_label,
        "headline": headline,
        "advice": advice_text,
        "reasons": reasons,
        "actions": actions,
        "risks": risks,
        "confidence": round(confidence, 3),
        "suggested_max_position_pct": round(max_position_pct, 3),
        "disclaimer": DISCLAIMER,
    }


def _fetch_ticker_24h(symbol: str, *, exchange_id: str = "binance") -> dict[str, Any] | None:
    try:
        import ccxt

        ex_cls = getattr(ccxt, exchange_id, None)
        if ex_cls is None:
            return None
        ex = ex_cls({"enableRateLimit": True})
        pair = cxt.to_ccxt_symbol(symbol)
        ticker = ex.fetch_ticker(pair)
        qv = ticker.get("quoteVolume")
        if qv is None and ticker.get("baseVolume") and ticker.get("last"):
            qv = float(ticker["baseVolume"]) * float(ticker["last"])
        return {
            "pair": pair,
            "last": ticker.get("last"),
            "quote_volume_usdt": round(float(qv), 2) if qv is not None else None,
            "base_volume": ticker.get("baseVolume"),
            "percentage": ticker.get("percentage"),
        }
    except Exception:
        return None


def advise_spot_volume(
    symbol: str,
    *,
    data_dir: str = "data/crypto",
    timeframe: str = "1d",
    limit: int = 120,
    refresh: bool = True,
    exchange_id: cxt.ExchangeId = "binance",
    include_ticker: bool = True,
) -> dict[str, Any]:
    sym = symbol.strip().upper()
    if sym not in FOCUS_SYMBOLS:
        raise ValueError(f"spot volume advisor v1 supports {sorted(FOCUS_SYMBOLS)}, got {symbol}")

    from quant_rd_tool.crypto_storage import ohlcv_csv_path
    from quant_rd_tool.crypto_analysis import crypto_root

    root = crypto_root(data_dir, sym)
    root.mkdir(parents=True, exist_ok=True)
    csv_file = ohlcv_csv_path(root, timeframe)

    if refresh or not csv_file.is_file():
        df = cxt.fetch_ohlcv(sym, timeframe=timeframe, limit=limit, exchange_id=exchange_id)
    else:
        df = pd.read_csv(csv_file)
        df["date"] = pd.to_datetime(df["date"])

    if df is None or df.empty or len(df) < 10:
        raise ValueError(f"not enough OHLCV bars for {sym}")

    metrics = compute_volume_metrics(df, timeframe=timeframe)
    scheme = classify_volume_scheme(metrics)
    analysis = analyze_crypto_ohlcv(df)
    tech_signal = derive_trading_signal(analysis)
    ticker = _fetch_ticker_24h(sym, exchange_id=exchange_id) if include_ticker else None
    advice = build_volume_advice(
        metrics,
        scheme=scheme,
        technical_stance=str(tech_signal.get("stance") or "中性"),
        ticker_24h=ticker,
    )

    return {
        "symbol": sym,
        "pair": cxt.to_ccxt_symbol(sym),
        "timeframe": timeframe,
        "metrics": metrics,
        "technical_stance": tech_signal.get("stance"),
        "technical_action": tech_signal.get("action"),
        "ticker_24h": ticker,
        "advice": advice,
        "generated_at": now_iso(),
    }
