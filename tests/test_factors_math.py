import numpy as np
import pandas as pd

from quant_rd_tool.factors import compute_factors


def test_compute_factors_basic() -> None:
    idx = pd.date_range("2024-01-01", periods=80, freq="D")
    close = pd.Series(np.linspace(100, 120, len(idx)), index=idx)
    df = pd.DataFrame({"Close": close})
    out = compute_factors(df)
    assert out["as_of"] is not None
    assert "mom_5d" in out
    assert out["rsi_14"] is not None
