"""Transformation du texte en vecteurs (embeddings).

On utilise FastEmbed : il tourne en local sur CPU (pas de clé API, pas de coût),
et le modèle multilingue gère bien le français.
"""

from __future__ import annotations

import re
from typing import Protocol

import numpy as np

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# un mot, y compris les mots composés : L'HAY-LES-ROSES, accord-cadre
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_RUN_MIN_WORDS = 3  # à partir de 3 mots en majuscules d'affilée, c'est du texte « crié »
_LONE_MIN_CHARS = 5  # un mot isolé en majuscules plus court est sans doute un sigle (VRD, CAIH)


def normalize_case(text: str) -> str:
    """Met en minuscules le texte écrit EN MAJUSCULES, en gardant les sigles.

    Le tokenizer du modèle distingue les majuscules : « NETTOYAGE » est découpé en
    fragments qu'il connaît mal. Mesuré sur le jeu d'évaluation : similarité 0,16 avec
    le titre en majuscules, 0,55 avec le même titre en minuscules.
    Les sigles isolés (VRD, CFA, CNRS) sont gardés tels quels.
    """
    words = list(_WORD.finditer(text))
    to_lower: set[int] = set()
    run: list[int] = []
    for i, m in enumerate([*words, None]):
        if m is not None and m.group().isupper() and len(m.group()) > 1:
            run.append(i)
            continue
        if len(run) >= _RUN_MIN_WORDS:
            to_lower.update(run)
        else:
            to_lower.update(j for j in run if len(words[j].group()) >= _LONE_MIN_CHARS)
        run = []

    if not to_lower:
        return text
    parts: list[str] = []
    last = 0
    for i in sorted(to_lower):
        m = words[i]
        parts.append(text[last : m.start()])
        parts.append(m.group().lower())
        last = m.end()
    parts.append(text[last:])
    return "".join(parts)


class Embedder(Protocol):
    """Tout objet qui sait transformer des textes en vecteurs."""

    dim: int

    def embed(self, texts: list[str]) -> list[np.ndarray]: ...


class FastEmbedEmbedder:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        cache_dir: str | None = None,
        normalize: bool = True,
    ):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self.normalize = normalize
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = len(self.embed(["test"])[0])  # dimension lue sur le modèle, jamais codée en dur

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        # la normalisation ne touche que le texte VECTORISÉ : le texte stocké et montré
        # au LLM reste celui de l'avis. Elle s'applique aussi aux questions, par symétrie.
        if self.normalize:
            texts = [normalize_case(t) for t in texts]
        return [np.asarray(v, dtype=np.float32) for v in self._model.embed(texts)]
