"""Récupération et lecture des avis du BOAMP (données ouvertes, API Opendatasoft v2.1).

Point d'entrée de l'API :
    https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records

IMPORTANT : les noms de champs utilisés ici (objet, nomacheteur, datelimitereponse...)
sont ceux habituellement exposés par le jeu de données. Lancez d'abord
`python scripts/inspect_boamp.py` pour voir les vrais champs, et ajustez
FIELD_CANDIDATES si besoin. Le code est défensif : un champ absent ne casse rien.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from tenderpilot.models import Notice

BOAMP_RECORDS_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
)
PAGE_SIZE = 100  # maximum autorisé par page sur l'API Opendatasoft v2.1

# Pour chaque information, les noms de champs possibles, du plus probable au moins probable.
FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "id": ("idweb", "id", "reference"),
    "title": ("objet", "titre", "intitule"),
    "buyer": ("nomacheteur", "acheteur", "nom_acheteur"),
    "published": ("dateparution", "date_parution"),
    "deadline": ("datelimitereponse", "date_limite_reponse", "datefindiffusion"),
    "url": ("url_avis", "url"),
    "nature": ("nature_libelle", "nature"),
    "market_type": ("type_marche", "type_marche_facette"),
    "descriptors": ("descripteur_libelle", "descripteur"),
}

# Clés de `donnees` qui n'apportent rien au texte (identifiants techniques, balises...).
_SKIP_KEYS = {"@xmlns", "xmlns", "schemaLocation", "@version"}
_MAX_DETAIL_LINES = 400


def _first(record: dict[str, Any], key: str) -> Any:
    for name in FIELD_CANDIDATES[key]:
        value = record.get(name)
        if value not in (None, "", []):
            return value
    return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    return str(value)


def _flatten(value: Any, path: str = "") -> Iterator[str]:
    """Transforme le JSON imbriqué de `donnees` en lignes « chemin : valeur »."""
    if isinstance(value, dict):
        for key, sub in value.items():
            if key in _SKIP_KEYS:
                continue
            yield from _flatten(sub, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for item in value:
            yield from _flatten(item, path)
    elif value not in (None, ""):
        text = " ".join(str(value).split())
        if text:
            label = path.rsplit(".", 2)[-2:]  # garde les 2 derniers niveaux, plus lisible
            yield f"{' > '.join(label)} : {text}"


def parse_donnees(raw: Any) -> list[str]:
    """`donnees` contient le détail complet de l'avis, en JSON (souvent sous forme de texte)."""
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return [" ".join(raw.split())]
    lines = list(_flatten(raw))
    return lines[:_MAX_DETAIL_LINES]


def record_to_notice(record: dict[str, Any]) -> Notice | None:
    """Convertit un enregistrement BOAMP en Notice. Renvoie None s'il manque l'essentiel."""
    notice_id = _as_text(_first(record, "id"))
    title = _as_text(_first(record, "title"))
    if not notice_id or not title:
        return None

    buyer = _as_text(_first(record, "buyer"))
    published = _as_text(_first(record, "published"))
    deadline = _as_text(_first(record, "deadline"))
    header = [
        f"Objet : {title}",
        f"Acheteur : {buyer}" if buyer else None,
        f"Nature de l'avis : {_as_text(_first(record, 'nature'))}"
        if _first(record, "nature")
        else None,
        f"Type de marché : {_as_text(_first(record, 'market_type'))}"
        if _first(record, "market_type")
        else None,
        f"Mots-clés : {_as_text(_first(record, 'descriptors'))}"
        if _first(record, "descriptors")
        else None,
        f"Date de parution : {published}" if published else None,
        f"Date limite de réponse : {deadline}" if deadline else None,
    ]
    details = parse_donnees(record.get("donnees"))
    text = "\n".join(line for line in header if line)
    if details:
        text += "\n\nDétails de l'avis :\n" + "\n".join(details)

    return Notice(
        id=notice_id,
        title=title,
        text=text,
        buyer=buyer,
        published=published,
        deadline=deadline,
        url=_as_text(_first(record, "url")),
        raw=record,
    )


def fetch_records(
    where: str | None = None,
    limit: int = 50,
    order_by: str = "dateparution desc",
    timeout: float = 30.0,
) -> Iterator[dict[str, Any]]:
    """Récupère jusqu'à `limit` enregistrements, page par page."""
    import httpx  # import local : les tests de parsing n'ont pas besoin du réseau

    fetched = 0
    with httpx.Client(timeout=timeout) as client:
        while fetched < limit:
            params: dict[str, Any] = {
                "limit": min(PAGE_SIZE, limit - fetched),
                "offset": fetched,
                "order_by": order_by,
            }
            if where:
                params["where"] = where
            response = client.get(BOAMP_RECORDS_URL, params=params)
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                return
            yield from results
            fetched += len(results)


def load_records_from_file(path: str) -> list[dict[str, Any]]:
    """Charge des enregistrements depuis un fichier JSON (réponse API ou liste)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["results"] if isinstance(data, dict) else data
