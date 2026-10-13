"""Transformation du texte en vecteurs (embeddings).

On utilise FastEmbed : il tourne en local sur CPU (pas de clé API, pas de coût),
et le modèle multilingue gère bien le français.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    """Tout objet qui sait transformer des textes en vecteurs."""

    dim: int

    def embed(self, texts: list[str]) -> list[np.ndarray]: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: str | None = None):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = len(self.embed(["test"])[0])  # dimension lue sur le modèle, jamais codée en dur

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.asarray(v, dtype=np.float32) for v in self._model.embed(texts)]
