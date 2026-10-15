"""Client LLM compatible avec l'API OpenAI.

Par défaut on utilise Groq (rapide, offre gratuite), mais il suffit de changer
LLM_BASE_URL et LLM_MODEL pour passer à un autre fournisseur compatible.
"""

from __future__ import annotations

from typing import Protocol


class LLM(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


class OpenAICompatibleLLM:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 800,
        **request_options,
    ):
        from openai import OpenAI

        if not api_key:
            raise ValueError("LLM_API_KEY est vide : ajoutez votre clé dans le fichier .env")
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        # options propres au fournisseur, ex. reasoning_effort='low' pour gpt-oss
        self.request_options = request_options

    def complete(self, messages: list[dict[str, str]]) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **self.request_options,
        )
        return (response.choices[0].message.content or "").strip()
