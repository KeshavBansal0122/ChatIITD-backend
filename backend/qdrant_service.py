"""Qdrant vector-database helpers for admin-uploaded documents."""

from __future__ import annotations

import os
import uuid
import logging
from typing import List, Any, Dict, TYPE_CHECKING

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ---------- Config ----------
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "documents"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dim

# ---------- Singletons (initialised lazily) ----------
_client: QdrantClient | None = None
_model: SentenceTransformer | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers is required for document embeddings. "
                "Install it with: uv pip install sentence-transformers"
            ) from e
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


# ---------- Collection management ----------

def ensure_collection() -> None:
    """Create the documents collection if it doesn't already exist."""
    client = _get_client()
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection '%s'", COLLECTION_NAME)


# ---------- Upsert ----------

def upsert_chunks(
    file_id: int,
    file_name: str,
    description: str,
    upload_date: str,
    payloads: List[Any],
    batch_size: int = 100,
) -> int:
    """Embed each payload's `content` and upsert to Qdrant.

    Args:
        file_id:     The SQL Document.id
        file_name:   Original filename for metadata tagging
        description: Admin-supplied description
        upload_date: ISO-format upload timestamp
        payloads:    List of chunker Payload objects (have .content and .metadata)
        batch_size:  Qdrant upsert batch size

    Returns:
        Number of points upserted.
    """
    ensure_collection()
    client = _get_client()
    model = _get_model()

    points: List[PointStruct] = []
    for p in payloads:
        content = p.content
        embedding = model.encode(content).tolist()

        # Merge chunker metadata with document-level metadata
        metadata: Dict[str, Any] = {}
        if hasattr(p, "metadata") and isinstance(p.metadata, dict):
            metadata.update(p.metadata)
        metadata.update({
            "file_id": file_id,
            "file_name": file_name,
            "description": description,
            "upload_date": upload_date,
        })

        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={"content": content, "metadata": metadata},
            )
        )

    # Batch upsert
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)
        logger.info(
            "Upserted batch %d/%d (%d points)",
            i // batch_size + 1,
            (len(points) + batch_size - 1) // batch_size,
            len(batch),
        )

    logger.info("Upserted %d total points for file_id=%d", len(points), file_id)
    return len(points)


# ---------- Delete ----------

def delete_by_file_id(file_id: int) -> None:
    """Remove all points belonging to a given file_id from the collection."""
    ensure_collection()
    client = _get_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="metadata.file_id",
                    match=MatchValue(value=file_id),
                )
            ]
        ),
    )
    logger.info("Deleted all points for file_id=%d from '%s'", file_id, COLLECTION_NAME)
