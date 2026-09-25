# Notes de développement

🇬🇧 [English version](DEVELOPMENT.md)

Ce document retrace l'évolution du projet Pokémon RAG au fil du
développement. Il ne cherche pas à présenter une architecture finale
figée : il conserve les principales étapes, les problèmes rencontrés,
les expérimentations et les décisions qui ont progressivement façonné le
système.

Un document de synthèse séparé sera produit lorsque le projet sera
terminé.

------------------------------------------------------------------------

## 1. Point de départ : expérimenter un RAG local

Le projet a commencé comme une expérimentation autour d'un pipeline de
Retrieval-Augmented Generation exécuté localement.

Pokémon a été choisi comme domaine de travail parce qu'il combine
naturellement deux types d'informations :

-   un corpus documentaire important, notamment via Poképédia ;
-   des données fortement structurées, disponibles notamment via
    PokéAPI.

Le domaine est suffisamment grand pour faire apparaître de vrais
problèmes de retrieval, tout en restant facile à vérifier manuellement.

L'objectif initial était donc de construire un système capable de
répondre à des questions détaillées à partir de Poképédia, avec des
modèles locaux servis par LM Studio.

------------------------------------------------------------------------

## 2. Construction du corpus Poképédia

La première étape a consisté à télécharger et nettoyer les pages
Poképédia afin de constituer un corpus local exploitable.

Le pipeline général est progressivement devenu :

``` text
Poképédia
    ↓
Téléchargement
    ↓
Pages brutes
    ↓
Nettoyage
    ↓
Documents structurés
    ↓
Découpage en chunks
    ↓
ChromaDB
```

Le corpus représente plus d'un millier de documents et plusieurs
dizaines de milliers de chunks.

Dès le nettoyage, il est apparu important de conserver la structure des
articles. Les documents indexés gardent donc des informations permettant
notamment d'identifier le Pokémon, le document source et la section
d'origine.

Cette décision s'est révélée importante par la suite, lorsque le
retrieval a commencé à exploiter directement la structure des sections.

------------------------------------------------------------------------

## 3. Premier pipeline de retrieval

La première architecture RAG combinait recherche sémantique et recherche
lexicale :

``` text
Question
   ↓
Recherche vectorielle
   +
BM25
   ↓
Reciprocal Rank Fusion
   ↓
CrossEncoder
   ↓
Contexte
   ↓
LLM
```

La combinaison des embeddings, de BM25 et d'un reranker a donné de
meilleurs résultats qu'une recherche vectorielle seule.

Cependant, les premiers essais ont montré qu'obtenir des chunks
individuellement pertinents ne garantissait pas encore un contexte
fiable.

Deux problèmes sont rapidement devenus importants :

1.  des résultats provenant du mauvais Pokémon pouvaient être récupérés
    ;
2.  un chunk pertinent pouvait ne contenir qu'une partie de
    l'information nécessaire.

------------------------------------------------------------------------

## 4. Limiter la recherche au Pokémon concerné

Lorsqu'une question mentionne explicitement un seul Pokémon, une
recherche globale peut récupérer des passages concernant d'autres
Pokémon utilisant un vocabulaire similaire.

Une règle stricte a donc été ajoutée :

> Lorsqu'un seul Pokémon est identifié sans ambiguïté, le retrieval
> reste limité à ce Pokémon.

Cette contrainte est conservée lors des éventuelles nouvelles recherches
effectuées par le système.

Le comportement général est devenu :

``` text
Un Pokémon identifié
        ↓
Recherche limitée à ce Pokémon

Aucun Pokémon identifié
        ↓
Recherche globale

Plusieurs Pokémon ou ambiguïté
        ↓
Traitement adapté au contexte
```

Cette étape a réduit une source importante de contamination du contexte.

------------------------------------------------------------------------

## 5. Exploiter la structure des sections

Les articles Poképédia sont organisés en sections et sous-sections. Une
information peut être répartie sur plusieurs chunks appartenant à une
même section logique.

Le retrieval a donc évolué pour tenir compte de cette structure.

Lorsqu'un résultat pertinent est sélectionné, le système peut retrouver
les autres chunks appartenant exactement à la même section, plutôt que
de simplement prendre les chunks voisins dans l'index.

L'objectif est de reconstruire un contexte cohérent :

``` text
Résultat pertinent
      ↓
Identification de sa section
      ↓
Expansion de la section
      ↓
Contexte documentaire complet
```

Cette évolution a amélioré la cohérence du contexte fourni au
générateur.

