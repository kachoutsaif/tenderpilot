"""Semaine 2 : mesurer la qualité du RAG sur le jeu d'évaluation.

    # recherche seule (rapide, sans appel au LLM)
    python scripts/evaluate.py --label naif

    # avec génération + juge de fidélité (appelle le LLM : 2 appels par question)
    python scripts/evaluate.py --label naif --with-llm

Les résultats détaillés sont enregistrés dans eval/results/<date>_<label>.json,
pour comparer les configurations entre elles (naïf, hybride, reranker...).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from tenderpilot.config import get_settings
from tenderpilot.evaluation.dataset import load_questions
from tenderpilot.evaluation.runner import run_evaluation, to_dict
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.rag.llm import OpenAICompatibleLLM
from tenderpilot.store import PgVectorStore

COLUMNS = [
    "questions",
    "hit@k",
    "recall@k",
    "mrr",
    "fidelite",
    "hors_sujet_ok",
    "citations_invalides",
    "erreurs",
    "latence_moy_s",
    "latence_p95_s",
]


def print_table(summary: dict) -> None:
    rows = [("GLOBAL", summary["global"])] + list(summary["par_type"].items())
    width = max(len(name) for name, _ in rows) + 2
    print("\n" + "type".ljust(width) + "".join(c.rjust(14) for c in COLUMNS))
    for name, values in rows:
        cells = "".join(("-" if values[c] is None else str(values[c])).rjust(14) for c in COLUMNS)
        print(name.ljust(width) + cells)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="eval/questions.jsonl")
    parser.add_argument("--label", default="sans-nom", help="nom de la configuration testée")
    parser.add_argument("--k", type=int, default=None, help="nombre de morceaux récupérés")
    parser.add_argument("--with-llm", action="store_true", help="évalue aussi les réponses")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux questions")
    args = parser.parse_args()

    s = get_settings()
    k = args.k or s.top_k
    questions = load_questions(args.file)
    print(f"{len(questions)} questions chargées, k = {k}, configuration « {args.label} »")

    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    store = PgVectorStore(s.database_url, dim=embedder.dim)
    llm = judge = None
    if args.with_llm:
        llm = OpenAICompatibleLLM(api_key=s.llm_api_key, base_url=s.llm_base_url, model=s.llm_model)
        judge = OpenAICompatibleLLM(
            api_key=s.llm_api_key,
            base_url=s.llm_base_url,
            model=s.judge_model or s.llm_model,
            max_tokens=2000,
        )

    def progress(i, total, r):
        status = "ERREUR" if r.error else ("ok" if r.hit in (None, 1.0) else "raté")
        print(f"  [{i:>2}/{total}] {r.id:<6} {status:<6} {r.question[:70]}")

    results, summary = run_evaluation(
        questions, embedder, store, k=k, llm=llm, judge=judge, pause=args.pause, progress=progress
    )
    print_table(summary)

    missed = [r for r in results if r.hit == 0.0]
    if missed:
        print("\nQuestions où aucun avis attendu n'a été retrouvé :")
        for r in missed:
            print(f"  {r.id} : attendu {r.expected}, obtenu {r.retrieved}")
    unfaithful = [r for r in results if r.unsupported]
    if unfaithful:
        print("\nAffirmations non soutenues par les sources :")
        for r in unfaithful:
            for claim in r.unsupported:
                print(f"  {r.id} : {claim}")

    out_dir = Path("eval/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M}_{args.label}.json"
    payload = {
        "label": args.label,
        "date": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "k": k,
            "embedding_model": s.embedding_model,
            "llm_model": s.llm_model,
            "chunk_size": s.chunk_size,
            "chunk_overlap": s.chunk_overlap,
        },
        "summary": summary,
        "results": to_dict(results),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRésultats détaillés : {out}")
    store.close()


if __name__ == "__main__":
    main()
