"""Métriques de recherche : le bon avis est-il retrouvé, et à quel rang ?

On raisonne au niveau de l'avis (pas du morceau) : si deux morceaux du même avis
sont retrouvés, l'avis ne compte qu'une fois, à son meilleur rang.
"""

from __future__ import annotations

from collections.abc import Iterable


def unique_in_order(ids: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


def hit_at_k(retrieved: list[str], expected: set[str]) -> float:
    """1 si au moins un avis attendu est retrouvé, sinon 0."""
    return 1.0 if expected & set(retrieved) else 0.0


def recall_at_k(retrieved: list[str], expected: set[str]) -> float:
    """Part des avis attendus qui ont été retrouvés."""
    if not expected:
        return 0.0
    return len(expected & set(retrieved)) / len(expected)


def reciprocal_rank(retrieved: list[str], expected: set[str]) -> float:
    """1/rang du premier avis attendu (1 = premier, 0.5 = deuxième...), 0 si absent."""
    for rank, notice_id in enumerate(retrieved, start=1):
        if notice_id in expected:
            return 1.0 / rank
    return 0.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]