------------------------------------------------------------------------

## 6. Grounding et mécanisme de retry

Une réponse produite à partir d'un contexte récupéré peut malgré tout
introduire une information absente des sources ou contredire celles-ci.

Un contrôle de grounding a donc été ajouté après la génération.

Il distingue plusieurs situations :

``` text
PASS
CONTRADICTION
UNSUPPORTED
INSUFFICIENT
```

Cette étape a également conduit à introduire un mécanisme de retry.
Selon le type d'échec, le système peut tenter une nouvelle génération ou
rechercher un meilleur contexte.

Cette expérimentation a cependant fait apparaître une distinction
importante :

> Une réponse peut être parfaitement ancrée dans son contexte sans pour
> autant répondre correctement à la question.

------------------------------------------------------------------------

## 7. Expérimentation autour de la suffisance du contexte

Pour traiter ce problème, une étape séparée de vérification de la
suffisance du contexte a été expérimentée.

L'idée était de distinguer deux questions :

``` text
Grounding
→ La réponse est-elle supportée par le contexte ?

Suffisance
→ Le contexte contient-il réellement ce qu'il faut pour répondre ?
```

En pratique, cette nouvelle validation pouvait elle-même produire des
faux positifs et ajoutait un appel supplémentaire au modèle local.

Cette étape a renforcé une idée qui deviendra importante pour la suite
du projet : ajouter des validations LLM ne corrige pas nécessairement un
problème situé plus tôt dans la chaîne de retrieval.

------------------------------------------------------------------------

## 8. Améliorer la représentation utilisée pour la recherche

Une partie des erreurs de retrieval provenait de la représentation des
chunks dans l'index.

Le système a donc été modifié pour distinguer :

-   le texte source, conservé pour être fourni au générateur ;
-   une représentation enrichie, utilisée pour les embeddings et la
    recherche.

La représentation de recherche contient davantage de contexte
structurel, notamment l'identité du Pokémon et la position du passage
dans l'article.

Cette séparation permet d'améliorer la recherche sans polluer le texte
documentaire finalement transmis au LLM.

Après reconstruction de l'index, le corpus contient environ 36 000
chunks.

------------------------------------------------------------------------

## 9. Limites du RAG pour les données structurées

Au fil des tests, certaines questions se sont révélées mal adaptées au
RAG.

Des demandes concernant par exemple :

-   une évolution ;
-   des capacités apprises à certains niveaux ;
-   des CT disponibles dans une version ;
-   une méthode d'apprentissage ;

correspondent davantage à des requêtes relationnelles qu'à de la
recherche documentaire.

Faire passer systématiquement ces questions par le RAG ajoutait
plusieurs risques :

-   retrieval incomplet ;
-   mauvaise section ;
-   filtrage approximatif par le LLM ;
-   perte d'informations présentes dans des tableaux ;
-   latence inutile.

Le projet a donc commencé à évoluer d'un RAG pur vers une architecture
hybride.

------------------------------------------------------------------------

## 10. Introduction des données PokéAPI

Les données PokéAPI ont été téléchargées et importées dans SQLite.

L'objectif n'était pas de reproduire toute la structure de PokéAPI dans
le code applicatif, mais de disposer localement d'une source
relationnelle suffisamment complète pour répondre de manière
déterministe aux questions structurées.

Au cours de cette étape, le schéma importé a été progressivement
complété lorsque certaines relations nécessaires n'étaient pas encore
disponibles localement.

Cette phase a également montré l'intérêt de valider le schéma réel de
PokéAPI plutôt que de compenser ses particularités dans les couches
supérieures du système.

------------------------------------------------------------------------

## 11. Intégration du Pokédex personnalisé

En parallèle, un tableur bilingue est utilisé pour stocker des
informations spécifiques au projet qui ne sont pas directement
disponibles dans PokéAPI.

Il contient les espèces du Pokédex national ainsi que les formes
pertinentes pour le projet et diverses informations complémentaires.

Un mapping explicite avec PokéAPI a été ajouté afin de relier sans
ambiguïté les lignes du tableur aux entités de la base officielle.

Cette étape a permis de préparer la fusion entre les données
personnalisées et les données PokéAPI.

------------------------------------------------------------------------

## 12. Passage à une base SQLite unifiée

À un moment du développement, le runtime utilisait à la fois SQLite et
le tableur via Pandas.

Cette organisation créait deux chemins d'accès différents aux données
structurées.

L'architecture a donc été simplifiée autour d'une seule base :

