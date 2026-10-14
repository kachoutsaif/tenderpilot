"""Stockage des avis et des vecteurs dans PostgreSQL + pgvector."""

from __future__ import annotations

import json
from collections.abc import Sequence

import numpy as np

from tenderpilot.models import Chunk, Notice, RetrievedChunk

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS notices (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    buyer        TEXT,
    published    TEXT,
    deadline     TEXT,
    url          TEXT,
    raw          JSONB,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    notice_id    TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    chunk_index  INT  NOT NULL,
    content      TEXT NOT NULL,
    embedding    vector({dim}) NOT NULL,
    UNIQUE (notice_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
"""


class PgVectorStore:
    def __init__(self, database_url: str, dim: int):
        import psycopg
        from pgvector.psycopg import register_vector

        self.dim = dim
        self.conn = psycopg.connect(database_url, autocommit=True)
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)

    def init_schema(self) -> None:
        self.conn.execute(SCHEMA_SQL.format(dim=int(self.dim)))
        row = self.conn.execute(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
        if row and row[0] != self.dim:
            raise RuntimeError(
                f"La table 'chunks' attend des vecteurs de dimension {row[0]}, "
                f"mais le modèle d'embedding produit {self.dim}. "
                "Changez de modèle ou recréez la table (voir README)."
            )

    def upsert_notice(
        self, notice: Notice, chunks: Sequence[Chunk], vectors: Sequence[np.ndarray]
    ) -> None:
        """Insère ou remplace un avis et tous ses morceaux (ré-ingestion sans doublon)."""
        if len(chunks) != len(vectors):
            raise ValueError("Il faut autant de vecteurs que de morceaux")
        with self.conn.transaction():
            self.conn.execute(
                """
                INSERT INTO notices (id, title, buyer, published, deadline, url, raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title, buyer = EXCLUDED.buyer,
                    published = EXCLUDED.published, deadline = EXCLUDED.deadline,
                    url = EXCLUDED.url, raw = EXCLUDED.raw, ingested_at = now()
                """,
                (
                    notice.id,
                    notice.title,
                    notice.buyer,
                    notice.published,
                    notice.deadline,
                    notice.url,
                    json.dumps(notice.raw, ensure_ascii=False, default=str),
                ),
            )
            self.conn.execute("DELETE FROM chunks WHERE notice_id = %s", (notice.id,))
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (notice_id, chunk_index, content, embedding) "
                    "VALUES (%s, %s, %s, %s)",
                    [
                        (c.notice_id, c.index, c.content, v)
                        for c, v in zip(chunks, vectors, strict=True)
                    ],
                )

    def delete_notices(self, notice_ids: Sequence[str]) -> int:
        """Supprime des avis (et leurs morceaux). Renvoie le nombre d'avis supprimés."""
        if not notice_ids:
            return 0
        cur = self.conn.execute("DELETE FROM notices WHERE id = ANY(%s)", (list(notice_ids),))
        return cur.rowcount

    def search(self, query_vector: np.ndarray, k: int = 5) -> list[RetrievedChunk]:
        """Les k morceaux les plus proches (similarité cosinus)."""
        rows = self.conn.execute(
            """
            SELECT c.notice_id, c.chunk_index, c.content,
                   1 - (c.embedding <=> %(q)s) AS score, n.title, n.url
            FROM chunks c JOIN notices n ON n.id = c.notice_id
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(k)s
            """,
            {"q": np.asarray(query_vector, dtype=np.float32), "k": k},
        ).fetchall()
        return [
            RetrievedChunk(
                notice_id=r[0],
                chunk_index=r[1],
                content=r[2],
                score=float(r[3]),
                title=r[4],
                url=r[5],
            )
            for r in rows
        ]

    def list_notices(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, title, buyer, published, deadline, url FROM notices "
            "ORDER BY ingested_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        keys = ("id", "title", "buyer", "published", "deadline", "url")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def count(self) -> tuple[int, int]:
        notices = self.conn.execute("SELECT count(*) FROM notices").fetchone()[0]
        chunks = self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        return notices, chunks

    def close(self) -> None:
        self.conn.close()
