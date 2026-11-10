"""API HTTP de TenderPilot.

Lancer en local :  uvicorn tenderpilot.api.main:app --reload
Documentation interactive : http://localhost:8000/docs
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from tenderpilot.api.ui import UI_HTML
from tenderpilot.config import get_settings
from tenderpilot.rag.pipeline import answer_question

app = FastAPI(
    title="TenderPilot",
    description="Analyse d'appels d'offres publics avec un RAG cité.",
    version="0.1.0",
)


# --- Dépendances (créées une seule fois, remplaçables dans les tests) ---


@lru_cache
def get_embedder():
    from tenderpilot.rag.embeddings import FastEmbedEmbedder

    s = get_settings()
    return FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)


@lru_cache
def get_store():
    from tenderpilot.store import PgVectorStore

    store = PgVectorStore(get_settings().database_url, dim=get_embedder().dim)
    store.init_schema()
    return store


@lru_cache
def get_llm():
    from tenderpilot.rag.llm import OpenAICompatibleLLM

    s = get_settings()
    # gpt-oss « réfléchit » avant d'écrire, et cette réflexion compte dans max_tokens :
    # sans réglage, les réponses longues (un tableau de 5 avis) étaient coupées net.
    options = {"reasoning_effort": "low"} if "gpt-oss" in s.llm_model else {}
    return OpenAICompatibleLLM(
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        model=s.llm_model,
        max_tokens=4000,
        **options,
    )


# --- Schémas d'entrée / sortie ---


class AskRequest(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=1000,
        examples=["Quels marchés de nettoyage ont une date limite en novembre ?"],
    )
    k: int = Field(default=5, ge=1, le=20)


class CitationOut(BaseModel):
    number: int
    notice_id: str
    title: str | None
    url: str | None
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    invalid_citations: list[int]


# --- Routes ---


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/notices")
def list_notices(limit: int = 20, store=Depends(get_store)):
    return store.list_notices(limit=min(max(limit, 1), 100))


@app.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest, embedder=Depends(get_embedder), store=Depends(get_store), llm=Depends(get_llm)
):
    try:
        result = answer_question(
            body.question, embedder, store, llm, k=body.k, mode=get_settings().retrieval_mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AskResponse(
        answer=result.text,
        citations=[CitationOut(**c.__dict__) for c in result.citations],
        invalid_citations=result.invalid_citations,
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def interface() -> str:
    """Interface web de démonstration."""
    return UI_HTML
