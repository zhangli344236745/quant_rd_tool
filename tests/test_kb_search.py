from quant_rd_tool.kb_embed import embed_texts_keyword_fallback
from quant_rd_tool.kb_search import cosine_similarity, retrieve


def test_cosine_identical():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) == 1.0


def test_retrieve_with_synthetic_embeddings(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    monkeypatch.setattr("quant_rd_tool.config.settings.kb_data_dir", str(kb_dir))
    from quant_rd_tool import kb_store

    kb_store.init_db(kb_dir)
    doc_id = kb_store.upsert_document(title="BTC", source="project", tags=["crypto"], data_dir=kb_dir)
    e1 = embed_texts_keyword_fallback(["bitcoin report bullish"])[0]
    e2 = embed_texts_keyword_fallback(["unrelated cooking recipe"])[0]
    kb_store.replace_chunks(
        doc_id,
        [
            {"text": "bitcoin report bullish", "embedding": e1},
            {"text": "unrelated cooking recipe", "embedding": e2},
        ],
        data_dir=kb_dir,
    )

    def fake_embed(texts):
        return embed_texts_keyword_fallback(texts)

    hits = retrieve("bitcoin bullish", top_k=2, embed_fn=fake_embed, data_dir=str(kb_dir))
    assert hits
    assert hits[0].text.startswith("bitcoin")
