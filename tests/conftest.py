"""Faux objets partagés : ils remplacent le modèle, la base et le LLM dans les tests."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest

from tenderpilot.ingestion.boamp import load_records_from_file
from tenderpilot.models import RetrievedChunk

FIXTURES = Path(__file__).parent / "fixtures"


class FakeEmbedder:
    """Sac de mots haché : deux textes qui partagent des mots ont des vecteurs proches."""

    dim = 512  # assez grand pour limiter les collisions du hachage

    def embed(self, texts):
        vectors = []
        for text in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            for word in re.findall(r"\w{3,}", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
            norm = np.linalg.norm(v)
            vectors.append(v / norm if norm else v)
        return vectors


class InMemoryStore:
    """Même interface que PgVectorStore, mais en mémoire."""

    def __init__(self):
        self.notices = {}
        self.rows = []  # (chunk, vector)

    def upsert_notice(self, notice, chunks, vectors):
        self.notices[notice.id] = notice
        self.rows = [r for r in self.rows if r[0].notice_id != notice.id]
        self.rows += list(zip(chunks, vectors, strict=True))

    def delete_notices(self, notice_ids):
        removed = [i for i in notice_ids if i in self.notices]
        for i in removed:
            del self.notices[i]
        self.rows = [r for r in self.rows if r[0].notice_id not in removed]
        return len(removed)

    def search(self, query_vector, k=5):
        scored = sorted(
            ((float(np.dot(query_vector, v)), c) for c, v in self.rows),
            key=lambda x: x[0],
            reverse=True,
        )[:k]
        return [
            RetrievedChunk(
                notice_id=c.notice_id,
                chunk_index=c.index,
                content=c.content,
                score=s,
                title=self.notices[c.notice_id].title,
                url=self.notices[c.notice_id].url,
            )
            for s, c in scored
        ]

    def search_fulltext(self, query, k=5):
        """Version simplifiée : nombre de mots de la question (4 lettres ou plus) présents."""
        words = set(re.findall(r"\w{4,}", query.lower()))
        scored = []
        for c, _ in self.rows:
            score = sum(1 for w in words if w in c.content.lower())
            if score:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            RetrievedChunk(
                notice_id=c.notice_id,
                chunk_index=c.index,
                content=c.content,
                score=float(s),
                title=self.notices[c.notice_id].title,
                url=self.notices[c.notice_id].url,
            )
            for s, c in scored[:k]
        ]

    def get_notice(self, notice_id):
        return self.notices.get(notice_id)

    def list_notices(self, limit=20):
        return [{"id": n.id, "title": n.title} for n in list(self.notices.values())[:limit]]


class FakeLLM:
    def __init__(self, reply="Le marché porte sur le nettoyage de 3 bâtiments [1]."):
        self.reply = reply
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return self.reply


@pytest.fixture
def sample_records():
    return load_records_from_file(str(FIXTURES / "boamp_sample.json"))


@pytest.fixture
def embedder():
    return FakeEmbedder()


@pytest.fixture
def store():
    return InMemoryStore()
