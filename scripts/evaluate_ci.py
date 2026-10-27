"""Semaine 4 : évaluer la recherche sur le corpus figé, sans LLM. Fait pour la CI.

    EVAL_DATABASE_URL=postgresql://.../tenderpilot_eval python scripts/evaluate_ci.py

Étapes : vider la base d'évaluation -> charger eval/corpus.jsonl (découpage + vecteurs)
-> poser les questions -> hit@k, recall@k, MRR -> tableau Markdown et fichier JSON
-> PORTE QUALITÉ : code de sortie 1 (la CI échoue) si un score passe sous la référence
   (eval/reference.json) moins la tolérance. Voir evaluation/gate.py.

    python scripts/evaluate_ci.py --update-reference --note "pourquoi"   # nouvelle référence

ATTENTION : la base indiquée est VIDÉE. Par sécurité, son nom doit finir par « _test » ou
« _eval » : impossible d'effacer par erreur la base de développement (« tenderpilot »).
En local, créez une base dédiée une fois pour toutes :
    docker compose exec db createdb -U tender tenderpilot_eval
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from tenderpilot.config import get_settings
from tenderpilot.evaluation.corpus import load_corpus
from tenderpilot.evaluation.dataset import load_questions
from tenderpilot.evaluation.gate import (
    DEFAULT_TOLERANCE,
    check_gate,
    gate_markdown,
    load_reference,
    save_reference,
)
from tenderpilot.evaluation.offline import load_into_store, markdown_report
from tenderpilot.evaluation.runner import run_evaluation, to_dict
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.store import PgVectorStore


def safe_database_url(url: str | None) -> str:
    if not url:
        raise SystemExit("Indiquez la base d'évaluation : EVAL_DATABASE_URL ou --database-url")
    name = urlparse(url).path.lstrip("/")
    if not name.endswith(("_test", "_eval")):
        raise SystemExit(
            f"Refus : la base « {name} » va être VIDÉE. Son nom doit finir par _test ou _eval."
        )
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("EVAL_DATABASE_URL"))
    parser.add_argument("--corpus", default="eval/corpus.jsonl")
    parser.add_argument("--questions", default="eval/questions.jsonl")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", default="hybrid", choices=["vector", "text", "hybrid"])
    parser.add_argument("--out", default="out/evaluation_ci.json")  # out/ : ignoré par git
    parser.add_argument("--summary", help="fichier où AJOUTER le rapport Markdown (CI)")
    parser.add_argument("--reference", default="eval/reference.json")
    parser.add_argument(
        "--update-reference", action="store_true", help="enregistre ces scores comme référence"
    )
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument("--note", default="", help="raison de la mise à jour de la référence")
    args = parser.parse_args()

    url = safe_database_url(args.database_url)
    s = get_settings()
    start = time.perf_counter()
    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    store = PgVectorStore(url, dim=embedder.dim)
    store.conn.execute("DROP TABLE IF EXISTS chunks, notices")
    store.init_schema()

    notices = load_corpus(args.corpus)
    n_notices, n_chunks = load_into_store(
        notices, embedder, store, max_chars=s.chunk_size, overlap=s.chunk_overlap
    )
    print(f"Corpus chargé : {n_notices} avis, {n_chunks} morceaux")

    questions = load_questions(args.questions)
    results, summary = run_evaluation(questions, embedder, store, k=args.k, mode=args.mode)
    store.close()

    config = {
        "mode": args.mode,
        "k": args.k,
        "modèle": s.embedding_model.split("/")[-1],
        "morceaux": f"{s.chunk_size}/{s.chunk_overlap}",
        "corpus": f"{n_notices} avis",
        "questions": len(questions),
        "durée": f"{time.perf_counter() - start:.0f} s",
    }
    report = markdown_report(summary, results, config)
    passed = True
    if args.update_reference:
        save_reference(summary, args.reference, args.tolerance, args.note)
        report += f"\nRéférence mise à jour : `{args.reference}`\n"
    elif Path(args.reference).exists():
        checks = check_gate(summary, load_reference(args.reference))
        passed = all(c.ok for c in checks)
        report += gate_markdown(checks, args.k)
    else:
        report += f"\nAucune référence ({args.reference}) : porte qualité non appliquée.\n"
    print(report)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(report)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"config": config, "summary": summary, "results": to_dict(results)}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Résultats détaillés : {out}")
    if not passed:
        raise SystemExit(1)  # la CI échoue : la pull request ne peut pas être fusionnée


if __name__ == "__main__":
    main()
