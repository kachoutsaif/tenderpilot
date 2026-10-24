"""Serveur MCP (Model Context Protocol) de TenderPilot.

Lancer :  python -m tenderpilot.mcpserver.server     (transport stdio)

Un client MCP (Claude Desktop, MCP Inspector, scripts/mcp_client_demo.py...) démarre ce
programme et lui parle en JSON-RPC sur l'entrée et la sortie standard.

RÈGLE ABSOLUE en stdio : ne jamais écrire sur la sortie standard (pas de print) ; elle est
réservée aux messages du protocole. Les journaux vont sur stderr.

Les docstrings des outils ne sont pas de la simple documentation : le client les envoie au
LLM, qui s'en sert pour CHOISIR l'outil et ses arguments. Ce sont des prompts.
"""

from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from tenderpilot.mcpserver.tools import TenderTools
from tenderpilot.mcpserver.tracing import traced

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE = PROJECT_ROOT / "profiles" / "exemple_proprete.toml"
log = logging.getLogger("tenderpilot.mcp")

# Annotations : indications pour le client (ex. demander confirmation avant une action).
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

mcp = MCPServer(
    "tenderpilot",
    # le SDK configure lui-même les journaux à sa création (niveau INFO par défaut) :
    # WARNING masque le détail des requêtes HTTP des bibliothèques (Hugging Face, httpx)
    log_level="WARNING",
    instructions=(
        "Outils d'analyse des appels d'offres publics français (BOAMP) pour une PME. "
        "Flux conseillé : rechercher_avis -> lire_avis ou qualifier_avis -> présenter la "
        "décision proposée à l'utilisateur -> rediger_brouillon UNIQUEMENT après son accord."
    ),
)


@lru_cache
def tools() -> TenderTools:
    """Les dépendances sont créées au premier appel d'outil, pas au démarrage du serveur."""
    from tenderpilot.agent.memory import PgLessonStore
    from tenderpilot.agent.profile import load_profile
    from tenderpilot.config import get_settings
    from tenderpilot.store import PgVectorStore

    s = get_settings()
    profile_path = Path(os.environ.get("TENDERPILOT_PROFILE", DEFAULT_PROFILE))
    store = PgVectorStore(s.database_url, dim=384)
    log.info("Base connectée, profil : %s", profile_path)

    def embedder():
        from tenderpilot.rag.embeddings import FastEmbedEmbedder

        return FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)

    def llm():
        from tenderpilot.rag.llm import OpenAICompatibleLLM

        options = {"reasoning_effort": "low"} if "gpt-oss" in s.llm_model else {}
        return OpenAICompatibleLLM(
            api_key=s.llm_api_key,
            base_url=s.llm_base_url,
            model=s.llm_model,
            max_tokens=4000,
            **options,
        )

    return TenderTools(
        store,
        load_profile(profile_path),
        PgLessonStore(store.conn),
        embedder_factory=embedder,
        llm_factory=llm,
        retrieval_mode=s.retrieval_mode,
    )


# --- Outils : ce que l'assistant peut FAIRE ---
# @traced (sous @mcp.tool) écrit une ligne JSON par appel sur stderr : outil, paramètres,
# durée, statut. Dans Claude Desktop, ces lignes arrivent dans mcp-server-tenderpilot.log.


@mcp.tool(annotations=READ_ONLY)
@traced
def rechercher_avis(
    question: str, k: int = 5, departements: list[str] | None = None
) -> list[dict[str, Any]] | dict[str, Any]:
    """Cherche des avis de marchés publics (BOAMP) correspondant à une question en français.

    Exemple : « marchés de nettoyage de vitres », « assurance pour une commune ».
    departements : codes de département pour filtrer, ex. ["59"] pour le Nord, ["59", "62"]
    pour le Nord et le Pas-de-Calais. Mettez le lieu ici plutôt que dans la question.
    Renvoie au plus k avis (10 au maximum) : identifiant, titre, extrait, lien.
    Ne consomme aucun token LLM.
    """
    return tools().rechercher_avis(question, k, departements)


@mcp.tool(annotations=READ_ONLY)
@traced
def lire_avis(avis: str) -> dict[str, Any]:
    """Renvoie le texte complet d'un avis à partir de son identifiant (ex. « 26-98519 »)."""
    return tools().lire_avis(avis)


@mcp.tool(annotations=READ_ONLY)
@traced
def qualifier_avis(avis: str, extraire_exigences: bool = False) -> dict[str, Any]:
    """Propose une décision GO / A_ETUDIER / NO_GO pour l'entreprise, avec le détail des contrôles.

    Contrôles : secteur, zone d'intervention, délai, chiffre d'affaires, certifications,
    rectificatif. Renvoie aussi les lots (une PME peut ne répondre qu'à un lot) et les
    modifications si l'avis a été rectifié.
    La décision vient de règles explicites, pas d'un LLM. Avec extraire_exigences=true,
    les exigences de l'avis sont d'abord extraites par un LLM (1 appel, mis en cache),
    chacune avec sa preuve. Présente toujours le résultat à l'utilisateur pour validation.
    """
    return tools().qualifier_avis(avis, extraire_exigences)


@mcp.tool(annotations=WRITES)
@traced
def rediger_brouillon(
    avis: str, decision_validee: str, commentaire: str = "", lot: str | None = None
) -> dict[str, Any]:
    """Rédige un brouillon de note de candidature pour un avis.

    À n'appeler QU'APRÈS que l'utilisateur a explicitement validé la décision
    (decision_validee = GO ou A_ETUDIER) : c'est la validation humaine de l'agent.
    commentaire : consignes de l'utilisateur pour ce brouillon.
    lot : numéro du lot visé (ex. « 1 ») si l'utilisateur ne répond qu'à un lot ; omis = tous.
    Le brouillon est vérifié automatiquement (fidélité) et corrigé une fois si besoin.
    Ne modifiez pas le brouillon renvoyé : présentez-le tel quel, les [À COMPLÉTER] sont
    à remplir par l'entreprise. Coûteux : 3 à 6 appels LLM.
    """
    return tools().rediger_brouillon(avis, decision_validee, commentaire, lot)


@mcp.tool(annotations=READ_ONLY)
@traced
def lister_lecons() -> list[dict[str, Any]]:
    """Liste la mémoire de leçons : les consignes injectées dans chaque brouillon."""
    return tools().lister_lecons()


@mcp.tool(annotations=WRITES)
@traced
def ajouter_lecon(texte: str) -> dict[str, Any]:
    """Ajoute une consigne durable pour tous les futurs brouillons, à la demande de l'utilisateur.

    Exemple : « Ne pas promettre de délai d'intervention. » (10 à 250 caractères)
    """
    return tools().ajouter_lecon(texte)


# --- Ressource : ce que l'assistant peut LIRE ---


@mcp.resource("profil://entreprise")
def profil_entreprise() -> str:
    """Profil de l'entreprise : activités, zone, chiffre d'affaires, certifications, références."""
    path = Path(os.environ.get("TENDERPILOT_PROFILE", DEFAULT_PROFILE))
    return path.read_text(encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)  # jamais stdout en stdio
    log.setLevel(logging.INFO)  # nos messages, sans le détail des requêtes HTTP des bibliothèques
    mcp.run()  # transport stdio par défaut


if __name__ == "__main__":
    main()
