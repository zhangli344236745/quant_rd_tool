#!/usr/bin/env python3
"""
演示 Alpha158：把本地 qlib 5m K 线转成 ~158 维特征矩阵。

请在项目根目录运行：
  uv run python src/tools/demo_alpha158.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP

# 项目根目录（本文件在 src/tools/ 下）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_rd_tool.qlib_init import init_qlib, reset_qlib_init_state
from quant_rd_tool.qlib_ml import _build_handler, _time_segments


def _resolve_paths(symbol: str = "BTC") -> tuple[Path, Path, str]:
    from quant_rd_tool import ccxt_data as cxt

    code = cxt.to_qlib_code(symbol)
    root = PROJECT_ROOT / "data" / "crypto" / code
    qlib_dir = root / "qlib_5m"
    csv_file = root / "ohlcv_5m.csv"
    if not qlib_dir.joinpath("calendars", "5min.txt").exists():
        raise FileNotFoundError(
            f"未找到 {qlib_dir}/calendars/5min.txt\n"
            f"请先执行: uv run quant-rd crypto analyze --symbol {symbol} --timeframe 5m"
        )
    if not csv_file.exists():
        raise FileNotFoundError(f"未找到 {csv_file}")
    return qlib_dir, csv_file, code


def _period_from_csv(csv_file: Path) -> tuple[str, str, int]:
    df = pd.read_csv(csv_file, usecols=["date"])
    df["date"] = pd.to_datetime(df["date"])
    start = df["date"].min().strftime("%Y-%m-%d %H:%M:%S")
    end = df["date"].max().strftime("%Y-%m-%d %H:%M:%S")
    return start, end, len(df)


def run_alpha158_demo(symbol: str = "BTC") -> dict:
    """Run Alpha158 feature extraction; return summary stats."""
    qlib_dir, csv_file, code = _resolve_paths(symbol)
    start, end, n_bars = _period_from_csv(csv_file)

    reset_qlib_init_state()
    init_qlib(str(qlib_dir.resolve()), clear_cache=True)

    segments = _time_segments(start, end, min_span_days=60, intraday=True)
    fit_end = segments["train"][1]
    handler = _build_handler(code, start, end, fit_end=fit_end, qlib_freq="5min")
    dataset = DatasetH(handler, segments=segments)

    df_train = dataset.prepare("train", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
    n_rows = len(df_train)
    if isinstance(df_train.columns, pd.MultiIndex):
        feat_cols = list(df_train["feature"].columns)
        n_features = len(feat_cols)
        sample_feats = feat_cols[:10]
    else:
        n_features = len(df_train.columns) - 1
        sample_feats = list(df_train.columns[:10])

    label_col = df_train["label"].iloc[:, 0] if isinstance(df_train["label"], pd.DataFrame) else df_train["label"]
    label_non_null = int(label_col.notna().sum())

    return {
        "symbol": code,
        "qlib_dir": str(qlib_dir),
        "period": {"start": start, "end": end, "bars": n_bars},
        "segments": segments,
        "train_rows": n_rows,
        "feature_count": n_features,
        "sample_features": sample_feats,
        "label_non_null": label_non_null,
        "head_index": [str(x) for x in df_train.head(2).index.tolist()],
    }


def main() -> None:
    print("=== Alpha158 演示（BTC 5m 本地 qlib 数据）===\n")
    print(f"项目根目录: {PROJECT_ROOT}\n")

    summary = run_alpha158_demo("BTC")

    print(f"标的: {summary['symbol']}")
    print(f"qlib 目录: {summary['qlib_dir']}")
    print(
        f"样本区间（北京时间）: {summary['period']['start']} ~ {summary['period']['end']} "
        f"({summary['period']['bars']} 根 5m K 线)"
    )
    print(f"训练段行数（Alpha158 特征+标签）: {summary['train_rows']}")
    print(f"特征维度: {summary['feature_count']}（Alpha158 约 158 个）")
    print(f"标签非空行数: {summary['label_non_null']}")
    print(f"前 10 个特征名: {summary['sample_features']}")
    print(f"前两行时间索引: {summary['head_index']}")
    print(
        "\n说明: Alpha158 把 OHLCV 变成固定维度的技术面特征矩阵，"
        "供 XGBoost/LightGBM 学习「下一根收益」方向（见 qlib_ml.py）。"
    )


if __name__ == "__main__":
    main()
