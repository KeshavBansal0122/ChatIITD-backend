"""
Hybrid knowledge retrieval over Qdrant: dense (MiniLM) + BM25 keyword scores, RRF fusion.

Collection: `knowledge`
Payload fields include generation (legacy|2025), doc_type, page_*, section_*, source_url.
"""

from __future__ import annotations

import logging
import math
import os
import re
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, TYPE_CHECKING

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
KNOWLEDGE_COLLECTION = os.environ.get("QDRANT_KNOWLEDGE_COLLECTION", "knowledge")
# Keep admin uploads on the existing dense-only collection
DOCUMENTS_COLLECTION = os.environ.get("QDRANT_DOCUMENTS_COLLECTION", "documents")
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_SIZE = 384

_client: QdrantClient | None = None
_model: SentenceTransformer | None = None
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.I)


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def ensure_knowledge_collection(recreate: bool = False) -> None:
    client = _get_client()
    names = [c.name for c in client.get_collections().collections]
    if recreate and KNOWLEDGE_COLLECTION in names:
        client.delete_collection(KNOWLEDGE_COLLECTION)
        names.remove(KNOWLEDGE_COLLECTION)
    if KNOWLEDGE_COLLECTION not in names:
        client.create_collection(
            collection_name=KNOWLEDGE_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection '%s'", KNOWLEDGE_COLLECTION)


def upsert_knowledge_payloads(
    payloads: Sequence[Any],
    *,
    batch_size: int = 64,
) -> int:
    """Embed and upsert Payload-like objects into the knowledge collection."""
    ensure_knowledge_collection()
    client = _get_client()
    model = _get_model()

    points: List[PointStruct] = []
    contents = []
    metas = []
    for p in payloads:
        content = getattr(p, "content", None) or p.get("content")
        metadata = getattr(p, "metadata", None) or p.get("metadata") or {}
        if not content:
            continue
        contents.append(content)
        metas.append(dict(metadata))

    if not contents:
        return 0

    embeddings = model.encode(contents, show_progress_bar=len(contents) > 50, batch_size=64)

    for content, metadata, emb in zip(contents, metas, embeddings):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=emb.tolist() if hasattr(emb, "tolist") else list(emb),
                payload={
                    "content": content,
                    "metadata": metadata,
                    # Flatten key filters for Qdrant FieldCondition
                    "generation": metadata.get("generation"),
                    "doc_type": metadata.get("doc_type"),
                    "source_url": metadata.get("source_url"),
                    "source_name": metadata.get("source_name") or metadata.get("source_file"),
                },
            )
        )

    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=KNOWLEDGE_COLLECTION, points=batch)
        logger.info(
            "Upserted knowledge batch %d (%d points)",
            i // batch_size + 1,
            len(batch),
        )
    return len(points)


