"""Le graphe de l'agent (LangGraph).

    charger ──► extraire ──► qualifier ──► validation humaine ──► rédiger ──► vérifier ──► fin
                                                                               ▲          │
                                                                réviser ◄──────┘ (si affirmations
                                                                (1 fois max)       non soutenues)
       │                                          │
       └── avis introuvable ──► fin               └── NO-GO confirmé ──► fin

La validation humaine utilise `interrupt()` : le graphe s'arrête, son état est
sauvegardé par le checkpointer, et il reprend quand l'humain répond
(`graph.invoke(Command(resume=...), config)`). Rien n'est rédigé sans accord humain.
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, Protocol, TypedDict

from tenderpilot.agent.drafting import build_draft_messages, build_revision_messages, check_draft
from tenderpilot.agent.extraction import (
    Requirements,
    extract_requirements,
    grounding_rate,
    normalize,
)
from tenderpilot.agent.profile import CompanyProfile
from tenderpilot.agent.rules import (
    DECISIONS,
    GO,
    NO_GO,
    PARIS,
    TO_STUDY,
    notice_departments,
    qualify,
)
from tenderpilot.models import Notice


class NoticeStore(Protocol):
    def get_notice(self, notice_id: str) -> Notice | None: ...


class AgentState(TypedDict, total=False):
    notice_id: str
    notice: dict[str, Any]
    requirements: dict[str, Any]
    grounding: float | None
    decision: str  # décision proposée par les règles
    checks: list[dict[str, Any]]
    review: dict[str, Any]  # réponse de l'humain : {"decision": ..., "comment": ...}
    draft: str
    draft_check: dict[str, Any]  # dernière vérification du brouillon (juge LLM)
    # toutes les vérifications successives : operator.add AJOUTE au lieu de remplacer
    draft_history: Annotated[list[dict[str, Any]], operator.add]
    revisions: int
    error: str


def notice_to_dict(notice: Notice) -> dict[str, Any]:
    keywords = notice.raw.get("descripteur_libelle") or []
    return {
        "id": notice.id,
        "title": notice.title,
        "text": notice.text,
        "buyer": notice.buyer,
        "deadline": notice.deadline,
        "url": notice.url,
        "departments": notice_departments(notice.raw),
        "keywords": keywords if isinstance(keywords, list) else [keywords],
    }


_ALIASES = {
    "GO": GO,
    "A_ETUDIER": TO_STUDY,
    "ETUDIER": TO_STUDY,
    "NO_GO": NO_GO,
    "NOGO": NO_GO,
}


def parse_review(answer: Any, proposed: str) -> dict[str, str]:
    """Réponse humaine -> {"decision", "comment"}. Accepte un dict ou un simple texte.

    Une réponse vide ou « ok » valide la décision proposée par les règles.
    """
    if isinstance(answer, dict):
        decision = str(answer.get("decision") or proposed)
        comment = str(answer.get("comment") or "")
    else:
        text = str(answer or "").strip()
        decision = proposed if text.lower() in ("", "ok", "oui", "o", "y") else text
        comment = ""
    key = normalize(decision).upper().replace("-", "_").replace(" ", "_")
    if key not in _ALIASES:
        raise ValueError(f"Décision inconnue : {decision!r} (choix : {', '.join(DECISIONS)})")
    return {"decision": _ALIASES[key], "comment": comment}


def build_agent(
    store: NoticeStore,
    llm,
    profile: CompanyProfile,
    today=None,
    checkpointer=None,
    max_revisions: int = 1,
):
    """Construit et compile le graphe. `today` est remplaçable pour les tests."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    def charger(state: AgentState) -> dict:
        notice = store.get_notice(state["notice_id"])
        if notice is None:
            return {"error": f"Avis {state['notice_id']} introuvable dans la base"}
        return {"notice": notice_to_dict(notice)}

    def extraire(state: AgentState) -> dict:
        notice = state["notice"]
        requirements = extract_requirements(llm, notice["title"], notice["text"])
        return {
            "requirements": requirements.model_dump(),
            "grounding": grounding_rate(requirements),
        }

    def qualifier(state: AgentState) -> dict:
        requirements = Requirements.model_validate(state["requirements"])
        day = today or datetime.now(PARIS).date()
        decision, checks = qualify(state["notice"], requirements, profile, day)
        return {"decision": decision, "checks": [c.to_dict() for c in checks]}

    def validation_humaine(state: AgentState) -> dict:
        # le graphe s'arrête ici ; la valeur passée à Command(resume=...) devient `answer`
        answer = interrupt(
            {
                "notice_id": state["notice"]["id"],
                "title": state["notice"]["title"],
                "decision": state["decision"],
                "checks": state["checks"],
            }
        )
        return {"review": parse_review(answer, state["decision"])}

    def rediger(state: AgentState) -> dict:
        messages = build_draft_messages(
            state["notice"]["title"],
            Requirements.model_validate(state["requirements"]),
            profile,
            state["checks"],
            state["review"]["decision"],
            state["review"].get("comment", ""),
        )
        return {"draft": llm.complete(messages), "revisions": 0}

    def verifier_brouillon(state: AgentState) -> dict:
        requirements = Requirements.model_validate(state["requirements"])
        check = check_draft(llm, state["draft"], requirements, profile)
        return {"draft_check": check, "draft_history": [check]}

    def reviser(state: AgentState) -> dict:
        messages = build_revision_messages(state["draft"], state["draft_check"]["unsupported"])
        return {"draft": llm.complete(messages), "revisions": state.get("revisions", 0) + 1}

    def after_check(state: AgentState) -> str:
        """Boucle d'auto-correction, bornée : on ne révise pas indéfiniment."""
        if state["draft_check"]["unsupported"] and state.get("revisions", 0) < max_revisions:
            return "reviser"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("charger", charger)
    graph.add_node("extraire", extraire)
    graph.add_node("qualifier", qualifier)
    graph.add_node("validation_humaine", validation_humaine)
    graph.add_node("rediger", rediger)
    graph.add_node("verifier_brouillon", verifier_brouillon)
    graph.add_node("reviser", reviser)

    graph.add_edge(START, "charger")
    graph.add_conditional_edges(
        "charger", lambda s: END if s.get("error") else "extraire", ["extraire", END]
    )
    graph.add_edge("extraire", "qualifier")
    graph.add_edge("qualifier", "validation_humaine")
    graph.add_conditional_edges(
        "validation_humaine",
        lambda s: END if s["review"]["decision"] == NO_GO else "rediger",
        ["rediger", END],
    )
    graph.add_edge("rediger", "verifier_brouillon")
    graph.add_conditional_edges("verifier_brouillon", after_check, ["reviser", END])
    graph.add_edge("reviser", "verifier_brouillon")
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
