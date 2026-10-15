"""Juge de fidélité (LLM-as-judge).

Un LLM relit la réponse, la découpe en affirmations, et vérifie pour chacune
si elle est soutenue par les sources. Fidélité = affirmations soutenues / total.

Limite à connaître : si le juge est le même modèle que celui qui répond, il peut
être indulgent avec lui-même. On peut choisir un autre modèle avec JUDGE_MODEL.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from tenderpilot.models import RetrievedChunk
from tenderpilot.rag.prompt import NOT_FOUND, format_sources

JUDGE_PROMPT = """Tu es un évaluateur strict. On te donne des SOURCES et une RÉPONSE.

1. Découpe la RÉPONSE en affirmations factuelles simples (un fait par affirmation :
   un acheteur, une date, une durée, un montant, une exigence, une qualification...).
2. Pour chaque affirmation, indique si elle est ENTIÈREMENT soutenue par les SOURCES.
   Une affirmation est non soutenue si elle ajoute une information absente des sources,
   même plausible (par exemple le sens d'un sigle qui n'est pas écrit dans les sources).
3. Ignore les formules de politesse et les phrases qui disent seulement ne pas savoir.
4. Écris les affirmations en français.

Réponds UNIQUEMENT avec un JSON de la forme :
{"claims": [{"claim": "...", "supported": true}, {"claim": "...", "supported": false}]}"""


@dataclass
class Judgement:
    faithfulness: float
    claims: list[dict]
    unsupported: list[str]


def build_judge_messages(question: str, answer: str, sources: list[RetrievedChunk]):
    user = (
        f"SOURCES :\n\n{format_sources(sources)}\n\n"
        f"QUESTION : {question}\n\nRÉPONSE À ÉVALUER :\n{answer}"
    )
    return [{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": user}]


def parse_judgement(raw: str) -> Judgement:
    """Lit le JSON du juge, même entouré de texte ou de balises ```json."""
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        raise ValueError("Le juge n'a pas renvoyé de JSON")
    data = json.loads(match.group(0))
    claims = [c for c in data.get("claims", []) if isinstance(c, dict) and c.get("claim")]
    if not claims:
        return Judgement(faithfulness=1.0, claims=[], unsupported=[])
    unsupported = [c["claim"] for c in claims if c.get("supported") is not True]
    return Judgement(
        faithfulness=(len(claims) - len(unsupported)) / len(claims),
        claims=claims,
        unsupported=unsupported,
    )


def judge_answer(llm, question: str, answer: str, sources: list[RetrievedChunk]) -> Judgement:
    if NOT_FOUND in answer and len(answer) < len(NOT_FOUND) + 40:
        return Judgement(faithfulness=1.0, claims=[], unsupported=[])
    messages = build_judge_messages(question, answer, sources)
    try:
        return parse_judgement(llm.complete(messages))
    except ValueError:  # JSON coupé ou absent (json.JSONDecodeError hérite de ValueError)
        return parse_judgement(llm.complete(messages))  # une seule nouvelle tentative


def says_not_found(answer: str) -> bool:
    return NOT_FOUND.lower().rstrip(".") in answer.lower()
