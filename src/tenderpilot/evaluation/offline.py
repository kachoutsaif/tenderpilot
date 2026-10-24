"""Évaluation hors ligne de la recherche : sans LLM, reproductible, faite pour la CI.

Hors ligne = aucun appel à une API payante ou limitée (Groq). Seuls le modèle d'embedding
(local) et PostgreSQL sont utilisés. Même code + même corpus = même score, à chaque fois.
C'est la condition pour qu'une porte qualité soit juste : elle ne doit bloquer une
modification que si la modification a vraiment dégradé la recherche.
"""

from __future__ import annotations

from collections.abc import Iterable

from tenderpilot.models import Notice
from tenderpilot.rag.pipeline import ingest_notice

METRICS = ("hit@k", "recall@k", "mrr")


def load_into_store(
    notices: Iterable[Notice], embedder, store, max_chars: int = 1200, overlap: int = 200
) -> tuple[int, int]:
    """Découpe, vectorise et enregistre les avis. Renvoie (avis, morceaux)."""
    count = chunks = 0
    for notice in notices:
        chunks += ingest_notice(notice, embedder, store, max_chars=max_chars, overlap=overlap)
        count += 1
    return count, chunks


def _cell(value) -> str:
    return "–" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def markdown_report(summary: dict, results, config: dict) -> str:
    """Rapport lisible dans la page de la CI (GitHub affiche le Markdown du résumé)."""
    k = config.get("k", "k")
    header = ["type", "questions", *(m.replace("@k", f"@{k}") for m in METRICS)]
    rows = [("**global**", summary["global"]), *summary["par_type"].items()]
    lines = [
        "## Évaluation de la recherche (hors ligne, sans LLM)",
        "",
        " · ".join(f"{key} : `{value}`" for key, value in config.items()),
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    for name, values in rows:
        cells = [name, str(values["questions"]), *(_cell(values[m]) for m in METRICS)]
        lines.append("| " + " | ".join(cells) + " |")

    missed = [r for r in results if r.hit == 0.0]
    partial = [r for r in results if r.recall is not None and 0.0 < r.recall < 1.0]
    if missed:
        lines += ["", f"**Questions ratées ({len(missed)})** : aucun avis attendu retrouvé", ""]
        lines += [f"- `{r.id}` {r.question} — attendu {', '.join(r.expected)}" for r in missed]
    if partial:
        lines += ["", f"**Questions partielles ({len(partial)})** : une partie seulement", ""]
        lines += [f"- `{r.id}` {r.question} — rappel {r.recall:.2f}" for r in partial]
    return "\n".join(lines) + "\n"