``` text
PokéAPI
   ↓
Base intermédiaire
   │
   ├──── Données du Pokédex personnalisé
   ↓
pokemon.db
```

Le tableur reste une source de construction, mais n'est plus consulté
directement à l'exécution.

La règle est désormais simple :

> Les requêtes structurées du runtime passent par `pokemon.db`.

Cette unification réduit les dépendances du runtime et fournit une
interface unique pour les données structurées.

------------------------------------------------------------------------

## 13. Création du moteur de requêtes structurées

Le système ne laisse pas le LLM générer du SQL librement.

À la place, une question structurée est transformée en une opération
sémantique contrainte, puis validée par Python avant l'exécution d'une
requête SQL prédéfinie.

Le principe est :

``` text
Question
   ↓
Interprétation
   ↓
Plan structuré validé
   ↓
Fonction SQL prédéfinie
   ↓
Résultat déterministe
```

Les premières familles de requêtes concernent les évolutions et les
capacités, notamment l'apprentissage par niveau, les CT et les méthodes
d'apprentissage.

Ce choix conserve la compréhension du langage naturel tout en évitant la
génération arbitraire de SQL.

------------------------------------------------------------------------

## 14. Stabilisation des évolutions et des formes

Les évolutions ont constitué l'une des premières parties complexes du
moteur structuré.

Les données peuvent dépendre d'une forme, d'une version, d'un objet,
d'un niveau ou d'autres conditions.

Plusieurs problèmes ont été découverts au cours de cette phase,
notamment autour de la distinction entre :

-   l'espèce ;
-   la forme du Pokémon ;
-   la version du jeu.

Le moteur a progressivement été corrigé pour conserver ces notions
séparées et éviter qu'une règle associée à une forme particulière ne
soit appliquée à une autre.

Cette phase a aussi servi à renforcer les tests de régression du moteur
structuré.

------------------------------------------------------------------------

## 15. Extension aux requêtes sur les capacités

Le moteur structuré a ensuite été étendu aux principales questions
portant sur l'apprentissage des capacités.

Il peut notamment traiter :

``` text
capacités apprises par niveau
CT
méthodes d'apprentissage
```

Cette étape a confirmé que les données PokéAPI étaient plus adaptées que
le RAG pour ce type de questions.

Elle a également permis d'identifier et de corriger plusieurs hypothèses
faites initialement sur le schéma relationnel.

------------------------------------------------------------------------

## 16. Apparition des trois routes d'exécution

À ce stade, l'architecture a pris une forme plus générale avec trois
chemins :

``` text
                     Question
                        │
                     Routeur
              ┌─────────┼─────────┐
              │         │         │
        STRUCTURED      RAG     HYBRID
              │         │         │
         pokemon.db  Poképédia   combinaison
```

### STRUCTURED

Utilisé lorsque la réponse peut être obtenue directement depuis les
données relationnelles.

### RAG

Utilisé lorsque la réponse nécessite du contenu documentaire, explicatif
ou contextuel.

### HYBRID

Utilisé lorsque les deux sources peuvent contribuer à la réponse.

Cette séparation constitue un changement important par rapport au RAG
initial : le système ne cherche plus à faire résoudre toutes les
questions par le même pipeline.

------------------------------------------------------------------------

## 17. Refactorisation de la structure du projet

Avec l'augmentation du nombre de composants, le projet a été réorganisé
autour d'un package `src/pokemon_rag`.

Les responsabilités ont été séparées entre plusieurs ensembles :

``` text
graph/       orchestration et routage
structured/  interrogation de pokemon.db
rag/         retrieval et validations documentaires
scripts/     construction et ingestion des données
tests/       régressions
```

Les chemins vers les données, les bases et les index ont également été
centralisés.

Cette refactorisation a permis de clarifier la séparation entre :

-   construction des données ;
-   runtime ;
-   tests.

------------------------------------------------------------------------

## 18. Premier travail ciblé sur les performances

Une fois les principales routes fonctionnelles, les mesures de temps ont
montré que SQLite n'était pas le principal goulot d'étranglement.

Les requêtes SQL s'exécutaient généralement en quelques dizaines de
millisecondes, tandis que certains appels aux modèles locaux prenaient
plusieurs secondes.

Le premier composant ciblé a été le routeur.

### Fast Router

Un routeur déterministe a été ajouté devant le routeur LLM.

Son principe est volontairement conservateur :

``` text
Question
   ↓
Fast Router
   ├── décision certaine → route directe
   └── incertitude       → routeur LLM
```

