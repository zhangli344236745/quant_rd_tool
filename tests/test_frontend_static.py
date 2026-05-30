from fastapi.testclient import TestClient


def test_favicon_and_crypto_ops_not_500():
    from quant_rd_tool.main import app

    with TestClient(app) as client:
        fav = client.get("/favicon.ico")
        assert fav.status_code == 200

        ops = client.get("/api/v1/crypto/ops/summary")
        assert ops.status_code == 200
        assert "schedules" in ops.json()
