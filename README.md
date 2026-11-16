# TenderPilot

![CI](https://github.com/kachoutsaif/tenderpilot/actions/workflows/ci.yml/badge.svg)
![Infrastructure](https://github.com/kachoutsaif/tenderpilot/actions/workflows/infra.yml/badge.svg)

**Agent IA d'analyse d'appels d'offres publics français.** TenderPilot lit les avis de marchés
publics (données ouvertes du BOAMP), répond aux questions d'une PME en citant ses sources,
décide s'il faut répondre (GO / À ÉTUDIER / NO-GO) et rédige un brouillon de candidature,
**avec validation humaine** avant toute rédaction.

> RAG hybride · agent LangGraph · serveur MCP · évaluation automatisée qui bloque les
> régressions · infrastructure AWS en Terraform · Python 3.14

---

## Ce qu'il fait, sur un cas réel

Question posée dans **Claude Desktop**, qui utilise TenderPilot comme serveur MCP :

> « Quels marchés de nettoyage sont ouverts dans le Nord (59) ? »

1. `rechercher_avis(departements=["59"])` : recherche hybride filtrée en SQL ;
2. `lire_avis("26-98519")` : Ville de Maubeuge, nettoyage des locaux, **2 lots**, **avis rectifié**
   (date limite reportée au 09/11/2026), critères technique 11 pts / prix 8 pts / environnement 1 pt ;
3. qualification par **règles** : GO (secteur, zone, délai OK ; chiffre d'affaires et
   certifications « à vérifier » dans le dossier de consultation) ;
4. **l'utilisateur valide** ; alors seulement, rédaction d'un brouillon vérifié par un juge
   (fidélité 100 %), avec `[À COMPLÉTER]` partout où l'entreprise doit fournir l'information.

Chaque appel d'outil est tracé (une ligne JSON : outil, paramètres, durée, statut).

## Résultats mesurés

| Mesure | Valeur | Conditions |
|---|---|---|
| Recherche : hit@5 | **0,962** | corpus figé de 240 avis réels, 30 questions, reproductible au millième (PC = CI) |
| Recherche : recall@5 / MRR | 0,871 / 0,821 | même corpus |
| Apport de la recherche hybride | **+27 points** de hit@5 | vecteurs seuls : 0,692 (mesuré en CI, régression volontaire) |
| Fidélité des réponses | 0,967 | juge LLM (autre modèle que celui qui répond), échantillon de 5 questions |
| Brouillons de candidature | fidélité 96 % → 100 % | après une révision automatique bornée, 3 avis × 3 lancements |
| Tests | 150+ | unitaires + intégration sur un vrai PostgreSQL/pgvector |

## Architecture

```
API BOAMP ──► lecteur eForms ──► découpage ──► embeddings (FastEmbed, local) ──► PostgreSQL + pgvector
                                                                                  │ vecteurs + plein texte FR
Question ──► recherche hybride (RRF) ──► LLM (gpt-oss via Groq) ──► réponse + citations vérifiées
                                    │
Agent LangGraph : charger → extraire (preuves citées) → qualifier (RÈGLES) → VALIDATION HUMAINE
                  → rédiger → vérifier (juge) → réviser (1 fois max) → apprendre (leçons)
                                    │
Serveur MCP (6 outils, 1 ressource) ──► Claude Desktop, ou tout autre hôte MCP
```

## Décisions d'ingénierie

- **Le LLM lit, les règles décident.** Une décision GO / NO-GO doit être reproductible et
  justifiable : elle est prise par des règles Python testées, jamais par le LLM.
- **Des preuves vérifiées.** Chaque exigence extraite cite l'avis mot pour mot ; Python vérifie
  que la citation existe, sinon l'exigence est ignorée.
- **Validation humaine** (`interrupt()` LangGraph) avant toute rédaction, et instruction
  explicite aux hôtes MCP de demander l'accord de l'utilisateur.
- **Recherche hybride** (vecteurs + plein texte français, fusion RRF) : les embeddings ratent
  les sigles, noms de lieux et mots rares (« VRD », « Val-d'Oise », « traiteur »).
- **Ne jamais faire confiance aux paramètres choisis par un LLM** : `k` borné, départements
  validés, lot vérifié avant tout appel coûteux.
- **Données personnelles** : le corpus publié est audité et nettoyé (lignes de contact, noms,
  courriels, téléphones). Effet secondaire mesuré : la recherche s'est **améliorée**.

## Qualité : ce que la CI garantit

| Contrôle | Quand | Effet |
|---|---|---|
| ruff + 150+ tests (dont intégration pgvector) | chaque PR | bloque la fusion |
| **Porte qualité** : hit@5, recall@5, MRR sur corpus figé, seuil = référence − 0,02 | chaque PR | **bloque la fusion** si la recherche régresse |
| Terraform : fmt, validate, **Checkov** (sécurité) | chaque PR | bloque la fusion |
| Image Docker construite (et publiée sur ghcr.io depuis `main`) | chaque PR | bloque la fusion |
| Évaluation des réponses avec LLM (fidélité, hors sujet) | à la main et chaque lundi | informe (non déterministe) |

`main` est protégée : pull request obligatoire, tous les contrôles requis.

**Deux incidents qui ont rendu le système plus solide :**
1. *La porte bloque une vraie régression.* Retirer le plein texte fait passer hit@5 de 0,962 à
   0,692 : CI rouge, fusion impossible.
2. *La porte a donné une fausse alerte* (0,923 en CI contre 0,962 en local, sans changement de
   code) : la CI installait les dernières versions des bibliothèques. Correctif :
   `requirements-lock.txt`, Python 3.14 et pgvector 0.8.7 figés partout.

## Déploiement AWS (Terraform)

`infra/terraform/` décrit un déploiement **sous contrainte de budget** : un serveur EC2 (Docker :
API + PostgreSQL), un pare-feu ouvert à une seule IP sur un seul port, aucun SSH (Session
Manager), un rôle IAM au moindre privilège, les secrets dans Parameter Store (la clé LLM ne
passe jamais par Terraform), les journaux dans CloudWatch, une alerte de budget, IMDSv2 et
disque chiffré. Pas de NAT Gateway, de load balancer ni de RDS : facturés en continu.

Checkov : 58 règles respectées, **7 exceptions justifiées dans le code** (toutes par le coût
d'une démo). L'image de l'application est publiée sur `ghcr.io/kachoutsaif/tenderpilot` et
testée en conditions de déploiement (image, base, ingestion de 50 avis réels, API).

**État :** le code est validé en CI ; le déploiement réel attend un accès AWS. Détails, coûts
et choix de production : [docs/SEMAINE_5.md](docs/SEMAINE_5.md).

## Démarrage rapide

Prérequis : Python 3.14, Docker, une clé API Groq gratuite.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt && pip install -e . --no-deps
cp .env.example .env                                   # puis LLM_API_KEY=...
docker compose up -d db
python scripts/init_db.py
python scripts/ingest_boamp.py --days 14 --limit 200   # avis réels du BOAMP
python scripts/ask.py "Quels marchés concernent la maintenance informatique ?"
python scripts/qualify.py 26-98519                     # agent : qualification + brouillon
uvicorn tenderpilot.api.main:app                       # interface : http://localhost:8000
                                                       # API documentée : http://localhost:8000/docs
```

Ou avec l'image publiée : `docker pull ghcr.io/kachoutsaif/tenderpilot:latest`.
Serveur MCP pour Claude Desktop : [docs/SEMAINE_3_MCP.md](docs/SEMAINE_3_MCP.md).

## Limites connues

- Jeu d'évaluation de 30 questions, écrites en regardant les avis (biais de sélection).
- Le juge vérifie les faits, pas les liens entre eux (une affirmation fausse faite de faits vrais
  peut passer).
- Le texte écrit par un hôte MCP autour de nos outils échappe à nos garde-fous.
- La recherche renvoie toujours k résultats, même non pertinents (pas de seuil absolu).
- Le LLM ne connaît pas la date du jour : « quels marchés sont ouverts ? » repose sur son
  interprétation des dates citées. Correction prévue : filtrer en SQL sur la date limite,
  comme pour les départements (ce qui peut être une règle ne doit pas être confié au LLM).

## Documentation, semaine par semaine

| | Contenu |
|---|---|
| [Semaine 1](docs/SEMAINE_1.md) | ingestion BOAMP / eForms, RAG avec citations vérifiées, API, CI |
| [Semaine 2](docs/SEMAINE_2.md) | jeu d'évaluation, juge de fidélité, recherche hybride |
| [Semaine 3](docs/SEMAINE_3.md) | agent LangGraph, auto-correction, mémoire de leçons (Reflexion) |
| [Semaine 3 – MCP](docs/SEMAINE_3_MCP.md) | serveur MCP, Claude Desktop |
| [Semaine 4](docs/SEMAINE_4.md) | traçage, corpus figé, porte qualité, évaluation LLM |
| [Semaine 5](docs/SEMAINE_5.md) | Terraform, Checkov, image Docker, reproductibilité |

## Données

Avis issus de l'API ouverte du BOAMP (Bulletin officiel des annonces des marchés publics).
Le corpus d'évaluation publié est nettoyé des données personnelles. Le profil d'entreprise
utilisé pour les démonstrations (« Clair & Net Services ») est fictif.
