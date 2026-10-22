"""Qualification GO / À ÉTUDIER / NO-GO par des règles explicites (pas par le LLM).

Pourquoi des règles plutôt qu'un LLM pour décider ?
- la décision est reproductible : même avis + même profil = même décision ;
- elle est explicable : chaque contrôle donne son statut et sa raison ;
- elle est testable sans appel à une API.
Le LLM ne sert qu'à LIRE l'avis (extraction des exigences, avec preuves vérifiées).

Chaque contrôle renvoie « ok », « ko », « inconnu » ou « a_verifier ». Un « ko » bloquant
donne NO-GO ; un « ko » non bloquant ou un « inconnu » donne À ÉTUDIER ; sinon GO.
« a_verifier » ne change pas la décision mais doit apparaître dans les points à vérifier :
c'est le cas des exigences absentes de l'avis, souvent écrites seulement dans le DCE.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from tenderpilot.agent.extraction import Requirements, normalize
from tenderpilot.agent.profile import CompanyProfile

GO, TO_STUDY, NO_GO = "GO", "A_ETUDIER", "NO_GO"
DECISIONS = (GO, TO_STUDY, NO_GO)
PARIS = ZoneInfo("Europe/Paris")


@dataclass
class Check:
    name: str
    status: str  # "ok" | "ko" | "inconnu" | "a_verifier"
    detail: str
    blocking: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# --- Lecture des données de l'avis ---


def notice_departments(raw: dict) -> list[str]:
    value = raw.get("code_departement")
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else [value]
    return [str(v).strip() for v in values if str(v).strip()]


def deadline_date(value: str | None) -> date | None:
    """Date limite en heure de Paris, depuis le format ISO de l'API.

    '2026-11-09T12:00:00+01:00' -> date(2026, 11, 9)
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(PARIS)
    return moment.date()


def parse_amount(text: str) -> float | None:
    """'300 000 euros' -> 300000 ; '1,5 M€' -> 1500000 ; '200 k€' -> 200000."""
    t = normalize(text).replace("€", " eur")
    match = re.search(r"(\d[\d .]*(?:,\d+)?)\s*(millions?|m(?:€|eur|\b)|k(?:€|eur|\b))?", t)
    if not match:
        return None
    number = match.group(1).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        amount = float(number)
    except ValueError:
        return None
    unit = (match.group(2) or "").strip()
    if unit.startswith("m"):
        amount *= 1_000_000
    elif unit.startswith("k"):
        amount *= 1_000
    return amount


# --- Les contrôles ---


def check_activity(title: str, keywords: list[str], profile: CompanyProfile) -> Check:
    haystack = normalize(" ".join([title, *keywords]))
    found = [a for a in profile.activites if normalize(a) in haystack]
    if found:
        return Check("secteur", "ok", f"Correspond à l'activité : {', '.join(found)}")
    return Check(
        "secteur", "ko", "Aucune activité du profil dans l'objet ni les mots-clés", blocking=True
    )


def check_zone(departments: list[str], profile: CompanyProfile) -> Check:
    if not profile.departements:
        return Check("zone", "ok", "Le profil couvre toute la France")
    if not departments:
        return Check("zone", "inconnu", "Département non renseigné dans l'avis")
    inside = [d for d in departments if d in profile.departements]
    if inside:
        return Check("zone", "ok", f"Département {', '.join(inside)} dans la zone d'intervention")
    return Check("zone", "ko", f"Département {', '.join(departments)} hors zone d'intervention")


def check_deadline(deadline: date | None, profile: CompanyProfile, today: date) -> Check:
    if deadline is None:
        return Check("delai", "inconnu", "Date limite non trouvée")
    days = (deadline - today).days
    if days < 0:
        return Check("delai", "ko", f"Date limite dépassée ({deadline:%d/%m/%Y})", blocking=True)
    if days < profile.delai_minimum_jours:
        return Check(
            "delai",
            "ko",
            f"Seulement {days} jour(s) pour répondre (minimum souhaité : "
            f"{profile.delai_minimum_jours})",
        )
    return Check("delai", "ok", f"{days} jours pour répondre (jusqu'au {deadline:%d/%m/%Y})")


def check_turnover(requirements: Requirements, profile: CompanyProfile) -> Check:
    item = requirements.chiffre_affaires_min
    if item is None or not item.verified:
        return Check(
            "chiffre_affaires", "a_verifier", "Aucun seuil dans l'avis : à vérifier au DCE"
        )
    required = parse_amount(item.value) or parse_amount(item.quote)
    if required is None or profile.chiffre_affaires is None:
        return Check("chiffre_affaires", "inconnu", f"Seuil exigé non comparable : {item.value}")
    if profile.chiffre_affaires >= required:
        return Check(
            "chiffre_affaires",
            "ok",
            f"CA {profile.chiffre_affaires:,.0f} € ≥ seuil {required:,.0f} €".replace(",", " "),
        )
    return Check(
        "chiffre_affaires",
        "ko",
        f"CA {profile.chiffre_affaires:,.0f} € < seuil {required:,.0f} €".replace(",", " "),
        blocking=True,
    )


def check_certifications(requirements: Requirements, profile: CompanyProfile) -> Check:
    required = [item for item in requirements.certifications if item.verified]
    if not required:
        return Check(
            "certifications", "a_verifier", "Aucune certification dans l'avis : à vérifier au DCE"
        )
    owned = [normalize(c) for c in profile.certifications]
    missing = [
        item.value
        for item in required
        if not any(c in normalize(item.value) or normalize(item.value) in c for c in owned)
    ]
    if missing:
        detail = f"Certification(s) manquante(s) : {'; '.join(missing)}"
        return Check("certifications", "ko", detail)
    return Check("certifications", "ok", "Toutes les certifications exigées sont détenues")


def check_correction(notice: dict) -> Check:
    """Un avis rectifié n'empêche pas de répondre, mais la PME doit relire ce qui a changé."""
    changes = notice.get("modifications", [])
    if notice.get("rectificatif") or changes:
        detail = "Avis rectifié : " + ("; ".join(changes[:3]) if changes else "voir l'avis")
        return Check("rectificatif", "a_verifier", detail)
    return Check("rectificatif", "ok", "Avis initial, non rectifié")


def qualify(
    notice: dict, requirements: Requirements, profile: CompanyProfile, today: date
) -> tuple[str, list[Check]]:
    """Applique tous les contrôles et renvoie (décision, contrôles)."""
    checks = [
        check_activity(notice["title"], notice.get("keywords", []), profile),
        check_zone(notice.get("departments", []), profile),
        check_deadline(deadline_date(notice.get("deadline")), profile, today),
        check_turnover(requirements, profile),
        check_certifications(requirements, profile),
        check_correction(notice),
    ]
    if any(c.status == "ko" and c.blocking for c in checks):
        return NO_GO, checks
    if any(c.status in ("ko", "inconnu") for c in checks):
        return TO_STUDY, checks
    return GO, checks
