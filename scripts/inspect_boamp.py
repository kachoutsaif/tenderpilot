"""Étape 1 : regarder à quoi ressemblent les vraies données BOAMP.

    python scripts/inspect_boamp.py
    python scripts/inspect_boamp.py --where 'dateparution >= "2026-10-01"' --save data/sample.json

Affiche les champs d'un avis réel, leur type et un exemple de valeur.
Si un nom de champ diffère de FIELD_CANDIDATES (src/tenderpilot/ingestion/boamp.py),
ajoutez-le dans la liste correspondante.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from tenderpilot.ingestion.boamp import fetch_records, record_to_notice


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--where", default=None, help="filtre ODSQL, ex. 'dateparution >= \"2026-10-01\"'"
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--save", default=None, help="enregistre les avis bruts en JSON")
    args = parser.parse_args()

    records = list(fetch_records(where=args.where, limit=args.limit))
    print(f"{len(records)} avis récupérés\n")
    if not records:
        return

    print("Champs du premier avis :")
    for key, value in records[0].items():
        preview = json.dumps(value, ensure_ascii=False, default=str)[:90]
        print(f"  {key:<28} {type(value).__name__:<6} {preview}")

    for field in ("nature", "nature_libelle", "type_marche"):
        if field in records[0]:
            print(f"\nValeurs de '{field}' :", Counter(str(r.get(field)) for r in records))

    notice = record_to_notice(records[0])
    print("\nTexte construit pour le premier avis :\n")
    print(notice.text[:1500] if notice else "!! Aucun avis construit : vérifiez FIELD_CANDIDATES")

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(json.dumps(records, ensure_ascii=False, indent=2), "utf-8")
        print(f"\nAvis enregistrés dans {args.save}")


if __name__ == "__main__":
    main()
