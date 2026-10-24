"""Corpus d'évaluation figé : les avis nécessaires pour évaluer la recherche dans la CI.

Pourquoi un corpus figé ? La CI démarre sur une machine vide, sans notre base. Et une porte
qualité exige un score REPRODUCTIBLE : même code + mêmes données = même score. Si les données
changeaient à chaque lancement (nouveaux avis BOAMP), une baisse du score pourrait venir
des données et non du code, et la porte bloquerait des modifications sans raison.

Ce qu'on enregistre : le texte produit par NOTRE lecteur d'avis (pas l'enregistrement BOAMP
brut), plus quelques champs utiles. Deux raisons :
- l'enregistrement brut contient les noms et coordonnées d'agents publics : notre lecteur
  les écarte, et ce fichier sera publié sur GitHub ;
- il est environ deux fois plus petit (les données eForms brutes sont verbeuses).
Masquage : les avis contiennent parfois des courriels et des téléphones dans leur texte
libre (constaté le 24/10 : 24 avis sur 240). Ils sont remplacés par [courriel] et
[téléphone] avant l'écriture du fichier. Effet négligeable sur la recherche : personne ne
cherche un marché par l'adresse électronique de l'acheteur.
Conséquence à connaître : une modification du lecteur d'avis (ingestion/) n'est pas
mesurée par cette évaluation. Il faudra alors régénérer le corpus.

Format : JSON Lines, un avis par ligne, triés par identifiant (diffs git lisibles).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tenderpilot.models import Notice

# Champs de l'enregistrement BOAMP conservés : ceux que le code utilise (filtre par
# département, rectificatif, mots-clés du contrôle de secteur).
KEPT_RAW_FIELDS = ("code_departement", "etat", "descripteur_libelle", "idweb")


EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
# numéros français : 03 27 53 75 00, 03.27.53.75.00, 0327537500, +33 3 27 53 75 00
PHONE = re.compile(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")


def redact(text: str) -> str:
    """Masque courriels et numéros de téléphone (données personnelles possibles)."""
    return PHONE.sub("[téléphone]", EMAIL.sub("[courriel]", text))


def notice_to_line(notice: Notice) -> dict[str, Any]:
    return {
        "id": notice.id,
        "title": notice.title,
        "buyer": notice.buyer,
        "published": notice.published,
        "deadline": notice.deadline,
        "url": notice.url,
        "raw": {key: notice.raw[key] for key in KEPT_RAW_FIELDS if key in notice.raw},
        "text": redact(notice.text),
    }


def line_to_notice(data: dict[str, Any]) -> Notice:
    return Notice(
        id=data["id"],
        title=data["title"],
        text=data["text"],
        buyer=data.get("buyer"),
        published=data.get("published"),
        deadline=data.get("deadline"),
        url=data.get("url"),
        raw=data.get("raw") or {},
        # pas de « replaces » : chaque avis du corpus est déjà la version à jour
    )


def save_corpus(notices: Iterable[Notice], path: str | Path) -> int:
    """Écrit le corpus (trié, sans doublon). Renvoie le nombre d'avis."""
    unique = {n.id: n for n in notices}
    lines = [
        json.dumps(notice_to_line(unique[i]), ensure_ascii=False, sort_keys=True)
        for i in sorted(unique)
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def load_corpus(path: str | Path) -> list[Notice]:
    text = Path(path).read_text(encoding="utf-8")
    return [line_to_notice(json.loads(line)) for line in text.splitlines() if line.strip()]
