"""Semaine 3 : l'agent qualifie un avis pour une PME, avec validation humaine.

    python scripts/qualify.py 26-98519
    python scripts/qualify.py 26-98519 --profile profiles/exemple_proprete.toml
    python scripts/qualify.py 26-98519 --yes      # accepte la décision des règles sans demander

Étapes : charger l'avis -> extraire les exigences (LLM, preuves vérifiées) -> qualifier
(règles) -> VOUS validez -> rédiger un brouillon (LLM), vérifié automatiquement par un
juge LLM. Le rapport est enregistré dans out/<avis>.md.
"""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from tenderpilot.agent.graph import build_agent, parse_review
from tenderpilot.agent.memory import PgLessonStore
from tenderpilot.agent.profile import load_profile
from tenderpilot.agent.report import LABELS, checks_lines, requirements_lines, to_markdown
from tenderpilot.config import get_settings
from tenderpilot.rag.llm import OpenAICompatibleLLM
from tenderpilot.store import PgVectorStore


def ask_human(payload: dict, state: dict) -> dict:
    print(f"\n=== {payload['notice_id']} : {payload['title']}")
    print("\nExigences extraites :")
    for line in requirements_lines(state.get("requirements", {})):
        print(f"  {line}")
    print("\nContrôles :")
    for line in checks_lines(payload["checks"]):
        print(f"  {line}")
    proposed = payload["decision"]
    print(f"\nDécision proposée par les règles : {LABELS[proposed]}")
    while True:
        answer = input("Valider ? [Entrée = oui, ou tapez GO / A_ETUDIER / NO_GO] : ")
        try:
            review = parse_review(answer, proposed)
            break
        except ValueError as exc:
            print(f"  {exc}")
    review["comment"] = input("Commentaire pour CE brouillon (facultatif) : ").strip()
    review["lesson"] = input(
        "Leçon à retenir pour TOUS les prochains brouillons (facultatif) : "
    ).strip()
    return review


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("notice_id")
    parser.add_argument("--profile", default="profiles/exemple_proprete.toml")
    parser.add_argument("--yes", action="store_true", help="valide la décision sans demander")
    parser.add_argument(
        "--memory",
        choices=["learn", "use", "off"],
        default="learn",
        help="learn : utilise et enrichit les leçons ; use : les utilise seulement ; off : aucune",
    )
    args = parser.parse_args()

    from langgraph.types import Command

    s = get_settings()
    profile = load_profile(args.profile)
    store = PgVectorStore(s.database_url, dim=1)  # pas de recherche vectorielle ici
    options = {"reasoning_effort": "low"} if "gpt-oss" in s.llm_model else {}
    llm = OpenAICompatibleLLM(
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        model=s.llm_model,
        max_tokens=4000,  # l'extraction JSON et le brouillon sont plus longs qu'une réponse
        **options,
    )
    lessons = PgLessonStore(store.conn) if args.memory != "off" else None
    agent = build_agent(store, llm, profile, lessons=lessons, learn=args.memory == "learn")
    config = {"configurable": {"thread_id": f"{args.notice_id}-{uuid.uuid4().hex[:8]}"}}

    print(f"Profil : {profile.nom}. Analyse de l'avis {args.notice_id}...")
    state = agent.invoke({"notice_id": args.notice_id}, config)
    if state.get("error"):
        store.close()
        raise SystemExit(state["error"])

    if "__interrupt__" in state:  # le graphe attend la validation humaine
        payload = state["__interrupt__"][0].value
        if args.yes:
            review = {"decision": payload["decision"], "comment": ""}
        else:
            review = ask_human(payload, state)
        print("Rédaction..." if review["decision"] != "NO_GO" else "Arrêt : NO-GO confirmé.")
        state = agent.invoke(Command(resume=review), config)

    check = state.get("draft_check")
    if check:
        steps = " → ".join(f"{h['faithfulness']:.0%}" for h in state.get("draft_history", []))
        print(f"\nContrôle du brouillon : fidélité {steps or format(check['faithfulness'], '.0%')}")
        for claim in check["unsupported"]:
            print(f"  NON SOUTENU (restant) : {claim}")

    if state.get("lessons_used"):
        print(f"Leçons utilisées : {len(state['lessons_used'])}")
    for text in state.get("lessons_learned", []):
        print(f"  LEÇON retenue : {text}")

    out = Path("out") / f"{args.notice_id}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(to_markdown(state), encoding="utf-8")
    print(f"\nRapport enregistré : {out}")
    store.close()


if __name__ == "__main__":
    main()