Les questions structurées suffisamment explicites peuvent ainsi être
dirigées vers `STRUCTURED` sans appel au modèle.

Le routeur LLM reste disponible comme fallback pour les questions
ambiguës, documentaires ou hybrides.

Sur les cas structurés simples, cette modification a réduit le temps du
routage de plusieurs secondes à quelques dizaines de millisecondes.

------------------------------------------------------------------------

## 19. Fast Parser pour les requêtes structurées

Après l'optimisation du routeur, les mesures ont montré que le principal
coût restant sur une requête structurée simple venait du parser
sémantique.

Un Fast Parser déterministe a donc été ajouté devant le parser LLM.

L'architecture devient :

``` text
Question
   ↓
Fast Router
   ↓
Fast Parser
   ├── plan certain → SQL
   └── incertitude  → parser LLM → SQL
```

Le Fast Parser ne cherche pas à comprendre toutes les formulations
possibles.

Il prend uniquement la main lorsqu'il peut identifier de manière
suffisamment sûre l'opération et ses paramètres. Dans les autres cas, le
comportement LLM existant est conservé.

Cette approche poursuit le même principe que le Fast Router : réserver
les modèles aux situations où leur capacité d'interprétation apporte
réellement quelque chose.

------------------------------------------------------------------------

## 20. Suppression du Sufficiency Checker

Le pipeline RAG utilisait jusqu'ici un contrôle de suffisance du contexte avant l'appel au modèle principal. Ce contrôle nécessitait un appel LLM supplémentaire et faisait en partie doublon avec le Grounding Checker exécuté après génération.

Le Grounding Checker distingue déjà plusieurs situations :

- `PASS` : la réponse est correctement supportée par le contexte ;
- `INSUFFICIENT` : le contexte récupéré ne permet pas de répondre correctement ;
- `UNSUPPORTED` : certaines affirmations de la réponse ne sont pas supportées par le contexte ;
- `CONTRADICTION` : la réponse contredit le contexte.

Le Sufficiency Checker a donc été retiré du chemin d'exécution RAG et HYBRID.

Le pipeline devient :

Retrieval → Construction du contexte → Génération → Grounding

Le Grounding Checker devient ainsi le mécanisme central permettant de déterminer si la réponse peut être acceptée ou si un retry est nécessaire.

En particulier :

- `INSUFFICIENT` déclenche un nouveau retrieval ;
- `UNSUPPORTED` ou `CONTRADICTION` déclenchent une nouvelle génération à partir du contexte existant ;
- `PASS` termine normalement l'exécution.

Des tests d'intégration du graphe ont été ajoutés afin de vérifier les principaux chemins de retry, l'absence de boucle infinie et le maintien du scope Pokémon lors d'un nouveau retrieval.

La suppression du Sufficiency Checker permet également d'éviter un appel LLM systématique avant chaque génération RAG/HYBRID.
## 21. Chargement paresseux du pipeline de retrieval

L'initialisation du système de retrieval était auparavant effectuée dès l'import du module `retrieval.py`.

Cette initialisation comprend notamment :

- l'ouverture de la collection Chroma ;
- le chargement du modèle d'embeddings ;
- le chargement du reranker ;
- le chargement du corpus ;
- la construction des index par Pokémon et par section ;
- la construction de l'index BM25.

Ce comportement imposait donc le coût complet d'initialisation du RAG à tout module important `retrieval.py`, y compris lorsque le retrieval n'était pas réellement utilisé.

Cela affectait particulièrement les tests du graphe et des nodes, qui pouvaient nécessiter plusieurs dizaines de secondes alors que leurs dépendances de retrieval étaient mockées.

L'initialisation a été déplacée dans une fonction dédiée et est maintenant effectuée de manière paresseuse lors du premier accès réel au pipeline de retrieval.

L'import des modules du graphe ne déclenche donc plus automatiquement le chargement du corpus et des modèles.

Les tests d'intégration utilisant réellement le retrieval déclenchent explicitement cette initialisation avant de vérifier directement le contenu du corpus ou de ses index.

Cette modification conserve le comportement du pipeline de retrieval tout en réduisant fortement le coût des tests qui n'en ont pas besoin.


## 22. Séparation des politiques de retry

Le graphe utilisait initialement un compteur unique `retry_count` pour limiter les retries après le Grounding Checker.

Ce compteur était partagé entre deux mécanismes différents :

