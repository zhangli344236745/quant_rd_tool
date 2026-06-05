"""Subprocess entry: A-share zipline backtest in .venv-zipline."""

from __future__ import annotations

import json
import sys

from quant_rd_tool.stock_zipline_zipline_engine import run_zipline_backtest_inprocess


def main() -> None:
    payload = json.loads(sys.stdin.read())
    result = run_zipline_backtest_inprocess(
        symbol=payload["symbol"],
        data_dir=payload["data_dir"],
        strategy_id=payload["strategy_id"],
        strategy_params=payload.get("strategy_params"),
        capital_base=float(payload.get("capital_base", 100_000)),
        start=payload["start"],
        end=payload["end"],
        lookback_days=int(payload.get("lookback_days", 365)),
        force_reingest=bool(payload.get("force_reingest", False)),
        timeframe=payload.get("timeframe", "1d"),
        combo_spec=payload.get("combo_spec"),
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
