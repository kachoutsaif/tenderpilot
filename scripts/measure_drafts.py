"""Mesurer si la mémoire de leçons améliore les brouillons (protocole entraînement / test).

    python scripts/lessons.py clear                                         # partir de zéro
    python scripts/measure_drafts.py --set test  --memory off   --label sans_memoire
    python scripts/measure_drafts.py --set train --memory learn --label apprentissage
    python scripts/measure_drafts.py --set test  --memory use   --label avec_memoire

On compare « sans_memoire » et « avec_memoire » sur les MÊMES avis de test, que l'agent
n'a jamais vus pendant l'apprentissage (comme un jeu de test en machine learning).
L'indicateur principal est la fidélité du PREMIER brouillon, avant toute révision.

Pour une comparaison équitable, l'extraction des exigences est mise en cache
(out/cache/) : les deux conditions rédigent à partir des mêmes exigences.
La décision est forcée à GO pour toujours obtenir un brouillon.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from statistics import mean

from tenderpilot.agent.extraction import Requirements, extract_requirements
from tenderpilot.agent.graph import build_agent
from tenderpilot.agent.memory import PgLessonStore
from tenderpilot.agent.profile import load_profile
from tenderpilot.config import get_settings
from tenderpilot.rag.llm import OpenAICompatibleLLM
from tenderpilot.store import PgVectorStore

# avis de nettoyage de la base du 14/10, répartis en deux groupes disjoints
SETS = {
    "train": ["26-98400", "26-98454", "26-98934"],
    "test": ["26-98391", "26-98519", "26-99151"],
}
CACHE = Path("out/cache")


def cached_extract(llm, title: str, text: str) -> Requirements:
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    path = CACHE / f"{key}.json"
    if path.exists():
        return Requirements.model_validate_json(path.read_text(encoding="utf-8"))
    requirements = extract_requirements(llm, title, text)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(requirements.model_dump_json(indent=2), encoding="utf-8")
    return requirements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=list(SETS), default="test")
    parser.add_argument("--ids", nargs="*", help="remplace la liste d'avis du --set")
    parser.add_argument("--memory", choices=["off", "use", "learn"], default="off")
    parser.add_argument("--label", required=True)
    parser.add_argument("--repeat", type=int, default=1, help="lancements par avis (variance)")
    parser.add_argument("--pause", type=float, default=15, help="secondes entre deux avis")
    parser.add_argument("--profile", default="profiles/exemple_proprete.toml")
    args = parser.parse_args()

    from langgraph.types import Command

    s = get_settings()
    store = PgVectorStore(s.database_url, dim=1)
    options = {"reasoning_effort": "low"} if "gpt-oss" in s.llm_model else {}
    llm = OpenAICompatibleLLM(
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        model=s.llm_model,
        max_tokens=4000,
        **options,
    )
    lessons = PgLessonStore(store.conn) if args.memory != "off" else None
    agent = build_agent(
        store,
        llm,
        load_profile(args.profile),
        lessons=lessons,
        learn=args.memory == "learn",
        extract_fn=cached_extract,
    )

    ids = args.ids or SETS[args.set]
    print(f"{len(ids)} avis × {args.repeat}, mémoire « {args.memory} », « {args.label} »")
    rows = []
    for notice_id in ids:
        for run in range(args.repeat):
            config = {"configurable": {"thread_id": f"{notice_id}-{uuid.uuid4().hex[:8]}"}}
            state = agent.invoke({"notice_id": notice_id}, config)
            if state.get("error"):
                print(f"  {notice_id} : {state['error']}")
                break
            state = agent.invoke(Command(resume={"decision": "GO"}), config)
            history = state["draft_history"]
            row = {
                "notice_id": notice_id,
                "run": run + 1,
                "first_faithfulness": history[0]["faithfulness"],
                "first_unsupported": history[0]["unsupported"],
                "final_faithfulness": history[-1]["faithfulness"],
                "revisions": state.get("revisions", 0),
                "lessons_used": len(state.get("lessons_used", [])),
                "lessons_learned": state.get("lessons_learned", []),
            }
            rows.append(row)
            print(
                f"  {notice_id} #{run + 1} : 1er jet {row['first_faithfulness']:.0%} "
                f"({len(row['first_unsupported'])} non soutenue(s)), final "
                f"{row['final_faithfulness']:.0%}, révisions {row['revisions']}, "
                f"leçons utilisées {row['lessons_used']}"
            )
            for text in row["lessons_learned"]:
                print(f"      leçon : {text}")
            time.sleep(args.pause)  # limite de tokens par minute de l'offre gratuite

    if rows:
        summary = {
            "avis": len(rows),
            "fidelite_1er_jet": round(mean(r["first_faithfulness"] for r in rows), 3),
            "non_soutenues_1er_jet": round(mean(len(r["first_unsupported"]) for r in rows), 2),
            "fidelite_finale": round(mean(r["final_faithfulness"] for r in rows), 3),
            "part_revisee": round(mean(r["revisions"] > 0 for r in rows), 3),
        }
        print("\n" + "  ".join(f"{k} = {v}" for k, v in summary.items()))
        out = Path("eval/results") / f"{datetime.now():%Y%m%d-%H%M}_drafts_{args.label}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"label": args.label, "memory": args.memory, "summary": summary, "rows": rows}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Détail : {out}")
    store.close()


if __name__ == "__main__":
    main()
