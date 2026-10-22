"""La logique des outils MCP, sans dépendance au protocole MCP.

Séparer « ce que fait l'outil » (ici) de « comment il est exposé » (mcp/server.py)
permet de tester les outils comme des fonctions Python ordinaires, avec de faux objets,
sans lancer de serveur.

Coût en tokens de chaque outil (quota Groq) :
    rechercher_avis, lire_avis, lister_lecons, ajouter_lecon    0 appel LLM
    qualifier_avis                                              0 (ou 1 avec extraction)
    rediger_brouillon                                           3 à 6 appels LLM
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from tenderpilot.agent.cache import make_cached_extract
from tenderpilot.agent.extraction import Requirements, extract_requirements
from tenderpilot.agent.graph import build_agent, notice_to_dict, parse_review
from tenderpilot.agent.memory import HUMAN, LessonStore
from tenderpilot.agent.profile import CompanyProfile
from tenderpilot.agent.rules import NO_GO, PARIS, qualify
from tenderpilot.agent.structure import lot_lines
from tenderpilot.rag.retrieval import retrieve

MAX_TEXT_CHARS = 8_000  # un avis complet peut être long : on borne ce qu'on renvoie au client


class TenderTools:
    def __init__(
        self,
        store,
        profile: CompanyProfile,
        lessons: LessonStore | None,
        embedder_factory,
        llm_factory,
        retrieval_mode: str = "hybrid",
        use_cache: bool = True,
    ):
        self.store = store
        self.profile = profile
        self.lessons = lessons
        # le modèle d'embedding (250 Mo) et le client LLM ne sont créés qu'au premier besoin
        self._embedder_factory = embedder_factory
        self._llm_factory = llm_factory
        self._embedder = None
        self._llm = None
        self.retrieval_mode = retrieval_mode
        self.extract_fn = make_cached_extract() if use_cache else extract_requirements

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = self._embedder_factory()
        return self._embedder

    @property
    def llm(self):
        if self._llm is None:
            self._llm = self._llm_factory()
        return self._llm

    # --- Lecture (aucun appel LLM) ---

    def rechercher_avis(self, question: str, k: int = 5) -> list[dict[str, Any]]:
        chunks = retrieve(question, self.embedder, self.store, k=k * 3, mode=self.retrieval_mode)
        results: dict[str, dict[str, Any]] = {}
        for c in chunks:  # plusieurs morceaux d'un même avis : on garde le mieux classé
            if c.notice_id not in results:
                results[c.notice_id] = {
                    "avis": c.notice_id,
                    "titre": c.title,
                    "extrait": c.content[:300],
                    "url": c.url,
                }
        return list(results.values())[:k]

    def lire_avis(self, notice_id: str) -> dict[str, Any]:
        notice = self.store.get_notice(notice_id)
        if notice is None:
            return {"erreur": f"Avis {notice_id} introuvable dans la base"}
        text = notice.text
        return {
            "avis": notice.id,
            "titre": notice.title,
            "acheteur": notice.buyer,
            "date_limite": notice.deadline,
            "url": notice.url,
            "texte": text[:MAX_TEXT_CHARS],
            "tronque": len(text) > MAX_TEXT_CHARS,
        }

    def qualifier_avis(self, notice_id: str, extraire_exigences: bool = False) -> dict[str, Any]:
        notice = self.store.get_notice(notice_id)
        if notice is None:
            return {"erreur": f"Avis {notice_id} introuvable dans la base"}
        data = notice_to_dict(notice)
        requirements = (
            self.extract_fn(self.llm, data["title"], data["text"])
            if extraire_exigences
            else Requirements()
        )
        decision, checks = qualify(data, requirements, self.profile, datetime.now(PARIS).date())
        out: dict[str, Any] = {
            "avis": notice.id,
            "titre": notice.title,
            "decision_proposee": decision,
            "controles": [c.to_dict() for c in checks],
            "lots": lot_lines(data["lots"]),
            "modifications": data["modifications"],
            "note": "Décision proposée par des règles : elle doit être validée par un humain.",
        }
        if extraire_exigences:
            out["exigences"] = [
                {
                    "champ": name,
                    "valeur": item.value,
                    "preuve": item.quote,
                    "verifiee": item.verified,
                }
                for name, item in requirements.items()
            ]
        return out

    # --- Mémoire de leçons (aucun appel LLM) ---

    def lister_lecons(self) -> list[dict[str, Any]]:
        if self.lessons is None:
            return []
        return [
            {"id": x.id, "texte": x.text, "source": x.source, "compteur": x.count}
            for x in self.lessons.all()
        ]

    def ajouter_lecon(self, texte: str) -> dict[str, Any]:
        texte = " ".join(texte.split())
        if self.lessons is None:
            return {"erreur": "Mémoire de leçons désactivée"}
        if not 10 <= len(texte) <= 250:
            return {"erreur": "Une leçon doit faire entre 10 et 250 caractères"}
        lesson = self.lessons.add(texte, HUMAN)
        return {"id": lesson.id, "texte": lesson.text, "compteur": lesson.count}

    # --- Action (appels LLM) : seulement après accord humain ---

    def rediger_brouillon(
        self, notice_id: str, decision_validee: str, commentaire: str = ""
    ) -> dict[str, Any]:
        review = parse_review({"decision": decision_validee, "comment": commentaire}, NO_GO)
        if review["decision"] == NO_GO:
            return {"avis": notice_id, "message": "Décision NO-GO : aucun brouillon rédigé."}
        from langgraph.types import Command

        agent = build_agent(
            self.store,
            self.llm,
            self.profile,
            lessons=self.lessons,
            learn=False,  # depuis MCP, la mémoire est lue mais jamais modifiée automatiquement
            extract_fn=self.extract_fn,
        )
        config = {"configurable": {"thread_id": f"mcp-{notice_id}-{uuid.uuid4().hex[:8]}"}}
        state = agent.invoke({"notice_id": notice_id}, config)
        if state.get("error"):
            return {"erreur": state["error"]}
        # la validation humaine a déjà eu lieu dans la conversation : on reprend le graphe
        state = agent.invoke(Command(resume=review), config)
        history = state.get("draft_history", [])
        return {
            "avis": notice_id,
            "decision_validee": review["decision"],
            "fidelite": [round(h["faithfulness"], 2) for h in history],
            "affirmations_non_soutenues_restantes": state["draft_check"]["unsupported"],
            "brouillon": state["draft"],
        }
