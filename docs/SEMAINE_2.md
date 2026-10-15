# Semaine 2 : mesurer avant d'améliorer

**Objectif :** remplacer « ça a l'air de marcher » par des **chiffres**. À la fin de la semaine,
vous avez un jeu d'environ 50 questions, un score de référence pour le RAG naïf, et un
tableau qui montre le gain de chaque amélioration.

> Principe : on ne change qu'une chose à la fois, et on mesure à chaque fois.

---

## Ce que mesure `scripts/evaluate.py`

| Métrique | Question à laquelle elle répond | Coût |
|---|---|---|
| **hit@k** | Au moins un bon avis est-il dans les k résultats ? | gratuit |
| **recall@k** | Quelle part des bons avis est retrouvée ? (important pour les questions « liste ») | gratuit |
| **MRR** | Le bon avis arrive-t-il en tête ? (1 = premier, 0,5 = deuxième…) | gratuit |
| **fidélité** | Les affirmations de la réponse sont-elles toutes dans les sources ? (LLM juge) | 2 appels LLM / question |
| **hors_sujet_ok** | Le système dit-il « je ne trouve pas » quand l'info n'existe pas ? | 1 appel LLM / question |
| **citations invalides** | Le modèle cite-t-il des sources [n] qui n'existent pas ? | inclus |
| **latence moy. / p95** | Temps de réponse moyen et des 5 % les plus lents | inclus |

Les métriques de recherche sont calculées **par avis**, pas par morceau.

---

## Jour 1 : construire le jeu d'évaluation

Le fichier `eval/questions.jsonl` contient déjà 8 questions tirées de vos tests du 14/10.
Complétez-le jusqu'à **environ 50 questions**, réparties ainsi :

| Type (`kind`) | Exemple | Combien |
|---|---|---|
| `recherche` | « La ville de Nevers a-t-elle publié un marché de signalisation ? » | ~20 |
| `liste` | « Quels marchés de nettoyage sont ouverts ? » | ~10 |
| `filtre` | « Quels marchés de travaux ont une date limite avant le 15 novembre ? » | ~10 |
| `hors_sujet` | « Quel est le budget du stade olympique de Marseille ? » | ~5 |

Pour trouver les bonnes réponses, utilisez l'outil de recherche par mots-clés :

```bash
python scripts/find_notices.py nettoyage
python scripts/find_notices.py maintenance informatique
```

**Règle d'or : vérifiez chaque avis sur boamp.fr avant de l'ajouter dans `expected`.**
La vérité de référence, c'est vous qui la garantissez. Une erreur dans le jeu fausse tous les scores.

Écrivez les questions **comme un vrai utilisateur** (une PME), pas en recopiant le titre de l'avis :
sinon la recherche paraîtra meilleure qu'elle ne l'est.

> ⚠️ La base change si vous ré-ingérez d'autres jours. Pour comparer des configurations,
> gardez **la même base** (ne relancez pas l'ingestion entre deux mesures).

## Jour 2 : la mesure de référence

```bash
python scripts/evaluate.py --label naif                # recherche seule, rapide
python scripts/evaluate.py --label naif --with-llm     # + réponses et fidélité
```

Le script affiche un tableau par type de question, la liste des questions ratées et les
affirmations non soutenues. Le détail est enregistré dans `eval/results/`.

Notez les chiffres dans le README, dans un tableau « Résultats » :

| Configuration | hit@5 | recall@5 | MRR | fidélité | hors sujet OK | latence moy. |
|---|---|---|---|---|---|---|
| RAG naïf (semaine 1) | … | … | … | … | … | … |

Si l'API Groq renvoie des erreurs de limite (« rate limit »), augmentez la pause :
`--pause 3`.

## Jour 3 : analyser les échecs

Ouvrez le fichier de résultats et classez chaque échec :

- **le bon avis n'est pas retrouvé** → problème de recherche (embedding, découpage, mots exacts) ;
- **retrouvé mais mal classé** (MRR faible) → un reranker aidera ;
- **les questions `liste` ont un recall faible** → k trop petit ;
- **les questions `filtre` échouent** → il faut des filtres de métadonnées (dates, durées) ;
- **affirmations non soutenues** → le prompt doit être plus strict.

## Jours 4 et 5 : premières améliorations, une par une

Testez d'abord ce qui ne demande pas de code, en mesurant après chaque changement :

1. **k plus grand** : `python scripts/evaluate.py --label k10 --k 10`. Le recall des questions
   « liste » monte-t-il ? La latence et la fidélité bougent-elles ?
2. **morceaux plus petits** : dans `.env`, mettez `CHUNK_SIZE=500` et `CHUNK_OVERLAP=100`,
   videz la base, ré-ingérez **les mêmes jours**, puis `--label chunks500`.
   Rappel : le modèle d'embedding actuel ne lit qu'environ 128 tokens par morceau.

Envoyez-moi vos tableaux : on décidera ensemble de la suite (recherche hybride, filtres,
reranker), dans l'ordre que les chiffres justifient.

---

## Jour 6 : recherche hybride (plein texte + vecteurs)

**Pourquoi :** le diagnostic (`scripts/diagnose_misses.py`) a montré que 15 avis attendus sur 18
étaient au-delà du rang 20 en recherche vectorielle. Le modèle d'embedding comprend le thème
général mais rate les mots rares (« traiteur » au rang 17, alors que le titre contient le mot).

**Ce qui a été ajouté :**

| Élément | Rôle |
|---|---|
| colonne `tsv` (calculée par PostgreSQL) + index GIN | texte racinisé en français, sans accents ni majuscules |
| `store.search_fulltext` | score = somme des IDF des mots de la question présents (mots reliés par OU) |
| `rag/retrieval.py` | trois modes : `vector`, `text`, `hybrid` (fusion RRF des deux classements) |
| `RETRIEVAL_MODE` dans `.env` | choisit le mode utilisé par l'API et `ask.py` |

**Mesurer les trois modes sur la même base :**

```bash
python scripts/init_db.py                                # ajoute la colonne tsv (sans perte)
python scripts/evaluate.py --label casse_vector --mode vector
python scripts/evaluate.py --label texte --mode text
python scripts/evaluate.py --label hybride --mode hybrid
```

Si l'hybride gagne, mettez `RETRIEVAL_MODE=hybrid` dans `.env`.

**RRF en une phrase :** chaque morceau reçoit 1 / (60 + rang) dans chaque classement où il
apparaît, et on additionne. On fusionne des rangs, donc pas besoin de rendre comparables une
similarité cosinus et un score plein texte.

---

## Questions d'entretien sur cette semaine

- Quelle différence entre hit@k, recall@k et MRR ? Laquelle compte le plus pour votre cas ?
- Comment évaluer un RAG sans annotation humaine ? Quelles sont les limites du LLM-as-judge ?
- Pourquoi une citation valide n'implique-t-elle pas une réponse fidèle ? (votre exemple CAIH)
- Comment éviter que le jeu d'évaluation soit biaisé en faveur de votre système ?
- Pourquoi RRF plutôt qu'une moyenne pondérée des scores ? Que représente la constante 60 ?
- Pourquoi un mot comme « marché » ne doit-il presque pas compter dans le score plein texte ?
- Votre recherche plein texte n'a pas de normalisation par longueur (contrairement à BM25) :
  quel biais cela introduit-il ?
