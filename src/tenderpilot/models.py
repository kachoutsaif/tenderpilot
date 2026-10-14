"""Objets métier partagés par l'ingestion, le stockage et le RAG.

Ces classes n'ont aucune dépendance externe : elles restent faciles à tester.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Notice:
    """Un avis de marché public (une annonce BOAMP)."""

    id: str
    title: str
    text: str
    buyer: str | None = None
    published: str | None = None
    deadline: str | None = None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    # identifiants des avis remplacés (un rectificatif remplace l'avis d'origine)
    replaces: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    """Un morceau de texte d'un avis, prêt à être vectorisé."""

    notice_id: str
    index: int
    content: str


@dataclass
class RetrievedChunk:
    """Un morceau retrouvé par la recherche, avec son score de similarité."""

    notice_id: str
    chunk_index: int
    content: str
    score: float
    title: str | None = None
    url: str | None = None


@dataclass
class Citation:
    """Une source citée dans la réponse, avec son numéro [n]."""

    number: int
    notice_id: str
    title: str | None
    url: str | None
    excerpt: str


@dataclass
class Answer:
    """Réponse finale du RAG."""

    text: str
    citations: list[Citation]
    invalid_citations: list[int]
    sources: list[RetrievedChunk]
