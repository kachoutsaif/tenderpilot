# Semaine 3 : l'agent de qualification

**Objectif :** passer d'un système qui *répond à des questions* à un agent qui *fait un travail* :
lire un avis, décider s'il faut y répondre, et préparer un brouillon, avec un humain qui valide.

## Le graphe

```
charger ──► extraire ──► qualifier ──► validation humaine ──► rédiger ──► vérifier ──► fin
   │                                          │
   └── avis introuvable ──► fin               └── NO-GO confirmé ──► fin
```

| Étape | Qui fait le travail | Pourquoi |
|---|---|---|
| charger | Python (base) | l'avis complet, reconstruit depuis l'enregistrement BOAMP d'origine |
| extraire | **LLM** | lire un texte libre : durée, critères, certifications, chiffre d'affaires minimum… |
| (vérifier) | Python | chaque exigence doit citer l'avis mot pour mot ; sinon elle est ignorée |
| qualifier | **règles Python** | décision reproductible, explicable et testable |
| validation | **humain** | `interrupt()` : le graphe s'arrête et attend votre réponse |
| rédiger | **LLM** | brouillon de note de candidature, `[À COMPLÉTER]` quand une info manque |
| vérifier | **LLM juge** | fidélité du brouillon (sections 1 à 3) aux exigences et au profil |

**Trois choix de conception à savoir défendre :**

1. **Un avis à la fois.** En semaine 2, le LLM a attribué à un avis une information d'un autre
   (« accord-cadre composite »). Ici, le contexte ne contient qu'un seul avis.
2. **Le LLM lit, les règles décident.** Une décision GO / NO-GO doit être la même à chaque fois
   et justifiable devant un client. Un LLM ne garantit ni l'un ni l'autre.
3. **Des preuves vérifiées.** Le LLM recopie la phrase qui justifie chaque exigence ; Python
   vérifie qu'elle existe dans l'avis. Le « taux de preuves retrouvées » mesure l'extraction.

## Les contrôles

| Contrôle | ko bloquant (NO-GO) | ko non bloquant (À ÉTUDIER) |
|---|---|---|
| secteur | aucune activité du profil dans l'objet ou les mots-clés | – |
| zone | – | département hors zone d'intervention |
| délai | date limite dépassée | moins de `delai_minimum_jours` |
| chiffre d'affaires | CA du profil < seuil exigé | – |
| certifications | – | certification exigée non détenue |

Un contrôle « inconnu » (information attendue mais introuvable, comme la date limite) donne
aussi À ÉTUDIER. Un contrôle « à vérifier » (exigence absente de l'avis, souvent écrite dans le
DCE : chiffre d'affaires, certifications) ne change pas la décision, mais il est repris dans
les points à vérifier du brouillon.

**Pourquoi ce statut ?** Premier essai (26-98519) : sans seuil dans l'avis, le contrôle
affichait « OK », et le brouillon concluait « aucun point à vérifier », ce qui est faux.
Mais classer ces cas en « inconnu » rendrait presque tous les avis À ÉTUDIER, car le BOAMP
détaille rarement les capacités exigées. « À vérifier » sépare les deux questions :
*peut-on y aller ?* et *que reste-t-il à contrôler ?*

## Premier essai : le brouillon inventait

Sur 26-98519, le premier brouillon ajoutait des attentes absentes de l'avis (« reporting
mensuel », « reconduction selon le DCE », « entretien quotidien ») et des pratiques absentes
du profil (« produits biodégradables »). Corrections : un prompt plus strict (section 1 limitée
aux exigences, `[À COMPLÉTER]` pour tout ce que le profil ne dit pas), et une étape de
vérification qui réutilise le juge de la semaine 2.

## Deuxième essai : la vérification trouve, la révision corrige

Le juge a relevé 3 affirmations non soutenues (fidélité 75 %) :
- « entretien quotidien et nettoyage approfondi » : encore une invention ;
- « nous intervenons dans le département 59 » : **vrai**, mais la zone n'était pas transmise
  au rédacteur ni au juge. C'est un oubli de notre côté, révélé par le juge (corrigé) ;
- « nous nous engageons sur 48 mois » : un engagement que l'entreprise doit décider elle-même.

D'où une **boucle d'auto-correction** : si des affirmations ne sont pas soutenues, l'étape
« réviser » reçoit leur liste et doit les supprimer ou les remplacer par `[À COMPLÉTER]`,
puis le brouillon est revérifié. La boucle est **bornée** (1 révision par défaut) : un agent
qui peut boucler sans limite peut aussi consommer des tokens sans limite.

## Mémoire de leçons : l'agent apprend de ses erreurs (pattern Reflexion)

La boucle vérifier ⇄ réviser corrige une erreur **pendant** une exécution, mais l'agent oublie
tout ensuite : il refait la même erreur sur l'avis suivant et paie une révision de plus.

```
erreurs relevées par le juge ──► réflexion (LLM) ──► leçon GÉNÉRALE ──► table lessons
leçon donnée par l'humain    ──────────────────────────────────────────┘        │
                                                                                 ▼
                                        prompt du rédacteur (10 meilleures leçons, humain d'abord)
```

- **Généraliser** : « entretien quotidien » (erreur précise) devient « Ne pas indiquer de
  fréquence d'intervention absente de l'avis » (valable pour tous les avis).
- **Pas de doublons** : le LLM voit les leçons existantes et renforce l'une d'elles
  (compteur) au lieu d'en écrire une nouvelle équivalente.
