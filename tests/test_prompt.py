from tenderpilot.models import RetrievedChunk
from tenderpilot.rag.prompt import NOT_FOUND, build_messages, extract_citations


def _chunks(n):
    return [
        RetrievedChunk(
            notice_id=f"N{i}", chunk_index=0, content=f"contenu {i}", score=0.9, title=f"Titre {i}"
        )
        for i in range(1, n + 1)
    ]


def test_sources_are_numbered_in_prompt():
    messages = build_messages("Quelle date limite ?", _chunks(2))
    user = messages[1]["content"]
    assert "[1] (avis N1 — Titre 1)" in user
    assert "[2] (avis N2 — Titre 2)" in user
    assert "Quelle date limite ?" in user
    assert NOT_FOUND in messages[0]["content"]


def test_valid_and_invalid_citations_are_separated():
    valid, invalid = extract_citations("Réponse [1] et [3][1], mais aussi [7].", _chunks(3))
    assert [c.number for c in valid] == [1, 3]
    assert valid[1].notice_id == "N3"
    assert invalid == [7]


def test_answer_without_citation():
    valid, invalid = extract_citations(NOT_FOUND, _chunks(3))
    assert valid == [] and invalid == []
