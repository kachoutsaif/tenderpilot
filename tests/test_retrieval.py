import pytest

from tenderpilot.models import RetrievedChunk
from tenderpilot.rag.pipeline import ingest_notice
from tenderpilot.rag.retrieval import retrieve, rrf_fuse


def chunk(notice_id, index=0, score=0.0):
    return RetrievedChunk(notice_id=notice_id, chunk_index=index, content="", score=score)


def test_rrf_favorise_les_morceaux_presents_dans_les_deux_classements():
    vector = [chunk("A"), chunk("B"), chunk("C")]
    text = [chunk("D"), chunk("C"), chunk("B")]
    fused = rrf_fuse([vector, text])
    # B et C apparaissent dans les deux listes : ils passent devant A et D (une seule liste)
    assert [c.notice_id for c in fused][:2] == ["B", "C"]
    assert {c.notice_id for c in fused} == {"A", "B", "C", "D"}


def test_rrf_score_calcule():
    fused = rrf_fuse([[chunk("A")], [chunk("A")]], rrf_k=60)
    assert fused[0].score == pytest.approx(2 / 61)


def test_rrf_distingue_les_morceaux_d_un_meme_avis():
    fused = rrf_fuse([[chunk("A", 0), chunk("A", 1)]])
    assert [(c.notice_id, c.chunk_index) for c in fused] == [("A", 0), ("A", 1)]


@pytest.fixture
def filled_store(store, embedder, sample_records):
    from tenderpilot.ingestion.boamp import record_to_notice

    for record in sample_records:
        notice = record_to_notice(record)
        if notice:
            ingest_notice(notice, embedder, store)
    return store


@pytest.mark.parametrize("mode", ["vector", "text", "hybrid"])
def test_retrieve_tous_les_modes(filled_store, embedder, mode):
    results = retrieve("maintenance des serveurs informatiques", embedder, filled_store, 2, mode)
    assert results
    assert results[0].notice_id == "TEST-0002"
    assert len(results) <= 2


def test_retrieve_mode_inconnu(filled_store, embedder):
    with pytest.raises(ValueError, match="Mode de recherche inconnu"):
        retrieve("test", embedder, filled_store, mode="bm25")


@pytest.mark.parametrize("mode", ["vector", "text", "hybrid"])
def test_filtre_par_departement(filled_store, embedder, mode):
    filled_store.notices["TEST-0001"].raw["code_departement"] = ["59"]
    filled_store.notices["TEST-0002"].raw["code_departement"] = "75"  # parfois une valeur seule
    question = "maintenance des serveurs informatiques"  # vise TEST-0002, qui est dans le 75
    nord = retrieve(question, embedder, filled_store, 5, mode, departements=["59"])
    assert {c.notice_id for c in nord} <= {"TEST-0001"}
    paris = retrieve(question, embedder, filled_store, 5, mode, departements=["75"])
    assert paris and {c.notice_id for c in paris} == {"TEST-0002"}
