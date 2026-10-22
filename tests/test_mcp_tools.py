"""Outils MCP testés comme des fonctions Python, sans serveur ni protocole."""

import json

import pytest

from tenderpilot.agent.memory import InMemoryLessonStore
from tenderpilot.agent.profile import CompanyProfile
from tenderpilot.ingestion.boamp import record_to_notice
from tenderpilot.mcpserver.tools import TenderTools
from tenderpilot.rag.pipeline import ingest_notice

from .conftest import FakeLLM

EXTRACTION = json.dumps(
    {
        "resume": "Nettoyage",
        "chiffre_affaires_min": {
            "value": "300 000 euros",
            "quote": "Chiffre d'affaires annuel minimum de 300 000 euros",
        },
    }
)


@pytest.fixture
def tools(store, embedder, sample_records, tmp_path):
    for record in sample_records:
        notice = record_to_notice(record)
        if notice:
            ingest_notice(notice, embedder, store)
    llm = FakeLLM(EXTRACTION)
    t = TenderTools(
        store,
        CompanyProfile(nom="Test", activites=["nettoyage"], chiffre_affaires=1_000_000),
        InMemoryLessonStore(),
        embedder_factory=lambda: embedder,
        llm_factory=lambda: llm,
        retrieval_mode="hybrid",
        use_cache=False,
    )
    t.fake_llm = llm
    return t


def test_rechercher_avis_un_resultat_par_avis(tools):
    results = tools.rechercher_avis("maintenance des serveurs informatiques", k=2)
    assert results[0]["avis"] == "TEST-0002"
    assert len({r["avis"] for r in results}) == len(results) <= 2


def test_lire_avis(tools):
    assert tools.lire_avis("TEST-0001")["titre"].startswith("Prestations de nettoyage")
    assert "erreur" in tools.lire_avis("INCONNU")


def test_qualifier_sans_llm(tools):
    result = tools.qualifier_avis("TEST-0002")  # informatique : hors secteur
    assert result["decision_proposee"] == "NO_GO"
    assert "exigences" not in result
    assert tools.fake_llm.last_messages is None  # aucun token consommé


def test_qualifier_avec_extraction(tools):
    result = tools.qualifier_avis("TEST-0001", extraire_exigences=True)
    assert result["exigences"][0]["verifiee"] is True
    assert tools.fake_llm.last_messages is not None


def test_lecons(tools):
    assert "erreur" in tools.ajouter_lecon("court")
    added = tools.ajouter_lecon("Ne pas promettre de délai d'intervention.")
    assert tools.lister_lecons() == [
        {"id": added["id"], "texte": added["texte"], "source": "humain", "compteur": 1}
    ]


def test_brouillon_refuse_si_no_go(tools):
    result = tools.rediger_brouillon("TEST-0001", "NO_GO")
    assert "aucun brouillon" in result["message"]
    assert tools.fake_llm.last_messages is None


def test_serveur_expose_les_outils():
    pytest.importorskip("mcp")
    import asyncio

    from tenderpilot.mcpserver.server import mcp

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {
        "rechercher_avis",
        "lire_avis",
        "qualifier_avis",
        "rediger_brouillon",
        "lister_lecons",
        "ajouter_lecon",
    }


def test_appel_d_outil_a_travers_le_protocole(tools, monkeypatch):
    """Le même appel, mais en passant par la couche MCP (sérialisation JSON comprise)."""
    pytest.importorskip("mcp")
    import asyncio

    from tenderpilot.mcpserver import server

    monkeypatch.setattr(server, "tools", lambda: tools)
    result = asyncio.run(server.mcp.call_tool("qualifier_avis", {"avis": "TEST-0002"}))
    assert "NO_GO" in str(result)