def _rrf(rank_lists: Sequence[Sequence[str]], k: int = 60) -> List[str]:
    scores: Dict[str, float] = defaultdict(float)
    for ranks in rank_lists:
        for rank, pid in enumerate(ranks, start=1):
            scores[pid] += 1.0 / (k + rank)
    return [pid for pid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def _bm25_scores(query: str, docs: Sequence[str]) -> List[float]:
    """Simple BM25 without external deps (k1=1.5, b=0.75)."""
    q_tokens = tokenize(query)
    if not q_tokens or not docs:
        return [0.0] * len(docs)
    tokenized = [tokenize(d) for d in docs]
    N = len(tokenized)
    avgdl = sum(len(t) for t in tokenized) / max(N, 1)
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    k1, b = 1.5, 0.75
    scores = []
    for toks in tokenized:
        tf = Counter(toks)
        dl = len(toks) or 1
        score = 0.0
        for term in q_tokens:
            if term not in tf:
                continue
            n_qi = df.get(term, 0)
            idf = math.log(1 + (N - n_qi + 0.5) / (n_qi + 0.5))
            freq = tf[term]
            score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
        scores.append(score)
    return scores


def _build_filter(
    generation: Optional[str],
    doc_types: Optional[Sequence[str]],
) -> Optional[Filter]:
    must = []
    if generation:
        must.append(FieldCondition(key="generation", match=MatchValue(value=generation)))
    if doc_types:
        must.append(FieldCondition(key="doc_type", match=MatchAny(any=list(doc_types))))
    return Filter(must=must) if must else None


def hybrid_search(
    query: str,
    *,
    generation: Optional[str] = None,
    doc_types: Optional[Sequence[str]] = None,
    limit: int = 8,
    candidate_multiplier: int = 4,
) -> List[Dict[str, Any]]:
    """
    Hybrid dense + BM25 retrieval with Reciprocal Rank Fusion.

    Hard-gates on `generation` when provided (legacy vs 2025).
    """
    if not query or not query.strip():
        return []

    ensure_knowledge_collection()
    client = _get_client()
    model = _get_model()
    q_filter = _build_filter(generation, doc_types)
    fetch_n = max(limit * candidate_multiplier, limit)

    dense_vec = model.encode(query).tolist()
    dense_hits = client.search(
        collection_name=KNOWLEDGE_COLLECTION,
        query_vector=dense_vec,
        query_filter=q_filter,
        limit=fetch_n,
        with_payload=True,
    )

    # Keyword candidates: scroll a larger pool filtered by generation, score BM25 locally.
    # For corpora of a few thousand chunks this is acceptable.
    keyword_pool: List[Any] = []
    next_offset = None
    while len(keyword_pool) < max(fetch_n * 5, 200):
        records, next_offset = client.scroll(
            collection_name=KNOWLEDGE_COLLECTION,
            scroll_filter=q_filter,
            limit=256,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            break
        keyword_pool.extend(records)
        if next_offset is None:
            break

    # If pool is huge, prefer docs that share any query token via cheap prefilter
    q_toks = set(tokenize(query))
    if q_toks and len(keyword_pool) > fetch_n * 3:
        keyword_pool = [
            r
            for r in keyword_pool
            if q_toks.intersection(tokenize((r.payload or {}).get("content") or ""))
        ] or keyword_pool

    docs = [(r.payload or {}).get("content") or "" for r in keyword_pool]
    bm25 = _bm25_scores(query, docs)
    bm25_ranked = [
        str(r.id)
        for r, _ in sorted(zip(keyword_pool, bm25), key=lambda x: x[1], reverse=True)[:fetch_n]
        if _ > 0
    ]
    dense_ranked = [str(h.id) for h in dense_hits]

    fused_ids = _rrf([dense_ranked, bm25_ranked])[:limit]
    by_id = {str(h.id): h for h in dense_hits}
    for r in keyword_pool:
        by_id.setdefault(str(r.id), r)

    results: List[Dict[str, Any]] = []
    for pid in fused_ids:
        hit = by_id.get(pid)
        if not hit:
            continue
        payload = hit.payload or {}
        meta = payload.get("metadata") or {}
        results.append(
            {
                "id": pid,
                "content": payload.get("content") or "",
                "metadata": meta,
                "generation": payload.get("generation") or meta.get("generation"),
                "doc_type": payload.get("doc_type") or meta.get("doc_type"),
                "source_url": payload.get("source_url") or meta.get("source_url"),
                "score": getattr(hit, "score", None),
            }
        )
    return results


def format_hit_citation(hit: Dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    source_name = meta.get("source_name") or meta.get("source_file") or "unknown"
    if isinstance(source_name, str) and "/" in source_name:
        source_name = source_name.rsplit("/", 1)[-1]
    page_start = meta.get("page_start") or meta.get("page")
    page_end = meta.get("page_end") or page_start
    section = meta.get("section_title") or " > ".join(meta.get("section_path") or [])
    url = hit.get("source_url") or meta.get("source_url") or ""

    if page_start and page_end and page_start != page_end:
        page_bit = f"p.{page_start}–{page_end}"
    elif page_start:
        page_bit = f"p.{page_start}"
    else:
        page_bit = "web"

    lines = [f"[source: {source_name} | {page_bit} | section: {section}]"]
    if url:
        lines.append(f"URL: {url}")
    lines.append(hit.get("content") or "")
    return "\n".join(lines)
