"""Technical and risk analytics for a single OHLCV series."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from qlib.contrib.evaluate import risk_analysis

from quant_rd_tool import akshare_data as ak_data


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    safe_loss = avg_loss.replace(0, np.nan)
    rs = avg_gain / safe_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return rsi


def _period_return(close: pd.Series, days: int) -> float | None:
    if len(close) <= days:
        return None
    v = close.iloc[-1] / close.iloc[-1 - days] - 1
    return round(float(v), 6) if pd.notna(v) else None


def _risk_metrics(daily_ret: pd.Series) -> dict[str, float | None]:
    r = daily_ret.dropna()
    if len(r) < 5:
        return {}
    risk = risk_analysis(r, freq="day")

    def _get(key: str) -> float | None:
        try:
            val = float(risk.loc[key, "risk"])
            return None if np.isnan(val) else round(val, 6)
        except (KeyError, TypeError):
            return None

    return {
        "annualized_return": _get("annualized_return"),
        "annualized_volatility": _get("std"),
        "sharpe_ratio": _get("information_ratio"),
        "max_drawdown": _get("max_drawdown"),
    }


def analyze_ohlcv(
    df: pd.DataFrame,
    *,
    benchmark_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compute indicators and summary statistics from normalized OHLCV."""
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values("date").set_index("date")
    close = work["close"].astype(float)
    volume = work["volume"].astype(float) if "volume" in work.columns else None
    daily_ret = close.pct_change()

    latest = close.iloc[-1]
    period_high = float(close.max())
    period_low = float(close.min())
    drawdown_series = close / close.cummax() - 1
    current_dd = float(drawdown_series.iloc[-1])

    sma20 = close.rolling(20).mean()
    sma60 = close.rolling(60).mean()
    rsi = _rsi(close)

    ma_signal = "震荡"
    if pd.notna(sma20.iloc[-1]) and pd.notna(sma60.iloc[-1]):
        if latest > sma20.iloc[-1] > sma60.iloc[-1]:
            ma_signal = "多头排列"
        elif latest < sma20.iloc[-1] < sma60.iloc[-1]:
            ma_signal = "空头排列"

    rsi_val = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None
    rsi_zone = "中性"
    if rsi_val is not None:
        if rsi_val >= 70:
            rsi_zone = "超买"
        elif rsi_val <= 30:
            rsi_zone = "超卖"

    vol_trend = None
    if volume is not None and len(volume) >= 20:
        recent = volume.iloc[-5:].mean()
        base = volume.iloc[-25:-5].mean()
        if base > 0:
            vol_trend = round(float(recent / base - 1), 4)

    bench_block: dict[str, Any] = {}
    if benchmark_df is not None and not benchmark_df.empty:
        b = benchmark_df.copy()
        b["date"] = pd.to_datetime(b["date"])
        b = b.set_index("date")["close"].astype(float)
        aligned = pd.concat([daily_ret, b.pct_change()], axis=1, join="inner").dropna()
        if len(aligned) >= 20:
            aligned.columns = ["stock", "bench"]
            corr = float(aligned["stock"].corr(aligned["bench"]))
            cov = aligned.cov().iloc[0, 1]
            var_b = aligned["bench"].var()
            beta = float(cov / var_b) if var_b and var_b > 0 else None
            excess = aligned["stock"].mean() - aligned["bench"].mean()
            bench_block = {
                "benchmark_code": benchmark_df["symbol"].iloc[0],
                "correlation": round(corr, 4),
                "beta": round(beta, 4) if beta is not None else None,
                "avg_daily_excess_return": round(float(excess), 6),
            }

    qlib_code = str(df["symbol"].iloc[0])
    return {
        "symbol": qlib_code,
        "bare_code": ak_data.to_ak_code(qlib_code),
        "period": {
            "start": str(work.index.min().date()),
            "end": str(work.index.max().date()),
            "bars": int(len(work)),
        },
        "price": {
            "latest_close": round(float(latest), 4),
            "period_high": round(period_high, 4),
            "period_low": round(period_low, 4),
            "pct_from_high": round(float(latest / period_high - 1), 6),
            "current_drawdown": round(current_dd, 6),
        },
        "returns": {
            "1d": _period_return(close, 1),
            "5d": _period_return(close, 5),
            "20d": _period_return(close, 20),
            "60d": _period_return(close, 60),
            "252d": _period_return(close, 252),
        },
        "risk": _risk_metrics(daily_ret),
        "technical": {
            "ma_alignment": ma_signal,
            "close_vs_sma20": round(float(latest / sma20.iloc[-1] - 1), 6)
            if pd.notna(sma20.iloc[-1])
            else None,
            "rsi_14": round(rsi_val, 2) if rsi_val is not None else None,
            "rsi_zone": rsi_zone,
            "volume_trend_5d_vs_20d": vol_trend,
        },
        "benchmark": bench_block,
    }


