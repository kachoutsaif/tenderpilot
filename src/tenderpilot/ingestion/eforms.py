"""Lecture des avis au format eForms (standard européen des marchés publics).

Dans le BOAMP, le champ `donnees` des avis européens contient le XML eForms converti
en JSON : les attributs deviennent des clés « @... », le texte d'un élément est sous
« #text », et un élément répété devient une liste.

Plutôt que d'aplatir tout l'arbre (ce qui produit beaucoup de bruit technique :
codes, identifiants, attributs), on va chercher les informations utiles à une PME :
objet, description, lots, CPV, durée, critères d'attribution, montants, modifications
et titulaires.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

NOTICE_KINDS = ("ContractNotice", "ContractAwardNotice", "PriorInformationNotice")

CRITERION_TYPE = {"price": "Prix", "cost": "Coût", "quality": "Qualité"}
DURATION_UNIT = {"DAY": "jours", "WEEK": "semaines", "MONTH": "mois", "YEAR": "ans"}


# --- Petits outils de navigation dans l'arbre ---------------------------------


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def text(node: Any) -> str | None:
    """Texte d'un élément : chaîne directe, ou valeur de « #text »."""
    if isinstance(node, dict):
        node = node.get("#text")
    if node is None or isinstance(node, (dict, list)):
        return None
    value = " ".join(str(node).split())
    return value or None


