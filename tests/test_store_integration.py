"""Test d'intégration avec un vrai Postgres + pgvector.

Lancé seulement si TEST_DATABASE_URL est défini (dans la CI, ou en local).
ATTENTION : ce test supprime les tables. Utilisez une base dédiée aux tests,
jamais votre base de développement.
"""

import os

import pytest

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("TEST_DATABASE_URL non défini : test d'intégration ignoré", allow_module_level=True)
pytest.importorskip("psycopg")
pytest.importorskip("pgvector")

from tenderpilot.ingestion.boamp import record_to_notice  # noqa: E402
from tenderpilot.rag.pipeline import ingest_notice  # noqa: E402
from tenderpilot.store import PgVectorStore  # noqa: E402

from .conftest import FakeEmbedder  # noqa: E402


@pytest.fixture
def pg_store():
    embedder = FakeEmbedder()
    store = PgVectorStore(DATABASE_URL, dim=embedder.dim)
    store.conn.execute("DROP TABLE IF EXISTS chunks, notices")
    store.init_schema()
    yield store, embedder
    store.conn.execute("DROP TABLE IF EXISTS chunks, notices")
    store.close()


def test_ingest_and_search_in_postgres(pg_store, sample_records):
    store, embedder = pg_store
    for record in sample_records:
        notice = record_to_notice(record)
        if notice:
            ingest_notice(notice, embedder, store, max_chars=400, overlap=50)

    notices, chunks = store.count()
    assert notices == 3 and chunks >= 3

    results = store.search(embedder.embed(["maintenance postes informatiques serveurs"])[0], k=2)
    assert results[0].notice_id == "TEST-0002"
    assert results[0].title.startswith("Maintenance")


def test_reingestion_replaces_chunks(pg_store, sample_records):
    store, embedder = pg_store
    notice = record_to_notice(sample_records[0])
    ingest_notice(notice, embedder, store)
    first = store.count()
    ingest_notice(notice, embedder, store)
    assert store.count() == first


def test_delete_notices(pg_store, sample_records):
    store, embedder = pg_store
    for record in sample_records[:2]:
        ingest_notice(record_to_notice(record), embedder, store)
    assert store.delete_notices(["TEST-0001", "INCONNU"]) == 1
    notices, _ = store.count()
    assert notices == 1
    assert store.delete_notices([]) == 0


def test_search_text(pg_store, sample_records):
    store, embedder = pg_store
    for record in sample_records[:3]:
        ingest_notice(record_to_notice(record), embedder, store)
    rows = store.search_text(["maintenance", "serveurs"])
    assert [r["id"] for r in rows] == ["TEST-0002"]
    assert store.search_text(["introuvable-xyz"]) == []


def test_search_fulltext_sans_accents_ni_majuscules(pg_store, sample_records):
    store, embedder = pg_store
    for record in sample_records:
        notice = record_to_notice(record)
        if notice:
            ingest_notice(notice, embedder, store)
    # « SERVEURS » en majuscules et sans accent doit retrouver l'avis de maintenance
    results = store.search_fulltext("Qui gère la MAINTENANCE des SERVEURS ?", k=3)
    assert results and results[0].notice_id == "TEST-0002"
    assert results[0].score > 0
    assert store.search_fulltext("zzzz introuvable", k=3) == []


def test_get_notice_reconstruit_l_avis_complet(pg_store, sample_records):
    store, embedder = pg_store
    original = record_to_notice(sample_records[0])
    ingest_notice(original, embedder, store, max_chars=200, overlap=50)
    notice = store.get_notice(original.id)
    assert notice.text == original.text  # pas de répétition due au chevauchement
    assert store.get_notice("INCONNU") is None
