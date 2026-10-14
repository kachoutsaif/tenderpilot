"""Étape 2 : récupérer des avis, les découper, les vectoriser et les stocker.

# avis de marché (marchés ouverts) publiés depuis 14 jours
python scripts/ingest_boamp.py --days 14 --limit 300

# toutes les natures d'avis (y compris les résultats de marché)
python scripts/ingest_boamp.py --days 14 --limit 300 --nature tous

# sans réseau, avec le jeu d'exemple fictif des tests
python scripts/ingest_boamp.py --from-file tests/fixtures/boamp_sample.json
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

from tenderpilot.config import get_settings
from tenderpilot.ingestion.boamp import fetch_records, load_records_from_file, prepare_notices
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.rag.pipeline import ingest_notice
from tenderpilot.store import PgVectorStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="avis publiés depuis N jours")
    parser.add_argument("--where", default=None, help="filtre ODSQL supplémentaire")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--nature",
        default="APPEL_OFFRE",
        help="APPEL_OFFRE (marchés ouverts, par défaut), ATTRIBUTION, ou 'tous'",
    )
    parser.add_argument("--from-file", default=None, help="JSON local au lieu de l'API")
    args = parser.parse_args()

    settings = get_settings()
    if args.from_file:
        records = load_records_from_file(args.from_file)
    else:
        since = (date.today() - timedelta(days=args.days)).isoformat()
        where = f'dateparution >= "{since}"'
        if args.nature.lower() != "tous":
            where += f' and nature = "{args.nature}"'
        if args.where:
            where = f"({where}) and ({args.where})"
        print(f"Filtre : {where}")
        records = list(fetch_records(where=where, limit=args.limit))

    print(f"{len(records)} avis récupérés. Chargement du modèle d'embedding...")
    embedder = FastEmbedEmbedder(settings.embedding_model, cache_dir=settings.embedding_cache_dir)
    store = PgVectorStore(settings.database_url, dim=embedder.dim)
    store.init_schema()

    start = time.perf_counter()
    notices_to_index, skipped = prepare_notices(records)
    total_chunks = corrections = 0
    for notice in notices_to_index:
        corrections += bool(notice.replaces)
        total_chunks += ingest_notice(
            notice, embedder, store, settings.chunk_size, settings.chunk_overlap
        )
    ingested = len(notices_to_index)

    notices, chunks = store.count()
    print(
        f"Terminé en {time.perf_counter() - start:.1f} s : {ingested} avis indexés, "
        f"dont {corrections} rectificatifs ({total_chunks} morceaux), {skipped} ignorés. "
        f"Base : {notices} avis, {chunks} morceaux."
    )
    store.close()


if __name__ == "__main__":
    main()
