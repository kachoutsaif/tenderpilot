import json

import pytest

from tenderpilot.evaluation.dataset import load_questions
from tenderpilot.evaluation.judge import judge_answer, parse_judgement, says_not_found
from tenderpilot.evaluation.metrics import (
    hit_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    unique_in_order,
)
from tenderpilot.evaluation.runner import run_evaluation
from tenderpilot.ingestion.boamp import record_to_notice
from tenderpilot.rag.pipeline import ingest_notice
from tenderpilot.rag.prompt import NOT_FOUND

from .conftest import FakeLLM


def test_metrics():
    retrieved = unique_in_order(["A", "A", "B", "C"])
    assert retrieved == ["A", "B", "C"]
    assert hit_at_k(retrieved, {"C", "Z"}) == 1.0
    assert hit_at_k(retrieved, {"Z"}) == 0.0
    assert recall_at_k(retrieved, {"B", "C", "Z", "Y"}) == 0.5
    assert reciprocal_rank(retrieved, {"B"}) == 0.5
    assert reciprocal_rank(retrieved, {"Z"}) == 0.0
    assert percentile([1, 2, 3, 4, 100], 95) == 100


def _write(tmp_path, lines):
    path = tmp_path / "q.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_load_questions_and_validation(tmp_path):
    ok = _write(
        tmp_path,
        [
            "// commentaire",
            json.dumps({"id": "q1", "question": "x", "expected": ["A"]}),
            json.dumps({"id": "q2", "question": "y", "kind": "hors_sujet"}),
        ],
    )
    qs = load_questions(ok)
    assert [q.id for q in qs] == ["q1", "q2"] and qs[0].kind == "recherche"

    with pytest.raises(ValueError, match="vide"):
        load_questions(_write(tmp_path, [json.dumps({"id": "a", "question": "x"})]))
    with pytest.raises(ValueError, match="double"):
        line = json.dumps({"id": "a", "question": "x", "expected": ["A"]})
        load_questions(_write(tmp_path, [line, line]))
    with pytest.raises(ValueError, match="inconnu"):
        line = json.dumps({"id": "a", "question": "x", "expected": ["A"], "kind": "autre"})
        load_questions(_write(tmp_path, [line]))


def test_parse_judgement():
    raw = (
        'Voici :\n```json\n{"claims": [{"claim": "a", "supported": true},'
        ' {"claim": "b", "supported": false}]}\n```'
    )
    verdict = parse_judgement(raw)
    assert verdict.faithfulness == 0.5
    assert verdict.unsupported == ["b"]
    assert parse_judgement('{"claims": []}').faithfulness == 1.0
    with pytest.raises(ValueError):
        parse_judgement("pas de json")


def test_not_found_answer_is_not_sent_to_judge():
    judge = FakeLLM("ne doit pas être appelé")
    verdict = judge_answer(judge, "q", NOT_FOUND, [])
    assert verdict.faithfulness == 1.0 and judge.last_messages is None
    assert says_not_found(f"Désolé. {NOT_FOUND}")


def test_run_evaluation_end_to_end(sample_records, embedder, store, tmp_path):
    for record in sample_records:
        notice = record_to_notice(record)
        if notice:
            ingest_notice(notice, embedder, store)
    path = _write(
        tmp_path,
        [
            json.dumps(
                {
                    "id": "q1",
                    "question": "maintenance des postes informatiques",
                    "expected": ["TEST-0002"],
                }
            ),
            json.dumps(
                {"id": "q2", "question": "repas pour les écoles", "expected": ["TEST-0001"]}
            ),
            json.dumps({"id": "q3", "question": "stade olympique", "kind": "hors_sujet"}),
        ],
    )
    answer_llm = FakeLLM("Réponse [1] et [9].")
    judge = FakeLLM('{"claims": [{"claim": "x", "supported": true}]}')
    results, summary = run_evaluation(
        load_questions(path), embedder, store, k=1, llm=answer_llm, judge=judge
    )
    by_id = {r.id: r for r in results}
    assert by_id["q1"].hit == 1.0 and by_id["q1"].rr == 1.0
    assert by_id["q2"].hit == 0.0  # le bon avis (TEST-0003) n'est pas celui attendu ici
    assert by_id["q3"].hit is None and by_id["q3"].not_found_ok is False
    assert summary["global"]["hit@k"] == 0.5
    assert summary["global"]["citations_invalides"] == 3  # [9] invalide pour chaque question
    assert summary["global"]["fidelite"] == 1.0
    assert set(summary["par_type"]) == {"recherche", "hors_sujet"}


def test_errors_do_not_stop_evaluation(sample_records, embedder, store, tmp_path):
    class Broken:
        def complete(self, messages):
            raise RuntimeError("API indisponible")

    ingest_notice(record_to_notice(sample_records[0]), embedder, store)
    path = _write(tmp_path, [json.dumps({"id": "q1", "question": "x", "expected": ["A"]})])
    results, summary = run_evaluation(load_questions(path), embedder, store, llm=Broken())
    assert results[0].error.startswith("RuntimeError")
    assert summary["global"]["erreurs"] == 1
