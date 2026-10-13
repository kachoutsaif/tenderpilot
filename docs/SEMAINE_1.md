# Semaine 1 : données + RAG de base avec citations

**Objectif de la semaine :** à la fin, vous posez une question en français sur des appels d'offres
réels et vous obtenez une réponse dont chaque affirmation renvoie à un avis précis. Le tout tourne
en local avec Docker, et les tests passent automatiquement sur GitHub à chaque push.

Le squelette du code est fourni. Votre travail : **le faire tourner, le comprendre ligne par ligne,
le vérifier sur les vraies données, et faire les exercices**. C'est cette compréhension qu'on vous
demandera en entretien.

---

## Jour 1 : installation et premier lancement

1. Créez un dépôt GitHub **public** `tenderpilot` et poussez ce code :
   ```bash
   git init && git add . && git commit -m "Initialisation : RAG de base semaine 1"
   git branch -M main
   git remote add origin https://github.com/kachoutsaif/tenderpilot.git
   git push -u origin main
   ```
2. Ouvrez l'onglet **Actions** sur GitHub : la CI doit passer au vert (lint + tests + test pgvector).
3. Suivez le « Démarrage rapide » du README jusqu'à `docker compose up -d db`.
4. Lancez `pytest` en local : tout doit passer.

✅ **Validé quand :** la CI est verte sur GitHub et `pytest` passe chez vous.

## Jour 2 : comprendre les vraies données

1. Lancez `python scripts/inspect_boamp.py --limit 10 --save data/sample.json`.
2. Comparez les champs affichés avec `FIELD_CANDIDATES` dans `src/tenderpilot/ingestion/boamp.py`.
   **Le code a été écrit sans accès à l'API.** Si un champ a un autre nom, ajoutez-le dans la liste.
3. Regardez les valeurs du champ `nature` : repérez celle des **avis de marché** (appels d'offres
   ouverts), par opposition aux avis d'attribution.
4. Ouvrez `data/sample.json` et lisez le champ `donnees` d'un avis : c'est là que se trouvent les
   détails (critères, durée, lots...).

✅ **Validé quand :** le texte construit pour un avis (affiché en fin de script) contient l'objet,
l'acheteur, la date limite et des détails lisibles.

## Jour 3 : indexer

1. Ingérez uniquement les avis de marché, par exemple :
   `python scripts/ingest_boamp.py --days 14 --limit 300 --where 'nature="APPEL_OFFRE"'`
   (remplacez par la vraie valeur trouvée au jour 2).
2. Le premier lancement télécharge le modèle d'embedding (une seule fois).
3. Notez le temps d'ingestion et le nombre de morceaux : ce sont vos premières métriques.

Si FastEmbed ne reconnaît pas le modèle, affichez la liste des modèles disponibles :
`python -c "from fastembed import TextEmbedding; print([m['model'] for m in TextEmbedding.list_supported_models()])"`
et choisissez un modèle **multilingue** dans `EMBEDDING_MODEL`.

## Jour 4 : interroger et observer

1. Posez 10 questions variées avec `scripts/ask.py` :
   - par secteur (« Quels marchés concernent le nettoyage ? »)
   - par date (« Quels avis ont une date limite avant fin novembre ? »)
   - par critère (« Quels marchés exigent une certification ISO ? »)
   - une question **hors sujet** : le système doit répondre qu'il ne trouve pas.
2. Pour chaque réponse, vérifiez à la main que les citations [n] disent vraiment ce qui est affirmé.
3. Lancez l'API (`uvicorn ...`) et testez `/ask` depuis http://localhost:8000/docs.

✅ **Validé quand :** vous avez noté pour chaque question si la réponse était juste, partiellement
juste ou fausse. **Gardez ce fichier** : c'est le début de votre jeu d'évaluation de la semaine 2.

## Jour 5 : exercices (à coder vous-même)

1. **Filtre par score.** `answer_question` accepte `min_score`. Ajoutez `MIN_SCORE` dans la
   configuration et testez l'effet de 0.3 sur la question hors sujet. Écrivez un test.
2. **Ingestion de PDF.** `ingestion/pdf.py` sait lire un PDF. Ajoutez une route
   `POST /documents` (upload d'un fichier) qui l'indexe. Écrivez un test avec un petit PDF.
3. **Questions sur les dates.** Les questions « avant fin novembre » marchent mal avec la seule
   recherche par similarité. Pourquoi ? Notez votre explication : c'est la motivation de la
   recherche hybride et des filtres de métadonnées de la semaine 2.

---

## Ce que vous devez savoir expliquer en entretien

- Pourquoi découper les documents en morceaux, et pourquoi avec un **chevauchement** ?
- Qu'est-ce qu'un **embedding**, et pourquoi la **similarité cosinus** ?
- Pourquoi un index **HNSW** dans pgvector (et quel compromis vitesse / précision) ?
- Comment le système **évite d'inventer** : prompt contraint, réponse « je ne trouve pas »,
  vérification des numéros de citation (`invalid_citations`).
- Pourquoi les dépendances sont **injectées** (embedder, store, llm) : tests sans base ni clé API.
- Pourquoi deux variables `DATABASE_URL` et `TEST_DATABASE_URL`.

## Critères de fin de semaine

- [ ] Dépôt GitHub public, CI verte
- [ ] Au moins 200 avis réels indexés
- [ ] 10 questions testées et notées à la main
- [ ] Exercices 1 et 2 faits, avec leurs tests
- [ ] Un commit par étape, avec des messages clairs
