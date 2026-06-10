from __future__ import annotations


def test_init_and_document_crud(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_data_dir", str(kb_dir))
    from quant_rd_tool import kb_store

    kb_store.init_db(kb_dir)
    doc_id = kb_store.upsert_document(
        title="Test Doc",
        source="upload",
        path="x.md",
        tags=["test"],
        content_hash="abc",
        data_dir=kb_dir,
    )
    kb_store.replace_chunks(
        doc_id,
        [{"text": "hello world", "embedding": [1.0, 0.0], "meta": {}}],
        data_dir=kb_dir,
    )
    listed = kb_store.list_documents(data_dir=kb_dir)
    assert listed["total"] == 1
    assert listed["items"][0]["title"] == "Test Doc"
    assert listed["items"][0]["chunk_count"] == 1

    assert kb_store.delete_document(doc_id, data_dir=kb_dir)
    assert kb_store.list_documents(data_dir=kb_dir)["total"] == 0


def test_session_and_messages(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_data_dir", str(kb_dir))
    from quant_rd_tool import kb_store

    sid = kb_store.create_session(title="chat1", data_dir=kb_dir)
    kb_store.add_message(sid, "user", "hi", data_dir=kb_dir)
    kb_store.add_message(sid, "assistant", "hello", citations=[{"title": "doc"}], data_dir=kb_dir)
    kb_store.update_session_agent(sid, "agent-123", data_dir=kb_dir)
    msgs = kb_store.list_messages(sid, data_dir=kb_dir)
    assert len(msgs) == 2
    assert msgs[1]["citations"][0]["title"] == "doc"
    session = kb_store.get_session(sid, data_dir=kb_dir)
    assert session["agent_id"] == "agent-123"
