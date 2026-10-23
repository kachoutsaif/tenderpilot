"""Lots et modifications d'un avis, lus SANS LLM dans le texte produit par le lecteur eForms.

Constat sur l'avis réel 26-98519 (Maubeuge) : le marché a 2 lots et c'est un rectificatif
(date limite reportée, pièces modifiées). Ces informations étaient bien dans notre texte,
mais l'extraction par LLM n'avait pas de case pour elles : elles étaient perdues.

Comme notre lecteur eForms écrit ces informations dans un format fixe (« Lot 2 : titre »,
« Modification : ... »), une lecture déterministe suffit : fiable, gratuite, testable.
Principe du projet : ce qui peut être une règle ne doit pas être confié au LLM.
"""

from __future__ import annotations

import re

_LOT = re.compile(r"^Lot\s+(\S+)\s*:\s*(.+)$")
_FIELDS = {
    "Durée": "duree",
    "Date limite de remise des offres": "date_limite",
    "Adapté aux PME": "pme",
}


def parse_lots(text: str) -> list[dict[str, str]]:
    """Un dict par lot : numero, titre, et si présents duree, date_limite, pme."""
    lots: list[dict[str, str]] = []
    for paragraph in text.split("\n\n"):
        lines = [line.strip() for line in paragraph.strip().splitlines() if line.strip()]
        match = _LOT.match(lines[0]) if lines else None
        if not match:
            continue
        lot = {"numero": match.group(1), "titre": match.group(2)}
        for line in lines[1:]:
            label, _, value = line.partition(" : ")
            if label in _FIELDS and value:
                lot[_FIELDS[label]] = value
        if lot["numero"] not in {existing["numero"] for existing in lots}:
            lots.append(lot)
    return lots


def parse_modifications(text: str) -> list[str]:
    """Les modifications annoncées par un avis rectificatif."""
    prefix = "Modification : "
    return [
        line.strip()[len(prefix) :] for line in text.splitlines() if line.strip().startswith(prefix)
    ]


def lot_lines(lots: list[dict[str, str]]) -> list[str]:
    """Une ligne lisible par lot, pour le rédacteur et le rapport."""
    lines = []
    for lot in lots:
        details = [f"durée : {lot['duree']}"] if lot.get("duree") else []
        if lot.get("date_limite"):
            details.append(f"date limite : {lot['date_limite']}")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"Lot {lot['numero']} : {lot['titre']}{suffix}")
    return lines


def find_lot(lots: list[dict[str, str]], wanted: str) -> dict[str, str] | None:
    """Le lot demandé : « 1 », « Lot 1 », « lot 01 » désignent tous le lot numéro 1."""

    def key(value: str) -> str:
        value = re.sub(r"(?i)^\s*lot\s*", "", str(value)).strip()
        return value.lstrip("0") or "0" if value.isdigit() else value.upper()

    return next((lot for lot in lots if key(lot["numero"]) == key(wanted)), None)
