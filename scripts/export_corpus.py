"""Semaine 4 : exporter le corpus figé qui servira à évaluer la recherche dans la CI.

    python scripts/export_corpus.py                 # avis attendus + 200 avis « bruit »
    python scripts/export_corpus.py --noise 300

Contenu du corpus (eval/corpus.jsonl) :
- les avis ATTENDUS par les questions d'évaluation (sinon on ne peut pas les retrouver) ;
- des avis « BRUIT », choisis de façon déterministe : sans eux, la recherche serait trop
  facile (avec 10 avis, le bon est presque toujours dans les 5 premiers).

Le choix des avis bruit est déterministe (tri par empreinte md5 de l'identifiant) :
relancer le script sur la même base donne exactement le même fichier.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tenderpilot.config import get_settings
from tenderpilot.evaluation.corpus import save_corpus
from tenderpilot.evaluation.dataset import load_questions
from tenderpilot.store import PgVectorStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="eval/questions.jsonl")
    parser.add_argument("--out", default="eval/corpus.jsonl")
    parser.add_argument("--noise", type=int, default=200, help="nombre d'avis bruit")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    expected = sorted({i for q in questions for i in q.expected})
    store = PgVectorStore(get_settings().database_url, dim=1)  # aucune recherche ici

    notices, missing = [], []
    for notice_id in expected:
        notice = store.get_notice(notice_id)
        if notice:
            notices.append(notice)
        else:
            missing.append(notice_id)

    rows = store.conn.execute(
        "SELECT id FROM notices WHERE NOT (id = ANY(%s)) ORDER BY md5(id) LIMIT %s",
        (expected, args.noise),
    ).fetchall()
    noise = [n for n in (store.get_notice(r[0]) for r in rows) if n]
    total, _ = store.count()
    store.close()

    count = save_corpus(notices + noise, args.out)
    size_kb = Path(args.out).stat().st_size / 1024
    print(f"{len(questions)} questions, {len(expected)} avis attendus")
    print(f"  trouvés dans la base : {len(notices)}")
    print(f"  avis bruit           : {len(noise)} (sur {total} avis en base)")
    print(f"Corpus : {args.out}, {count} avis, {size_kb:.0f} Ko")
    if missing:
        print(f"\nATTENTION : avis attendus absents de la base : {', '.join(missing)}")
        print("Les questions correspondantes seront forcément ratées : corrigez-les ou ingérez")
        print("ces avis (scripts/ingest_boamp.py) avant de publier le corpus.")


if __name__ == "__main__":
    main()
