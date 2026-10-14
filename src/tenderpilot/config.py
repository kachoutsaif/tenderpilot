"""Configuration lue depuis les variables d'environnement (ou le fichier .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from tenderpilot.rag.embeddings import DEFAULT_MODEL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://tender:tender@localhost:5432/tenderpilot"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    # modèle utilisé comme juge pendant l'évaluation (par défaut : le même que LLM_MODEL)
    judge_model: str | None = None

    embedding_model: str = DEFAULT_MODEL
    embedding_cache_dir: str | None = None

    chunk_size: int = 1200
    chunk_overlap: int = 200
    top_k: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
