"""Mise en forme du résultat de l'agent : console et rapport Markdown."""

from __future__ import annotations

from tenderpilot.agent.extraction import Requirements
from tenderpilot.agent.structure import lot_lines

LABELS = {"GO": "GO", "A_ETUDIER": "À ÉTUDIER", "NO_GO": "NO-GO"}
STATUS = {"ok": "OK", "ko": "KO", "inconnu": "??", "a_verifier": "À VÉRIFIER"}


def checks_lines(checks: list[dict]) -> list[str]:
    lines = []
    for c in checks:
        flag = " (bloquant)" if c["status"] == "ko" and c.get("blocking") else ""
        lines.append(f"[{STATUS.get(c['status'], c['status'])}] {c['name']} : {c['detail']}{flag}")
    return lines


def notice_facts_lines(notice: dict) -> list[str]:
    """Lots et modifications (rectificatif), lus sans LLM dans le texte de l'avis."""
    out: list[str] = []
    if notice.get("lots"):
        out += ["", f"## Lots ({len(notice['lots'])})", ""]
        out += [f"- {line}" for line in lot_lines(notice["lots"])]
    if notice.get("modifications"):
        out += ["", "## Avis rectifié : modifications", ""]
        out += [f"- {change}" for change in notice["modifications"]]
    return out


def requirements_lines(requirements: dict) -> list[str]:
    req = Requirements.model_validate(requirements)
    lines = [f"Résumé : {req.resume}"] if req.resume else []
    for name, item in req.items():
        mark = "preuve vérifiée" if item.verified else "PREUVE NON RETROUVÉE (ignorée)"
        lines.append(f"- {name} : {item.value}  [{mark}]")
        if item.quote:
            lines.append(f"    « {item.quote[:200]} »")
    return lines


def to_markdown(state: dict) -> str:
    notice = state.get("notice", {})
    out = [f"# {notice.get('title', state.get('notice_id'))}", ""]
    out += [f"- Avis : {notice.get('id')}", f"- Acheteur : {notice.get('buyer') or '-'}"]
    if notice.get("url"):
        out.append(f"- Lien : {notice['url']}")
    out += ["", f"## Décision proposée par les règles : {LABELS.get(state.get('decision'), '-')}"]
    out += ["", *[f"- {line}" for line in checks_lines(state.get("checks", []))]]
    out += notice_facts_lines(notice)
    review = state.get("review")
    if review:
        out += ["", f"## Décision validée par l'humain : {LABELS[review['decision']]}"]
        if review.get("lot"):
            out.append(f"Réponse limitée au lot : {review['lot']}")
        if review.get("comment"):
            out.append(f"Commentaire : {review['comment']}")
    if state.get("requirements"):
        grounding = state.get("grounding")
        rate = "-" if grounding is None else f"{grounding:.0%}"
        out += ["", f"## Exigences extraites (preuves retrouvées : {rate})", ""]
        out += requirements_lines(state["requirements"])
    check = state.get("draft_check")
    if check:
        history = state.get("draft_history") or [check]
        steps = " → ".join(f"{h['faithfulness']:.0%}" for h in history)
        revisions = state.get("revisions", 0)
        suffix = f" (après {revisions} révision)" if revisions else ""
        out += ["", f"## Contrôle du brouillon : fidélité {steps}{suffix}", ""]
        if check["unsupported"]:
            out.append("Affirmations NON soutenues par l'avis ou le profil (à corriger) :")
            out += [f"- {claim}" for claim in check["unsupported"]]
        else:
            out.append("Toutes les affirmations vérifiées sont soutenues par l'avis ou le profil.")
    if state.get("lessons_used"):
        out += ["", "## Leçons utilisées pour la rédaction", ""]
        out += [f"- {text}" for text in state["lessons_used"]]
    if state.get("lessons_learned"):
        out += ["", "## Leçons apprises ou renforcées à l'issue de cet avis", ""]
        out += [f"- {text}" for text in state["lessons_learned"]]
    if state.get("draft"):
        out += ["", "---", "", "# Brouillon de note de candidature", "", state["draft"]]
    return "\n".join(out) + "\n"
