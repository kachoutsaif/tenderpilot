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

from dataclasses import replace
from typing import Protocol

import numpy as np

from tenderpilot.models import RetrievedChunk
from tenderpilot.rag.embeddings import Embedder

MODES = ("vector", "text", "hybrid")
RRF_K = 60


class SearchableStore(Protocol):
    def search(self, query_vector: np.ndarray, k: int = 5) -> list[RetrievedChunk]: ...
    def search_fulltext(self, query: str, k: int = 5) -> list[RetrievedChunk]: ...


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
) -> list[RetrievedChunk]:
    """Les k morceaux les plus pertinents pour la question, selon le mode choisi."""
    if mode not in MODES:
        raise ValueError(f"Mode de recherche inconnu : {mode!r} (choix : {', '.join(MODES)})")
    if mode == "text":
        return store.search_fulltext(question, k=k)
    n_vector = k if mode == "vector" else candidates
    vector_hits = store.search(embedder.embed([question])[0], k=n_vector)
    if mode == "vector":
        return vector_hits
    text_hits = store.search_fulltext(question, k=candidates)
    return rrf_fuse([vector_hits, text_hits])[:k]
