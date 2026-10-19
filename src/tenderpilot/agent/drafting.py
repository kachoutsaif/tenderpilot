"""Rédaction d'un brouillon de note de candidature, après validation humaine."""

from __future__ import annotations

import re

from tenderpilot.agent.extraction import Requirements
from tenderpilot.agent.memory import format_lessons
from tenderpilot.agent.profile import CompanyProfile
from tenderpilot.models import RetrievedChunk

TO_COMPLETE = "[À COMPLÉTER]"

DRAFT_PROMPT = f"""Tu aides une PME à préparer sa réponse à un appel d'offres public.
Rédige en français un BROUILLON de note de candidature, en Markdown, avec ces sections :

## 1. Compréhension du besoin (objet et CONTEXTE)
## 2. Réponse aux exigences (une ligne par EXIGENCE À TRAITER : exigence -> notre réponse)
## 3. Références similaires
## 4. Points à vérifier avant de répondre
## 5. Pièces à préparer (liste usuelle, à confirmer avec le DCE)

Règles strictes (ce brouillon sera vérifié automatiquement) :
- Section 1 : reformule UNIQUEMENT l'objet et le CONTEXTE fournis. N'ajoute aucune attente,
  fréquence, reconduction, prestation ou obligation qui n'y figure pas.
- Le CONTEXTE (lieu, durée, montant) ne se traite qu'en section 1 : n'écris AUCUNE phrase
  de capacité, d'engagement ou de disponibilité à son sujet (« nous assurerons sur 48 mois »,
  « nos équipes interviendront sur le site »...).
- Section 2 : uniquement les EXIGENCES À TRAITER. S'il n'y en a aucune, écris « Aucune
  exigence de capacité dans l'avis : à vérifier dans le DCE. »
- Sections 2 et 3 : chaque affirmation sur l'entreprise doit venir du PROFIL fourni.
  Pour tout ce que le profil ne dit pas (méthodes, moyens, produits, organisation,
  engagements), écris {TO_COMPLETE} suivi de ce qu'il faut décrire.
  Exemple : « {TO_COMPLETE} décrire les produits utilisés et leur écolabel ».
- N'invente aucun chiffre, aucune certification, aucune référence, aucun nom.
- Section 4 : reprends tous les contrôles « ko », « inconnu » et « a_verifier »."""


def _profile_block(profile: CompanyProfile) -> str:
    lines = [f"Nom : {profile.nom}", f"Activité : {profile.description}"]
    if profile.chiffre_affaires is not None:
        lines.append(f"Chiffre d'affaires : {profile.chiffre_affaires:,.0f} €".replace(",", " "))
    if profile.effectif is not None:
        lines.append(f"Effectif : {profile.effectif} personnes")
    zone = ", ".join(profile.departements) or "toute la France"
    lines.append(f"Zone d'intervention (départements) : {zone}")
    lines.append(f"Certifications : {', '.join(profile.certifications) or 'aucune'}")
    for ref in profile.references:
        details = []
        if ref.annee:
            details.append(str(ref.annee))
        if ref.montant:
            details.append(f"{ref.montant:,.0f} €".replace(",", " "))
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"Référence : {ref.titre}{suffix}")
    return "\n".join(lines)


# Informations de cadrage : à reformuler, pas à « répondre ». Les présenter comme des
# exigences poussait le rédacteur à inventer une réponse (« nous nous engageons sur 48 mois »).
CONTEXT_FIELDS = ("lieu_execution", "duree", "montant_estime")


def _requirements_block(requirements: Requirements) -> str:
    verified = [(name, item) for name, item in requirements.items() if item.verified]
    context = [f"- {n} : {i.value}" for n, i in verified if n in CONTEXT_FIELDS]
    to_answer = [f"- {n} : {i.value}" for n, i in verified if n not in CONTEXT_FIELDS]
    return "\n".join(
        [f"Objet : {requirements.resume}", "CONTEXTE :", *(context or ["(aucun)"])]
        + ["EXIGENCES À TRAITER :", *(to_answer or ["(aucune)"])]
    )


def build_draft_messages(
    title: str,
    requirements: Requirements,
    profile: CompanyProfile,
    checks: list[dict],
    decision: str,
    comment: str = "",
    lessons: list[str] | None = None,
) -> list[dict[str, str]]:
    checks_block = "\n".join(f"- {c['name']} : {c['status']} ({c['detail']})" for c in checks)
    user = (
        f"AVIS : {title}\n\nEXIGENCES VÉRIFIÉES :\n{_requirements_block(requirements)}\n\n"
        f"PROFIL DE L'ENTREPRISE :\n{_profile_block(profile)}\n\n"
        f"CONTRÔLES :\n{checks_block}\n\nDÉCISION VALIDÉE : {decision}"
    )
    if comment:
        user += f"\nCOMMENTAIRE DU VALIDEUR : {comment}"
    system = DRAFT_PROMPT + format_lessons(lessons or [])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# --- Vérification automatique du brouillon (réutilise le juge de la semaine 2) ---

_SECTION_4 = re.compile(r"^#+\s*4\.", flags=re.MULTILINE)
_TO_COMPLETE_SPAN = re.compile(r"\[À COMPLÉTER\][^\n|]*")


def claims_part(draft: str) -> str:
    """Les sections 1 à 3 seulement, sans les « [À COMPLÉTER] ».

    Les sections 4 et 5 reprennent les contrôles et une liste de pièces usuelles :
    ce ne sont pas des affirmations sur l'avis ou sur l'entreprise.
    """
    match = _SECTION_4.search(draft)
    head = draft[: match.start()] if match else draft
    return _TO_COMPLETE_SPAN.sub("", head)


def draft_sources(requirements: Requirements, profile: CompanyProfile) -> list[RetrievedChunk]:
    """Ce que le rédacteur avait le droit d'utiliser : les exigences et le profil."""
    return [
        RetrievedChunk("avis", 0, _requirements_block(requirements), 1.0, "Exigences de l'avis"),
        RetrievedChunk("profil", 0, _profile_block(profile), 1.0, "Profil de l'entreprise"),
    ]


def check_draft(llm, draft: str, requirements: Requirements, profile: CompanyProfile) -> dict:
    """Fidélité du brouillon : part des affirmations soutenues par l'avis ou le profil."""
    from tenderpilot.evaluation.judge import judge_answer

    verdict = judge_answer(
        llm, "Note de candidature", claims_part(draft), draft_sources(requirements, profile)
    )
    return {"faithfulness": verdict.faithfulness, "unsupported": verdict.unsupported}


REVISION_PROMPT = f"""Tu corriges un brouillon de note de candidature.
Un vérificateur a trouvé des affirmations NON soutenues par l'avis ou par le profil.
Réécris le brouillon COMPLET, identique, sauf pour ces affirmations : supprime-les, ou
remplace-les par {TO_COMPLETE} suivi de ce que l'entreprise doit décrire.
Ne change rien d'autre et n'ajoute aucune nouvelle information."""


def build_revision_messages(draft: str, unsupported: list[str]) -> list[dict[str, str]]:
    claims = "\n".join(f"- {c}" for c in unsupported)
    user = f"AFFIRMATIONS NON SOUTENUES :\n{claims}\n\nBROUILLON :\n{draft}"
    return [{"role": "system", "content": REVISION_PROMPT}, {"role": "user", "content": user}]
