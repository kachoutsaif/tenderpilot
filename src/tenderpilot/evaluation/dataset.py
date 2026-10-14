"""Jeu d'évaluation : une question par ligne, au format JSON Lines (.jsonl).

Exemple de ligne :
{"id": "q01", "question": "...", "expected": ["26-98309"], "kind": "recherche", "notes": "..."}

- expected : identifiants (idweb) des avis qui DOIVENT être retrouvés ;
             liste vide pour une question hors sujet.
- kind     : recherche | liste | filtre | hors_sujet (pour analyser les résultats par type).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("recherche", "liste", "filtre", "hors_sujet")


@dataclass
class EvalQuestion:
    id: str
    question: str
    expected: list[str] = field(default_factory=list)
    kind: str = "recherche"
    notes: str = ""


def load_questions(path: str | Path) -> list[EvalQuestion]:
    questions: list[EvalQuestion] = []
    ids: set[str] = set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Ligne {number} : JSON invalide ({exc.msg})") from exc
        q = EvalQuestion(
            id=str(data["id"]),
            question=data["question"],
            expected=[str(x) for x in data.get("expected", [])],
            kind=data.get("kind", "recherche"),
            notes=data.get("notes", ""),
        )
        if q.kind not in KINDS:
            raise ValueError(f"Ligne {number} : kind '{q.kind}' inconnu (attendu : {KINDS})")
        if q.id in ids:
            raise ValueError(f"Ligne {number} : identifiant '{q.id}' en double")
        if q.kind != "hors_sujet" and not q.expected:
            raise ValueError(f"Ligne {number} : 'expected' est vide pour une question {q.kind}")
        ids.add(q.id)
        questions.append(q)
    return questions
