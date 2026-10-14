"""Tests sur deux avis BOAMP réels au format eForms (26-98309 et 26-98298)."""

from pathlib import Path

import pytest

from tenderpilot.ingestion.boamp import load_records_from_file, prepare_notices, record_to_notice
from tenderpilot.ingestion.eforms import eforms_sections, find_all, text
from tenderpilot.rag.pipeline import ingest_notice

FIXTURE = Path(__file__).parent / "fixtures" / "boamp_eforms_real.json"


@pytest.fixture
def real_records():
    return load_records_from_file(str(FIXTURE))


@pytest.fixture
def nevers(real_records):
    return record_to_notice(real_records[0])


@pytest.fixture
def award(real_records):
    return record_to_notice(real_records[2])


def test_no_technical_noise(nevers, award):
    for notice in (nevers, award):
        for noise in ("@listName", "#text", "cbc:", "efac:", "ORG-0001", "cn-standard", "per-exa"):
            assert noise not in notice.text


def test_lots_are_separate_paragraphs(nevers):
    assert "Nombre de lots : 2" in nevers.text
    paragraphs = nevers.text.split("\n\n")
    lot1 = next(p for p in paragraphs if p.startswith("Lot 1 :"))
    lot2 = next(p for p in paragraphs if p.startswith("Lot 2 :"))
    assert "plaques de rue" in lot1
    assert "balisages de chantiers" in lot2
    assert "Durée : 48 mois" in lot1


def test_lot_details(nevers):
    assert "Adapté aux PME : oui" in nevers.text
    assert "Date limite de remise des offres : 09/11/2026 à 12:00" in nevers.text
    assert "Documents de la consultation : https://marches.ternum-bfc.fr" in nevers.text
    assert "Codes CPV : 44423400" in nevers.text
    # le CPV identique à celui de l'objet global n'est pas répété dans chaque lot
    assert nevers.text.count("Codes CPV") == 1


def test_correction_is_detected(nevers):
    assert "Avis de marché (rectificatif)" in nevers.text
    assert "Modification : Report date et heure de remise des offres" in nevers.text
    assert nevers.replaces == ["26-93392"]


def test_award_notice_result(award):
    assert "Résultat de marché" in award.text
    assert "Montant total attribué : 31 302 994 EUR" in award.text
    assert "Titulaire(s) : SUEZ RV REUNION" in award.text
    assert "Nombre d'offres reçues : 1" in award.text
    assert "Coût global des prestations (55 %)" in award.text
    assert "Qualité technique (40 %)" in award.text
    # le tribunal (organisme de recours) n'est pas un titulaire
    assert "Tribunal" not in award.text.split("Titulaire(s) :")[1]


def test_single_lot_does_not_repeat_the_title(award):
    assert "Conditions du marché" in award.text
    assert "Lot 1 :" not in award.text


def test_buyer_location_without_duplicate(award, nevers):
    assert "Localisation de l'acheteur : 97441\n" in award.text + "\n"
    assert "Localisation de l'acheteur : 58000 Nevers" in nevers.text


def test_prepare_notices_drops_replaced_original(real_records):
    notices, skipped = prepare_notices(real_records)
    ids = [n.id for n in notices]
    assert "26-93392" not in ids  # remplacé par le rectificatif 26-98309
    assert "26-98309" in ids and "26-98298" in ids
    assert skipped == 1


def test_correction_deletes_original_already_in_store(real_records, embedder, store):
    original = record_to_notice(real_records[1])
    ingest_notice(original, embedder, store)
    assert "26-93392" in store.notices
    ingest_notice(record_to_notice(real_records[0]), embedder, store)
    assert "26-93392" not in store.notices
    assert "26-98309" in store.notices


def test_not_eforms_returns_none():
    assert eforms_sections({"autre": "format"}) is None
    assert eforms_sections("texte") is None


def test_helpers():
    tree = {"a": [{"k": {"#text": " x  y "}}, {"b": {"k": "z"}}]}
    assert [text(v) for v in find_all(tree, "k")] == ["x y", "z"]
