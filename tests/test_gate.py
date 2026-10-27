"""Porte qualité : seuil = référence - tolérance ; cliquet quand la recherche s'améliore."""

import json

from tenderpilot.evaluation.gate import check_gate, gate_markdown, load_reference, save_reference

REFERENCE = {"tolerance": 0.02, "scores": {"hit@k": 0.962, "recall@k": 0.871, "mrr": 0.821}}


def summary(hit, recall, mrr):
    return {"global": {"hit@k": hit, "recall@k": recall, "mrr": mrr}}


def test_meme_score_reussit():
    assert all(c.ok for c in check_gate(summary(0.962, 0.871, 0.821), REFERENCE))


def test_une_question_perdue_echoue():
    # 26 questions notées : une de moins = -0,038 sur hit@5 et recall@5
    checks = {c.metric: c for c in check_gate(summary(0.923, 0.833, 0.802), REFERENCE)}
    assert not checks["hit@k"].ok and not checks["recall@k"].ok
    assert checks["mrr"].ok  # le MRR n'a baissé que de 0,019 : toléré


def test_changement_d_ordre_tolere():
    # un bon avis passe du rang 1 au rang 2 sur une question : MRR -0,019
    assert all(c.ok for c in check_gate(summary(0.962, 0.871, 0.802), REFERENCE))


def test_rapport_markdown():
    ok = gate_markdown(check_gate(summary(0.962, 0.871, 0.830), REFERENCE), k=5)
    assert "✅ Porte qualité : réussie" in ok
    assert "| mrr | 0.830 (+0.009) | 0.821 | 0.801 | ✅ |" in ok
    ko = gate_markdown(check_gate(summary(0.923, 0.871, 0.821), REFERENCE), k=5)
    assert "❌ Porte qualité : ÉCHEC" in ko and "| hit@5 |" in ko and "--update-reference" in ko


def test_mise_a_jour_de_la_reference(tmp_path):
    path = tmp_path / "reference.json"
    save_reference(summary(0.97, 0.9, 0.85), path, tolerance=0.02, note="meilleur découpage")
    saved = load_reference(path)
    assert saved["scores"] == {"hit@k": 0.97, "recall@k": 0.9, "mrr": 0.85}
    assert saved["note"] == "meilleur découpage"
    # le plancher a monté : l'ancien niveau n'est plus accepté (cliquet)
    assert not all(c.ok for c in check_gate(summary(0.962, 0.871, 0.821), saved))


def test_reference_du_projet_valide():
    reference = json.loads(open("eval/reference.json", encoding="utf-8").read())
    assert set(reference["scores"]) == {"hit@k", "recall@k", "mrr"}
    assert 0 <= reference["tolerance"] < 0.05
