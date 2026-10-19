"""Extraction des exigences d'un avis par le LLM, avec preuves VÉRIFIÉES.

Le LLM doit recopier, pour chaque exigence, la phrase exacte de l'avis qui la justifie
(`quote`). On vérifie ensuite en Python que cette phrase existe vraiment dans l'avis :
une exigence sans preuve retrouvée est marquée `verified=False` et n'est pas utilisée
pour décider. C'est l'équivalent, pour l'extraction, de la vérification des citations [n].
"""

from __future__ import annotations

import json
import re
import unicodedata

from pydantic import BaseModel, Field, ValidationError

MAX_NOTICE_CHARS = 15_000  # au-delà, on tronque (limite de tokens de l'offre gratuite)


class Item(BaseModel):
    value: str
    quote: str = ""
    verified: bool = False


class Requirements(BaseModel):
    resume: str = ""
    lieu_execution: Item | None = None
    duree: Item | None = None
    montant_estime: Item | None = None
    criteres: list[Item] = Field(default_factory=list)
    certifications: list[Item] = Field(default_factory=list)
    chiffre_affaires_min: Item | None = None
    references_exigees: list[Item] = Field(default_factory=list)
    autres_exigences: list[Item] = Field(default_factory=list)

    def items(self) -> list[tuple[str, Item]]:
        """Toutes les exigences, avec le nom de leur champ."""
        out: list[tuple[str, Item]] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, Item):
                out.append((name, value))
            elif isinstance(value, list):
                out.extend((name, v) for v in value if isinstance(v, Item))
        return out


EXTRACTION_PROMPT = """Tu extrais les exigences d'UN avis de marché public pour une PME.

Pour chaque information trouvée, donne :
- "value" : l'information, reformulée brièvement ;
- "quote" : la phrase de l'avis qui la prouve, RECOPIÉE MOT POUR MOT (200 caractères max).

N'invente rien. Si une information n'est pas dans l'avis, mets null (ou une liste vide).
Les certifications sont des normes ou labels exigés (ISO, Qualibat...). Le chiffre
d'affaires minimum est un seuil de capacité financière exigé du candidat.

Réponds UNIQUEMENT avec un JSON de cette forme :
{
  "resume": "objet du marché en une phrase",
  "lieu_execution": {"value": "...", "quote": "..."} ou null,
  "duree": {"value": "...", "quote": "..."} ou null,
  "montant_estime": {"value": "...", "quote": "..."} ou null,
  "criteres": [{"value": "...", "quote": "..."}],
  "certifications": [{"value": "...", "quote": "..."}],
  "chiffre_affaires_min": {"value": "...", "quote": "..."} ou null,
  "references_exigees": [{"value": "...", "quote": "..."}],
  "autres_exigences": [{"value": "...", "quote": "..."}]
}"""


def normalize(text: str) -> str:
    """Minuscules, sans accents, espaces uniformisés : pour comparer des textes."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    """La citation figure-t-elle dans l'avis ? (tolère majuscules, accents, espaces, « … »)"""
    parts = [p for p in re.split(r"\.\.\.|…", normalize(quote)) if len(p.strip()) >= 8]
    haystack = normalize(text)
    return bool(parts) and all(p.strip() in haystack for p in parts)


def build_extraction_messages(title: str, text: str) -> list[dict[str, str]]:
    body = text[:MAX_NOTICE_CHARS]
    if len(text) > MAX_NOTICE_CHARS:
        body += "\n[... avis tronqué ...]"
    user = f"AVIS : {title}\n\n{body}"
    return [{"role": "system", "content": EXTRACTION_PROMPT}, {"role": "user", "content": user}]


def parse_requirements(raw: str) -> Requirements:
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        raise ValueError("Le LLM n'a pas renvoyé de JSON")
    try:
        return Requirements.model_validate(json.loads(match.group(0)))
    except ValidationError as exc:
        raise ValueError(f"JSON d'extraction invalide : {exc.error_count()} erreur(s)") from exc


def verify(requirements: Requirements, text: str) -> Requirements:
    """Marque chaque exigence comme vérifiée si sa citation est bien dans l'avis."""
    for _, item in requirements.items():
        item.verified = quote_in_text(item.quote, text)
    return requirements


def extract_requirements(llm, title: str, text: str) -> Requirements:
    """Extraction + vérification. Une nouvelle tentative si le JSON est illisible."""
    messages = build_extraction_messages(title, text)
    try:
        requirements = parse_requirements(llm.complete(messages))
    except (ValueError, json.JSONDecodeError):
        requirements = parse_requirements(llm.complete(messages))
    return verify(requirements, text)


def grounding_rate(requirements: Requirements) -> float | None:
    """Part des exigences dont la preuve a été retrouvée dans l'avis."""
    items = requirements.items()
    if not items:
        return None
    return sum(item.verified for _, item in items) / len(items)
