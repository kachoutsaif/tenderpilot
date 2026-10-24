"""Traçage des appels d'outils : une ligne JSON par appel, sur stderr.

Pourquoi ? Pendant l'essai dans Claude Desktop, l'interface ne montrait pas les paramètres
des appels, et son journal n'enregistrait parfois même pas les appels. Un serveur ne doit
pas dépendre de l'hôte pour savoir ce qu'il a fait : il trace lui-même ses appels.

Exemple de ligne (une seule ligne en vrai, ici coupée pour la lecture) :
    {"evenement": "appel_outil", "id": "3f9c2a1b", "outil": "rechercher_avis",
     "parametres": {"question": "nettoyage", "departements": ["59"]},
     "statut": "ok", "duree_ms": 412, "resultat": {"elements": 5}}

Une ligne JSON (et non une phrase) se filtre avec grep/jq, et s'envoie telle quelle à un
service de journaux (CloudWatch en semaine 5).

Ce qu'on ne trace PAS : le contenu des résultats (un brouillon fait plusieurs pages, et un
avis peut contenir des noms de personnes). Seulement leur forme : nombre d'éléments, clés.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

log = logging.getLogger("tenderpilot.mcp.trace")

MAX_PARAM_CHARS = 200  # un commentaire ou une question très longue est tronqué


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_PARAM_CHARS:
        return value[:MAX_PARAM_CHARS] + "…"
    if isinstance(value, list):
        return [_short(v) for v in value]
    return value


def summarize(result: Any) -> tuple[str, dict[str, Any]]:
    """(statut, résumé) d'un résultat d'outil, sans son contenu."""
    if isinstance(result, dict) and "erreur" in result:
        return "erreur", {"erreur": _short(str(result["erreur"]))}
    if isinstance(result, list):
        return "ok", {"elements": len(result)}
    if isinstance(result, dict):
        return "ok", {"cles": sorted(result)}
    return "ok", {"type": type(result).__name__}


def traced(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Décorateur : trace chaque appel de `fn` (paramètres, durée, statut).

    `functools.wraps` conserve le nom, la docstring et la signature de `fn` : le SDK MCP
    s'en sert pour construire la description et le schéma JSON de l'outil.
    Une exception est tracée PUIS relancée : le SDK la transforme en erreur MCP.
    """
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        record: dict[str, Any] = {
            "evenement": "appel_outil",
            "id": uuid.uuid4().hex[:8],
            "outil": fn.__name__,
            "parametres": {name: _short(value) for name, value in bound.arguments.items()},
        }
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            record.update(statut="exception", exception=f"{type(exc).__name__}: {exc}")
            raise
        else:
            record["statut"], record["resultat"] = summarize(result)
            return result
        finally:
            record["duree_ms"] = round((time.perf_counter() - start) * 1000)
            log.info(json.dumps(record, ensure_ascii=False, default=str))

    return wrapper
