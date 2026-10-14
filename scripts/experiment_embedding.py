"""Expérience : QUEL texte faut-il vectoriser pour que le bon avis ressorte ?

    python scripts/experiment_embedding.py

Pour chaque question ratée, on compare la similarité entre la question et
plusieurs versions du texte de l'avis attendu :
  A. le morceau n°0 tel qu'il est stocké (titre + en-tête de métadonnées) ;
  B. le titre seul ;
  C. le titre en minuscules (beaucoup d'avis sont écrits EN MAJUSCULES) ;
  D. le morceau n°0 sans les lignes de métadonnées (Acheteur, Procédure...).
On affiche aussi le score du 1er résultat actuel : pour que le bon avis passe
devant, il faut dépasser ce score.
Rien n'est modifié dans la base.
"""

from __future__ import annotations

import re
import sys

import numpy as np

from tenderpilot.config import get_settings
from tenderpilot.evaluation.dataset import load_questions
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.store import PgVectorStore

FAILED = ["q09", "q10", "q13", "q14", "q15", "q16", "q18", "q21", "q27"]
METADATA = re.compile(
    r"^(Objet|Acheteur|Département|Nature de l'avis|Procédure|Type de marché|"
    r"Mots-clés|Date de parution|Date limite)\s*:",
)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def without_metadata(content: str) -> str:
    lines = content.split("\n")
    return "\n".join(line for line in lines if not METADATA.match(line.strip()))


def main() -> None:
    ids = sys.argv[1:] or FAILED
    s = get_settings()
    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    store = PgVectorStore(s.database_url, dim=embedder.dim)

    gains = {"B": 0, "C": 0, "D": 0}
    total = 0
    for q in load_questions("eval/questions.jsonl"):
        if q.id not in ids or not q.expected:
            continue
        qv = embedder.embed([q.question])[0]
        top_score = store.search(qv, k=1)[0].score
        print(f"\n=== {q.id} : {q.question}")
        print(f"  score à battre (1er résultat actuel) : {top_score:.3f}")
        for notice_id in q.expected:
            row = store.conn.execute(
                "SELECT n.title, c.content FROM notices n JOIN chunks c ON c.notice_id = n.id "
                "WHERE n.id = %s AND c.chunk_index = 0",
                (notice_id,),
            ).fetchone()
            if not row:
                print(f"  {notice_id} : absent de la base")
                continue
            title, chunk0 = row
            variants = {
                "A": chunk0,
                "B": title,
                "C": title.lower(),
                "D": without_metadata(chunk0),
            }
            vectors = embedder.embed(list(variants.values()))
            scores = {name: cosine(qv, v) for name, v in zip(variants, vectors, strict=True)}
            total += 1
            for name in gains:
                gains[name] += scores[name] > scores["A"]
            line = "  ".join(f"{n}={sc:.3f}" for n, sc in scores.items())
            print(f"  {notice_id} : {line}   | {title[:60]}")

    print("\nA = morceau stocké, B = titre, C = titre en minuscules, D = morceau sans métadonnées")
    for name, n in gains.items():
        print(f"  {name} fait mieux que A pour {n}/{total} avis")
    store.close()


if __name__ == "__main__":
    main()
