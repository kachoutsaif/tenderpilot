"""Cache de l'extraction des exigences : un avis n'est lu par le LLM qu'une seule fois.

Utile pour les mesures (les conditions comparées partent des mêmes exigences) et pour
économiser le quota de tokens (l'extraction est l'appel le plus long).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from tenderpilot.agent.extraction import Requirements, extract_requirements

DEFAULT_CACHE = Path("out/cache")


def make_cached_extract(cache_dir: Path = DEFAULT_CACHE):
    def cached_extract(llm, title: str, text: str) -> Requirements:
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        path = Path(cache_dir) / f"{key}.json"
        if path.exists():
            return Requirements.model_validate_json(path.read_text(encoding="utf-8"))
        requirements = extract_requirements(llm, title, text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(requirements.model_dump_json(indent=2), encoding="utf-8")
        return requirements

    return cached_extract
