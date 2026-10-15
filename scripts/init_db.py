"""Crée ou met à jour le schéma de la base, SANS toucher aux données.

    python scripts/init_db.py

Toutes les instructions du schéma sont idempotentes (IF NOT EXISTS) : on peut relancer
ce script sans risque. Il sert après une mise à jour du code qui ajoute une colonne
ou un index (par exemple la colonne plein texte `tsv` de la recherche hybride).
"""

from __future__ import annotations

from tenderpilot.config import get_settings
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.store import PgVectorStore


def main() -> None:
    s = get_settings()
    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    store = PgVectorStore(s.database_url, dim=embedder.dim)
    store.init_schema()
    notices, chunks = store.count()
    indexed = store.conn.execute("SELECT count(*) FROM chunks WHERE tsv IS NOT NULL").fetchone()[0]
    print(f"Schéma à jour : {notices} avis, {chunks} morceaux, {indexed} indexés en plein texte.")
    store.close()


if __name__ == "__main__":
    main()
