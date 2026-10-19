"""Mémoire de leçons : l'agent apprend de ses erreurs d'une exécution à l'autre.

Pattern « Reflexion » (Shinn et al., 2023). Un LLM n'a aucune mémoire entre deux appels :
pour qu'il ne refasse pas la même erreur, on lui redonne l'expérience passée dans son prompt.

    erreur détectée par le juge ──► leçon GÉNÉRALE ──► table `lessons` ──► prompt du rédacteur
    leçon donnée par l'humain   ──┘

Garde-fous :
- pas de doublons : le LLM reçoit les leçons existantes et renforce l'une d'elles (compteur)
  plutôt que d'en écrire une nouvelle qui dit la même chose ;
- prompt borné : seules les `limit` meilleures leçons sont injectées (humain d'abord) ;
- transparence : les leçons sont lisibles et supprimables (`scripts/lessons.py`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from tenderpilot.agent.extraction import normalize

HUMAN, JUDGE = "humain", "juge"
MAX_NEW_PER_RUN = 3
MIN_CHARS, MAX_CHARS = 10, 250


@dataclass
class Lesson:
    id: int
    text: str
    source: str  # "humain" ou "juge"
    count: int = 1  # nombre de fois où l'erreur a été constatée (ou la leçon redonnée)


class LessonStore(Protocol):
    def top(self, limit: int = 10) -> list[Lesson]: ...
    def add(self, text: str, source: str) -> Lesson: ...
    def reinforce(self, lesson_id: int) -> None: ...
    def all(self) -> list[Lesson]: ...
    def delete(self, lesson_id: int) -> bool: ...


def _rank(lesson: Lesson) -> tuple:
    # les leçons humaines d'abord, puis les erreurs les plus fréquentes
    return (lesson.source != HUMAN, -lesson.count, lesson.id)


class InMemoryLessonStore:
    """Même interface que PgLessonStore, en mémoire (tests, mesures sans base)."""

    def __init__(self, lessons: list[Lesson] | None = None):
        self._lessons: dict[int, Lesson] = {lesson.id: lesson for lesson in lessons or []}

    def top(self, limit: int = 10) -> list[Lesson]:
        return sorted(self._lessons.values(), key=_rank)[:limit]

    def add(self, text: str, source: str) -> Lesson:
        for lesson in self._lessons.values():
            if normalize(lesson.text) == normalize(text):
                lesson.count += 1
                return lesson
        lesson = Lesson(id=max(self._lessons, default=0) + 1, text=text, source=source)
        self._lessons[lesson.id] = lesson
        return lesson

    def reinforce(self, lesson_id: int) -> None:
        if lesson_id in self._lessons:
            self._lessons[lesson_id].count += 1

    def all(self) -> list[Lesson]:
        return sorted(self._lessons.values(), key=_rank)

    def delete(self, lesson_id: int) -> bool:
        return self._lessons.pop(lesson_id, None) is not None


LESSONS_SQL = """
CREATE TABLE IF NOT EXISTS lessons (
    id          SERIAL PRIMARY KEY,
    text        TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL,
    count       INT  NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PgLessonStore:
    """Les leçons dans PostgreSQL : elles survivent aux redémarrages."""

    def __init__(self, conn):
        self.conn = conn  # connexion psycopg en autocommit (celle de PgVectorStore)
        self.conn.execute(LESSONS_SQL)

    @staticmethod
    def _lesson(row) -> Lesson:
        return Lesson(id=row[0], text=row[1], source=row[2], count=row[3])

    def top(self, limit: int = 10) -> list[Lesson]:
        rows = self.conn.execute(
            "SELECT id, text, source, count FROM lessons "
            "ORDER BY (source = %s) DESC, count DESC, id LIMIT %s",
            (HUMAN, limit),
        ).fetchall()
        return [self._lesson(r) for r in rows]

    def add(self, text: str, source: str) -> Lesson:
        row = self.conn.execute(
            "INSERT INTO lessons (text, source) VALUES (%s, %s) "
            "ON CONFLICT (text) DO UPDATE SET count = lessons.count + 1, updated_at = now() "
            "RETURNING id, text, source, count",
            (text, source),
        ).fetchone()
        return self._lesson(row)

    def reinforce(self, lesson_id: int) -> None:
        self.conn.execute(
            "UPDATE lessons SET count = count + 1, updated_at = now() WHERE id = %s", (lesson_id,)
        )

    def all(self) -> list[Lesson]:
        return self.top(limit=10_000)

    def delete(self, lesson_id: int) -> bool:
        return self.conn.execute("DELETE FROM lessons WHERE id = %s", (lesson_id,)).rowcount > 0


# --- Réflexion : transformer des erreurs précises en leçons générales ---

REFLECTION_PROMPT = f"""Tu améliores un rédacteur de notes de candidature aux marchés publics.
On te donne des affirmations de ses brouillons jugées NON soutenues par l'avis ou par le
profil de l'entreprise, et la liste numérotée des leçons déjà connues.

Pour chaque TYPE d'erreur (regroupe les erreurs semblables) :
- si une leçon existante la couvre déjà, renvoie son numéro : {{"existing": 3}} ;
- sinon, écris UNE nouvelle leçon : {{"new": "Ne pas ..."}}.

Une leçon est une consigne GÉNÉRALE, valable pour tous les avis : courte (25 mots maximum),
commençant par « Ne pas » ou « Toujours », sans nom de ville, d'acheteur ni de numéro d'avis.
{MAX_NEW_PER_RUN} éléments au maximum.

Réponds UNIQUEMENT avec un JSON : {{"lessons": [{{"existing": 3}}, {{"new": "Ne pas ..."}}]}}"""


def build_reflection_messages(claims: list[str], known: list[Lesson]) -> list[dict[str, str]]:
    known_block = "\n".join(f"{lesson.id}. {lesson.text}" for lesson in known) or "(aucune)"
    claims_block = "\n".join(f"- {c}" for c in claims)
    user = f"AFFIRMATIONS NON SOUTENUES :\n{claims_block}\n\nLEÇONS CONNUES :\n{known_block}"
    return [{"role": "system", "content": REFLECTION_PROMPT}, {"role": "user", "content": user}]


def parse_reflection(raw: str, known_ids: set[int]) -> tuple[list[int], list[str]]:
    """-> (leçons existantes à renforcer, nouvelles leçons). Ignore ce qui est mal formé."""
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return [], []
    try:
        items = json.loads(match.group(0)).get("lessons", [])
    except (json.JSONDecodeError, AttributeError):
        return [], []
    existing: list[int] = []
    new: list[str] = []
    for item in items[:MAX_NEW_PER_RUN] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("existing"), int) and item["existing"] in known_ids:
            existing.append(item["existing"])
        elif isinstance(item.get("new"), str):
            text = " ".join(item["new"].split())
            if MIN_CHARS <= len(text) <= MAX_CHARS:
                new.append(text)
    return existing, new


def learn_from_errors(llm, store: LessonStore, claims: list[str], context: int = 30) -> list[str]:
    """Réflexion sur les erreurs du juge. Renvoie les textes des leçons apprises ou renforcées."""
    if not claims:
        return []
    known = store.top(limit=context)
    existing, new = parse_reflection(
        llm.complete(build_reflection_messages(claims, known)), {lesson.id for lesson in known}
    )
    learned: list[str] = []
    by_id = {lesson.id: lesson for lesson in known}
    for lesson_id in existing:
        store.reinforce(lesson_id)
        learned.append(by_id[lesson_id].text)
    for text in new:
        learned.append(store.add(text, JUDGE).text)
    return learned


def format_lessons(lessons: list[str]) -> str:
    if not lessons:
        return ""
    lines = "\n".join(f"- {text}" for text in lessons)
    return f"\n\nLeçons tirées des brouillons précédents (à respecter absolument) :\n{lines}"
