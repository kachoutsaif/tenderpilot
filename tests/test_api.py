"""Tests de l'API. Ignorés automatiquement si FastAPI n'est pas installé."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from fastapi.testclient import TestClient  # noqa: E402

from tenderpilot.api import main  # noqa: E402
from tenderpilot.ingestion.boamp import record_to_notice  # noqa: E402
from tenderpilot.rag.pipeline import ingest_notice  # noqa: E402

from .conftest import FakeEmbedder, FakeLLM, InMemoryStore  # noqa: E402


@pytest.fixture
def client(sample_records):
    embedder, store = FakeEmbedder(), InMemoryStore()
    for record in sample_records:
        notice = record_to_notice(record)
        if notice:
            ingest_notice(notice, embedder, store)
    main.app.dependency_overrides = {
        main.get_embedder: lambda: embedder,
        main.get_store: lambda: store,
        main.get_llm: lambda: FakeLLM("Restauration scolaire, 1 100 repas par jour [1]."),
    }
    yield TestClient(main.app)
    main.app.dependency_overrides = {}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ask_returns_answer_and_citations(client):
    response = client.post("/ask", json={"question": "repas pour les écoles", "k": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["citations"][0]["notice_id"] == "TEST-0003"
    assert body["invalid_citations"] == []


def test_ask_validates_input(client):
    assert client.post("/ask", json={"question": "a"}).status_code == 422
    assert client.post("/ask", json={"question": "valide", "k": 99}).status_code == 422


def test_list_notices(client):
    assert len(client.get("/notices").json()) == 3
