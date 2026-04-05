"""
Samantha OS — Semantic Embedding Search
Uses Ollama's nomic-embed-text for vector similarity over memories.
"""

import os
import struct
import logging
import sqlite3
from typing import Optional

import httpx

logger = logging.getLogger("samantha.embeddings")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


class EmbeddingEngine:
    """Compute and search embeddings via Ollama."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self._create_table()

    def _create_table(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                text_content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_emb_source
            ON memory_embeddings(source_type, source_id)
        """)
        self.db.commit()

    async def embed_text(self, text: str) -> list[float] | None:
        """Get embedding vector from Ollama."""
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"http://{OLLAMA_HOST}/api/embed", json={
                    "model": EMBED_MODEL,
                    "input": text,
                })
                r.raise_for_status()
                embeddings = r.json().get("embeddings", [])
                if embeddings:
                    return embeddings[0]
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
        return None

    def _pack_embedding(self, vec: list[float]) -> bytes:
        """Pack float list to bytes for SQLite storage."""
        return struct.pack(f'{len(vec)}f', *vec)

    def _unpack_embedding(self, blob: bytes) -> list[float]:
        """Unpack bytes to float list."""
        n = len(blob) // 4
        return list(struct.unpack(f'{n}f', blob))

    async def store(self, source_type: str, source_id: int, text: str):
        """Embed text and store alongside its source reference."""
        vec = await self.embed_text(text)
        if vec is None:
            return
        self.db.execute(
            "INSERT INTO memory_embeddings (source_type, source_id, embedding, text_content) VALUES (?, ?, ?, ?)",
            (source_type, source_id, self._pack_embedding(vec), text)
        )
        self.db.commit()

    async def search(self, query: str, limit: int = 5, source_type: Optional[str] = None) -> list[dict]:
        """Find most similar memories by cosine similarity."""
        query_vec = await self.embed_text(query)
        if query_vec is None:
            return []

        if source_type:
            rows = self.db.execute(
                "SELECT id, source_type, source_id, embedding, text_content FROM memory_embeddings WHERE source_type = ?",
                (source_type,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id, source_type, source_id, embedding, text_content FROM memory_embeddings"
            ).fetchall()

        if not rows:
            return []

        results = []
        q_norm = _norm(query_vec)
        for row in rows:
            stored_vec = self._unpack_embedding(row[3])
            sim = _cosine_sim(query_vec, stored_vec, q_norm)
            results.append({
                "id": row[0],
                "source_type": row[1],
                "source_id": row[2],
                "text": row[4],
                "similarity": sim,
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]


def _norm(vec: list[float]) -> float:
    return sum(x * x for x in vec) ** 0.5


def _cosine_sim(a: list[float], b: list[float], a_norm: float = 0) -> float:
    if not a_norm:
        a_norm = _norm(a)
    b_norm = _norm(b)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (a_norm * b_norm)
