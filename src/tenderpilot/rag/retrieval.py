"""Recherche des morceaux pertinents : vectorielle, plein texte, ou hybride.

- « vector »  : similarité des embeddings. Comprend le sens général, mais rate les mots
                rares, les sigles et les noms propres (mesuré : « traiteur » au rang 17).
- « text »    : recherche plein texte PostgreSQL en français. Trouve les mots exacts
                (racinisés : « lavage » = « laver »), mais ignore les synonymes.
- « hybrid »  : les deux classements fusionnés par RRF (Reciprocal Rank Fusion).

RRF : chaque morceau reçoit, pour chaque classement où il apparaît, 1 / (60 + rang).
On additionne. Avantage : on fusionne des RANGS, pas des scores, donc pas besoin de
rendre comparables une similarité cosinus (0 à 1) et un score plein texte (0 à 20+).
La constante 60 vient de l'article d'origine (Cormack et al., 2009) : elle évite
qu'un premier rang dans un seul classement écrase tout le reste.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

import numpy as np

from tenderpilot.models import RetrievedChunk
from tenderpilot.rag.embeddings import Embedder

MODES = ("vector", "text", "hybrid")
RRF_K = 60


class SearchableStore(Protocol):
    def search(
        self, query_vector: np.ndarray, k: int = 5, departements: Sequence[str] | None = None
    ) -> list[RetrievedChunk]: ...
    def search_fulltext(
        self, query: str, k: int = 5, departements: Sequence[str] | None = None
    ) -> list[RetrievedChunk]: ...


def rrf_fuse(rankings: list[list[RetrievedChunk]], rrf_k: int = RRF_K) -> list[RetrievedChunk]:
    """Fusionne plusieurs classements de morceaux. Le score renvoyé est le score RRF."""
    scores: dict[tuple[str, int], float] = {}
    chunks: dict[tuple[str, int], RetrievedChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            key = (chunk.notice_id, chunk.chunk_index)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            chunks.setdefault(key, chunk)
    ordered = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [replace(chunks[key], score=scores[key]) for key in ordered]


def retrieve(
    question: str,
    embedder: Embedder,
    store: SearchableStore,
    k: int = 5,
    mode: str = "vector",
    candidates: int = 30,
    departements: Sequence[str] | None = None,
) -> list[RetrievedChunk]:
    """Les k morceaux les plus pertinents pour la question, selon le mode choisi.

    `departements` : ne garder que les avis de ces départements. Le filtre est appliqué
    PENDANT la recherche (dans la base), pas après : sinon, sur 30 candidats, il pourrait
    n'en rester aucun du bon département.
    """
    if mode not in MODES:
        raise ValueError(f"Mode de recherche inconnu : {mode!r} (choix : {', '.join(MODES)})")
    if mode == "text":
        return store.search_fulltext(question, k=k, departements=departements)
    n_vector = k if mode == "vector" else candidates
    query_vector = embedder.embed([question])[0]
    vector_hits = store.search(query_vector, k=n_vector, departements=departements)
    if mode == "vector":
        return vector_hits
    text_hits = store.search_fulltext(question, k=candidates, departements=departements)
    return rrf_fuse([vector_hits, text_hits])[:k]
