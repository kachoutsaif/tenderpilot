import pytest

from tenderpilot.ingestion.boamp import record_to_notice
from tenderpilot.rag.pipeline import answer_question, ingest_notice
from tenderpilot.rag.prompt import NOT_FOUND

from .conftest import FakeLLM


def _ingest_all(records, embedder, store):
    for record in records:
        notice = record_to_notice(record)
        if notice:
            ingest_notice(notice, embedder, store, max_chars=400, overlap=50)


def test_retrieval_finds_the_right_notice(sample_records, embedder, store):
    _ingest_all(sample_records, embedder, store)
    llm = FakeLLM()
    answer = answer_question(
        "maintenance des postes informatiques et serveurs", embedder, store, llm, k=2
    )
    assert answer.sources[0].notice_id == "TEST-0002"
    assert "Sources :" in llm.last_messages[1]["content"]


def test_answer_contains_checked_citations(sample_records, embedder, store):
    _ingest_all(sample_records, embedder, store)
    llm = FakeLLM("Nettoyage de 3 bâtiments [1], critère prix 40 % [1], voir aussi [9].")
    answer = answer_question("nettoyage des locaux", embedder, store, llm, k=3)
    assert [c.number for c in answer.citations] == [1]
    assert answer.invalid_citations == [9]


def test_reingestion_does_not_duplicate(sample_records, embedder, store):
    _ingest_all(sample_records, embedder, store)
    before = len(store.rows)
    _ingest_all(sample_records, embedder, store)
    assert len(store.rows) == before


def test_empty_index_returns_not_found(embedder, store):
    llm = FakeLLM()
    answer = answer_question("n'importe quoi", embedder, store, llm)
    assert answer.text == NOT_FOUND
    assert llm.last_messages is None  # le LLM n'est même pas appelé


def test_empty_question_is_rejected(embedder, store):
    with pytest.raises(ValueError):
        answer_question("   ", embedder, store, FakeLLM())
