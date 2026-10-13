"""Lecture des PDF (cahiers des charges, règlements de consultation).

Utilisé à partir de la semaine 1 (exercice) pour indexer les documents de consultation.
"""

from __future__ import annotations

from pathlib import Path

from tenderpilot.models import Notice


def pdf_to_text(path: str | Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        content = (page.extract_text() or "").strip()
        if content:
            pages.append(f"--- Page {number} ---\n{content}")
    return "\n\n".join(pages)


def pdf_to_notice(path: str | Path, notice_id: str, title: str | None = None) -> Notice:
    path = Path(path)
    return Notice(id=notice_id, title=title or path.stem, text=pdf_to_text(path))
