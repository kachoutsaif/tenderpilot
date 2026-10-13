import pytest

from tenderpilot.ingestion.chunking import chunk_notice, split_text
from tenderpilot.models import Notice


def test_short_text_gives_one_chunk():
    assert split_text("Une seule ligne.", max_chars=100, overlap=10) == ["Une seule ligne."]


def test_chunks_respect_max_size():
    text = "\n".join(f"Paragraphe numéro {i} avec quelques mots de remplissage." for i in range(80))
    chunks = split_text(text, max_chars=300, overlap=50)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)


def test_no_content_is_lost():
    lines = [f"ligne-{i}" for i in range(200)]
    chunks = split_text("\n".join(lines), max_chars=120, overlap=30)
    joined = "\n".join(chunks)
    assert all(line in joined for line in lines)


def test_consecutive_chunks_overlap():
    text = "\n".join(f"Phrase {i} sur les conditions du marché." for i in range(30))
    chunks = split_text(text, max_chars=200, overlap=60)
    assert any(chunks[i][-20:].strip() in chunks[i + 1] for i in range(len(chunks) - 1))


def test_very_long_sentence_is_hard_split():
    chunks = split_text("x" * 1000, max_chars=300, overlap=0)
    assert all(len(c) <= 300 for c in chunks)
    assert "".join(chunks) == "x" * 1000


@pytest.mark.parametrize("max_chars,overlap", [(0, 0), (100, 100), (100, -1)])
def test_invalid_parameters_are_rejected(max_chars, overlap):
    with pytest.raises(ValueError):
        split_text("abc", max_chars=max_chars, overlap=overlap)


def test_chunk_notice_prefixes_title_and_numbers_chunks():
    notice = Notice(id="A1", title="Marché test", text="\n".join(["mot " * 50] * 10))
    chunks = chunk_notice(notice, max_chars=400, overlap=50)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.content.startswith("[Marché test]") for c in chunks)
    assert all(len(c.content) <= 400 for c in chunks)
