"""Traçage des appels d'outils MCP : une ligne JSON par appel."""

import inspect
import json
import logging

import pytest

from tenderpilot.mcpserver.tracing import summarize, traced


def trace_lines(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name.endswith(".trace")]


@traced
def chercher(question: str, k: int = 5, departements: list[str] | None = None) -> list:
    """Docstring conservée."""
    return ["a", "b"]


@traced
def en_erreur(avis: str) -> dict:
    return {"erreur": f"Avis {avis} introuvable"}


@traced
def plante(avis: str) -> dict:
    raise RuntimeError("base arrêtée")


def test_signature_et_docstring_conservees():
    # le SDK MCP construit le schéma de l'outil à partir de la signature et de la docstring
    assert list(inspect.signature(chercher).parameters) == ["question", "k", "departements"]
    assert chercher.__doc__ == "Docstring conservée."
    assert chercher.__name__ == "chercher"


def test_appel_reussi(caplog):
    caplog.set_level(logging.INFO, logger="tenderpilot.mcp.trace")
    assert chercher("nettoyage", departements=["59"]) == ["a", "b"]
    (line,) = trace_lines(caplog)
    assert line["outil"] == "chercher"
    assert line["parametres"] == {"question": "nettoyage", "k": 5, "departements": ["59"]}
    assert line["statut"] == "ok" and line["resultat"] == {"elements": 2}
    assert isinstance(line["duree_ms"], int) and len(line["id"]) == 8


def test_erreur_metier_tracee(caplog):
    caplog.set_level(logging.INFO, logger="tenderpilot.mcp.trace")
    en_erreur("INCONNU")
    (line,) = trace_lines(caplog)
    assert line["statut"] == "erreur"
    assert "INCONNU" in line["resultat"]["erreur"]


def test_exception_tracee_puis_relancee(caplog):
    caplog.set_level(logging.INFO, logger="tenderpilot.mcp.trace")
    with pytest.raises(RuntimeError):
        plante("26-98519")
    (line,) = trace_lines(caplog)
    assert line["statut"] == "exception"
    assert line["exception"] == "RuntimeError: base arrêtée"


def test_le_contenu_n_est_pas_trace():
    statut, resume = summarize({"brouillon": "x" * 10_000, "avis": "26-98519"})
    assert statut == "ok" and resume == {"cles": ["avis", "brouillon"]}  # pas le texte


def test_parametre_long_tronque(caplog):
    caplog.set_level(logging.INFO, logger="tenderpilot.mcp.trace")
    chercher("x" * 1000)
    (line,) = trace_lines(caplog)
    assert len(line["parametres"]["question"]) == 201  # 200 caractères + « … »


def test_trace_a_travers_le_protocole(caplog, monkeypatch):
    """Appel réel via la couche MCP : la ligne de trace est bien écrite."""
    pytest.importorskip("mcp")
    import asyncio

    from tenderpilot.mcpserver import server

    class FakeTools:
        def lister_lecons(self):
            return [{"id": 1, "texte": "Ne pas inventer."}]

    monkeypatch.setattr(server, "tools", lambda: FakeTools())
    caplog.set_level(logging.INFO, logger="tenderpilot.mcp.trace")
    asyncio.run(server.mcp.call_tool("lister_lecons", {}))
    (line,) = trace_lines(caplog)
    assert line["outil"] == "lister_lecons" and line["resultat"] == {"elements": 1}
