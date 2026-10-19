"""Mémoire de leçons (pattern Reflexion) : stockage, réflexion, injection dans le prompt."""

import pytest

from tenderpilot.agent.drafting import build_draft_messages
from tenderpilot.agent.extraction import Requirements
from tenderpilot.agent.graph import parse_review
from tenderpilot.agent.memory import (
    HUMAN,
    JUDGE,
    InMemoryLessonStore,
    Lesson,
    learn_from_errors,
    parse_reflection,
)
from tenderpilot.agent.profile import CompanyProfile

from .conftest import FakeLLM


@pytest.fixture
def lessons():
    return InMemoryLessonStore(
        [
            Lesson(1, "Ne pas indiquer de fréquence d'intervention absente de l'avis.", JUDGE, 3),
            Lesson(2, "Ne pas promettre de délai d'intervention.", HUMAN, 1),
        ]
    )


def test_les_lecons_humaines_passent_en_premier(lessons):
    assert [lesson.id for lesson in lessons.top()] == [2, 1]


def test_pas_de_doublon_a_la_casse_et_aux_accents_pres(lessons):
    lesson = lessons.add("ne pas indiquer de frequence d'intervention absente de l'avis.", JUDGE)
    assert lesson.id == 1 and lesson.count == 4
    assert len(lessons.all()) == 2


def test_supprimer(lessons):
    assert lessons.delete(1) and not lessons.delete(1)


def test_parse_reflection():
    raw = """Voici : {"lessons": [{"existing": 1}, {"existing": 99},
             {"new": "Ne pas qualifier l'effectif sans source."}, {"new": "court"}]}"""
    existing, new = parse_reflection(raw, known_ids={1, 2})
    assert existing == [1]  # 99 n'existe pas : ignoré
    assert new == ["Ne pas qualifier l'effectif sans source."]  # « court » : trop court


def test_parse_reflection_limite_et_json_invalide():
    many = '{"lessons": [' + ", ".join(['{"new": "Ne pas inventer de chiffres."}'] * 5) + "]}"
    assert len(parse_reflection(many, set())[1]) == 3
    assert parse_reflection("pas de json", set()) == ([], [])


def test_learn_from_errors(lessons):
    llm = FakeLLM('{"lessons": [{"existing": 1}, {"new": "Ne pas écrire que l\'offre garantit."}]}')
    learned = learn_from_errors(llm, lessons, ["Entretien quotidien", "Offre garantie"])
    assert len(learned) == 2
    assert lessons.top()[1].count == 4  # la leçon 1 a été renforcée
    assert "LEÇONS CONNUES" in llm.last_messages[1]["content"]  # le LLM voit l'existant


def test_aucune_erreur_aucun_appel(lessons):
    llm = FakeLLM("ne doit pas être appelé")
    assert learn_from_errors(llm, lessons, []) == [] and llm.last_messages is None


def test_les_lecons_sont_dans_le_prompt_du_redacteur():
    profile = CompanyProfile(nom="T", activites=["nettoyage"])
    messages = build_draft_messages(
        "Avis", Requirements(), profile, [], "GO", lessons=["Ne pas promettre de délai."]
    )
    assert "Ne pas promettre de délai." in messages[0]["content"]
    sans = build_draft_messages("Avis", Requirements(), profile, [], "GO")
    assert "Leçons" not in sans[0]["content"]


def test_parse_review_avec_lecon():
    review = parse_review({"decision": "GO", "lesson": "  Ne pas promettre de délai. "}, "GO")
    assert review["lesson"] == "Ne pas promettre de délai."
    assert "lesson" not in parse_review("", "GO")
