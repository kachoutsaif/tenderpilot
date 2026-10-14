import json

from tenderpilot.ingestion.boamp import donnees_sections, format_deadline, record_to_notice


def test_record_to_notice_reads_main_fields(sample_records):
    notice = record_to_notice(sample_records[0])
    assert notice.id == "TEST-0001"
    assert notice.title.startswith("Prestations de nettoyage")
    assert notice.buyer == "Commune de Valbrise (fictive)"
    assert notice.deadline.startswith("2026-11-05")
    assert "Date limite de réponse : 05/11/2026" in notice.text


def test_donnees_as_string_is_parsed_into_readable_lines(sample_records):
    notice = record_to_notice(sample_records[0])
    assert "4 200 m²" in notice.text
    assert "Chiffre d'affaires annuel minimum" in notice.text


def test_donnees_as_dict_is_supported(sample_records):
    notice = record_to_notice(sample_records[1])
    assert "650 postes" in notice.text
    assert "ISO 27001" in notice.text


def test_list_fields_are_joined(sample_records):
    notice = record_to_notice(sample_records[1])
    assert "Informatique (prestations de services), Maintenance" in notice.text


def test_record_without_id_is_ignored(sample_records):
    assert record_to_notice(sample_records[3]) is None


def test_generic_reading_handles_bad_input():
    assert donnees_sections(None) == []
    assert donnees_sections("texte libre  non JSON") == ["texte libre non JSON"]
    nested = json.dumps({"A": {"B": {"#text": "une vraie valeur", "@listName": "code"}}})
    assert donnees_sections(nested) == ["B : une vraie valeur"]


def test_generic_reading_drops_codes_and_attributes():
    raw = {"X": {"cbc:ID": "ORG-0001", "@schemeName": "org", "cbc:Note": "Visite du site"}}
    assert donnees_sections(raw) == ["Note : Visite du site"]


def test_format_deadline_uses_paris_day():
    assert format_deadline("2026-11-09T10:00:00+00:00") == "09/11/2026"
    assert format_deadline("2026-12-31T23:30:00+00:00") == "01/01/2027"  # déjà le lendemain à Paris
    assert format_deadline(None) is None
    assert format_deadline("pas une date") == "pas une date"
