"""Cross-sectional ML stock scoring for A-share VectorBT lab."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quant_rd_tool.stock_codes import to_qlib_code
from quant_rd_tool.stock_vbt_lab import VBT_LAB_DIR, load_ohlcv
from quant_rd_tool.watchlist import Watchlist

MlAlgorithm = Literal["lgb", "xgb"]
ML_DIR = VBT_LAB_DIR / "ml"

FEATURE_COLS = ("ret_1", "ret_5", "ret_20", "vol_20", "mom_60")


from quant_rd_tool.time_util import to_beijing_iso


def _iso_now(now: datetime | None = None) -> str:
    return to_beijing_iso(now)


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].astype(float)
    ret = close.pct_change()
    feats = pd.DataFrame(
        {
            "ret_1": ret,
            "ret_5": close.pct_change(5),
            "ret_20": close.pct_change(20),
            "vol_20": ret.rolling(20).std(),
            "mom_60": close / close.shift(60) - 1,
            "label": close.shift(-5) / close - 1,
        },
        index=df.index,
    )
    return feats.dropna()


def _fit_predict_score(
    feats: pd.DataFrame,
    *,
    algorithm: MlAlgorithm,
) -> tuple[float, dict[str, Any]]:
    if len(feats) < 80:
        raise ValueError("need at least 80 feature rows")
    train = feats.iloc[:-1]
    latest = feats.iloc[-1:]
    x_train = train[list(FEATURE_COLS)].values
    y_train = train["label"].values
    x_pred = latest[list(FEATURE_COLS)].values

    if algorithm == "xgb":
        import xgboost as xgb

        model = xgb.XGBRegressor(
            n_estimators=60,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(x_train, y_train)
        score = float(model.predict(x_pred)[0])
        importance = dict(zip(FEATURE_COLS, model.feature_importances_.tolist(), strict=True))
    else:
        import lightgbm as lgb

        train_set = lgb.Dataset(x_train, label=y_train)
        params = {
            "objective": "regression",
            "metric": "rmse",
            "verbosity": -1,
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "seed": 42,
        }
        model = lgb.train(params, train_set, num_boost_round=60)
        score = float(model.predict(x_pred)[0])
        importance = dict(zip(FEATURE_COLS, model.feature_importance().tolist(), strict=True))

    meta = {
        "algorithm": algorithm,
        "train_samples": len(train),
        "feature_importance": importance,
    }
    return score, meta


def score_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    algorithm: MlAlgorithm = "lgb",
    data_dir: str = "data/stocks",
    refresh_data: bool = False,
) -> dict[str, Any]:
    df = load_ohlcv(symbol, start, end, data_dir=data_dir, refresh=refresh_data)
    feats = build_feature_matrix(df)
    score, meta = _fit_predict_score(feats, algorithm=algorithm)
    return {
        "symbol": to_qlib_code(symbol),
        "score": score,
        "expected_fwd_return_5d": score,
        **meta,
    }


def screen_universe(
    *,
    symbols: list[str] | None = None,
    start: str,
    end: str,
    top_k: int = 10,
    algorithm: MlAlgorithm = "lgb",
    use_watchlist: bool = False,
    data_dir: str = "data/stocks",
    refresh_data: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be >= 1")

    universe = list(symbols or [])
    if use_watchlist:
        wl = Watchlist().list_codes()
        if wl:
            universe = wl
    if not universe:
        raise ValueError("no symbols to screen")

    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for sym in universe:
        try:
            row = score_symbol(
                sym,
                start,
                end,
                algorithm=algorithm,
                data_dir=data_dir,
                refresh_data=refresh_data,
            )
            items.append(row)
        except Exception as e:  # noqa: BLE001 - collect per-symbol errors
            errors.append({"symbol": str(sym), "error": str(e)})

    items.sort(key=lambda r: r.get("score", float("-inf")), reverse=True)
    ranked = items[:top_k]

    run_id = str(uuid.uuid4())
    run_dir = ML_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "run_id": run_id,
        "start": start,
        "end": end,
        "algorithm": algorithm,
        "top_k": top_k,
        "universe_size": len(universe),
        "scored": len(items),
        "items": ranked,
        "errors": errors,
        "created_at": _iso_now(now),
    }
    (run_dir / "scores.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "run_id": run_id,
        "items": ranked,
        "errors": errors,
        "universe_size": len(universe),
        "scored": len(items),
        "algorithm": algorithm,
    }
