"""Agent semaine 3 : extraction vérifiée, règles de qualification, validation humaine.

Ces tests n'ont besoin ni de LangGraph, ni de base, ni de clé API.
"""

import json
from datetime import date

import pytest

from tenderpilot.agent.extraction import (
    Item,
    Requirements,
    extract_requirements,
    grounding_rate,
    quote_in_text,
)
from tenderpilot.agent.graph import notice_to_dict, parse_review
from tenderpilot.agent.profile import CompanyProfile, load_profile
from tenderpilot.agent.rules import GO, NO_GO, TO_STUDY, deadline_date, parse_amount, qualify
from tenderpilot.ingestion.boamp import record_to_notice

from .conftest import FakeLLM

EXTRACTION = {
    "resume": "Nettoyage de 3 bâtiments administratifs",
    "duree": {"value": "12 mois reconductible 3 fois", "quote": "DUREE : 12 mois reconductible"},
    "criteres": [{"value": "Prix 40 %", "quote": "Prix 40 %, valeur technique 60 %"}],
    "certifications": [],
    "chiffre_affaires_min": {
        "value": "300 000 euros",
        "quote": "Chiffre d'affaires annuel minimum de 300 000 euros",
    },
    "autres_exigences": [{"value": "Drone", "quote": "Les candidats doivent posséder un drone"}],
}


@pytest.fixture
def notice(sample_records):
    return notice_to_dict(record_to_notice(sample_records[0]))  # nettoyage, Valbrise


@pytest.fixture
def profile():
    return CompanyProfile(
        nom="Test",
        activites=["nettoyage"],
        departements=[],
        chiffre_affaires=1_000_000,
        certifications=["ISO 9001"],
        delai_minimum_jours=10,
    )


TODAY = date(2026, 10, 20)  # date limite de l'avis de test : 05/11/2026


def test_profil_exemple_valide():
    profile = load_profile("profiles/exemple_proprete.toml")
    assert profile.activites and profile.references


def test_citation_retrouvee_malgre_casse_et_accents():
    text = "CAPACITÉ : Chiffre d'affaires annuel minimum de 300 000 euros"
    assert quote_in_text("chiffre d’affaires annuel MINIMUM de 300 000 euros", text)
    assert quote_in_text("Chiffre d'affaires … 300 000 euros", text)
    assert not quote_in_text("minimum de 500 000 euros", text)
    assert not quote_in_text("", text)


def test_extraction_verifie_les_preuves(notice):
    llm = FakeLLM(json.dumps(EXTRACTION, ensure_ascii=False))
    req = extract_requirements(llm, notice["title"], notice["text"])
    assert req.chiffre_affaires_min.verified
    assert req.duree.verified
    assert not req.autres_exigences[0].verified  # le « drone » n'est pas dans l'avis
    assert grounding_rate(req) == pytest.approx(3 / 4)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("300 000 euros", 300_000),
        ("1,5 M€", 1_500_000),
        ("200 k€", 200_000),
        ("2 millions d'euros", 2_000_000),
        ("non précisé", None),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_deadline_en_heure_de_paris():
    assert deadline_date("2026-11-04T23:30:00+00:00") == date(2026, 11, 5)
    assert deadline_date(None) is None


def _req(**fields):
    return Requirements.model_validate(fields)


def verified(value, quote="x"):
    return Item(value=value, quote=quote, verified=True)


def test_go(notice, profile):
    req = _req(chiffre_affaires_min=verified("300 000 euros"))
    decision, checks = qualify(notice, req, profile, TODAY)
    assert decision == GO, [c.detail for c in checks]


def test_hors_secteur_no_go(sample_records, profile):
    it_notice = notice_to_dict(record_to_notice(sample_records[1]))  # maintenance informatique
    decision, _ = qualify(it_notice, _req(), profile, TODAY)
    assert decision == NO_GO


