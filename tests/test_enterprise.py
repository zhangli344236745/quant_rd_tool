from fastapi.testclient import TestClient

from quant_rd_tool.enterprise.auth import clear_sessions_for_tests
from quant_rd_tool.enterprise.config import save_enterprise_settings
from quant_rd_tool.main import app


def test_enterprise_off_by_default():
    client = TestClient(app)
    r = client.get("/api/v1/enterprise/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    post = client.post("/api/v1/jobs/qlib-analyze", json={"code": "600519"})
    assert post.status_code in (202, 503)


def test_enterprise_auth_blocks_mutations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clear_sessions_for_tests()
    save_enterprise_settings(
        enabled=True,
        require_auth=True,
        audit_enabled=True,
        api_keys=[{"id": "dev", "label": "dev", "key": "secret-key"}],
    )
    client = TestClient(app)
    denied = client.post(
        "/api/v1/jobs/analyze-stock",
        json={"code": "600519", "start_date": "2020-01-01"},
    )
    assert denied.status_code == 401
    ok = client.post(
        "/api/v1/jobs/analyze-stock",
        json={"code": "600519", "start_date": "2020-01-01"},
        headers={"X-API-Key": "secret-key"},
    )
    assert ok.status_code in (202, 503)
    audit = client.get("/api/v1/enterprise/audit", headers={"X-API-Key": "secret-key"})
    assert audit.status_code == 200
    assert audit.json()["count"] >= 1
    audit_q = client.get("/api/v1/enterprise/audit?api_key=secret-key")
    assert audit_q.status_code == 200


def test_enterprise_login_and_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clear_sessions_for_tests()
    monkeypatch.setenv("QUANT_RD_ADMIN_PASSWORD", "admin-pass")
    save_enterprise_settings(enabled=True, require_auth=True, audit_enabled=True)
    client = TestClient(app)
    bad = client.post("/api/v1/enterprise/login", json={"password": "wrong"})
    assert bad.status_code == 401
    good = client.post("/api/v1/enterprise/login", json={"password": "admin-pass"})
    assert good.status_code == 200
    token = good.json()["token"]
    r = client.get("/api/v1/enterprise/audit", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