def build_narrative(analysis: dict[str, Any]) -> dict[str, Any]:
    """Turn structured analysis into Chinese report sections."""
    sym = analysis["symbol"]
    price = analysis["price"]
    ret = analysis["returns"]
    tech = analysis["technical"]
    risk = analysis.get("risk") or {}

    summary_parts = [
        f"标的 {sym}，样本区间 {analysis['period']['start']} 至 {analysis['period']['end']}，"
        f"共 {analysis['period']['bars']} 个交易日。",
        f"最新收盘价 {price['latest_close']}，较区间高点 {price['pct_from_high']:.2%}。",
    ]
    if ret.get("20d") is not None:
        summary_parts.append(f"近 20 日涨跌幅 {ret['20d']:.2%}。")

    observations: list[str] = []
    observations.append(f"均线结构：{tech['ma_alignment']}。")
    if tech.get("rsi_14") is not None:
        observations.append(f"RSI(14)={tech['rsi_14']}，处于{tech['rsi_zone']}区域。")
    if tech.get("volume_trend_5d_vs_20d") is not None:
        vt = tech["volume_trend_5d_vs_20d"]
        vol_word = "放大" if vt > 0.1 else "萎缩" if vt < -0.1 else "持平"
        observations.append(f"近 5 日成交量较此前 20 日均值{vol_word}（{vt:+.2%}）。")
    if risk.get("annualized_return") is not None:
        observations.append(
            f"样本年化收益约 {risk['annualized_return']:.2%}，"
            f"年化波动约 {risk.get('annualized_volatility', 0):.2%}，"
            f"最大回撤约 {abs(risk.get('max_drawdown') or 0):.2%}。"
        )

    bench = analysis.get("benchmark") or {}
    if bench.get("correlation") is not None:
        observations.append(
            f"相对基准 {bench.get('benchmark_code')}：相关系数 {bench['correlation']:.2f}，"
            f"Beta {bench.get('beta', 'N/A')}。"
        )

    stance = "中性"
    if tech["ma_alignment"] == "多头排列" and (ret.get("20d") or 0) > 0:
        stance = "偏多"
    elif tech["ma_alignment"] == "空头排列" or (ret.get("20d") or 0) < -0.05:
        stance = "谨慎"
    if tech.get("rsi_zone") == "超买":
        observations.append("短期技术指标偏热，注意回调风险。")
    elif tech.get("rsi_zone") == "超卖":
        observations.append("短期技术指标偏冷，可能存在反弹动能（需结合趋势）。")

    risks = [
        "本报告基于历史行情统计，不代表未来表现。",
        "未包含财务基本面、行业政策与资金面等信息。",
        "不构成任何证券买卖建议。",
    ]

    return {
        "stance": stance,
        "summary": "".join(summary_parts),
        "observations": observations,
        "risks": risks,
        "disclaimer": "仅供量化研究学习，不构成投资建议。",
    }
