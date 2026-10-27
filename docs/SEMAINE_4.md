# Semaine 4 : CI/CD avec porte qualité

**Objectif :** chaque modification est mesurée automatiquement, et une baisse de qualité
est bloquée avant d'arriver sur `main`.

| Étape | Contenu | État |
|---|---|---|
| 1 | Traçage des appels d'outils MCP | fait |
| 2 | Évaluation de la recherche dans la CI, sans LLM (hit@k, MRR) | fait |
| 3 | Porte qualité : la CI échoue si le score passe sous un seuil | à faire |
| 4 | Évaluation complète avec LLM, à la main ou une fois par semaine | à faire |
| 5 | Branches et pull requests, porte qualité obligatoire | à faire |

## Étape 1 : traçage des appels d'outils

**Constat (essai dans Claude Desktop, 23-24/10) :** l'interface ne montrait pas les paramètres
des appels, et son journal notait `method="tools/call" params { metadata: undefined }`, puis,
le lendemain, plus rien du tout. Impossible de savoir si Claude avait utilisé le filtre
`departements`. **Un serveur ne doit pas dépendre de l'hôte pour savoir ce qu'il a fait.**

**Solution :** le décorateur `@traced` (`mcpserver/tracing.py`) écrit une ligne JSON par appel
sur stderr :

```json
{"evenement": "appel_outil", "id": "3f9c2a1b", "outil": "rechercher_avis",
 "parametres": {"question": "nettoyage de locaux", "k": 5, "departements": ["59"]},
 "statut": "ok", "resultat": {"elements": 5}, "duree_ms": 412}
```

Choix à savoir expliquer :
- **JSON plutôt qu'une phrase** : se filtre avec `grep` ou `jq`, et s'envoie tel quel à un
  service de journaux (CloudWatch en semaine 5).
- **Trois statuts** : `ok`, `erreur` (erreur métier renvoyée à l'hôte, par exemple un avis
  introuvable) et `exception` (bug ou panne : tracée, puis relancée).
- **On trace la forme du résultat, pas son contenu** : un brouillon fait plusieurs pages, et
  un avis peut contenir le nom d'un agent public (RGPD). Les paramètres longs sont tronqués.
- **stderr, jamais stdout** : en stdio, stdout est réservé au protocole.
- **`functools.wraps`** : le SDK MCP construit le schéma de l'outil à partir de la signature
  et de la docstring ; le décorateur doit les conserver (vérifié par un test).

Lire les traces de Claude Desktop depuis Ubuntu :

```bash
LOG=/mnt/c/Users/saifk/AppData/Local/Claude/logs/mcp-server-tenderpilot.log
grep '"appel_outil"' "$LOG" | tail -5
grep '"appel_outil"' "$LOG" | sed 's/^[^{]*//' | jq -c '{outil, parametres, duree_ms}'
```

(`sed` retire le préfixe ajouté par Claude Desktop avant le JSON ; `jq` s'installe avec
`sudo apt install jq`.)

**Premières traces (24/10), et ce qu'elles ont appris :**

| Outil | Paramètres | Durée | Lecture |
|---|---|---|---|
| rechercher_avis | « marchés de nettoyage de locaux », k=15, ["59"] | 3 115 ms | 1er appel : chargement du modèle d'embedding |
| rechercher_avis | « …propreté, entretien ménager, vitrerie », k=10, ["59"] | 68 ms | modèle déjà en mémoire : 45 fois plus rapide |
| lire_avis | 26-98519 | 6 ms | lecture en base seulement |

- Le filtre `departements` est bien utilisé : la description de l'outil a suffi à guider Claude.
- Claude choisit lui-même `k` (15) : rien ne l'empêchait de demander 1 000 résultats.
  Correction : `k` est borné à 10 (`MAX_RESULTS`), comme le texte renvoyé par `lire_avis`.
- Le coût du démarrage à froid (3 s) est visible : sur AWS (semaine 5), il faudra charger le
  modèle au démarrage du service, pas au premier appel d'un utilisateur.

## Étape 2 : évaluer la recherche dans la CI, sans LLM

**Corpus figé** (`eval/corpus.jsonl`, `scripts/export_corpus.py`) : les 40 avis attendus par
les questions + 200 avis « bruit » choisis de façon déterministe (tri par md5 de
l'identifiant). Texte produit par notre lecteur, courriels et téléphones masqués (96 avis
sur 240 concernés : notre lecteur les laissait dans le texte libre, découvert en auditant le
fichier avant publication).

**Évaluation** (`scripts/evaluate_ci.py`) : base vidée → corpus chargé avec le vrai modèle
d'embedding → 30 questions → hit@5, recall@5, MRR → tableau Markdown dans la page de la CI
(`$GITHUB_STEP_SUMMARY`) et JSON détaillé en artefact.

Pourquoi sans LLM ? Gratuit (pas de quota Groq), rapide, et surtout **reproductible** :
même code + même corpus = même score. Une porte qualité qui varie au hasard bloquerait des
modifications sans raison.

Garde-fou : le script vide la base indiquée, donc il refuse toute base dont le nom ne finit
pas par `_test` ou `_eval`.

En local :

```bash
docker compose exec db createdb -U tender tenderpilot_eval      # une seule fois
EVAL_DATABASE_URL=postgresql://tender:tender@localhost:5432/tenderpilot_eval \
    python scripts/evaluate_ci.py
```

**Score du corpus et score de la base locale ne sont pas égaux (24/10) :**

| | Avis | hit@5 | recall@5 | MRR |
|---|---|---|---|---|
| base locale | 300 | 0,962 | 0,866 | 0,779 |
| corpus figé | 240 | 0,923 | 0,846 | 0,788 |

Enquête : 24 questions sur 30 ont des résultats différents, mais une seule change de verdict
(q15). Comparaison avis par avis (nombre de morceaux et de caractères) : 96 avis diffèrent,
**tous à cause du masquage**, aucun pour une autre raison. Causes de l'écart : le masquage
modifie le texte (donc les vecteurs) de 40 % des avis, et retirer 60 avis change la rareté
des mots (IDF) du score plein texte.

Conséquence : la porte qualité compare un corpus **à lui-même** (avant / après une
modification) ; sa référence est donc le score du corpus, pas celui de la base locale.
Leçon : un score n'a de sens qu'avec la version exacte des données qui l'ont produit.

**Données personnelles : deuxième audit (24/10).** En vérifiant ce que masquait la règle
« téléphone », on a vu les noms juste avant : « nomContact : Pamela L... », « Mme T... -
Tél ». Notre lecteur recopie un bloc contact (102 lignes `nomContact` dans le corpus), et ce
corpus était déjà publié sur `main` (PR n° 2). Correction : les lignes de contact sont
supprimées en entier, les noms après une civilité (M., Mme, Monsieur, Madame) deviennent
`[personne]`. « Monsieur le Maire » est gardé : une fonction n'est pas un nom.
Leçon : auditer ce qu'on publie, et ne pas croire une documentation sans la vérifier (la
nôtre affirmait que le lecteur écartait les contacts). À faire en semaine 5 : appliquer le
même nettoyage dès l'ingestion, pour que la base elle-même ne stocke pas ces données.
