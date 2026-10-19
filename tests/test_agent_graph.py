"""Le graphe LangGraph complet, avec l'interruption pour la validation humaine."""

import json
from datetime import date

import pytest

pytest.importorskip("langgraph")

from langgraph.types import Command  # noqa: E402

from tenderpilot.agent.graph import build_agent  # noqa: E402
from tenderpilot.agent.memory import HUMAN, InMemoryLessonStore, Lesson  # noqa: E402
from tenderpilot.agent.profile import CompanyProfile  # noqa: E402
from tenderpilot.ingestion.boamp import record_to_notice  # noqa: E402

EXTRACTION = json.dumps(
    {
        "resume": "Nettoyage de 3 bâtiments",
        "chiffre_affaires_min": {
            "value": "300 000 euros",
            "quote": "Chiffre d'affaires annuel minimum de 300 000 euros",
        },
    }
)


class SequenceLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


class NoticeStore:
    def __init__(self, records):
        self.notices = {n.id: n for n in map(record_to_notice, records) if n}

    def get_notice(self, notice_id):
        return self.notices.get(notice_id)


@pytest.fixture
def agent_parts(sample_records):
    profile = CompanyProfile(nom="Test", activites=["nettoyage"], chiffre_affaires=1_000_000)
    judge = '{"claims": [{"claim": "Nettoyage de 3 bâtiments", "supported": true}]}'
    llm = SequenceLLM(EXTRACTION, "## 1. Compréhension du besoin\nBrouillon.", judge)
    agent = build_agent(NoticeStore(sample_records), llm, profile, today=date(2026, 10, 20))
    return agent, llm


def test_le_graphe_s_arrete_pour_la_validation_humaine(agent_parts):
    agent, llm = agent_parts
    config = {"configurable": {"thread_id": "t1"}}
    state = agent.invoke({"notice_id": "TEST-0001"}, config)
    assert "__interrupt__" in state
    payload = state["__interrupt__"][0].value
    assert payload["decision"] == "GO"
    assert "draft" not in state and len(llm.calls) == 1  # rien n'est rédigé avant l'accord

    state = agent.invoke(Command(resume={"decision": "GO", "comment": "allons-y"}), config)
    assert state["draft"].startswith("## 1.")
    assert state["review"] == {"decision": "GO", "comment": "allons-y"}
    assert "allons-y" in llm.calls[1][1]["content"]
    assert state["draft_check"] == {"faithfulness": 1.0, "unsupported": []}


def test_no_go_humain_arrete_le_graphe(agent_parts):
    agent, llm = agent_parts
    config = {"configurable": {"thread_id": "t2"}}
    agent.invoke({"notice_id": "TEST-0001"}, config)
    state = agent.invoke(Command(resume="NO_GO"), config)
    assert state["review"]["decision"] == "NO_GO"
    assert "draft" not in state and len(llm.calls) == 1


def test_avis_introuvable(agent_parts):
    agent, llm = agent_parts
    state = agent.invoke({"notice_id": "INCONNU"}, {"configurable": {"thread_id": "t3"}})
    assert "introuvable" in state["error"]
    assert not llm.calls


def test_brouillon_non_fidele_revise_une_fois(sample_records):
    profile = CompanyProfile(nom="Test", activites=["nettoyage"], chiffre_affaires=1_000_000)
    bad = '{"claims": [{"claim": "Reporting mensuel", "supported": false}]}'
    good = '{"claims": [{"claim": "Nettoyage", "supported": true}]}'
    llm = SequenceLLM(EXTRACTION, "## 1. Besoin\nReporting mensuel.", bad, "## 1. Besoin\n.", good)
    agent = build_agent(NoticeStore(sample_records), llm, profile, today=date(2026, 10, 20))
    config = {"configurable": {"thread_id": "t4"}}
    agent.invoke({"notice_id": "TEST-0001"}, config)
    state = agent.invoke(Command(resume="GO"), config)

    assert state["revisions"] == 1
    assert [h["faithfulness"] for h in state["draft_history"]] == [0.0, 1.0]
    assert "Reporting mensuel" in llm.calls[3][1]["content"]  # la révision reçoit la liste
    assert len(llm.calls) == 5