def find_all(node: Any, key: str) -> Iterator[Any]:
    """Toutes les valeurs de `key`, à n'importe quelle profondeur."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield from as_list(v)
            yield from find_all(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from find_all(item, key)


def find_first(node: Any, key: str) -> Any:
    return next(find_all(node, key), None)


def first_text(node: Any, key: str) -> str | None:
    for value in find_all(node, key):
        if (t := text(value)) is not None:
            return t
    return None


def _attr(node: Any, name: str) -> str | None:
    return node.get(name) if isinstance(node, dict) else None


def _amount(node: Any) -> str | None:
    value = text(node)
    if value is None:
        return None
    try:
        number = f"{float(value):,.0f}".replace(",", " ")
    except ValueError:
        number = value
    currency = _attr(node, "@currencyID") or ""
    return f"{number} {currency}".strip()


def _unique(values: list[str | None]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return seen


# --- Extraction ------------------------------------------------------------------


def notice_root(donnees: Any) -> tuple[str, dict] | None:
    """Renvoie (type d'avis, nœud racine) si `donnees` est un avis eForms."""
    if not isinstance(donnees, dict) or not isinstance(donnees.get("EFORMS"), dict):
        return None
    for kind in NOTICE_KINDS:
        root = donnees["EFORMS"].get(kind)
        if isinstance(root, dict):
            return kind, root
    return None


def _organizations(root: dict) -> dict[str, dict[str, str | None]]:
    orgs: dict[str, dict[str, str | None]] = {}
    for org in find_all(root.get("ext:UBLExtensions"), "efac:Organization"):
        company = org.get("efac:Company") if isinstance(org, dict) else None
        if not isinstance(company, dict):
            continue
        org_id = first_text(company.get("cac:PartyIdentification"), "cbc:ID")
        if org_id:
            address = company.get("cac:PostalAddress")
            address = address if isinstance(address, dict) else {}
            orgs[org_id] = {
                "name": first_text(company.get("cac:PartyName"), "cbc:Name"),
                "city": text(address.get("cbc:CityName")),
                "postal": text(address.get("cbc:PostalZone")),
            }
    return orgs


def _criteria(node: Any) -> str | None:
    parts = []
    for crit in find_all(node, "cac:SubordinateAwardingCriterion"):
        label = first_text(crit, "cbc:Description")
        kind = CRITERION_TYPE.get(first_text(crit, "cbc:AwardingCriterionTypeCode") or "")
        name = label or kind
        if not name:
            continue
        weight = first_text(crit, "efbc:ParameterNumeric")
        code = first_text(crit, "efbc:ParameterCode") or ""
        if weight:
            unit = " %" if code.startswith("per") else " pts"
            name = f"{name} ({weight}{unit})"
        parts.append(name)
    return " ; ".join(_unique(parts)) or None


def _duration(node: Any) -> str | None:
    measure = find_first(find_first(node, "cac:PlannedPeriod"), "cbc:DurationMeasure")
    value = text(measure)
    if not value:
        return None
    unit = DURATION_UNIT.get(_attr(measure, "@unitCode") or "", (_attr(measure, "@unitCode") or ""))
    return f"{value} {unit}".strip()


def _deadline(node: Any) -> str | None:
    """Date et heure telles qu'écrites par l'acheteur (heure locale, sans conversion)."""
    period = find_first(node, "cac:TenderSubmissionDeadlinePeriod")
    date = first_text(period, "cbc:EndDate")
    hour = first_text(period, "cbc:EndTime")
    if not date or len(date) < 10:
        return None
    day = f"{date[8:10]}/{date[5:7]}/{date[:4]}"
    return f"{day} à {hour[:5]}" if hour else day


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.casefold() == b.casefold()


def _project_lines(project: Any, parent: Any = None) -> list[str]:
    """Lignes d'un objet de marché (global ou lot).

    Pour un lot, `parent` est l'objet global : on n'y répète pas ce qui est identique.
    """
    if not isinstance(project, dict):
        return []
    parent = parent if isinstance(parent, dict) else {}
    lines: list[str] = []
    name = text(project.get("cbc:Name"))
    description = text(project.get("cbc:Description"))
    if (
        description
        and not _same(description, name)
        and not _same(description, text(parent.get("cbc:Description")))
    ):
        lines.append(f"Description : {description}")
    cpv = _unique([text(c) for c in find_all(project, "cbc:ItemClassificationCode")])
    parent_cpv = _unique([text(c) for c in find_all(parent, "cbc:ItemClassificationCode")])
    if cpv and cpv != parent_cpv:
        lines.append(f"Codes CPV : {', '.join(cpv)}")
    amount = _amount(find_first(project, "cbc:EstimatedOverallContractAmount"))
    if amount:
        lines.append(f"Montant estimé : {amount}")
    duration = _duration(project)
    if duration:
        lines.append(f"Durée : {duration}")
    city = first_text(find_first(project, "cac:RealizedLocation"), "cbc:CityName")
    if city:
        lines.append(f"Lieu d'exécution : {city}")
    sme = text(project.get("cbc:SMESuitableIndicator"))
    if sme == "true":
        lines.append("Adapté aux PME : oui")
    return lines


def eforms_sections(donnees: Any) -> list[str] | None:
    """Texte lisible d'un avis eForms, en paragraphes. None si ce n'est pas de l'eForms."""
    found = notice_root(donnees)
    if found is None:
        return None
    kind, root = found
    orgs = _organizations(root)
    sections: list[str] = []

    # 1. Vue d'ensemble
    overview: list[str] = []
    buyer_id = first_text(root.get("cac:ContractingParty"), "cbc:ID")
    buyer = orgs.get(buyer_id or "", {})
    if buyer.get("city"):
        parts = _unique([buyer.get("postal"), buyer.get("city")])
        overview.append(f"Localisation de l'acheteur : {' '.join(parts)}")
    overview += _project_lines(root.get("cac:ProcurementProject"))
    lots = [lot for lot in as_list(root.get("cac:ProcurementProjectLot")) if isinstance(lot, dict)]
    if len(lots) > 1:
        overview.append(f"Nombre de lots : {len(lots)}")
    if overview:
        sections.append("\n".join(overview))

    # 2. Modifications (avis rectificatif)
    changes = _unique(
        [text(c) for c in find_all(root.get("ext:UBLExtensions"), "efbc:ChangeDescription")]
        + [text(c) for c in find_all(root.get("ext:UBLExtensions"), "efbc:ReasonDescription")]
    )
    if changes:
        sections.append("\n".join(f"Modification : {c}" for c in changes))

    # 3. Un paragraphe par lot
    main_project = root.get("cac:ProcurementProject")
    main_name = text(main_project.get("cbc:Name")) if isinstance(main_project, dict) else None
    for number, lot in enumerate(lots, start=1):
        project = lot.get("cac:ProcurementProject")
        title = text(project.get("cbc:Name")) if isinstance(project, dict) else None
        if len(lots) == 1 and _same(title, main_name):
            header = "Conditions du marché"
        else:
            header = f"Lot {number}" + (f" : {title}" if title else "")
        lines = [header] + _project_lines(project, parent=main_project)
        criteria = _criteria(lot.get("cac:TenderingTerms"))
        if criteria:
            lines.append(f"Critères d'attribution : {criteria}")
        deadline = _deadline(lot.get("cac:TenderingProcess"))
        if deadline:
            lines.append(f"Date limite de remise des offres : {deadline}")
        documents = first_text(lot.get("cac:TenderingTerms"), "cbc:URI")
        if documents:
            lines.append(f"Documents de la consultation : {documents}")
        sections.append("\n".join(lines))

    # 4. Résultat (avis d'attribution)
    if kind == "ContractAwardNotice":
        ext = root.get("ext:UBLExtensions")
        result: list[str] = []
        total = _amount(find_first(find_first(ext, "efac:NoticeResult"), "cbc:TotalAmount"))
        if total:
            result.append(f"Montant total attribué : {total}")
        winners = _unique(
            [
                orgs.get(first_text(t, "cbc:ID") or "", {}).get("name")
                for t in find_all(ext, "efac:Tenderer")
            ]
        )
        if winners:
            result.append(f"Titulaire(s) : {', '.join(winners)}")
        offers = first_text(ext, "efbc:StatisticsNumeric")
        if offers:
            result.append(f"Nombre d'offres reçues : {offers}")
        if result:
            sections.append("Résultat du marché\n" + "\n".join(result))

    return sections
