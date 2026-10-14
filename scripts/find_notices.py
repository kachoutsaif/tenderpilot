"""Aide pour construire le jeu d'évaluation : trouver les avis qui parlent d'un sujet.

    python scripts/find_notices.py nettoyage
    python scripts/find_notices.py "maintenance" "informatique"

Cherche les avis dont le texte contient TOUS les mots donnés (sans tenir compte des
majuscules). Vérifiez ensuite chaque avis sur boamp.fr avant de l'ajouter comme réponse
attendue : c'est vous qui garantissez la vérité de référence.
"""

from __future__ import annotations

import sys

from tenderpilot.config import get_settings
from tenderpilot.store import PgVectorStore


def main() -> None:
    words = sys.argv[1:]
    if not words:
        sys.exit('Usage : python scripts/find_notices.py mot1 ["mot 2" ...]')
    s = get_settings()
    store = PgVectorStore(s.database_url, dim=1)  # la dimension n'est pas utilisée ici
    rows = store.search_text(words)
    print(f"{len(rows)} avis contiennent : {', '.join(words)}\n")
    for r in rows:
        title = (r["title"] or "")[:80]
        print(f"  {r['id']:<10} {title:<80} | {r['buyer'] or ''}")
        print(f"             https://www.boamp.fr/pages/avis/?q=idweb:{r['id']}")
    store.close()


if __name__ == "__main__":
    main()