- le nouveau retrieval déclenché après une décision `INSUFFICIENT` ;
- la nouvelle génération déclenchée après une décision `UNSUPPORTED` ou `CONTRADICTION`.

Cette architecture empêchait certains enchaînements légitimes. Par exemple, un retry de retrieval pouvait consommer l'unique budget disponible puis empêcher une correction de la réponse générée, et inversement.

Le compteur unique a été remplacé par deux compteurs indépendants :

- `retrieval_retry_count` pour les nouveaux retrievals ;
- `generation_retry_count` pour les nouvelles générations.

Chaque mécanisme dispose actuellement d'un budget maximal d'un retry.

Le graphe peut ainsi effectuer les enchaînements suivants lorsque cela est nécessaire :

Retrieval → Génération → `INSUFFICIENT` → nouveau Retrieval → nouvelle Génération

ou :

Génération → `UNSUPPORTED` / `CONTRADICTION` → nouvelle Génération

Les deux budgets étant indépendants, un retry de retrieval peut également être suivi d'un retry de génération, ou inversement.

Le routage après grounding a également été rendu fail-closed : une décision différente de `PASS`, `INSUFFICIENT`, `UNSUPPORTED` ou `CONTRADICTION` ne déclenche aucun retry supplémentaire et termine le pipeline.

Des tests spécifiques ont d'abord été introduits pour reproduire les limitations du compteur partagé. Après modification de la politique de retry, ces scénarios ainsi que l'ensemble des tests unitaires et d'intégration ont été validés.

La suite de tests unitaires et d'intégration atteint alors 213 tests passants.

## 23. Renforcement du Grounding Checker et distinction des types d'échec

Les tests longs du Grounding Checker ont été étendus afin d'évaluer plus largement sa capacité à distinguer la suffisance du contexte de la fidélité de la réponse.

Les premiers tests ont mis en évidence une confusion importante : le modèle pouvait considérer une réponse comme valide lorsqu'elle était simplement cohérente avec le contexte, alors que l'information nécessaire pour répondre à la question n'était pas réellement présente dans celui-ci.

Le Grounding Checker a donc été renforcé afin de distinguer explicitement :

- la suffisance du contexte pour répondre à la question ;
- les affirmations effectivement supportées par le contexte ;
- les contradictions avec une information établie ;
- les informations supplémentaires non supportées.

La sortie du checker contient désormais notamment `context_sufficient` et `unsupported_claims`, ce qui permet de rendre ces vérifications explicites et d'appliquer des contrôles fail-closed côté Python.

L'élargissement des tests a ensuite révélé un autre cas distinct : un contexte peut être entièrement suffisant alors que la réponse générée n'utilise qu'une partie des informations nécessaires. Ce cas ne correspond pas à `INSUFFICIENT`, puisque relancer le retrieval serait inutile.

Une nouvelle décision `INCOMPLETE` a donc été introduite.

La taxonomie du Grounding Checker devient :

- `PASS` : le contexte est suffisant et la réponse est complète et supportée ;
- `INSUFFICIENT` : le contexte ne contient pas suffisamment d'informations pour répondre à la question ;
- `INCOMPLETE` : le contexte est suffisant mais la réponse omet une partie nécessaire ;
- `UNSUPPORTED` : la réponse ajoute une affirmation importante qui n'est pas établie par le contexte ;
- `CONTRADICTION` : la réponse fournit une information incompatible avec ce que le contexte établit.

Cette distinction est également utilisée par la politique de retry du graphe :

- `INSUFFICIENT` déclenche un retry du retrieval ;
- `INCOMPLETE`, `UNSUPPORTED` et `CONTRADICTION` déclenchent un retry de génération ;
- `PASS` termine normalement l'exécution.

Les tests unitaires et d'intégration ont été adaptés à cette nouvelle taxonomie et la suite de régression reste entièrement passante.

Le Grounding Checker a ensuite été évalué sur un ensemble élargi de 20 situations couvrant notamment la suffisance du contexte, les réponses incomplètes, les contradictions, les informations supplémentaires non supportées et différentes contraintes explicites de la question.

Le checker classe correctement 19 cas sur 20. Le cas restant correspond à une confusion entre `CONTRADICTION` et `UNSUPPORTED` lorsqu'une réponse remplace entièrement une méthode établie par le contexte par une autre méthode non supportée. Cette confusion n'affecte actuellement pas la politique de retry, les deux décisions déclenchant un nouveau passage de génération.

Ce cas est conservé comme échec connu dans les tests longs plutôt que de spécialiser davantage le prompt pour cet exemple.

