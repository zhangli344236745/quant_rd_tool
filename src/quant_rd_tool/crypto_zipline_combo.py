"""Multi-strategy signal combination for pandas + zipline."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_rd_tool.crypto_zipline_strategies import get_strategy
from quant_rd_tool.crypto_zipline_strategies.signals import signal_for_strategy

COMBO_MODES = ("vote", "and", "or", "weighted")


def normalize_combo_spec(
    *,
    legs: list[dict[str, Any]],
    mode: str = "vote",
) -> dict[str, Any]:
    if not legs:
        raise ValueError("strategy_combo requires at least one leg")
    mode_n = (mode or "vote").strip().lower()
    if mode_n not in COMBO_MODES:
        raise ValueError(f"combo_mode must be one of {COMBO_MODES}")

    normalized: list[dict[str, Any]] = []
    for leg in legs:
        sid = str(leg.get("strategy") or leg.get("id") or "").strip()
        if not sid or get_strategy(sid) is None:
            raise ValueError(f"Unknown strategy in combo: {sid!r}")
        spec = get_strategy(sid)
        params = {**spec["default_params"], **(leg.get("params") or {})}
        weight = float(leg.get("weight", 1.0))
        if weight <= 0:
            raise ValueError(f"Invalid weight for {sid}: {weight}")
        normalized.append({"strategy": sid, "params": params, "weight": weight})

    return {"mode": mode_n, "legs": normalized}


def combo_min_bars(spec: dict[str, Any]) -> int:
    return max(
        int(get_strategy(leg["strategy"]).get("min_bars", 20)) + 5
        for leg in spec["legs"]
    )


def combine_targets(
    targets: list[float | None],
    weights: list[float],
    mode: str,
    *,
    require_all: bool = True,
) -> float | None:
    """Merge per-leg 0/1 targets into one position."""
    pairs = [(t, w) for t, w in zip(targets, weights, strict=True) if t is not None]
    if not pairs:
        return None
    if require_all and len(pairs) < len(targets):
        return None

    if mode == "and":
        return 1.0 if all(t >= 0.5 for t, _ in pairs) else 0.0
    if mode == "or":
        return 1.0 if any(t >= 0.5 for t, _ in pairs) else 0.0
    if mode == "weighted":
        wsum = sum(w for _, w in pairs)
        score = sum(t * w for t, w in pairs) / wsum
        return 1.0 if score >= 0.5 else 0.0
    # vote (default)
    votes = sum(1 for t, _ in pairs if t >= 0.5)
    return 1.0 if votes > len(pairs) / 2 else 0.0


def combo_target_from_context(
    spec: dict[str, Any],
    closes: list[float],
    volumes: list[float],
    last_target: float = 0.0,
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> float | None:
    mode = spec["mode"]
    targets: list[float | None] = []
    weights: list[float] = []
    for leg in spec["legs"]:
        t = signal_for_strategy(
            leg["strategy"],
            closes,
            volumes,
            leg["params"],
            highs=highs,
            lows=lows,
            last_target=last_target,
        )
        targets.append(t)
        weights.append(leg["weight"])
    require_all = mode in ("and", "weighted")
    return combine_targets(targets, weights, mode, require_all=require_all)


def _target_series_for_leg(df: pd.DataFrame, strategy_id: str, params: dict[str, Any]) -> pd.Series:
    """Bar-by-bar target column using same signal functions as zipline."""
    n = len(df)
    targets = [0.0] * n
    closes: list[float] = []
    volumes: list[float] = []
    last_target = 0.0
    vols = df["volume"].tolist() if "volume" in df.columns else [0.0] * n
    highs: list[float] = []
    lows: list[float] = []
    for i in range(n):
        closes.append(float(df["close"].iloc[i]))
        volumes.append(float(vols[i]))
        highs.append(float(df["high"].iloc[i]) if "high" in df.columns else closes[-1])
        lows.append(float(df["low"].iloc[i]) if "low" in df.columns else closes[-1])
        t = signal_for_strategy(
            strategy_id,
            closes,
            volumes,
            params,
            highs=highs,
            lows=lows,
            last_target=last_target,
        )
        if t is not None:
            targets[i] = t
            last_target = t
        else:
            targets[i] = last_target
    return pd.Series(targets, index=df.index)


def run_combo_pandas(
    df: pd.DataFrame,
    combo_spec: dict[str, Any],
    capital_base: float,
) -> dict[str, Any]:
    work = df.copy()
    leg_cols: list[pd.Series] = []
    weights: list[float] = []
    for leg in combo_spec["legs"]:
        leg_cols.append(_target_series_for_leg(work, leg["strategy"], leg["params"]))
        weights.append(leg["weight"])

    combined: list[float] = []
    mode = combo_spec["mode"]
    for i in range(len(work)):
        row_targets = [float(col.iloc[i]) for col in leg_cols]
        t = combine_targets(row_targets, weights, mode, require_all=False)
        combined.append(t if t is not None else (combined[-1] if combined else 0.0))

    work["target"] = pd.Series(combined, index=work.index)
    warmup = combo_min_bars(combo_spec)
    from quant_rd_tool.stock_ashare_pandas import get_ashare_ctx, run_ashare_bar_backtest

    ctx = get_ashare_ctx()
    if ctx is not None:
        out = run_ashare_bar_backtest(
            work,
            capital_base=capital_base,
            warmup=warmup,
            symbol=str(ctx.get("symbol") or ""),
        )
    else:
        from quant_rd_tool.crypto_zipline_pandas import run_bar_backtest

        out = run_bar_backtest(work, capital_base=capital_base, warmup=warmup)
    out["strategy_params"] = combo_spec
    out["combo_legs"] = [leg["strategy"] for leg in combo_spec["legs"]]
    return out
