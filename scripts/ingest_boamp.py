"""Étape 2 : récupérer des avis, les découper, les vectoriser et les stocker.

# avis réels publiés depuis 14 jours
python scripts/ingest_boamp.py --days 14 --limit 200

# sans réseau, avec le jeu d'exemple fictif des tests
python scripts/ingest_boamp.py --from-file tests/fixtures/boamp_sample.json
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

from tenderpilot.config import get_settings
from tenderpilot.ingestion.boamp import fetch_records, load_records_from_file, record_to_notice
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.rag.pipeline import ingest_notice
from tenderpilot.store import PgVectorStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="avis publiés depuis N jours")
    parser.add_argument("--where", default=None, help="filtre ODSQL supplémentaire")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--from-file", default=None, help="JSON local au lieu de l'API")
    args = parser.parse_args()

    settings = get_settings()
    if args.from_file:
        records = load_records_from_file(args.from_file)
    else:
        since = (date.today() - timedelta(days=args.days)).isoformat()
        where = f'dateparution >= "{since}"'
        if args.where:
            where = f"({where}) and ({args.where})"
        print(f"Filtre : {where}")
        records = list(fetch_records(where=where, limit=args.limit))

    print(f"{len(records)} avis récupérés. Chargement du modèle d'embedding...")
    embedder = FastEmbedEmbedder(settings.embedding_model, cache_dir=settings.embedding_cache_dir)
    store = PgVectorStore(settings.database_url, dim=embedder.dim)
    store.init_schema()

    start = time.perf_counter()
    ingested = skipped = total_chunks = 0
    for record in records:
        notice = record_to_notice(record)
        if notice is None:
            skipped += 1
            continue
        total_chunks += ingest_notice(
            notice, embedder, store, settings.chunk_size, settings.chunk_overlap
        )
        ingested += 1

    notices, chunks = store.count()
    print(
        f"Terminé en {time.perf_counter() - start:.1f} s : {ingested} avis indexés "
        f"({total_chunks} morceaux), {skipped} ignorés. Base : {notices} avis, {chunks} morceaux."
    )
    store.close()


if __name__ == "__main__":
    main()
