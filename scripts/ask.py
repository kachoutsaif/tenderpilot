"""Étape 3 : poser une question en ligne de commande.

python scripts/ask.py "Quels marchés concernent la maintenance informatique ?"
"""

from __future__ import annotations

import sys
import time

from tenderpilot.config import get_settings
from tenderpilot.rag.embeddings import FastEmbedEmbedder
from tenderpilot.rag.llm import OpenAICompatibleLLM
from tenderpilot.rag.pipeline import answer_question
from tenderpilot.store import PgVectorStore


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('Usage : python scripts/ask.py "votre question"')
    question = " ".join(sys.argv[1:])

    s = get_settings()
    embedder = FastEmbedEmbedder(s.embedding_model, cache_dir=s.embedding_cache_dir)
    store = PgVectorStore(s.database_url, dim=embedder.dim)
    llm = OpenAICompatibleLLM(api_key=s.llm_api_key, base_url=s.llm_base_url, model=s.llm_model)

    start = time.perf_counter()
    answer = answer_question(question, embedder, store, llm, k=s.top_k)
    elapsed = time.perf_counter() - start

    print(f"\n{answer.text}\n")
    print("Sources citées :")
    for c in answer.citations:
        print(f"  [{c.number}] avis {c.notice_id} — {c.title}")
        if c.url:
            print(f"      {c.url}")
    if answer.invalid_citations:
        print(f"  !! Citations inventées par le modèle : {answer.invalid_citations}")
    print(f"\n({elapsed:.1f} s, {len(answer.sources)} morceaux récupérés)")
    store.close()


if __name__ == "__main__":
    main()
