"""Récupération et lecture des avis du BOAMP (données ouvertes, API Opendatasoft v2.1).

Point d'entrée de l'API :
    https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records

Chaque enregistrement contient des champs simples (objet, nomacheteur, datelimitereponse...)
et un champ `donnees` avec le détail complet de l'avis. Pour les avis européens, `donnees`
suit le format eForms : il est lu par `eforms.py`. Les autres formats passent par une
lecture générique qui écarte le bruit technique.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tenderpilot.ingestion.eforms import eforms_sections
from tenderpilot.models import Notice

BOAMP_RECORDS_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
)
PAGE_SIZE = 100  # maximum autorisé par page sur l'API Opendatasoft v2.1
PARIS = ZoneInfo("Europe/Paris")

# Pour chaque information, les noms de champs possibles (vérifiés sur l'API en octobre 2026).
FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "id": ("idweb", "id"),
    "title": ("objet",),
    "buyer": ("nomacheteur",),
    "published": ("dateparution",),
    "deadline": ("datelimitereponse",),
    "url": ("url_avis",),
    "nature": ("nature_libelle", "nature"),
    "procedure": ("procedure_libelle",),
    "market_type": ("type_marche_facette", "type_marche"),
    "descriptors": ("descripteur_libelle",),
    "department": ("code_departement",),
}

_MAX_GENERIC_LINES = 150


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
        return ", ".join(str(v) for v in value if v not in (None, "")) or None
    return str(value)


def format_deadline(value: str | None) -> str | None:
    """'2026-11-09T10:00:00+00:00' -> '09/11/2026' (jour en heure de Paris).

    On n'affiche que le jour : l'heure exacte figure dans chaque lot, telle que
    l'acheteur l'a écrite, ce qui évite d'afficher deux heures différentes.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is not None:
        moment = moment.astimezone(PARIS)
    return moment.strftime("%d/%m/%Y")


def load_donnees(raw: Any) -> Any:
    """`donnees` arrive souvent sous forme de texte JSON."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return " ".join(raw.split()) or None
    return raw


def _generic_lines(value: Any, label: str = "") -> Iterator[str]:
    """Lecture de secours pour les formats non eForms.

    On ignore les attributs (« @... »), on lit « #text », et on ne garde que les valeurs
    qui ressemblent à du texte (au moins deux mots) : les codes et identifiants partent.
    """
    if isinstance(value, dict):
        if "#text" in value:
            yield from _generic_lines(value["#text"], label)
            return
        for key, sub in value.items():
            if key.startswith("@") or key.lower() in {"xmlns", "schemalocation"}:
                continue
            yield from _generic_lines(sub, key.split(":")[-1])
    elif isinstance(value, list):
        for item in value:
            yield from _generic_lines(item, label)
    elif value not in (None, ""):
        content = " ".join(str(value).split())
        if len(content.split()) >= 2:
            yield f"{label} : {content}" if label else content


def donnees_sections(raw: Any) -> list[str]:
    """Paragraphes lisibles tirés de `donnees`."""
    donnees = load_donnees(raw)
    if donnees in (None, ""):
        return []
    sections = eforms_sections(donnees)
    if sections is not None:
        return sections
    lines: list[str] = []
    for line in _generic_lines(donnees):
        if line not in lines:
            lines.append(line)
    return ["\n".join(lines[:_MAX_GENERIC_LINES])] if lines else []


def record_to_notice(record: dict[str, Any]) -> Notice | None:
    """Convertit un enregistrement BOAMP en Notice. Renvoie None s'il manque l'essentiel."""
    notice_id = _as_text(_first(record, "id"))
    title = _as_text(_first(record, "title"))
    if not notice_id or not title:
        return None

    buyer = _as_text(_first(record, "buyer"))
    published = _as_text(_first(record, "published"))
    deadline = _as_text(_first(record, "deadline"))
    is_correction = str(record.get("etat", "")).upper() == "RECTIFICATIF"
    nature = _as_text(_first(record, "nature"))
    if nature and is_correction:
        nature += " (rectificatif)"

    def line(label: str, value: str | None) -> str | None:
        return f"{label} : {value}" if value else None

    department = _as_text(_first(record, "department"))
    header = [
        line("Objet", title),
        line("Acheteur", buyer),
        line("Département", department),
        line("Nature de l'avis", nature),
        line("Procédure", _as_text(_first(record, "procedure"))),
        line("Type de marché", _as_text(_first(record, "market_type"))),
        line("Mots-clés", _as_text(_first(record, "descriptors"))),
        line("Date de parution", published),
        line("Date limite de réponse", format_deadline(deadline)),
    ]
    paragraphs = ["\n".join(h for h in header if h)] + donnees_sections(record.get("donnees"))

    replaces = [str(i) for i in (record.get("annonce_lie") or []) if i] if is_correction else []
    return Notice(
        id=notice_id,
        title=title,
        text="\n\n".join(p for p in paragraphs if p),
        buyer=buyer,
        published=published,
        deadline=deadline,
        url=_as_text(_first(record, "url")),
        raw=record,
        replaces=[r for r in replaces if r != notice_id],
    )


def prepare_notices(records: list[dict[str, Any]]) -> tuple[list[Notice], int]:
    """Convertit un lot d'enregistrements en avis prêts à indexer.

    - les avis sont triés du plus ancien au plus récent, pour qu'un rectificatif
      passe toujours après l'avis qu'il corrige ;
    - un avis remplacé par un rectificatif présent dans le même lot est écarté.

    Renvoie (avis à indexer, nombre d'enregistrements ignorés).
    """
    notices = [n for n in (record_to_notice(r) for r in records) if n is not None]
    skipped = len(records) - len(notices)
    replaced = {old for n in notices for old in n.replaces}
    kept = [n for n in notices if n.id not in replaced]
    skipped += len(notices) - len(kept)
    kept.sort(key=lambda n: n.published or "")
    return kept, skipped


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