## 24. Mise en place d'un benchmark du retrieval

Après la stabilisation du pipeline de retrieval et du mécanisme de grounding, un benchmark dédié au retrieval a été ajouté afin de mesurer objectivement sa qualité sur le corpus Poképédia réel.

L'objectif est de disposer d'une baseline reproductible avant toute nouvelle optimisation du retrieval.

### Construction du jeu de référence

Une première approche consistait à générer automatiquement les questions de benchmark à l'aide d'un LLM.

Cette approche a été abandonnée après analyse des questions produites. Plusieurs problèmes ont été observés :

- questions contenant plusieurs intentions ;
- formulations artificielles faisant référence au document source ;
- questions relevant en réalité du moteur de requêtes structurées ;
- répartition insuffisamment représentative des différents types de contenu du corpus.

Le jeu de référence a donc finalement été construit manuellement à partir du véritable index Chroma.

Un catalogue des sections présentes dans `pokemon_documents` a d'abord été extrait. L'index contient 27 970 sections logiques, identifiées par le couple :

```text
source_file + section_path
```

Trente sections ont ensuite été sélectionnées dans ce catalogue et leur contenu réel a été exporté depuis Chroma.

Le dataset final contient 30 questions réparties en trois catégories :

- 15 questions `core`, portant principalement sur des descriptions, comportements, origines ou informations générales sur les Pokémon ;
- 10 questions `documentary`, portant notamment sur les apparitions dans les dessins animés ou d'autres jeux ;
- 5 questions `rare`, construites à partir d'informations plus spécifiques présentes dans les sections d'anecdotes.

Les questions ont été rédigées manuellement à partir du contenu effectivement présent dans les sections sélectionnées.

Chaque question possède comme vérité terrain le couple exact :

```text
expected_source_file
expected_section_path
```

Les identifiants des chunks correspondants ont également été conservés afin de pouvoir auditer les cas du benchmark.

Cette méthode permet d'évaluer le moteur de retrieval sur le véritable corpus utilisé par l'application, sans créer un corpus artificiel spécifiquement adapté au benchmark.

### Métriques

Le benchmark exécute le véritable pipeline de retrieval :

```text
Vector Search
    +
BM25
    ↓
RRF
    ↓
candidats structurels
    ↓
CrossEncoder
    ↓
Top-K
```

Pour chaque question, la position de la section attendue dans les résultats est mesurée.

Les métriques retenues sont :

- `Recall@1` : proportion de questions pour lesquelles la bonne section est classée première ;
- `Recall@3` : proportion pour lesquelles elle apparaît dans les trois premiers résultats ;
- `Recall@5` : proportion pour lesquelles elle apparaît dans les cinq premiers résultats ;
- `MRR` (`Mean Reciprocal Rank`) : mesure tenant compte de la position du premier résultat correct.

Le temps d'initialisation du moteur est mesuré séparément des temps de requête afin de distinguer le cold start des performances une fois les modèles et index chargés.

### Résultats

Le benchmark sur les 30 questions donne les résultats suivants :

```text
Cas               : 30

Recall@1          : 0.767 (23/30)
Recall@3          : 1.000 (30/30)
Recall@5          : 1.000 (30/30)
MRR               : 0.872

Cold start        : 18.943 s

Warm mean         : 2247.7 ms
Warm median       : 2273.3 ms
Warm p95          : 2888.2 ms
Warm min/max      : 1041.5 / 3791.2 ms

Échecs Top-5      : 0
```

La section attendue est donc retrouvée pour les 30 questions dans les trois premiers résultats.

Dans 23 cas sur 30, elle est directement classée en première position.

Les sept autres cas correspondent à des problèmes de classement relatif plutôt qu'à une absence de la section recherchée dans les candidats retournés.

Ces résultats fournissent une première baseline mesurée du retrieval sur le corpus Poképédia réel.

Ils ne justifient pas à ce stade une modification du pipeline de retrieval : la bonne section est systématiquement disponible dans le Top-3 et aucune question du benchmark n'échoue en Top-5.

Les performances temporelles montrent en revanche un coût moyen d'environ 2,25 secondes par requête une fois le moteur initialisé. Cette mesure servira de référence pour les futures optimisations de performances.

## 25. Benchmark du router

Après la validation du benchmark du retrieval, un benchmark dédié au router a été ajouté afin de mesurer sa capacité à sélectionner correctement le chemin d'exécution du graphe.

Le jeu de référence contient 30 requêtes couvrant les trois routes disponibles :

