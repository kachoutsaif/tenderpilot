"""Le RAG de bout en bout : question -> recherche -> génération -> citations vérifiées.

Les dépendances (embedder, store, llm) sont passées en paramètres : on peut les
remplacer par des faux objets dans les tests, sans base ni clé API.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from tenderpilot.ingestion.chunking import chunk_notice
from tenderpilot.models import Answer, Notice, RetrievedChunk
from tenderpilot.rag.embeddings import Embedder
from tenderpilot.rag.llm import LLM
from tenderpilot.rag.prompt import NOT_FOUND, build_messages, extract_citations
from tenderpilot.rag.retrieval import retrieve


class VectorStore(Protocol):
    def search(self, query_vector: np.ndarray, k: int = 5) -> list[RetrievedChunk]: ...
    def search_fulltext(self, query: str, k: int = 5) -> list[RetrievedChunk]: ...
    def upsert_notice(self, notice: Notice, chunks, vectors) -> None: ...
    def delete_notices(self, notice_ids: list[str]) -> int: ...


def ingest_notice(
    notice: Notice,
    embedder: Embedder,
    store: VectorStore,
    max_chars: int = 1200,
    overlap: int = 200,
) -> int:
    """Découpe, vectorise et enregistre un avis. Renvoie le nombre de morceaux.

    Si l'avis est un rectificatif, l'avis d'origine qu'il remplace est supprimé :
    la base ne garde que la version à jour du marché.
    """
    if notice.replaces:
        store.delete_notices(notice.replaces)
    chunks = chunk_notice(notice, max_chars=max_chars, overlap=overlap)
    if not chunks:
        return 0
    vectors = embedder.embed([c.content for c in chunks])
    store.upsert_notice(notice, chunks, vectors)
    return len(chunks)


def answer_question(
    question: str,
    embedder: Embedder,
    store: VectorStore,
    llm: LLM,
    k: int = 5,
    min_score: float = 0.0,
    mode: str = "vector",
) -> Answer:
    """Répond à une question. `mode` : « vector », « text » ou « hybrid » (voir retrieval.py).

    Attention : `min_score` s'applique au score du mode choisi (cosinus, plein texte ou RRF),
    qui n'ont pas la même échelle.
    """
    question = question.strip()
    if not question:
        raise ValueError("La question est vide")

    found = retrieve(question, embedder, store, k=k, mode=mode)
    sources = [c for c in found if c.score >= min_score]
    if not sources:
        return Answer(text=NOT_FOUND, citations=[], invalid_citations=[], sources=[])

    text = llm.complete(build_messages(question, sources))
    citations, invalid = extract_citations(text, sources)
    return Answer(text=text, citations=citations, invalid_citations=invalid, sources=sources)
