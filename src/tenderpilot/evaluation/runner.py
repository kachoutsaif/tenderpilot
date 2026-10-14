"""Lance l'évaluation sur un jeu de questions et calcule les scores.

Deux niveaux :
- recherche seule (rapide, gratuit) : le bon avis est-il dans les k premiers ?
- avec LLM (--with-llm) : en plus, la réponse est-elle fidèle aux sources,
  et le système dit-il « je ne trouve pas » quand il le faut ?
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from statistics import mean

from tenderpilot.evaluation.dataset import EvalQuestion
from tenderpilot.evaluation.judge import judge_answer, says_not_found
from tenderpilot.evaluation.metrics import (
    hit_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    unique_in_order,
)
from tenderpilot.rag.pipeline import answer_question


@dataclass
class QuestionResult:
    id: str
    kind: str
    question: str
    expected: list[str]
    retrieved: list[str]
    hit: float | None = None
    recall: float | None = None
    rr: float | None = None
    search_seconds: float = 0.0
    answer: str | None = None
    answer_seconds: float | None = None
    faithfulness: float | None = None
    unsupported: list[str] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    not_found_ok: bool | None = None
    error: str | None = None


def evaluate_question(q: EvalQuestion, embedder, store, k: int, llm=None, judge=None):
    start = time.perf_counter()
    chunks = store.search(embedder.embed([q.question])[0], k=k)
    retrieved = unique_in_order(c.notice_id for c in chunks)
    result = QuestionResult(
        id=q.id,
        kind=q.kind,
        question=q.question,
        expected=q.expected,
        retrieved=retrieved,
        search_seconds=time.perf_counter() - start,
    )
    expected = set(q.expected)
    if q.kind != "hors_sujet":
        result.hit = hit_at_k(retrieved, expected)
        result.recall = recall_at_k(retrieved, expected)
        result.rr = reciprocal_rank(retrieved, expected)

    if llm is None:
        return result
    try:
        start = time.perf_counter()
        answer = answer_question(q.question, embedder, store, llm, k=k)
        result.answer_seconds = time.perf_counter() - start
        result.answer = answer.text
        result.invalid_citations = answer.invalid_citations
        if q.kind == "hors_sujet":
            result.not_found_ok = says_not_found(answer.text)
        if judge is not None:
            verdict = judge_answer(judge, q.question, answer.text, answer.sources)
            result.faithfulness = verdict.faithfulness
            result.unsupported = verdict.unsupported
    except Exception as exc:  # une question en erreur ne doit pas arrêter toute l'évaluation
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def _avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 3) if values else None


def summarize(results: list[QuestionResult]) -> dict:
    def block(rs: list[QuestionResult]) -> dict:
        answered = [r.answer_seconds for r in rs if r.answer_seconds is not None]
        out_of_scope = [r.not_found_ok for r in rs if r.not_found_ok is not None]
        return {
            "questions": len(rs),
            "hit@k": _avg(r.hit for r in rs),
            "recall@k": _avg(r.recall for r in rs),
            "mrr": _avg(r.rr for r in rs),
            "fidelite": _avg(r.faithfulness for r in rs),
            "hors_sujet_ok": _avg(float(x) for x in out_of_scope) if out_of_scope else None,
            "citations_invalides": sum(len(r.invalid_citations) for r in rs),
            "erreurs": sum(1 for r in rs if r.error),
            "latence_moy_s": round(mean(answered), 2) if answered else None,
            "latence_p95_s": round(percentile(answered, 95), 2) if answered else None,
        }

    by_kind: dict[str, list[QuestionResult]] = defaultdict(list)
    for r in results:
        by_kind[r.kind].append(r)
    return {"global": block(results), "par_type": {k: block(v) for k, v in sorted(by_kind.items())}}


def run_evaluation(questions, embedder, store, k=5, llm=None, judge=None, pause=0.0, progress=None):
    results = []
    for number, q in enumerate(questions, start=1):
        results.append(evaluate_question(q, embedder, store, k, llm=llm, judge=judge))
        if progress:
            progress(number, len(questions), results[-1])
        if pause and llm is not None:
            time.sleep(pause)  # pour respecter les limites de l'offre gratuite de l'API
    return results, summarize(results)


def to_dict(results: list[QuestionResult]) -> list[dict]:
    return [asdict(r) for r in results]
