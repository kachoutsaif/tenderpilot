"""Construction du prompt et vérification des citations.

Règle d'or : le modèle ne répond qu'à partir des sources fournies, et chaque
affirmation porte un numéro de source [n] que l'on peut vérifier.
"""

from __future__ import annotations

import re

from tenderpilot.models import Citation, RetrievedChunk

NOT_FOUND = "Je ne trouve pas cette information dans les avis indexés."

SYSTEM_PROMPT = f"""Tu es un assistant qui analyse des appels d'offres publics pour une PME.

Règles :
1. Réponds UNIQUEMENT à partir des sources numérotées fournies.
2. Après chaque affirmation, indique la source entre crochets, par exemple [1] ou [2][3].
3. N'invente jamais une date, un montant, un acheteur ou une exigence.
4. Si les sources ne contiennent pas la réponse, réponds exactement : « {NOT_FOUND} »
5. Réponds en français, de façon concise et structurée."""

_CITATION = re.compile(r"\[(\d+)\]")


def format_sources(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for n, chunk in enumerate(chunks, start=1):
        title = chunk.title or "sans titre"
        blocks.append(f"[{n}] (avis {chunk.notice_id} — {title})\n{chunk.content}")
    return "\n\n".join(blocks)


def build_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    user = (
        f"Sources :\n\n{format_sources(chunks)}\n\n"
        f"Question : {question}\n\n"
        "Réponds en citant les sources avec [n]."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def group_by_notice(citations: list[Citation]) -> list[tuple[list[int], Citation]]:
    """Regroupe les citations qui pointent vers le même avis : [4][5] -> un seul avis."""
    groups: dict[str, tuple[list[int], Citation]] = {}
    for c in citations:
        if c.notice_id in groups:
            groups[c.notice_id][0].append(c.number)
        else:
            groups[c.notice_id] = ([c.number], c)
    return list(groups.values())


def extract_citations(
    answer: str, chunks: list[RetrievedChunk], excerpt_chars: int = 240
) -> tuple[list[Citation], list[int]]:
    """Retrouve les [n] cités. Renvoie (citations valides, numéros invalides)."""
    numbers = sorted({int(n) for n in _CITATION.findall(answer)})
    valid: list[Citation] = []
    invalid: list[int] = []
    for n in numbers:
        if 1 <= n <= len(chunks):
            c = chunks[n - 1]
            valid.append(
                Citation(
                    number=n,
                    notice_id=c.notice_id,
                    title=c.title,
                    url=c.url,
                    excerpt=c.content[:excerpt_chars],
                )
            )
        else:
            invalid.append(n)
    return valid, invalid
