"""Recalcule les vecteurs de tous les morceaux déjà en base, SANS retélécharger les avis.

    python scripts/reembed.py

À utiliser quand on change la façon de vectoriser (normalisation, modèle de même
dimension...) : les avis et les morceaux restent identiques, seuls les vecteurs
changent. On compare donc deux configurations sur exactement les mêmes données.
"""

from __future__ import annotations

import time

from tenderpilot.config import get_settings
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.store import PgVectorStore

BATCH = 64


def main() -> None:
    s = get_settings()
    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    store = PgVectorStore(s.database_url, dim=embedder.dim)
    rows = store.conn.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()
    print(f"{len(rows)} morceaux à revectoriser (normalisation : {embedder.normalize})")

    start = time.perf_counter()
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        vectors = embedder.embed([content for _, content in batch])
        with store.conn.transaction():
            for (chunk_id, _), vec in zip(batch, vectors, strict=True):
                store.conn.execute(
                    "UPDATE chunks SET embedding = %s WHERE id = %s", (vec, chunk_id)
                )
        print(f"  {min(i + BATCH, len(rows))}/{len(rows)}", end="\r")
    print(f"\nTerminé en {time.perf_counter() - start:.1f} s.")
    store.close()


if __name__ == "__main__":
    main()