- `STRUCTURED` pour les informations pouvant être obtenues depuis `pokemon.db` ;
- `RAG` pour les recherches documentaires dans le corpus Poképédia ;
- `HYBRID` lorsque les deux sources sont nécessaires.

Des requêtes contenant plusieurs besoins informationnels ont également été ajoutées afin de vérifier la détection des questions multiples.

Le benchmark mesure séparément :

- la route choisie ;
- l'intent détecté ;
- la détection d'une question unique ;
- la correspondance exacte de l'ensemble de ces décisions ;
- le mode de routage utilisé (`FAST` ou `LLM`) ;
- le temps d'exécution.

Résultats obtenus :

```text
Cas               : 30
Route accuracy    : 0.900 (27/30)
Intent accuracy   : 0.900 (27/30)
Single accuracy   : 1.000 (30/30)
Exact accuracy    : 0.867 (26/30)
Modes             : {'FAST': 9, 'LLM': 21}
Temps moyen       : 7337.1 ms
Temps médian      : 9453.1 ms
Erreurs runtime   : 0
```

Les erreurs restantes concernent principalement des différences de classification entre `PROFILE`, `DOCUMENT_SEARCH`, `STRUCTURED` et `HYBRID`.

La détection des requêtes contenant plusieurs besoins est correcte sur l'ensemble du benchmark. C'est particulièrement important car ces requêtes sont rejetées avant l'exécution du reste du pipeline.

Aucune modification supplémentaire du router n'a été effectuée à ce stade. Le benchmark sert désormais de baseline pour mesurer de futures modifications.

## 26. Benchmark du grounding

Un benchmark spécifique a ensuite été ajouté pour évaluer le grounding checker indépendamment du retrieval et de la génération de réponse.

Le jeu contient 25 cas contrôlés, répartis équitablement entre les cinq décisions possibles :

- `PASS` ;
- `INSUFFICIENT` ;
- `CONTRADICTION` ;
- `UNSUPPORTED` ;
- `INCOMPLETE`.

Les contextes et réponses sont volontairement synthétiques afin d'isoler le raisonnement du checker de la qualité du retrieval et des connaissances Pokémon du modèle.

Résultats obtenus :

```text
Cas               : 25
Accuracy          : 0.800 (20/25)
PASS              : 0.800 (4/5)
INSUFFICIENT      : 0.800 (4/5)
CONTRADICTION     : 0.800 (4/5)
UNSUPPORTED       : 1.000 (5/5)
INCOMPLETE        : 0.600 (3/5)
Temps moyen       : 6321.0 ms
Temps médian      : 5887.0 ms
```

Les erreurs observées concernent principalement deux difficultés.

La première est la distinction entre l'insuffisance du contexte et une réponse contenant une information non supportée. Dans certains cas, le modèle classe directement une affirmation comme `UNSUPPORTED` alors que le contexte ne contient pas l'information nécessaire pour répondre à la question et devrait donc conduire à `INSUFFICIENT`.

La seconde concerne la complétude. Le modèle peut accepter avec `PASS` une réponse partielle alors que plusieurs éléments sont explicitement demandés et présents dans le contexte. Cette difficulté apparaît dans le score plus faible de `INCOMPLETE`.

Des erreurs ont également été observées sur certaines contraintes numériques simples, par exemple l'interprétation de « après le niveau 30 ».

Ces résultats sont conservés comme baseline. Le prompt du grounding checker n'a pas été complexifié davantage à ce stade afin d'éviter une optimisation excessive sur un petit jeu de cas.

## 27. Benchmark end-to-end du graphe

Après les benchmarks isolés du retrieval, du router et du grounding, un benchmark end-to-end a été ajouté afin de vérifier le comportement du système complet.

Contrairement aux benchmarks précédents, celui-ci exécute directement le graphe LangGraph avec ses composants réels.

Le jeu contient 16 requêtes couvrant :

- le chemin `STRUCTURED` ;
- le chemin `RAG` ;
- le chemin `HYBRID` ;
- le rejet des requêtes contenant plusieurs besoins.

Pour les requêtes structurées, le résultat attendu est une terminaison `DETERMINISTIC`, puisque la réponse est produite directement à partir des données structurées sans passer par le Main LLM ni par le grounding checker.

Pour les requêtes RAG et HYBRID, le résultat attendu est une terminaison `PASS` après vérification du grounding.

Les requêtes multiples doivent quant à elles terminer en `NOT_RUN`, le pipeline étant arrêté avant retrieval.

