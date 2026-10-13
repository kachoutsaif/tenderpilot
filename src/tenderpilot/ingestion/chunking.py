"""Découpage du texte en morceaux (chunks) qui se chevauchent légèrement.

Pourquoi un chevauchement ? Si une information est coupée entre deux morceaux,
elle reste entière dans au moins l'un des deux.
"""

from __future__ import annotations

import re

from tenderpilot.models import Chunk, Notice

_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    """Coupe un paragraphe trop long par phrases, puis en dur si une phrase est trop longue."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(paragraph):
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def split_text(text: str, max_chars: int = 1200, overlap: int = 200) -> list[str]:
    """Regroupe les paragraphes en morceaux de `max_chars` caractères au plus."""
    if max_chars <= 0:
        raise ValueError("max_chars doit être positif")
    if not 0 <= overlap < max_chars:
        raise ValueError("overlap doit être compris entre 0 et max_chars - 1")

    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            units.extend(_split_long(paragraph, max_chars))
        else:
            units.append(paragraph)

    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + 1 + len(unit) > max_chars:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            # on repart du début d'un mot pour ne pas commencer au milieu
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1 :]
            current = f"{tail}\n{unit}".strip() if tail else unit
            if len(current) > max_chars:  # le chevauchement + l'unité dépassent : on garde l'unité
                current = unit
        else:
            current = f"{current}\n{unit}".strip()
    if current:
        chunks.append(current)
    return chunks


def chunk_notice(notice: Notice, max_chars: int = 1200, overlap: int = 200) -> list[Chunk]:
    """Découpe un avis. Chaque morceau commence par l'objet de l'avis pour garder le contexte."""
    prefix = f"[{notice.title}]\n"
    budget = max(max_chars - len(prefix), 200)
    pieces = split_text(notice.text, max_chars=budget, overlap=min(overlap, budget - 1))
    return [Chunk(notice_id=notice.id, index=i, content=prefix + p) for i, p in enumerate(pieces)]
