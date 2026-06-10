from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quant_rd_tool.kb_cloud_agent import CursorCloudAgentClient, CursorCloudAgentError


def test_create_agent_parses_ids():
    client = CursorCloudAgentClient("test-key")
    client._request = MagicMock(  # type: ignore[method-assign]
        return_value={
            "agent": {"id": "bc-agent-1"},
            "run": {"id": "run-1"},
        }
    )
    aid, rid = client.create_agent("hello")
    assert aid == "bc-agent-1"
    assert rid == "run-1"


def test_wait_for_run_finished():
    client = CursorCloudAgentClient("test-key")
    client.get_run = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            {"status": "RUNNING"},
            {"status": "FINISHED", "result": "done answer"},
        ]
    )
    text = client.wait_for_run("bc-1", "run-1", poll_interval=0, timeout=5)
    assert text == "done answer"


def test_wait_for_run_error_status():
    client = CursorCloudAgentClient("test-key")
    client.get_run = MagicMock(return_value={"status": "ERROR"})  # type: ignore[method-assign]
    with pytest.raises(CursorCloudAgentError):
        client.wait_for_run("bc-1", "run-1", poll_interval=0, timeout=1)


def test_stream_run_text_assistant_events():
    client = CursorCloudAgentClient("test-key")

    class FakeStream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self):
            payload = (
                "event: assistant\n"
                'data: {"text":"hel"}\n\n'
                "event: assistant\n"
                'data: {"text":"lo"}\n\n'
            )
            yield payload.encode()

    fake_resp = FakeStream()
    client._client.stream = MagicMock(return_value=fake_resp)  # type: ignore[method-assign]
    chunks = list(client.stream_run_text("bc-1", "run-1"))
    assert chunks == ["hel", "lo"]