Résultats obtenus :

```text
Cas               : 16
Route accuracy    : 1.000 (13/13)
Single accuracy   : 1.000 (16/16)
Terminal accuracy : 1.000 (16/16)
Exact accuracy    : 1.000 (16/16)
Routes obtenues   : {'STRUCTURED': 4, 'RAG': 5, 'HYBRID': 7}
Décisions finales : {'DETERMINISTIC': 4, 'PASS': 9, 'NOT_RUN': 3}
Retries retrieval : 1
Retries génération: 0
Temps moyen       : 54.13 s
Temps médian      : 40.84 s
Temps min/max     : 0.05 / 226.29 s
```

Les 16 cas atteignent le comportement terminal attendu.

Un retry du retrieval a été déclenché pendant le benchmark et la requête concernée a tout de même terminé avec succès. Aucun retry de génération n'a été nécessaire.

Le benchmark a également mis en évidence le coût important du pipeline complet.

Lors de son initialisation, le système RAG a notamment mesuré :

```text
Chargement embeddings : 9.298 s
Chargement reranker   : 5.390 s
Chargement corpus     : 4.991 s
Construction BM25     : 0.865 s
Startup total         : 21.305 s
```

Le benchmark end-to-end présente ensuite une médiane de `40.84 s` par requête et un maximum de `226.29 s`.

Ces mesures montrent qu'après les travaux consacrés à la qualité fonctionnelle du pipeline, les performances constituent désormais un point mesurable à analyser. Les timings déjà exposés par les différents nœuds du graphe permettront d'identifier précisément les composants responsables de cette latence avant d'envisager des optimisations.
## 28. Ajout de l'observabilité et du profiling du graphe

Après la mise en place des benchmarks, le temps d'exécution global du graphe était mesurable, mais il restait difficile d'identifier précisément les composants responsables de la latence. Une couche d'observabilité légère a donc été ajoutée afin de suivre le parcours et les performances de chaque requête.

Un module `observability/tracing.py` a été introduit pour créer une trace par exécution du graphe. Chaque trace possède un identifiant unique et conserve les principales informations utiles au diagnostic : route choisie, intent, mode du router, Pokémon identifié, décision finale du grounding, nombre de retries et temps d'exécution des différents composants.

Les traces enregistrent également des informations sur le retrieval, notamment le nombre de chunks récupérés, le nombre de chunks réellement utilisés dans le contexte et la taille du contexte transmis au modèle.

L'instrumentation a été intégrée directement au graphe avec un nœud d'initialisation et un nœud de finalisation commun aux différents chemins terminaux. Cette approche permet de séparer l'observabilité de la logique métier des nœuds existants.

Les traces sont enregistrées au format JSONL dans le dossier `traces/`. Les fichiers générés sont exclus du versionnement. Les tests d'intégration continuent d'exécuter le mécanisme de finalisation des traces, mais l'écriture sur disque y est neutralisée afin de ne pas mélanger les traces de test avec les exécutions réelles.

Plusieurs exécutions réelles ont ensuite permis de valider l'instrumentation sur les principaux chemins du graphe :

- une requête `STRUCTURED` utilisant le Fast Router ;
- une requête `RAG` scoped sur un Pokémon identifié ;
- une requête `HYBRID` ;
- une requête `RAG` particulièrement lente, utile pour vérifier le diagnostic des anomalies de performance.

Ces premières traces ont montré que la construction du contexte et l'exécution SQL ont un coût négligeable par rapport aux appels aux modèles. Sur la requête structurée observée, l'exécution de la requête elle-même prenait environ 42 ms, alors que le parsing par modèle prenait environ 6,66 s. Sur les chemins RAG et HYBRID observés, la génération principale, le router LLM et le grounding représentaient l'essentiel du temps total.

Un script `scripts/observability/analyze_traces.py` a enfin été ajouté pour agréger les traces et faciliter le profiling. Il fournit notamment les temps moyens, médians et p95, les timings par composant, des regroupements par route et mode du router, les métriques de retrieval, les retries, les décisions finales et les requêtes les plus lentes.

Sur le premier échantillon de quatre traces réelles, les temps totaux observés allaient d'environ 6,76 s pour une requête `STRUCTURED` utilisant le Fast Router à environ 160,50 s pour une requête `RAG`. L'échantillon étant encore très réduit, les p95 sont explicitement présentés comme indicatifs.

Cette instrumentation permet désormais de localiser les coûts d'une exécution complète plutôt que de se limiter à mesurer sa durée globale.