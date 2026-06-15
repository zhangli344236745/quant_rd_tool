"""Qlib Alpha158 features + XGBoost / LightGBM training, signals, and backtest scores."""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
import pandas as pd
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.model.xgboost import XGBModel
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP

from quant_rd_tool.qlib_init import init_qlib

logger = logging.getLogger(__name__)

MlAlgorithm = Literal["xgb", "lgb", "both"]
MIN_TRAINING_BARS = 400
MIN_TRAIN_ROWS = 100
MIN_VALID_ROWS = 20


def _count_segment_rows(dataset: DatasetH, segment: str) -> int:
    try:
        df = dataset.prepare(segment, col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
    except Exception:
        return 0
    if df is None:
        return 0
    return int(len(df))


def _validate_dataset_segments(dataset: DatasetH) -> dict[str, int]:
    counts = {
        "train": _count_segment_rows(dataset, "train"),
        "valid": _count_segment_rows(dataset, "valid"),
        "test": _count_segment_rows(dataset, "test"),
    }
    if counts["train"] < MIN_TRAIN_ROWS:
        raise ValueError(
            f"训练集有效样本过少（train={counts['train']}），"
            f"valid={counts['valid']}，test={counts['test']}。"
            "若刚切换周期/币种，请确认 qlib 目录与 K 线周期一致；"
            "5m 需使用 qlib_5m 且 Alpha158 需足够历史。"
        )
    if counts["valid"] < MIN_VALID_ROWS:
        raise ValueError(
            f"验证集有效样本过少（valid={counts['valid']}），train={counts['train']}。"
        )
    return counts


def _ts_fmt(ts: pd.Timestamp, *, intraday: bool) -> str:
    if intraday:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return ts.strftime("%Y-%m-%d")


def _time_segments(
    start: str, end: str, *, min_span_days: int = 365, intraday: bool = False
) -> dict[str, tuple[str, str]]:
    from quant_rd_tool.oos_protocol import build_fixed_split_segments

    return build_fixed_split_segments(
        start, end, min_span_days=min_span_days, intraday=intraday
    )


def _extract_label(dataset: DatasetH, segment: str) -> pd.Series:
    raw = dataset.prepare(segment, col_set="label", data_key=DataHandlerLP.DK_L)
    if isinstance(raw, pd.DataFrame):
        if "LABEL0" in raw.columns:
            return raw["LABEL0"]
        if "label" in raw.columns:
            return raw["label"]
        return raw.iloc[:, 0]
    return raw


def _pred_to_date_series(pred: pd.Series, qlib_code: str) -> pd.Series:
    if isinstance(pred.index, pd.MultiIndex):
        dates = pred.index.get_level_values(0)
    else:
        dates = pred.index
    out = pd.Series(pred.values, index=pd.to_datetime(dates))
    out.name = qlib_code
    return out.sort_index()


def _segment_metrics(pred: pd.Series, label: pd.Series) -> dict[str, float | None]:
    frame = pd.concat([pred.rename("pred"), label.rename("label")], axis=1).dropna()
    if len(frame) < 10:
        return {}
    ic = float(frame["pred"].corr(frame["label"]))
    rank_ic = float(frame["pred"].corr(frame["label"], method="spearman"))
    direction = float((np.sign(frame["pred"]) == np.sign(frame["label"])).mean())
    mse = float(((frame["pred"] - frame["label"]) ** 2).mean())
    return {
        "samples": int(len(frame)),
        "ic": round(ic, 6) if pd.notna(ic) else None,
        "rank_ic": round(rank_ic, 6) if pd.notna(rank_ic) else None,
        "direction_accuracy": round(direction, 4),
        "mse": round(mse, 8),
    }


def _build_handler(
    qlib_code: str,
    start_time: str,
    end_time: str,
    fit_end: str,
    *,
    qlib_freq: str = "day",
) -> Alpha158:
    return Alpha158(
        instruments=[qlib_code],
        start_time=start_time,
        end_time=end_time,
        fit_start_time=start_time,
        fit_end_time=fit_end,
        freq=qlib_freq,
        infer_processors=[
            {
                "class": "RobustZScoreNorm",
                "kwargs": {"fields_group": "feature", "clip_outlier": True},
            },
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        learn_processors=[{"class": "DropnaLabel"}],
    )


DEFAULT_SIGNAL_THRESHOLD = 0.005


def _signal_from_pred(
    latest_pred: float | None, threshold: float = DEFAULT_SIGNAL_THRESHOLD
) -> str:
    if latest_pred is None:
        return "中性"
    if latest_pred > threshold:
        return "模型偏多"
    if latest_pred < -threshold:
        return "模型偏空"
    return "中性"


def _adaptive_signal_threshold(label: pd.Series) -> float:
    """Scale signal threshold to label volatility so intraday bars can fire.

    Fixed ±0.5% kills 15m/1h signals (per-bar returns ~0.1%); use 0.3 * label std,
    floored to avoid noise-trading on a dead-flat series.
    """
    clean = pd.Series(label).dropna()
    if len(clean) < 30:
        return DEFAULT_SIGNAL_THRESHOLD
    std = float(clean.std())
    if not np.isfinite(std) or std <= 0:
        return DEFAULT_SIGNAL_THRESHOLD
    return max(1e-4, round(0.3 * std, 6))


def _fit_xgb(
    dataset: DatasetH,
    *,
    num_boost_round: int,
    early_stopping_rounds: int,
) -> tuple[XGBModel, dict[str, Any]]:
    model = XGBModel(
        eta=0.05,
        max_depth=5,
        objective="reg:squarederror",
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
    )
    evals: dict[str, Any] = {}
    model.fit(
        dataset,
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
        verbose_eval=False,
        evals_result=evals,
    )
    train_eval = {
        "best_iteration": int(getattr(model.model, "best_iteration", num_boost_round)),
        "train_metric": evals.get("train"),
        "valid_metric": evals.get("valid"),
    }
    return model, train_eval


def _xy_from_handler_df(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(df.columns, pd.MultiIndex):
        x = df["feature"].values
        y = df["label"].iloc[:, 0].values
    elif "feature" in df.columns:
        x = df["feature"].values
        y = _extract_label_from_xy_df(df).values
    else:
        x = df.iloc[:, :-1].values
        y = df.iloc[:, -1].values
    return x, np.squeeze(y)


def _fit_lgb(
    dataset: DatasetH,
    *,
    num_boost_round: int,
    early_stopping_rounds: int,
) -> tuple[Any, dict[str, Any]]:
    """Train LightGBM on qlib DatasetH (raw lgb.train, avoids qlib.workflow R)."""
    import lightgbm as lgb

    df_tr = dataset.prepare("train", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
    df_va = dataset.prepare("valid", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)

    x_tr, y_tr = _xy_from_handler_df(df_tr)
    x_va, y_va = _xy_from_handler_df(df_va)

    if len(x_tr) == 0 or len(y_tr) == 0:
        raise ValueError("LightGBM 训练集为空（Alpha158 特征/标签在分段内无有效行）")
    if len(x_va) == 0 or len(y_va) == 0:
        raise ValueError("LightGBM 验证集为空")

    train_set = lgb.Dataset(x_tr, label=y_tr)
    valid_set = lgb.Dataset(x_va, label=y_va, reference=train_set)
    evals_result: dict[str, Any] = {}
    booster = lgb.train(
        {
            "objective": "mse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 5,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "verbosity": -1,
        },
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[train_set, valid_set],
        valid_names=["train", "valid"],
        callbacks=[
            lgb.early_stopping(early_stopping_rounds),
            lgb.log_evaluation(period=0),
            lgb.record_evaluation(evals_result),
        ],
    )
    train_eval = {
        "best_iteration": int(booster.best_iteration),
        "train_metric": evals_result.get("train"),
        "valid_metric": evals_result.get("valid"),
    }
    return booster, train_eval


def _extract_label_from_xy_df(df: pd.DataFrame) -> pd.Series:
    if "label" in df.columns:
        lab = df["label"]
        if isinstance(lab, pd.DataFrame):
            return lab.iloc[:, 0]
        return lab
    if "LABEL0" in df.columns:
        return df["LABEL0"]
    return df.iloc[:, -1]


def _predict_lgb(booster: Any, dataset: DatasetH, segment: str) -> pd.Series:
    x_test = dataset.prepare(segment, col_set="feature", data_key=DataHandlerLP.DK_I)
    if isinstance(x_test.columns, pd.MultiIndex):
        vals = x_test["feature"].values
    elif "feature" in x_test.columns:
        vals = x_test["feature"].values
    else:
        vals = x_test.values
    return pd.Series(booster.predict(vals), index=x_test.index)


def _feature_importance(
    model: Any, algorithm: str, feature_names: list[str] | None = None
) -> pd.Series:
    if algorithm == "xgb":
        return model.get_feature_importance()
    imp = model.feature_importance(importance_type="gain")
    if feature_names and len(feature_names) == len(imp):
        return pd.Series(imp, index=feature_names)
    return pd.Series(imp, index=[f"f{i}" for i in range(len(imp))])


def _run_one_model(
    dataset: DatasetH,
    qlib_code: str,
    algorithm: MlAlgorithm,
    *,
    num_boost_round: int,
    early_stopping_rounds: int,
) -> dict[str, Any]:
    if algorithm == "xgb":
        model, train_eval = _fit_xgb(
            dataset, num_boost_round=num_boost_round, early_stopping_rounds=early_stopping_rounds
        )
        pred_valid = model.predict(dataset, segment="valid")
        pred_test = model.predict(dataset, segment="test")
        importance = _feature_importance(model, "xgb")
        model_id = "qlib.contrib.model.xgboost.XGBModel"
    else:
        model, train_eval = _fit_lgb(
            dataset, num_boost_round=num_boost_round, early_stopping_rounds=early_stopping_rounds
        )
        pred_valid = _predict_lgb(model, dataset, "valid")
        pred_test = _predict_lgb(model, dataset, "test")
        x_sample = dataset.prepare("train", col_set="feature", data_key=DataHandlerLP.DK_L)
        if isinstance(x_sample.columns, pd.MultiIndex):
            names = list(x_sample["feature"].columns)
        else:
            names = list(x_sample.columns) if hasattr(x_sample, "columns") else None
        importance = _feature_importance(model, "lgb", names)
        model_id = "lightgbm (Alpha158 features via qlib)"

    label_valid = _extract_label(dataset, "valid")
    label_test = _extract_label(dataset, "test")
    valid_metrics = _segment_metrics(pred_valid, label_valid)
    test_metrics = _segment_metrics(pred_test, label_test)

    top_features = [
        {"feature": str(k), "importance": round(float(v), 6)}
        for k, v in importance.sort_values(ascending=False).head(15).items()
    ]

    latest_pred = float(pred_test.iloc[-1]) if len(pred_test) else None
    latest_date = (
        str(pred_test.index.get_level_values(0)[-1].date()) if len(pred_test) else None
    )
    signal_threshold = _adaptive_signal_threshold(
        pd.concat([label_valid, label_test]) if len(label_valid) or len(label_test) else label_test
    )
    signal = _signal_from_pred(latest_pred, signal_threshold)

    oos_pred = pd.concat([pred_valid, pred_test])
    score_series = _pred_to_date_series(oos_pred, qlib_code)

    return {
        "enabled": True,
        "algorithm": algorithm,
        "model": model_id,
        "features": "qlib Alpha158",
        "label": "Ref($close,-2)/Ref($close,-1)-1",
        "train_eval": train_eval,
        "valid_metrics": valid_metrics,
        "test_metrics": test_metrics,
        "top_features": top_features,
        "latest": {
            "date": latest_date,
            "predicted_return": round(latest_pred, 6) if latest_pred is not None else None,
            "signal": signal,
            "signal_threshold": signal_threshold,
        },
        "interpretation": _ml_interpretation(
            test_metrics, latest_pred, signal, top_features[:5], algorithm
        ),
        "oos_score_series": score_series,
    }


def run_ml_analysis(
    qlib_dir: str,
    qlib_code: str,
    *,
    start_date: str,
    end_date: str,
    num_bars: int,
    algorithm: MlAlgorithm = "xgb",
    num_boost_round: int = 300,
    early_stopping_rounds: int = 30,
    include_oos_scores: bool = False,
    min_span_days: int = 365,
    intraday: bool = False,
    qlib_freq: str = "day",
) -> dict[str, Any]:
    """Train Alpha158 + XGB and/or LightGBM for one instrument."""
    if num_bars < MIN_TRAINING_BARS:
        return {
            "enabled": False,
            "skipped": True,
            "reason": f"样本不足（{num_bars} 条），建议至少 {MIN_TRAINING_BARS} 个交易日。",
        }

    init_qlib(qlib_dir, clear_cache=True)
    segments = _time_segments(start_date, end_date, min_span_days=min_span_days, intraday=intraday)
    handler = _build_handler(
        qlib_code, start_date, end_date, fit_end=segments["train"][1], qlib_freq=qlib_freq
    )
    dataset = DatasetH(handler, segments=segments)

    try:
        segment_counts = _validate_dataset_segments(dataset)
    except ValueError as e:
        return {
            "enabled": False,
            "skipped": True,
            "reason": str(e),
            "segments": segments,
        }

    algos: list[MlAlgorithm] = ["xgb", "lgb"] if algorithm == "both" else [algorithm]
    results: dict[str, Any] = {}
    from quant_rd_tool.oos_protocol import build_fixed_split_report

    for algo in algos:
        try:
            one = _run_one_model(
                dataset,
                qlib_code,
                algo,
                num_boost_round=num_boost_round,
                early_stopping_rounds=early_stopping_rounds,
            )
            one["oos_protocol"] = build_fixed_split_report(
                segments=segments,
                segment_counts=segment_counts,
                valid_metrics=one.get("valid_metrics"),
                test_metrics=one.get("test_metrics"),
                algorithm=algo,
                instrument=qlib_code,
            )
            if not include_oos_scores:
                one.pop("oos_score_series", None)
            one["segment_counts"] = segment_counts
            results[algo] = one
        except ImportError as e:
            results[algo] = {"enabled": False, "skipped": True, "reason": str(e)}
        except ValueError as e:
            logger.warning("ML %s skipped for %s: %s", algo, qlib_code, e)
            results[algo] = {"enabled": False, "skipped": True, "reason": str(e)}
        except Exception as e:
            err = str(e)
            if "Empty dataset" in err or "num_data" in err:
                logger.warning("ML %s skipped for %s: %s", algo, qlib_code, err)
                results[algo] = {
                    "enabled": False,
                    "skipped": True,
                    "reason": (
                        f"{err}（多为 qlib 数据目录/周期未切换或分段无样本，"
                        f"segment_counts={segment_counts}）"
                    ),
                }
            else:
                logger.exception("ML %s failed for %s", algo, qlib_code)
                results[algo] = {"enabled": False, "skipped": True, "reason": err}

    if algorithm == "both":
        preferred = _compare_models(results).get("preferred_by_ic")
        oos_protocol = None
        if preferred and results.get(preferred, {}).get("oos_protocol"):
            oos_protocol = results[preferred]["oos_protocol"]
        return {
            "enabled": any(r.get("enabled") for r in results.values()),
            "algorithm": "both",
            "segments": segments,
            "models": results,
            "comparison": _compare_models(results),
            "oos_protocol": oos_protocol,
        }

    single = results[algorithm]
    single["segments"] = segments
    return single


def run_xgb_analysis(
    qlib_dir: str,
    qlib_code: str,
    *,
    start_date: str,
    end_date: str,
    num_bars: int,
    num_boost_round: int = 300,
    early_stopping_rounds: int = 30,
) -> dict[str, Any]:
    return run_ml_analysis(
        qlib_dir,
        qlib_code,
        start_date=start_date,
        end_date=end_date,
        num_bars=num_bars,
        algorithm="xgb",
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
    )


def run_lgb_analysis(
    qlib_dir: str,
    qlib_code: str,
    *,
    start_date: str,
    end_date: str,
    num_bars: int,
    num_boost_round: int = 300,
    early_stopping_rounds: int = 30,
) -> dict[str, Any]:
    return run_ml_analysis(
        qlib_dir,
        qlib_code,
        start_date=start_date,
        end_date=end_date,
        num_bars=num_bars,
        algorithm="lgb",
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
    )


def build_ml_score_panel(
    qlib_dir: str,
    stock_frames: dict[str, pd.DataFrame],
    *,
    start_date: str,
    end_date: str,
    algorithm: MlAlgorithm = "lgb",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Per-stock ML out-of-sample scores (valid+test), wide format for Top-K backtest.

    Returns (scores_wide, summary).
    """
    init_qlib(qlib_dir)
    pieces: list[pd.Series] = []
    per_stock: dict[str, Any] = {}
    alg = "lgb" if algorithm == "both" else algorithm

    for code, df in stock_frames.items():
        n = len(df)
        if n < MIN_TRAINING_BARS:
            per_stock[code] = {"skipped": True, "reason": "insufficient bars"}
            continue
        try:
            res = run_ml_analysis(
                qlib_dir,
                code,
                start_date=start_date,
                end_date=end_date,
                num_bars=n,
                algorithm=alg,
                num_boost_round=200,
                early_stopping_rounds=20,
                include_oos_scores=True,
            )
            if not res.get("enabled"):
                per_stock[code] = res
                continue
            series = res.get("oos_score_series")
            if series is None or series.empty:
                per_stock[code] = {"skipped": True, "reason": "no oos predictions"}
                continue
            pieces.append(series)
            per_stock[code] = {
                "test_ic": res.get("test_metrics", {}).get("ic"),
                "signal": res.get("latest", {}).get("signal"),
                "oos_protocol": res.get("oos_protocol"),
            }
        except Exception as e:
            per_stock[code] = {"skipped": True, "reason": str(e)}

    if not pieces:
        return pd.DataFrame(), {"algorithm": alg, "stocks": per_stock, "error": "no ml scores"}

    wide = pd.concat(pieces, axis=1).sort_index()
    wide = wide.loc[:, ~wide.columns.duplicated()]
    from quant_rd_tool.oos_protocol import summarize_panel_oos

    meta = {
        "algorithm": alg,
        "stocks": per_stock,
        "score_start": str(wide.index.min().date()),
        "oos_summary": summarize_panel_oos(per_stock),
    }
    return wide, meta


def _compare_models(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lines = []
    for algo, res in results.items():
        if not res.get("enabled"):
            continue
        tm = res.get("test_metrics") or {}
        lines.append(
            f"{algo.upper()}: IC={tm.get('ic')}, 方向命中率={tm.get('direction_accuracy')}, "
            f"信号={res.get('latest', {}).get('signal')}"
        )
    best = None
    best_ic = -999.0
    for algo, res in results.items():
        ic = (res.get("test_metrics") or {}).get("ic")
        if ic is not None and ic > best_ic:
            best_ic = ic
            best = algo
    return {"summary": "；".join(lines), "preferred_by_ic": best}


def _ml_interpretation(
    test_metrics: dict[str, float | None],
    latest_pred: float | None,
    signal: str,
    top_features: list[dict[str, Any]],
    algorithm: str,
) -> dict[str, Any]:
    lines: list[str] = []
    ic = test_metrics.get("ic")
    acc = test_metrics.get("direction_accuracy")
    if ic is not None:
        lines.append(
            f"[{algorithm.upper()}] 测试集 IC={ic:.4f}，方向命中率={acc:.2%}。"
        )
    if latest_pred is not None:
        lines.append(f"最新预测收益代理 {latest_pred:.4f}，信号：{signal}。")
    if top_features:
        names = ", ".join(f["feature"] for f in top_features[:3])
        lines.append(f"主要因子：{names} 等。")

    return {
        "summary": "".join(lines),
        "signal": signal,
        "caveats": [
            "单标的训练无截面信息，指标仅供样本内参考。",
            "Alpha158 因子易过拟合，请结合风控与基本面。",
        ],
    }
