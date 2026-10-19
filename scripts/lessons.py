"""Voir et gérer la mémoire de leçons de l'agent.

    python scripts/lessons.py                       # liste
    python scripts/lessons.py add "Ne pas promettre de délai d'intervention"
    python scripts/lessons.py delete 4
    python scripts/lessons.py clear                 # tout effacer (demande confirmation)

Une mauvaise leçon peut dégrader l'agent : relisez-les régulièrement.
"""

from __future__ import annotations

import sys

from tenderpilot.agent.memory import HUMAN, PgLessonStore
from tenderpilot.config import get_settings
from tenderpilot.store import PgVectorStore


def main() -> None:
    args = sys.argv[1:]
    store = PgVectorStore(get_settings().database_url, dim=1)
    lessons = PgLessonStore(store.conn)

    if not args or args[0] == "list":
        rows = lessons.all()
        print(f"{len(rows)} leçon(s), dans l'ordre où elles sont injectées dans le prompt :\n")
        for lesson in rows:
            print(f"  [{lesson.id:>3}] ×{lesson.count:<3} ({lesson.source:<6}) {lesson.text}")
    elif args[0] == "add" and len(args) == 2:
        lesson = lessons.add(args[1], HUMAN)
        print(f"Leçon {lesson.id} enregistrée (×{lesson.count}).")
    elif args[0] == "delete" and len(args) == 2:
        print("Supprimée." if lessons.delete(int(args[1])) else "Aucune leçon avec ce numéro.")
    elif args[0] == "clear":
        if input("Effacer TOUTES les leçons ? [oui/non] ").strip().lower() == "oui":
            store.conn.execute("DELETE FROM lessons")
            print("Mémoire vidée.")
    else:
        sys.exit(__doc__)
    store.close()


if __name__ == "__main__":
    main()
