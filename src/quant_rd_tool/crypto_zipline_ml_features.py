"""Feature engineering for walk-forward XGB crypto zipline strategies."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_rd_tool.crypto_zipline_strategies import signals as sig
from quant_rd_tool.crypto_zipline_strategies.tv_catalog import list_tv_strategies


def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in work.columns:
            if col == "volume":
                work[col] = 0.0
            elif col == "open":
                work[col] = work["close"].shift(1).fillna(work["close"])
            else:
                work[col] = work["close"]
    return work


def build_alpha158_style_features(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV-derived technical features (Alpha158-inspired, in-memory)."""
    work = _ensure_ohlcv(df)
    c = work["close"].astype(float)
    h = work["high"].astype(float)
    lo = work["low"].astype(float)
    v = work["volume"].astype(float)
    o = work["open"].astype(float)

    feats = pd.DataFrame(index=work.index)
    for n in (5, 10, 20, 30, 60):
        feats[f"ret_{n}"] = c.pct_change(n)
        feats[f"sma_{n}"] = c / c.rolling(n).mean() - 1.0
        feats[f"std_{n}"] = c.pct_change().rolling(n).std()
        feats[f"vol_{n}"] = v / v.rolling(n).mean().replace(0, np.nan) - 1.0
    feats["hl_range"] = (h - lo) / c
    feats["oc_gap"] = (o - c.shift(1)) / c.shift(1)
    feats["body"] = (c - o) / o.replace(0, np.nan)
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    feats["rsi14"] = 100 - (100 / (1 + rs))
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    feats["macd"] = ema12 - ema26
    feats["macd_sig"] = feats["macd"].ewm(span=9, adjust=False).mean()
    feats["atr14"] = (h - lo).rolling(14).mean() / c
    return feats.replace([np.inf, -np.inf], np.nan)


def build_tv_signal_matrix(df: pd.DataFrame, strategy_ids: list[str] | None = None) -> pd.DataFrame:
    """Compute TV strategy signals for each bar (uses only past data per bar)."""
    work = _ensure_ohlcv(df)
    ids = strategy_ids or [s["id"] for s in list_tv_strategies()]
    n = len(work)
    closes: list[float] = []
    volumes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    vols = work["volume"].tolist()
    out: dict[str, list[float]] = {sid: [0.0] * n for sid in ids}
    last_targets: dict[str, float] = {sid: 0.0 for sid in ids}

    for i in range(n):
        closes.append(float(work["close"].iloc[i]))
        volumes.append(float(vols[i]))
        highs.append(float(work["high"].iloc[i]))
        lows.append(float(work["low"].iloc[i]))
        opens.append(float(work["open"].iloc[i]))
        for sid in ids:
            spec = next((s for s in list_tv_strategies() if s["id"] == sid), None)
            params = dict(spec["default_params"]) if spec else {}
            t = sig.signal_for_strategy(
                sid,
                closes,
                volumes,
                params,
                highs=highs,
                lows=lows,
                opens=opens,
                last_target=last_targets[sid],
            )
            if t is not None:
                last_targets[sid] = t
                out[sid][i] = float(t)
            else:
                out[sid][i] = last_targets[sid]
    return pd.DataFrame(out, index=work.index)


def build_ml_feature_frame(
    df: pd.DataFrame,
    *,
    include_tv: bool = True,
    tv_vote_window: int = 5,
) -> pd.DataFrame:
    alpha = build_alpha158_style_features(df)
    if not include_tv:
        return alpha
    tv = build_tv_signal_matrix(df)
    tv["tv_vote_ratio"] = tv.mean(axis=1).rolling(tv_vote_window).mean()
    combined = pd.concat([alpha, tv], axis=1)
    return combined.replace([np.inf, -np.inf], np.nan)


def forward_return_labels(closes: pd.Series, horizon: int = 1) -> pd.Series:
    return closes.shift(-horizon) / closes - 1.0