def test_revisions_bornees(sample_records):
    profile = CompanyProfile(nom="Test", activites=["nettoyage"], chiffre_affaires=1_000_000)
    bad = '{"claims": [{"claim": "X", "supported": false}]}'
    llm = SequenceLLM(EXTRACTION, "brouillon", bad, "brouillon 2", bad)
    agent = build_agent(NoticeStore(sample_records), llm, profile, today=date(2026, 10, 20))
    config = {"configurable": {"thread_id": "t5"}}
    agent.invoke({"notice_id": "TEST-0001"}, config)
    state = agent.invoke(Command(resume="GO"), config)
    assert state["revisions"] == 1  # max_revisions = 1 : on s'arrête même si ce n'est pas fidèle
    assert state["draft_check"]["unsupported"] == ["X"]


def test_memoire_de_lecons_utilisee_puis_enrichie(sample_records):
    profile = CompanyProfile(nom="Test", activites=["nettoyage"], chiffre_affaires=1_000_000)
    lessons = InMemoryLessonStore([Lesson(1, "Ne pas inventer de fréquence.", "juge", 2)])
    bad = '{"claims": [{"claim": "Prestation quotidienne", "supported": false}]}'
    good = '{"claims": [{"claim": "Nettoyage", "supported": true}]}'
    reflection = '{"lessons": [{"existing": 1}, {"new": "Ne pas écrire que l\'offre garantit."}]}'
    llm = SequenceLLM(EXTRACTION, "brouillon", bad, "brouillon corrigé", good, reflection)
    agent = build_agent(
        NoticeStore(sample_records), llm, profile, today=date(2026, 10, 20), lessons=lessons
    )
    config = {"configurable": {"thread_id": "t6"}}
    agent.invoke({"notice_id": "TEST-0001"}, config)
    state = agent.invoke(
        Command(resume={"decision": "GO", "lesson": "Ne pas promettre de délai."}), config
    )

    assert "Ne pas inventer de fréquence." in llm.calls[1][0]["content"]  # injectée au rédacteur
    assert state["lessons_used"] == ["Ne pas inventer de fréquence."]
    assert "Prestation quotidienne" in llm.calls[5][1]["content"]  # erreurs du 1er jet analysées
    texts = {lesson.text: lesson for lesson in lessons.all()}
    assert texts["Ne pas promettre de délai."].source == HUMAN
    assert texts["Ne pas inventer de fréquence."].count == 3
    assert "Ne pas écrire que l'offre garantit." in texts
    assert len(state["lessons_learned"]) == 3


def test_memoire_en_lecture_seule(sample_records):
    profile = CompanyProfile(nom="Test", activites=["nettoyage"], chiffre_affaires=1_000_000)
    lessons = InMemoryLessonStore([Lesson(1, "Ne pas inventer de fréquence.", "juge", 2)])
    bad = '{"claims": [{"claim": "X", "supported": false}]}'
    llm = SequenceLLM(EXTRACTION, "brouillon", bad, "brouillon 2", bad)
    agent = build_agent(
        NoticeStore(sample_records),
        llm,
        profile,
        today=date(2026, 10, 20),
        lessons=lessons,
        learn=False,
    )
    config = {"configurable": {"thread_id": "t7"}}
    agent.invoke({"notice_id": "TEST-0001"}, config)
    state = agent.invoke(Command(resume="GO"), config)
    assert state["lessons_used"] == ["Ne pas inventer de fréquence."]
    assert state["lessons_learned"] == [] and len(llm.calls) == 5  # pas d'appel de réflexion
    assert len(lessons.all()) == 1