- **Transparence** : `python scripts/lessons.py` liste les leçons, `delete N` en supprime une.
  Une mauvaise leçon peut dégrader l'agent : on doit pouvoir la voir et la retirer.

### Mesurer l'apprentissage : protocole entraînement / test

```bash
python scripts/lessons.py clear
python scripts/measure_drafts.py --set test  --memory off   --label sans_memoire
python scripts/measure_drafts.py --set train --memory learn --label apprentissage
python scripts/measure_drafts.py --set test  --memory use   --label avec_memoire
```

Les leçons sont apprises sur 3 avis (train) et évaluées sur 3 AUTRES avis (test), comme en
machine learning : sinon on mesurerait la mémorisation, pas l'apprentissage. L'extraction est
mise en cache pour que les deux conditions rédigent à partir des mêmes exigences.
Indicateur principal : la fidélité du **premier** brouillon, avant révision.

**Limite à dire en entretien :** 3 avis de test, c'est peu, et le LLM varie d'un lancement à
l'autre ; `--repeat 3` relance chaque avis pour moyenner.

### Résultats (19/10, 3 avis de test × 3 lancements, gpt-oss-120b)

| Condition | Erreurs au 1er jet (9 brouillons) | Brouillons révisés | Fidélité finale |
|---|---|---|---|
| sans mémoire | 5 | 5 | 96 % |
| 2 leçons apprises automatiquement | 5 | 4 | 100 % |
| 5 leçons, dont 3 écrites à partir des erreurs mesurées | 5 | 4 | 100 % |

Ce que montrent ces chiffres :

1. **Un seul lancement trompe.** Avec 1 lancement par avis, la mémoire semblait apporter
   +2,7 points ; avec 3 lancements, l'écart disparaît : c'était la variabilité du LLM.
2. **Les leçons apprises automatiquement ne visaient pas les erreurs fréquentes** : 3 avis
   d'entraînement ne contenaient pas ces erreurs. L'agent n'apprend que ce qu'il a vu.
3. **Les leçons ciblées fonctionnent... et les erreurs se déplacent** (effet « tape-taupe ») :
   zone 5 → 0, pratiques environnementales 2 → 0, mais engagements sur la durée 1 → 3.
   Le total ne dit rien : il faut regarder la RÉPARTITION des erreurs.
4. **La cause était dans la structure du prompt** : on demandait « une réponse par exigence »,
   y compris pour « durée : 48 mois ». Correction : le CONTEXTE (lieu, durée, montant) est
   séparé des EXIGENCES À TRAITER. Principe : *ce qui peut être une règle ne doit pas être
   une leçon.* (Mesure de ce correctif : à venir.)
5. **Évaluer coûte cher** : ces mesures ont épuisé le quota quotidien de Groq (200 000 tokens).

## Cas réel : l'avis 26-98519 comparé à boamp.fr

En suivant cet avis de la source jusqu'à l'agent (boamp.fr → API → texte → base → agent), on a
trouvé deux informations importantes que l'agent ignorait :

| Information | API | Texte | Base | Agent (avant) |
|---|---|---|---|---|
| 2 lots (CTM/Police ; CMA/Maison Sport-Santé) | oui | oui | oui | **non** |
| Rectificatif : date limite reportée, pièces modifiées | oui | oui | oui | **non** |

L'ingestion était correcte : l'information se perdait à l'extraction, faute de case
« lots ». Méthode : **remonter le flux jusqu'à l'endroit où l'information disparaît.**

Correction (`agent/structure.py`) : lots et modifications sont lus **sans LLM**, car notre
lecteur eForms les écrit dans un format fixe. Les lots sont transmis au rédacteur (une PME
peut répondre à un seul lot ; la durée peut différer d'un lot à l'autre) et un 6e contrôle
« rectificatif » (À VÉRIFIER) signale les modifications à relire.

Autres points vus sur ce cas : la date limite arrive en UTC (11:00) et s'affiche en heure de
Paris (12:00) ; `annonce_lie` est vide, donc aucune ancienne version n'a été supprimée ; l'avis
contient le nom et les coordonnées d'un agent public, que le projet n'indexe pas (RGPD).

## Lancer l'agent

```bash
pip install -e ".[dev]"                 # installe LangGraph
python scripts/qualify.py 26-98519      # Maubeuge, nettoyage des locaux
python scripts/qualify.py 26-98342      # un marché informatique : NO-GO attendu (hors secteur)
```

Le profil fictif est dans `profiles/exemple_proprete.toml`. Le rapport est écrit dans `out/`.

## Questions d'entretien sur cette semaine

- Pourquoi un graphe (LangGraph) plutôt qu'une boucle « l'agent choisit ses outils » ?
- À quoi sert le checkpointer ? Que se passe-t-il si le programme s'arrête pendant la validation ?
- Pourquoi la décision GO / NO-GO n'est-elle pas confiée au LLM ?
- Comment mesurer la qualité de l'extraction ? (taux de preuves retrouvées, et ses limites)
- Une exigence peut avoir une preuve valide mais une valeur mal comprise : comment le détecter ?
- Quelle différence entre se corriger (Évaluateur-Optimiseur) et apprendre (Reflexion) ?
- Pourquoi une mémoire de leçons plutôt qu'un fine-tuning ? Quels sont ses risques ?
- Pourquoi séparer avis d'entraînement et avis de test pour mesurer l'apprentissage ?
