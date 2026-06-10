"""Vector retrieval for knowledge base."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from quant_rd_tool import kb_embed
from quant_rd_tool import kb_store


@dataclass
class ChunkHit:
    chunk_id: str
    doc_id: str
    doc_title: str
    doc_path: str | None
    text: str
    score: float
    tags: list[str]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def retrieve(
    query: str,
    *,
    top_k: int = 8,
    tags: list[str] | None = None,
    data_dir: str | None = None,
    embed_fn: Any = None,
) -> list[ChunkHit]:
    query = query.strip()
    if not query:
        return []
    q_vec = kb_embed.embed_texts([query], embed_fn=embed_fn)[0]
    chunks = kb_store.iter_all_chunks(data_dir=data_dir)
    hits: list[ChunkHit] = []
    for ch in chunks:
        ch_tags = ch.get("tags") or []
        if tags and not any(t in ch_tags for t in tags):
            continue
        emb = ch.get("embedding") or []
        score = cosine_similarity(q_vec, emb)
        hits.append(
            ChunkHit(
                chunk_id=ch["id"],
                doc_id=ch["doc_id"],
                doc_title=ch.get("doc_title") or "",
                doc_path=ch.get("doc_path"),
                text=ch["text"],
                score=score,
                tags=ch_tags,
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


def hits_to_citations(hits: list[ChunkHit]) -> list[dict[str, Any]]:
    cites: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in hits:
        if h.chunk_id in seen:
            continue
        seen.add(h.chunk_id)
        snippet = h.text[:240] + ("…" if len(h.text) > 240 else "")
        cites.append(
            {
                "doc_id": h.doc_id,
                "title": h.doc_title,
                "chunk_id": h.chunk_id,
                "snippet": snippet,
                "path": h.doc_path,
                "score": round(h.score, 4),
            }
        )
    return cites
