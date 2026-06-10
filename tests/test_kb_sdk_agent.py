from __future__ import annotations

from unittest.mock import MagicMock, patch

from quant_rd_tool.kb_sdk_agent import (
    mark_sdk_unavailable,
    reset_sdk_availability,
    run_sdk_chat,
    sdk_installed,
    sdk_usable,
)


def test_sdk_installed():
    assert sdk_installed() is True


def test_sdk_usable_skips_after_mark():
    reset_sdk_availability()
    mark_sdk_unavailable("bridge 502")
    assert sdk_usable() is False
    reset_sdk_availability()


def test_run_sdk_chat_resume_mock(monkeypatch):
    reset_sdk_availability()
    monkeypatch.setattr("quant_rd_tool.config.settings.cursor_api_key", "test-key")
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_cursor_model", "composer-2.5")

    mock_agent = MagicMock()
    mock_agent.__enter__ = MagicMock(return_value=mock_agent)
    mock_agent.__exit__ = MagicMock(return_value=False)
    mock_agent.agent_id = "bc-sdk-1"
    mock_run = MagicMock()
    mock_run.text.return_value = "sdk answer"
    mock_agent.send.return_value = mock_run

    with patch("quant_rd_tool.kb_sdk_agent._open_agent", return_value=mock_agent):
        answer, aid = run_sdk_chat("hello", agent_id="bc-old-1")

    assert answer == "sdk answer"
    assert aid == "bc-sdk-1"
    mock_agent.send.assert_called_once()
