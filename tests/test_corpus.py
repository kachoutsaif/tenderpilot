"""Corpus d'évaluation figé : aller-retour fidèle, fichier stable, données réduites."""

from tenderpilot.evaluation.corpus import load_corpus, redact, save_corpus
from tenderpilot.ingestion.boamp import record_to_notice


def notices(records):
    return [n for n in map(record_to_notice, records) if n]


def test_aller_retour(sample_records, tmp_path):
    original = notices(sample_records)
    path = tmp_path / "corpus.jsonl"
    assert save_corpus(original, path) == len(original)
    loaded = {n.id: n for n in load_corpus(path)}
    for n in original:
        assert loaded[n.id].text == redact(n.text)  # identique, aux données masquées près
        assert loaded[n.id].title == n.title
        assert loaded[n.id].deadline == n.deadline


def test_seuls_les_champs_utiles_sont_gardes(sample_records, tmp_path):
    notice = notices(sample_records)[0]
    notice.raw.update(code_departement=["59"], contact="Mme Dupont, 06 00 00 00 00")
    save_corpus([notice], tmp_path / "c.jsonl")
    (loaded,) = load_corpus(tmp_path / "c.jsonl")
    assert loaded.raw["code_departement"] == ["59"]
    assert "contact" not in loaded.raw  # pas de données personnelles dans un fichier publié
    assert "Dupont" not in (tmp_path / "c.jsonl").read_text(encoding="utf-8")


def test_fichier_stable_trie_sans_doublon(sample_records, tmp_path):
    items = notices(sample_records)
    save_corpus(items, tmp_path / "a.jsonl")
    save_corpus(list(reversed(items)) + items[:1], tmp_path / "b.jsonl")
    a = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert a == (tmp_path / "b.jsonl").read_text(encoding="utf-8")  # même contenu, même fichier
    ids = [n.id for n in load_corpus(tmp_path / "a.jsonl")]
    assert ids == sorted(ids) and len(ids) == len(set(ids))


def test_masquage_courriels_et_telephones():
    text = (
        "Écrire à jean.dupont@ville-maubeuge.fr ou marches@cc-sambre.fr, "
        "tél. 03 27 53 75 00, 03.27.53.75.00, 0327537500 ou +33 3 27 53 75 00. "
        "Durée : 48 mois, CPV 90911000, montant 210 000 euros, date 09/11/2026."
    )
    out = redact(text)
    assert "@" not in out and out.count("[courriel]") == 2
    assert out.count("[téléphone]") == 4
    # ce qui ressemble à des chiffres mais n'est pas un numéro reste intact
    assert "90911000" in out and "210 000 euros" in out and "09/11/2026" in out


def test_lignes_de_contact_et_noms_supprimes():
    text = (
        "nomOfficiel : Mairie de Raismes\n"
        "nomContact : Pamela Lescol\n"
        "telContact : 03 27 00 00 00\n"
        "capaciteExercice : Déclaration sur l'honneur\n"
        "Renseignements : Mme TANQUEREL - Tél : 03 27 00 00 01. Monsieur le Maire signe. "
        "Mme. Alexandra Martin"
    )
    out = redact(text)
    assert "Lescol" not in out and "TANQUEREL" not in out and "Contact" not in out
    assert "Alexandra" not in out and "Martin" not in out
    assert "nomOfficiel : Mairie de Raismes\ncapaciteExercice" in out  # le reste est gardé
    assert "[personne]" in out and "[téléphone]" in out
    assert "Monsieur le Maire" in out  # une fonction n'est pas un nom de personne


def test_contact_en_milieu_de_phrase_et_grades():
    text = (
        "Visite obligatoire. Contact : Cécile GONCALVES - cecile.g@ville.fr. "
        "S'inscrire auprès du Commandant Faure : Contact : visite@sdis.fr. "
        "Le maître d'ouvrage est la commune."
    )
    out = redact(text)
    assert "GONCALVES" not in out and "Cécile" not in out and "Faure" not in out
    assert "Contact : [personne]" in out and "Contact : [courriel]" in out
    assert "maître d'ouvrage" in out  # « maître » suivi d'un nom commun : gardé
