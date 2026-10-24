"""Évaluation hors ligne : chargement du corpus, scores, rapport Markdown."""

from tenderpilot.evaluation.dataset import EvalQuestion
from tenderpilot.evaluation.offline import load_into_store, markdown_report
from tenderpilot.evaluation.runner import run_evaluation
from tenderpilot.ingestion.boamp import record_to_notice

QUESTIONS = [
    EvalQuestion("q1", "maintenance des serveurs informatiques", ["TEST-0002"]),
    EvalQuestion("q2", "restauration scolaire et repas", ["TEST-0003"]),
    EvalQuestion("q3", "avis qui n'existe pas", ["INCONNU"]),
    EvalQuestion("q4", "nettoyage et informatique", ["TEST-0001", "INCONNU"], kind="liste"),
]


def run(store, embedder, sample_records):
    notices = [n for n in map(record_to_notice, sample_records) if n]
    loaded = load_into_store(notices, embedder, store)
    results, summary = run_evaluation(QUESTIONS, embedder, store, k=3, mode="hybrid")
    return loaded, results, summary


def test_chargement_et_scores(store, embedder, sample_records):
    (n_notices, n_chunks), results, summary = run(store, embedder, sample_records)
    assert n_notices == 3 and n_chunks >= 3
    by_id = {r.id: r for r in results}
    assert by_id["q1"].hit == 1.0 and by_id["q3"].hit == 0.0
    assert by_id["q4"].recall == 0.5  # un avis attendu sur deux existe
    assert summary["global"]["questions"] == 4


def test_meme_score_a_chaque_lancement(embedder, sample_records):
    from .conftest import InMemoryStore

    _, _, first = run(InMemoryStore(), embedder, sample_records)
    _, _, second = run(InMemoryStore(), embedder, sample_records)
    assert first == second  # reproductible : condition d'une porte qualité juste


def test_rapport_markdown(store, embedder, sample_records):
    _, results, summary = run(store, embedder, sample_records)
    report = markdown_report(summary, results, {"mode": "hybrid", "k": 3})
    assert "| type | questions | hit@3 | recall@3 | mrr |" in report
    assert "| **global** | 4 |" in report
    assert "`q3` avis qui n'existe pas — attendu INCONNU" in report  # les ratés sont listés
    assert "`q4`" in report and "rappel 0.50" in report  # les partiels aussi
