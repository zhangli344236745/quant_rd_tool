from __future__ import annotations

from unittest.mock import MagicMock

from quant_rd_tool.kb_cloud_agent import CursorCloudAgentError
from quant_rd_tool.kb_cursor_agent import build_prompt, get_stock_report_summary, run_agent_chat
from quant_rd_tool.kb_search import ChunkHit


def test_build_prompt_includes_chunks():
    hits = [
        ChunkHit(
            chunk_id="c1",
            doc_id="d1",
            doc_title="BTC",
            doc_path="data/crypto/CRYPTO_BTC/report.md",
            text="BTC bullish",
            score=0.9,
            tags=["crypto"],
        )
    ]
    prompt = build_prompt(hits, "要点？")
    assert "BTC bullish" in prompt
    assert "要点？" in prompt


def test_get_stock_report_summary_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = get_stock_report_summary("999999")
    assert out["available"] is False


def test_invalid_agent_id_retries_create(monkeypatch):
    monkeypatch.setattr("quant_rd_tool.kb_cursor_agent.cloud_agent_available", lambda: True)
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_agent_backend", "rest")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.create_run.side_effect = CursorCloudAgentError("bad", status_code=400)
    mock_client.create_agent.return_value = ("bc-new-1", "run-new-1")
    mock_client.wait_for_run.return_value = "cloud ok"

    result = run_agent_chat("hello", agent_id="fake-agent-1", client_factory=lambda: mock_client)
    assert result.answer == "cloud ok"
    assert result.agent_id == "bc-new-1"
    assert result.backend == "cloud_rest"
    mock_client.create_agent.assert_called_once()


def test_run_agent_chat_cloud_mock(monkeypatch):
    monkeypatch.setattr("quant_rd_tool.kb_cursor_agent.cloud_agent_available", lambda: True)
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_agent_backend", "rest")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.create_agent.return_value = ("bc-agent-1", "run-1")
    mock_client.wait_for_run.return_value = "cloud answer"

    result = run_agent_chat("hello", client_factory=lambda: mock_client)
    assert result.answer == "cloud answer"
    assert result.agent_id == "bc-agent-1"


def test_auto_backend_falls_back_to_rest(monkeypatch):
    monkeypatch.setattr("quant_rd_tool.kb_cursor_agent.cloud_agent_available", lambda: True)
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_agent_backend", "auto")
    monkeypatch.setattr("quant_rd_tool.kb_sdk_agent.sdk_usable", lambda **_: True)

    def _sdk_fail(*_a, **_k):
        raise RuntimeError("SDK bridge 502")

    monkeypatch.setattr("quant_rd_tool.kb_sdk_agent.run_sdk_chat", _sdk_fail)

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.create_agent.return_value = ("bc-rest-1", "run-1")
    mock_client.wait_for_run.return_value = "rest fallback"

    result = run_agent_chat("hello", client_factory=lambda: mock_client)
    assert result.answer == "rest fallback"
    assert result.backend == "cloud_rest"


def test_rag_only_answer():
    from quant_rd_tool.kb_cursor_agent import rag_only_answer

    hits = [
        ChunkHit("c1", "d1", "BTC", "path", "bullish trend", 0.9, ["crypto"]),
    ]
    ans = rag_only_answer(hits, "BTC 要点")
    assert "bullish" in ans
