from unittest.mock import patch

from fastapi.testclient import TestClient


def test_enqueue_qlib_returns_job_id():
    from quant_rd_tool.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/jobs/qlib-analyze",
            json={"code": "600519", "years": 2, "with_ml": False},
        )
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_stocks_qlib_async_by_default():
    from quant_rd_tool.main import app

    with TestClient(app) as client:
        r = client.post("/api/v1/stocks/qlib-analyze/600519", json={"with_ml": False})
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_watchlist_roundtrip():
    from quant_rd_tool.main import app
    from quant_rd_tool.watchlist import Watchlist

    wl_path = Watchlist().path
    if wl_path.exists():
        wl_path.unlink()

    with TestClient(app) as client:
        r = client.post("/api/v1/stocks/watchlist", json={"code": "600519", "name": "茅台"})
        assert r.status_code == 200
        r2 = client.get("/api/v1/stocks/watchlist")
    assert any(it["code"] == "600519" for it in r2.json()["items"])
