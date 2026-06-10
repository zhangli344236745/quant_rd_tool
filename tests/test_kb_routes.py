from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_kb_routes_smoke(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_data_dir", str(kb_dir))
    monkeypatch.setattr("quant_rd_tool.kb_ingest.project_root", lambda: tmp_path)

    from quant_rd_tool.main import app

    client = TestClient(app)

    r = client.get("/api/v1/kb/status")
    assert r.status_code == 200
    body = r.json()
    assert "doc_count" in body

    r = client.get("/api/v1/kb/documents")
    assert r.status_code == 200
    assert r.json()["total"] == 0

    r = client.post("/api/v1/kb/sync-project")
    assert r.status_code == 200

    fake_chat = {
        "session_id": "sess-1",
        "answer": "test answer",
        "citations": [],
        "disclaimer": "仅供参考，不构成投资建议。",
    }
    with patch("quant_rd_tool.kb_chat.chat", return_value=fake_chat):
        r = client.post("/api/v1/kb/chat", json={"message": "BTC?"})
    assert r.status_code == 200
    assert r.json()["answer"] == "test answer"

    with patch("quant_rd_tool.kb_chat.chat", side_effect=RuntimeError("no cursor")):
        r = client.post("/api/v1/kb/chat", json={"message": "BTC?"})
    assert r.status_code == 503

    with patch(
        "quant_rd_tool.kb_cursor_agent.resolve_answer_with_fallback",
        return_value=("rag summary", None, "rag", "cloud timeout"),
    ):
        r = client.post("/api/v1/kb/chat", json={"message": "BTC?"})
    assert r.status_code == 200
    assert r.json()["answer"] == "rag summary"
