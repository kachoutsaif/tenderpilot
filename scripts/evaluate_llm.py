"""Semaine 4, étape 4 : évaluer les RÉPONSES (avec LLM) sur le corpus figé.

    EVAL_DATABASE_URL=postgresql://.../tenderpilot_eval python scripts/evaluate_llm.py

Ce que la CI de chaque pull request ne mesure pas :
- fidélité : chaque affirmation de la réponse est-elle soutenue par les avis cités ?
  (juge LLM, de préférence un AUTRE modèle que celui qui répond : JUDGE_MODEL)
- hors sujet : pour une question sans réponse dans la base, le système dit-il
  « je ne trouve pas » au lieu d'inventer ?

Pourquoi pas à chaque pull request ?
- coût : ~60 appels LLM, environ 200 000 tokens, soit le quota QUOTIDIEN gratuit de Groq ;
- variabilité : deux lancements ne donnent pas exactement le même score (mesuré en
  semaine 3). Une porte bloquante bloquerait des PR au hasard.
Donc : lancé à la main ou une fois par semaine (.github/workflows/eval-llm.yml), il
INFORME (tendance, régressions à examiner) mais ne bloque rien.

Chaque lancement ajoute une ligne à eval/historique_llm.jsonl : on suit la tendance.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from tenderpilot.config import get_settings
from tenderpilot.evaluation.corpus import load_corpus
from tenderpilot.evaluation.dataset import load_questions
from tenderpilot.evaluation.offline import llm_markdown, prepare_store
from tenderpilot.evaluation.runner import run_evaluation, to_dict
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.rag.llm import OpenAICompatibleLLM


def make_llm(s, model: str, max_tokens: int | None = None) -> OpenAICompatibleLLM:
    # gpt-oss « réfléchit » avant de répondre : ses tokens de réflexion comptent dans
    # max_tokens. Effort faible = réponses et JSON du juge complets, moins de quota.
    options = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
    if max_tokens:
        options["max_tokens"] = max_tokens
    return OpenAICompatibleLLM(
        api_key=s.llm_api_key, base_url=s.llm_base_url, model=model, **options
    )


def current_commit() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"][:7]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True)
        return out.stdout.decode().strip() or "inconnu"
    except OSError:
        return "inconnu"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("EVAL_DATABASE_URL"))
    parser.add_argument("--corpus", default="eval/corpus.jsonl")
    parser.add_argument("--questions", default="eval/questions.jsonl")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", default="hybrid", choices=["vector", "text", "hybrid"])
    parser.add_argument("--pause", type=float, default=20.0, help="secondes entre questions")
    parser.add_argument("--limit", type=int, help="seulement les N premières questions")
    parser.add_argument("--out", default="out/evaluation_llm.json")
    parser.add_argument("--history", default="eval/historique_llm.jsonl")
    parser.add_argument("--summary", help="fichier où AJOUTER le rapport Markdown (CI)")
    args = parser.parse_args()

    s = get_settings()
    if not s.llm_api_key:
        raise SystemExit("LLM_API_KEY manquante (.env en local, secret GitHub dans la CI)")
    start = time.perf_counter()
    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    try:
        store, n_notices, _ = prepare_store(
            args.database_url, embedder, load_corpus(args.corpus), s.chunk_size, s.chunk_overlap
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    questions = load_questions(args.questions)[: args.limit]
    judge_model = s.judge_model or s.llm_model
    llm = make_llm(s, s.llm_model)
    judge = make_llm(s, judge_model, max_tokens=4000)

    def progress(i, total, r):
        state = "ERREUR" if r.error else f"fidélité {r.faithfulness}"
        print(f"  [{i:>2}/{total}] {r.id:<5} {state}", flush=True)

    results, summary = run_evaluation(
        questions,
        embedder,
        store,
        k=args.k,
        llm=llm,
        judge=judge,
        pause=args.pause,
        progress=progress,
        mode=args.mode,
    )
    store.close()

    config = {
        "modèle": s.llm_model,
        "juge": judge_model,
        "mode": args.mode,
        "k": args.k,
        "corpus": f"{n_notices} avis",
        "questions": len(questions),
        "commit": current_commit(),
        "durée": f"{(time.perf_counter() - start) / 60:.1f} min",
    }
    report = llm_markdown(summary, results, config)
    print(report)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(report)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"config": config, "summary": summary, "results": to_dict(results)}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    line = {"date": datetime.now().isoformat(timespec="minutes"), **config, **summary["global"]}
    with open(args.history, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(f"Résultats détaillés : {out} ; historique : {args.history}")


if __name__ == "__main__":
    main()
