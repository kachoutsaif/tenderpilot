# TenderPilot

**Agent IA d'analyse d'appels d'offres publics.** TenderPilot lit les avis de marchés publics
(données ouvertes du BOAMP), répond aux questions d'une PME en **citant ses sources**, et, à terme,
décide s'il faut répondre (GO / À ÉTUDIER / NO-GO) puis rédige un brouillon de réponse.

> Statut : **semaine 1/6** : ingestion des avis + RAG de base avec citations vérifiées.

## Pourquoi ce projet

Une PME peut passer des heures à lire des avis de marché pour savoir si elle peut y répondre.
TenderPilot automatise la lecture et la qualification, sans jamais inventer une information :
chaque affirmation renvoie à un passage précis de l'avis.

## Architecture (semaine 1)

```
API BOAMP ──► ingestion ──► découpage ──► embeddings ──► PostgreSQL + pgvector
                                          (FastEmbed,          │
                                           local, gratuit)     │ recherche par similarité
                                                               ▼
Question ──► FastAPI /ask ──► top-k morceaux ──► LLM (Groq) ──► réponse + citations [n] vérifiées
```

| Brique | Choix | Pourquoi |
|---|---|---|
| API | FastAPI | Rapide, typée, documentation automatique sur `/docs` |
| Base vectorielle | PostgreSQL + pgvector | Une seule base pour les données et les vecteurs ; même techno en local et sur AWS (RDS) |
| Embeddings | FastEmbed, modèle multilingue | Tourne en local sur CPU, pas de coût, gère le français |
| LLM | gpt-oss-120b via Groq (API compatible OpenAI) | Gratuit pour démarrer ; fournisseur interchangeable par configuration |
| Qualité | pytest + ruff + GitHub Actions | Tests à chaque push, y compris contre un vrai pgvector |

## Démarrage rapide

Prérequis : Python 3.11+, Docker, une clé API gratuite [Groq](https://console.groq.com/keys).

```bash
# 1. Installer
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                    # puis mettez votre clé LLM_API_KEY

# 2. Lancer la base
docker compose up -d db

# 3. Regarder les vraies données BOAMP, puis les indexer
python scripts/inspect_boamp.py --limit 5
python scripts/ingest_boamp.py --days 14 --limit 200

# 4. Poser une question
python scripts/ask.py "Quels marchés concernent la maintenance informatique ?"

# 5. Ou via l'API
uvicorn tenderpilot.api.main:app --reload               # puis http://localhost:8000/docs
```

Sans réseau, vous pouvez tester avec 3 avis **fictifs** :
`python scripts/ingest_boamp.py --from-file tests/fixtures/boamp_sample.json`

Tout en Docker : `docker compose up --build` (l'API est alors sur http://localhost:8000).

## Tests

```bash
pytest                    # tests unitaires (sans base, sans clé API)
ruff check . && ruff format --check .

# test d'intégration avec un vrai pgvector, sur une base DÉDIÉE (le test supprime les tables)
docker compose up -d db
docker compose exec db createdb -U tender tenderpilot_test
TEST_DATABASE_URL=postgresql://tender:tender@localhost:5432/tenderpilot_test pytest -m integration
```

## Évaluation (semaine 2)

```bash
python scripts/find_notices.py nettoyage            # trouver les avis pour le jeu d'évaluation
python scripts/evaluate.py --label naif             # hit@k, recall@k, MRR (sans LLM)
python scripts/evaluate.py --label naif --with-llm  # + fidélité (LLM juge), hors sujet, latence
```
Le jeu de questions est dans `eval/questions.jsonl`, les résultats dans `eval/results/`.
Guide complet : `docs/SEMAINE_2.md`.

## Structure

```
src/tenderpilot/
  ingestion/boamp.py     # récupération et lecture des avis BOAMP
  ingestion/chunking.py  # découpage avec chevauchement
  ingestion/pdf.py       # lecture des PDF (dossiers de consultation)
  rag/embeddings.py      # texte -> vecteurs
  rag/prompt.py          # prompt + vérification des citations
  rag/llm.py             # client LLM compatible OpenAI
  rag/pipeline.py        # ingestion et question-réponse de bout en bout
  ingestion/eforms.py    # lecture du format européen eForms
  evaluation/            # métriques, juge de fidélité, lancement de l'évaluation
  store.py               # PostgreSQL + pgvector
  api/main.py            # API FastAPI
scripts/                 # inspect, ingest, ask
tests/                   # tests unitaires + intégration
docs/SEMAINE_1.md        # guide pas à pas de la semaine 1
```

## Feuille de route

- [x] **Semaine 1** : ingestion BOAMP, RAG avec citations vérifiées, API, tests, CI
- [ ] **Semaine 2** : jeu d'évaluation (~50 questions), métriques de fidélité, recherche hybride + reranking
- [ ] **Semaine 3** : agent LangGraph (qualifier → extraire → matcher → rédiger) + serveur MCP + validation humaine
- [ ] **Semaine 4** : CI/CD complète avec évaluation automatique qui bloque le déploiement si la qualité baisse
- [ ] **Semaine 5** : déploiement AWS (ECS/App Runner, RDS, S3, Secrets Manager) avec Terraform, monitoring, coût par requête
- [ ] **Semaine 6** : interface, démo vidéo, tableau de métriques

## Données

Les avis proviennent de l'API ouverte du BOAMP (Bulletin officiel des annonces des marchés publics) :
`https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records`.
Le fichier `tests/fixtures/boamp_sample.json` contient uniquement des avis fictifs pour les tests.