def test_date_depassee_no_go(notice, profile):
    decision, checks = qualify(notice, _req(), profile, date(2026, 11, 6))
    assert decision == NO_GO
    assert any(c.name == "delai" and c.blocking for c in checks)


def test_delai_trop_court_a_etudier(notice, profile):
    decision, _ = qualify(notice, _req(), profile, date(2026, 11, 1))  # 4 jours
    assert decision == TO_STUDY


def test_chiffre_affaires_insuffisant_no_go(notice, profile):
    decision, _ = qualify(notice, _req(chiffre_affaires_min=verified("2 M€")), profile, TODAY)
    assert decision == NO_GO


def test_exigence_non_verifiee_ignoree(notice, profile):
    fake = Item(value="5 M€", quote="inventé", verified=False)
    decision, _ = qualify(notice, _req(chiffre_affaires_min=fake), profile, TODAY)
    assert decision == GO


def test_certification_manquante_a_etudier(notice, profile):
    req = _req(certifications=[verified("Qualipropre"), verified("ISO 9001:2015")])
    decision, checks = qualify(notice, req, profile, TODAY)
    assert decision == TO_STUDY
    cert = next(c for c in checks if c.name == "certifications")
    assert "Qualipropre" in cert.detail and "ISO 9001" not in cert.detail


def test_zone(notice, profile):
    profile.departements = ["59"]
    notice["departments"] = ["13"]
    assert qualify(notice, _req(), profile, TODAY)[0] == TO_STUDY  # hors zone, non bloquant
    notice["departments"] = ["59"]
    assert qualify(notice, _req(), profile, TODAY)[0] == GO


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("", GO),
        ("ok", GO),
        ("no-go", NO_GO),
        ("À étudier", TO_STUDY),
        ({"decision": "NO_GO", "comment": "trop loin"}, NO_GO),
    ],
)
def test_parse_review(answer, expected):
    assert parse_review(answer, proposed=GO)["decision"] == expected


def test_parse_review_refuse_une_decision_inconnue():
    with pytest.raises(ValueError):
        parse_review("peut-être", proposed=GO)


def test_controles_a_verifier_ne_changent_pas_la_decision(notice, profile):
    decision, checks = qualify(notice, _req(), profile, TODAY)  # ni seuil ni certification
    assert decision == GO
    assert {c.name for c in checks if c.status == "a_verifier"} == {
        "chiffre_affaires",
        "certifications",
    }


def test_claims_part_ignore_sections_4_5_et_a_completer():
    from tenderpilot.agent.drafting import claims_part

    draft = (
        "## 1. Besoin\nNettoyage.\n## 2. Réponse\n[À COMPLÉTER] décrire les produits\n"
        "## 4. Points à vérifier\nCA\n## 5. Pièces\nKbis"
    )
    part = claims_part(draft)
    assert "Nettoyage" in part and "décrire" not in part
    assert "Kbis" not in part and "Points à vérifier" not in part


def test_revision_et_profil_contiennent_ce_qu_il_faut():
    from tenderpilot.agent.drafting import _profile_block, build_revision_messages

    messages = build_revision_messages("Brouillon", ["Reporting mensuel"])
    assert "Reporting mensuel" in messages[1]["content"]
    assert "[À COMPLÉTER]" in messages[0]["content"]
    profile = CompanyProfile(nom="T", activites=["x"], departements=["59", "62"])
    assert "59, 62" in _profile_block(profile)  # la zone est donnée au rédacteur et au juge


def test_contexte_separe_des_exigences_a_traiter():
    from tenderpilot.agent.drafting import _requirements_block

    req = _req(
        duree=verified("48 mois"),
        criteres=[verified("Prix 40 %")],
    )
    block = _requirements_block(req)
    context, to_answer = block.split("EXIGENCES À TRAITER :")
    assert "48 mois" in context and "48 mois" not in to_answer
    assert "Prix 40 %" in to_answer
    assert "(aucune)" in _requirements_block(_req(duree=verified("12 mois")))
