"""Diagnostic des échecs de recherche : à quel rang se trouve le bon avis ?

    python scripts/diagnose_misses.py                 # questions ratées seulement
    python scripts/diagnose_misses.py q09 q14         # questions choisies
    python scripts/diagnose_misses.py --all

Pour chaque avis attendu, affiche son rang parmi TOUS les avis (recherche vectorielle
exhaustive) et le morceau le plus proche. Cela classe l'échec :
  - rang 6 à 20   -> « presque » : un reranker ou un k plus grand suffira ;
  - rang > 20     -> l'embedding ne comprend pas la question : recherche hybride, synonymes ;
  - morceau trouvé = morceau 0 ou non -> l'information est-elle au début de l'avis ?
"""

from __future__ import annotations

import argparse

from tenderpilot.config import get_settings
from tenderpilot.evaluation.dataset import load_questions
from tenderpilot.evaluation.metrics import unique_in_order
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.store import PgVectorStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*", help="identifiants de questions (q09 ...)")
    parser.add_argument("--file", default="eval/questions.jsonl")
    parser.add_argument("--k", type=int, default=5, help="k utilisé par l'évaluation")
    parser.add_argument("--all", action="store_true", help="toutes les questions")
    args = parser.parse_args()

    s = get_settings()
    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    store = PgVectorStore(s.database_url, dim=embedder.dim)
    # l'index HNSW ne renvoie qu'environ 40 résultats par défaut : on élargit pour tout classer
    store.conn.execute("SET hnsw.ef_search = 1000")
    _, total_chunks = store.count()

    questions = [q for q in load_questions(args.file) if q.expected]
    if args.ids:
        questions = [q for q in questions if q.id in args.ids]

    for q in questions:
        vec = embedder.embed([q.question])[0]
        chunks = store.search(vec, k=total_chunks)
        ranking = unique_in_order(c.notice_id for c in chunks)
        best_chunk = {}
        for c in chunks:
            best_chunk.setdefault(c.notice_id, c)

        ranks = {e: (ranking.index(e) + 1 if e in ranking else None) for e in q.expected}
        if not args.all and not args.ids and any(r and r <= args.k for r in ranks.values()):
            continue  # au moins un avis trouvé : pas un échec total

        print(f"\n=== {q.id} ({q.kind}) : {q.question}")
        for notice_id, rank in ranks.items():
            if rank is None:
                print(f"  {notice_id} : ABSENT de la base (mauvais identifiant ou pas ingéré ?)")
                continue
            c = best_chunk[notice_id]
            verdict = "trouvé" if rank <= args.k else "presque" if rank <= 20 else "loin"
            print(
                f"  {notice_id} : rang {rank:>3} / {len(ranking)}  [{verdict}]  "
                f"score {c.score:.3f}, morceau n°{c.chunk_index}"
            )
            print(f"      {c.content[:160].replace(chr(10), ' ')}...")
        top = chunks[0]
        title = (top.title or "")[:70]
        print(f"  -> 1er résultat : {top.notice_id} (score {top.score:.3f}) {title}")
    store.close()


if __name__ == "__main__":
    main()
