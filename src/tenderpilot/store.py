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

-- Recherche plein texte en français, sans tenir compte des accents ni des majuscules :
-- « Bâtiments » et « batiment » donnent la même racine « batiment ».
CREATE EXTENSION IF NOT EXISTS unaccent;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'fr_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION fr_unaccent (COPY = french);
        ALTER TEXT SEARCH CONFIGURATION fr_unaccent
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
    END IF;
END $$;

-- colonne calculée par PostgreSQL : toujours à jour, y compris pour les morceaux existants
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('fr_unaccent'::regconfig, content)) STORED;
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
"""

# Score plein texte d'un morceau = somme des IDF des mots de la question qu'il contient.
# IDF (formule de BM25) : un mot présent partout (« marché ») ne compte presque pas,
# un mot rare (« traiteur ») compte beaucoup. Les mots sont reliés par OU : un morceau
# n'a pas besoin de contenir tous les mots de la question.
FULLTEXT_SQL = """
WITH terms AS (
    SELECT DISTINCT lex
    FROM unnest(tsvector_to_array(to_tsvector('fr_unaccent', %(q)s))) AS lex
),
total AS (SELECT count(*)::float8 AS n FROM chunks),
weighted AS (
    SELECT quote_literal(t.lex)::tsquery AS tq,
           ln(1 + (total.n - s.df + 0.5) / (s.df + 0.5)) AS idf
    FROM terms t
    CROSS JOIN total
    CROSS JOIN LATERAL (
        SELECT count(*)::float8 AS df
        FROM chunks c
        WHERE c.tsv @@ quote_literal(t.lex)::tsquery
    ) s
    WHERE s.df > 0
)
SELECT c.notice_id, c.chunk_index, c.content, sum(w.idf) AS score, n.title, n.url
FROM weighted w
JOIN chunks c ON c.tsv @@ w.tq
JOIN notices n ON n.id = c.notice_id
GROUP BY c.id, n.id
ORDER BY score DESC, c.id
LIMIT %(k)s
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
        return [_to_chunk(r) for r in rows]

    def search_fulltext(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Les k morceaux qui contiennent le plus de mots rares de la question."""
        rows = self.conn.execute(FULLTEXT_SQL, {"q": query, "k": k}).fetchall()
        return [_to_chunk(r) for r in rows]

    def search_text(self, words: list[str], limit: int = 30) -> list[dict]:
        """Avis contenant tous les mots donnés (aide à la préparation de l'évaluation)."""
        conditions = " AND ".join(["c.content ILIKE %s"] * len(words)) or "TRUE"
        rows = self.conn.execute(
            f"""
            SELECT n.id, n.title, n.buyer, n.deadline, count(*) AS morceaux
            FROM chunks c JOIN notices n ON n.id = c.notice_id
            WHERE {conditions}
            GROUP BY n.id, n.title, n.buyer, n.deadline
            ORDER BY n.id
            LIMIT %s
            """,
            [f"%{w}%" for w in words] + [limit],
        ).fetchall()
        keys = ("id", "title", "buyer", "deadline", "morceaux")
        return [dict(zip(keys, r, strict=True)) for r in rows]

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


def _to_chunk(row) -> RetrievedChunk:
    notice_id, chunk_index, content, score, title, url = row
    return RetrievedChunk(
        notice_id=notice_id,
        chunk_index=chunk_index,
        content=content,
        score=float(score),
        title=title,
        url=url,
    )
