# Notes de développement

🇬🇧 [English version](DEVELOPMENT.md)

Ce document retrace l'évolution du projet Pokémon RAG au fil du
développement. Il ne cherche pas à présenter une architecture finale
figée : il conserve les principales étapes, les problèmes rencontrés,
les expérimentations et les décisions qui ont progressivement façonné le
système.

## 1. [Feature] Point de départ : expérimenter un RAG local

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

## 2. [Feature] Construction du corpus Poképédia

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

## 3. [Feature] Premier pipeline de retrieval

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

## 4. [Feature] Limiter la recherche au Pokémon concerné

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

## 5. [Feature] Exploiter la structure des sections

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

## 6. [Feature] Grounding et mécanisme de retry

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

## 7. [Feature] Expérimentation autour de la suffisance du contexte

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

## 8. [Architecture] Améliorer la représentation utilisée pour la recherche

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

## 9. [Architecture] Limites du RAG pour les données structurées

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

## 10. [Feature] Introduction des données PokéAPI

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

## 11. [Feature] Intégration du Pokédex personnalisé

En parallèle, un tableur bilingue est utilisé pour stocker des
informations spécifiques au projet qui ne sont pas directement
disponibles dans PokéAPI.

Il contient les espèces du Pokédex national ainsi que les formes
pertinentes pour le projet et diverses informations complémentaires.

Un mapping explicite avec PokéAPI a été ajouté afin de relier sans
ambiguïté les lignes du tableur aux entités de la base officielle.

Cette étape a permis de préparer la fusion entre les données
personnalisées et les données PokéAPI.

## 12. [Architecture] Passage à une base SQLite unifiée

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

## 13. [Feature] Création du moteur de requêtes structurées

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

## 14. [Bug fix] Stabilisation des évolutions et des formes

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

## 15. [Feature] Extension aux requêtes sur les capacités

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

## 16. [Feature] Apparition des trois routes d'exécution

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

**STRUCTURED**

Utilisé lorsque la réponse peut être obtenue directement depuis les
données relationnelles.

**RAG**

Utilisé lorsque la réponse nécessite du contenu documentaire, explicatif
ou contextuel.

**HYBRID**

Utilisé lorsque les deux sources peuvent contribuer à la réponse.

Cette séparation constitue un changement important par rapport au RAG
initial : le système ne cherche plus à faire résoudre toutes les
questions par le même pipeline.

## 17. [Architecture] Refactorisation de la structure du projet

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

## 18. [Performance] Premier travail ciblé sur les performances

Une fois les principales routes fonctionnelles, les mesures de temps ont
montré que SQLite n'était pas le principal goulot d'étranglement.

Les requêtes SQL s'exécutaient généralement en quelques dizaines de
millisecondes, tandis que certains appels aux modèles locaux prenaient
plusieurs secondes.

Le premier composant ciblé a été le routeur.

**Fast Router**

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

## 19. [Performance] Fast Parser pour les requêtes structurées

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

## 20. [Architecture] Suppression du contrôle de suffisance séparé

Le contrôle du contexte avant génération ajoutait un appel au modèle et
faisait en partie doublon avec le contrôle de fidélité effectué après la
réponse. Il a été retiré des chemins documentaires et hybrides.

Le contrôle après génération décide alors si la réponse peut être
acceptée, si une nouvelle recherche est nécessaire ou si la réponse doit
être régénérée. Les tests du graphe vérifient que ces reprises restent
limitées et que la recherche conserve le Pokémon ciblé.

## 21. [Performance] Chargement de la recherche à la demande

Importer les modules du graphe déclenchait le chargement du corpus et
des modèles de recherche, même lorsque la requête ou le test ne les
utilisait pas.

Cette initialisation a été déplacée au premier accès réel à la recherche
documentaire. Les traitements structurés et les tests utilisant des
dépendances simulées évitent ainsi ce coût.

## 22. [Bug fix] Séparation des budgets de reprise

Un compteur commun limitait les nouvelles recherches et les
régénérations. Une recherche supplémentaire pouvait donc empêcher la
correction ultérieure de la réponse.

Les deux mécanismes ont reçu des budgets indépendants, chacun autorisant
une reprise. Les tests de régression vérifient qu'ils peuvent
s'enchaîner sans provoquer de boucle. Une décision de contrôle non
reconnue arrête le traitement.

## 23. [Bug fix] Distinguer contexte insuffisant et réponse incomplète

Le contrôle de fidélité pouvait accepter une réponse cohérente avec les
sources alors que celles-ci ne permettaient pas réellement de répondre à
la question. Ses consignes et les vérifications Python ont été
renforcées pour examiner explicitement la suffisance du contexte et les
affirmations non étayées.

Une réponse pouvait aussi omettre des informations pourtant disponibles.
La décision INCOMPLETE a été ajoutée pour déclencher une régénération
dans ce cas, sans relancer inutilement la recherche documentaire.

## 24. [Feature] Mise en place des benchmarks

Des benchmarks séparés ont été ajoutés pour évaluer la recherche
documentaire, le routage et le contrôle de fidélité, puis un benchmark
du graphe complet a relié ces vérifications.

Pour la recherche, les questions ont été rédigées à partir de sections
réelles du corpus, avec une source attendue pour chaque cas. Pour le
contrôle de fidélité, des contextes synthétiques permettent d'isoler la
décision du modèle de la qualité de la recherche.

Le benchmark du graphe vérifie les chemins structurés, documentaires et
hybrides, ainsi que le rejet des demandes multiples. Il distingue une
réponse structurée produite directement d'une réponse générée soumise au
contrôle de fidélité.

Les durées observées sur le graphe complet ont motivé l'ajout de mesures
par étape pour localiser les coûts de traitement.

## 25. [Feature] Suivi des exécutions et de leurs performances

La durée globale d'une requête ne permettait pas d'expliquer sa lenteur.
Une trace par exécution a été ajoutée au graphe pour relier le parcours
suivi, les reprises, la décision finale et le temps passé dans chaque
étape.

Les traces sont enregistrées en JSONL et un script les agrège pour
comparer les parcours et repérer les requêtes lentes. Les premières
observations ont confirmé le poids des appels aux modèles par rapport à
l'exécution SQL et à la construction du contexte.

## 26. [Feature] Mesure de la consommation des modèles

La durée d'un appel ne suffisait pas à distinguer une réponse longue
d'un ralentissement du modèle. Les traces ont donc été enrichies avec
les volumes de tokens et le débit des appels de génération, de contrôle
et de régénération.

Le débit est calculé sur la durée totale de l'appel : il inclut le
traitement du prompt et ne mesure pas seulement la production du texte.
Le script d'analyse exploite ces informations tout en conservant la
lecture des anciennes traces.

## 27. [Bug fix] Alignement du routeur sur les opérations disponibles

Le routeur envoyait les questions sur les types, talents et statistiques
vers STRUCTURED, alors que le moteur ne proposait pas d'opération pour y
répondre.

Les règles rapides et le prompt ont été alignés sur les opérations
disponibles : évolutions, capacités par niveau, capacités par machine et
méthodes d'apprentissage. À cette étape, les autres questions ciblées
passent par la recherche documentaire. Les présentations générales
conservent le chemin hybride, qui utilise le profil issu du tableur.

Les tests et les attentes du benchmark ont été adaptés à ce
comportement.

## 28. [Bug fix] Abstention après échec du grounding

Une réponse rejetée par le grounding pouvait encore être affichée après
épuisement des retries.

Un nœud d'abstention remplace désormais cette réponse par un message
indiquant que les sources ne permettent pas de répondre de manière
suffisamment fiable. La décision et la justification du checker restent
disponibles pour le diagnostic.

## 29. [Bug fix] Gestion des erreurs de traitement

Une panne de recherche ou de génération pouvait interrompre le graphe
avant la sauvegarde de sa trace.

Les nœuds sont maintenant protégés pour conserver l'état déjà acquis et
identifier l'étape en échec. La fonction `run_graph()` gère également
les erreurs du moteur LangGraph. Le terminal, le batch et le benchmark
utilisent cette entrée commune.

En cas de panne, le système retourne un message explicite et tente de
sauvegarder la trace. Une erreur du checker est distinguée d'un contexte
insuffisant, ce qui évite de relancer inutilement la recherche
documentaire. Les délais réseau des clients LLM ont aussi été rendus
explicites.

## 30. [Bug fix] Sauvegarde des traces non bloquante

Une erreur d'écriture du fichier de traces ne doit pas empêcher de
retourner une réponse déjà produite.

La sauvegarde est désormais protégée : la réponse et la trace restent
disponibles en mémoire, et le résultat de l'écriture est signalé
séparément. L'erreur est journalisée sans nouvelle tentative
automatique, pour éviter de dupliquer une écriture partielle.

## 31. [Bug fix] Cumul des métriques des tentatives

Les retries remplaçaient les mesures précédentes par celles du dernier
appel, ce qui sous-estimait le coût du traitement.

Un historique conserve maintenant les mesures de chaque tentative. La
finalisation cumule les durées et les tokens des appels instrumentés de
génération, de grounding et de régénération, puis recalcule les débits à
partir des totaux.

Les consommations inconnues sont signalées plutôt que comptées comme
zéro. L'affichage et le script d'analyse ont été adaptés tout en
conservant la lecture des anciennes traces.

## 32. [Architecture] Isolation des tests et évaluation factuelle

Les tests rapides dépendaient parfois de la vraie base ou des modèles
locaux. Les tests du routeur et du parseur utilisent désormais un petit
catalogue SQLite en mémoire. Les marqueurs `real_data`, `models` et
`llm` permettent de sélectionner les tests selon leurs prérequis.

Le benchmark du graphe a aussi été complété par des références
factuelles issues des sources locales. Il exporte les réponses avec une
grille de relecture portant sur l'exactitude, la complétude et les
affirmations non étayées. Un comparateur vérifie les champs structurés
du cas de référence sur les évolutions de Pikachu.

Le verdict PASS du contrôle de fidélité ne suffit donc plus à compter
une réponse comme factuellement correcte.

Dans la continuité de ce travail, un test attendait CONTRADICTION alors
que son contexte n'excluait pas la méthode proposée par la réponse. Le
classement UNSUPPORTED du modèle était donc défendable.

Le contexte a été précisé pour rendre la contradiction explicite. Un cas
séparé vérifie l'ajout d'une condition absente des sources. Cette
distinction a été validée avec le modèle local, sans modifier le prompt.

## 33. [Bug fix] Correction des intervalles de niveaux

Le Fast Parser s'arrêtait à la première borne reconnue. Une demande «
après le niveau 20 mais avant le niveau 40 » pouvait ainsi perdre sa
limite supérieure.

Il collecte désormais les contraintes avant de calculer leur
intersection : cette demande produit les bornes 21 à 39. Les limites
inclusives sont également prises en charge, les intervalles impossibles
sont rejetés et les formulations partiellement comprises sont laissées
au parseur LLM.

Des tests de régression vérifient que les contraintes de niveau sont
conservées.

## 34. [Feature] Extension des requêtes structurées au Pokédex personnalisé

Le Pokédex personnalisé contient des données qui peuvent être restituées
directement, sans génération LLM : types, numéro national, génération
d'introduction et capacités signature.

Le moteur structuré a été étendu à ces demandes, avec un routage adapté
et une restitution directe des données. Les noms français ou anglais et
les formes explicitement nommées sont pris en charge.

Les réponses signalent les valeurs absentes et conservent les
annotations des sources. Ces données ne permettant pas de filtrer par
jeu, ce filtre est refusé. Les tests et les références factuelles du
benchmark couvrent les nouvelles opérations.

## 35. [Bug fix] Conservation des contraintes de jeu

Le parseur rapide pouvait ignorer un jeu inconnu et répondre toutes
versions confondues.

Il détecte désormais les mentions explicites de jeu non reconnues et le
traitement les rejette avant le recours au LLM, pour conserver la
contrainte de la question. Des tests de régression vérifient que la
contrainte de jeu est conservée.

## 36. [Feature] Exposition des capacités du projet via MCP

Pour utiliser le projet depuis des clients compatibles MCP, un serveur
expose les opérations structurées et la recherche documentaire sous
forme d'outils typés. Il réutilise le moteur existant et le pipeline de
recherche sans dupliquer la logique métier.

La recherche peut porter sur tout le corpus ou être limitée à un
Pokémon. Elle retourne des passages et leurs références de source.
Les outils appellent directement les composants sous-jacents, sans
passer par les contrôles et les reprises du graphe.

Un client découvre les outils disponibles et leurs schémas, puis confie
à Qwen le choix d'un outil et de ses arguments à partir de la question.
Il exécute cet outil via MCP et transmet le résultat à Qwen pour
formuler une réponse en français. Cette première boucle permet ainsi
au modèle de choisir entre données structurées et recherche
documentaire.

L'intégration a été validée sur des questions mobilisant ces deux
sources.

## 37. [Bug fix] Séparation des diagnostics RAG du protocole MCP

Au premier appel documentaire, l'initialisation RAG écrivait ses
diagnostics sur stdout, également utilisé par les messages MCP.

Ces diagnostics et les barres de progression sont désormais dirigés
vers stderr. Un test de régression avec une collection et des modèles
simulés vérifie que l'initialisation laisse stdout vide et conserve
les informations de diagnostic.

## 38. [Feature] Questions successives dans une session MCP

Le client ouvrait un nouveau serveur pour chaque question, ce qui empêchait
de conserver les ressources de recherche déjà chargées entre les appels.

Le terminal accepte désormais plusieurs questions dans une même session.
Le serveur, le catalogue d'outils et le client LLM sont réutilisés ; chaque
question reste indépendante. Un contexte réutilisable est aussi disponible
en Python, tandis que l'appel ponctuel conserve son fonctionnement.

Les ressources sont fermées à la sortie, en cas d'erreur ou d'annulation.
Des tests simulés vérifient cette fermeture et la réutilisation de la session.
Le gain de latence sur les modèles réels reste à mesurer.

## 39. [Bug fix] Arrêt explicite après une panne du routeur

Une panne du routeur déclenchait une recherche documentaire globale et son
diagnostic disparaissait de l'état du graphe. Le Pokémon ciblé pouvait ainsi
être perdu sans signalement.

Les erreurs de routage rapide, d'appel au modèle et de validation interrompent
désormais le traitement avant la recherche. Le diagnostic est conservé dans
l'état et les traces, ainsi que le Pokémon déjà validé. Le repli documentaire
après une sortie valide reste distinct de cette gestion des pannes.

Des tests simulés vérifient la conservation du scope, la trace du diagnostic
et l'absence d'appel aux étapes suivantes après une panne.

## 40. [Bug fix] Contrôle des contraintes avant un appel MCP

Le client MCP et le moteur structuré doivent interpréter les mêmes mentions de
forme, de jeu et de niveau. Le dossier `constraints` rassemble désormais leurs
règles d'extraction déterministes, sans accès aux données ni appel au modèle.

Le moteur conserve la validation des plans et l'accès à SQLite ; le client
conserve la réconciliation des arguments avant l'appel d'outil. Le guide du
module précise cette séparation et les limites de reconnaissance, pour ne pas
confondre extraction partagée et validation complète d'une demande.

Le client rétablit les filtres reconnus et refuse les contraintes non résolues
ou incompatibles avec l'outil. Les intervalles « entre les niveaux » sont reconnus,
et le moteur associe Tonnerre à son identifiant interne `thunderbolt` sans changer
la langue de l'interface. Les tests déterministes couvrent la réconciliation ;
la validation complète avec Qwen reste à effectuer. Les restrictions sur les
questions documentaires générales sont décrites dans le guide MCP.

## 41. [Architecture] Séparation des validations MCP

Les scénarios qui utilisent réellement Qwen sont regroupés dans `tests/long`,
séparément des parcours client simulés. Un test d'intégration du serveur vérifie
la découverte des outils et une requête structurée via stdio sans génération LLM.
Cette séparation permet de choisir une validation selon ses dépendances réelles.

## 42. [Architecture] Introduction d'un agent ADK local

ADK est introduit pour expérimenter une couche d'orchestration supplémentaire
sans remplacer les composants métier existants. Qwen reste le modèle qui génère
le texte ; ADK définit l'agent et ses instructions ; MCP est le protocole qui
expose les capacités du projet aux clients.

La première implémentation se limite volontairement à un seul agent répondant
en français, avec Qwen local via LiteLLM et l'API compatible OpenAI de LM Studio.
L'endpoint est explicite pour éviter qu'une configuration OpenAI externe détourne
les appels. Les versions ADK et LiteLLM validées localement sont déclarées dans
les dépendances du projet.

L'agent ne possède encore aucun outil. Son accès aux capacités existantes par
MCP est différé à une intégration distincte. Le graphe, le client et le serveur
MCP restent disponibles ; SQLite, Chroma, le moteur structuré, le RAG et le
grounding conservent leurs responsabilités.

## 43. [Feature] Connexion de l'agent ADK aux types Pokémon via MCP

Le function calling ADK/LiteLLM/Qwen a d'abord été validé manuellement avec
un outil Python simple, sans MCP. L'agent a ensuite été connecté au serveur
Pokémon par `McpToolset`, en limitant les outils visibles à `pokemon_types`.

La découverte échouait car l'initialisation MCP prenait environ 9,2 secondes,
au-delà du délai ADK de 5 secondes. Le diagnostic a identifié l'import immédiat
de `pokemon_rag.rag.retrieval`, et notamment de `sentence_transformers`, comme
cause principale. Cet import est désormais effectué uniquement dans l'outil
RAG : les outils structurés démarrent sans charger ce module lourd.

L'initialisation mesurée après correction est d'environ 1,7 seconde sur la même
machine. Ces mesures ont motivé le chargement différé, sans devenir des seuils
de test. La découverte de `pokemon_types` par `McpToolset` et le parcours complet
Qwen → ADK → MCP → `pokemon_types` → réponse ont été validés manuellement.
Les tests conservent des frontières distinctes : protocole stdio, découverte
ADK, function calling et parcours complet.

## 44. [Feature] Guard déterministe des niveaux dans l'agent ADK

Un callback avant l'appel d'outil réutilise l'extraction commune des contraintes
pour restaurer les bornes numériques dans `pokemon_level_up_moves`. Il bloque
les niveaux ambigus ou invalides et les outils qui ne peuvent pas les respecter.
Cette première protection porte uniquement sur les niveaux, sans remplacer
les contrôles du graphe ou du client MCP.

La détection `level_explicit` exige désormais un nombre en plus du mot niveau,
pour laisser passer une demande générale comme « en montant de niveau ».
Des tests unitaires avec le contexte ADK simulé vérifient ces décisions sans LLM.

## 45. [Feature] Extension du guard ADK aux jeux et aux formes

Le guard réutilise désormais aussi les groupes de versions et les formes
régionales reconnus par l'extracteur commun. Il rétablit ces arguments lorsque
l'outil les accepte, remplace les valeurs incorrectes proposées par le modèle
et bloque les outils incompatibles. Les jeux inconnus ou ambigus sont refusés.

Les tests unitaires couvrent ces contraintes et la combinaison jeu/niveaux,
sans appel au modèle. La reconnaissance des formes conserve les limites de
l'extracteur partagé ; le guard ne modifie pas le catalogue d'outils exposé.

## 46. [Feature] Accès ADK aux huit outils MCP

L'agent expose désormais les huit outils du serveur Pokémon, structurés et
documentaires. Le guard déterministe avant appel conserve la protection des
niveaux, groupes de versions et formes reconnus. Les instructions orientent
Qwen vers l'outil adapté et lui permettent de corriger son choix après un refus.

Le parcours ADK → Qwen local → MCP → données locales a été validé manuellement,
avec des scénarios de routage et de contraintes. Les huit schémas ont révélé
une fenêtre de contexte insuffisante : le contexte Qwen dans LM Studio a été
augmenté de 8192 à 16384 tokens.

Des différences de temps de traitement ont été observées pour les résultats
d'outils volumineux. Leur cause n'a pas été établie ; cette observation ne
constitue pas une mesure isolant un composant ou expliquant son coût.

## 47. [Feature] Interface conversationnelle Web avec Gradio

Une interface Gradio permet d'utiliser localement le root_agent ADK existant
depuis le navigateur, sans créer un autre agent ni contourner MCP. La session
ADK est conservée entre messages ; une action ouvre une nouvelle conversation.

Un panneau d'activité affiche progressivement les appels et arguments d'outils,
la réception de leurs réponses et un chrono actualisé pendant l'exécution.
Il s'appuie sur les événements function_call et function_response. Des questions
d'exemple sont tirées au hasard depuis un fichier annexe. Le lancement local
demande l'ouverture automatique du navigateur.

## 48. [Bug fix] Résolution des espèces à formes et consignes de réponse ADK

Nigirigon existait dans le Pokédex personnalisé sous son nom complet de forme,
mais son nom d'espèce ne correspondait à aucune entrée. La résolution utilise
désormais le catalogue d'espèces et la forme par défaut lorsque le nom complet
ne correspond pas, sans remplacer une forme explicitement demandée. Les tests
déterministes vérifient aussi d'autres espèces et la propagation des erreurs MCP.

Le diagnostic d'Opermine confirme que les noms français et anglais des capacités
sont présents dans les résultats, tandis que les jeux restent des identifiants
techniques. Les instructions ADK privilégient les noms français sans parenthèses
anglaises non demandées et imposent de signaler une donnée indisponible après
échec des sources, plutôt que de répondre de mémoire. Ces consignes de génération
restent à valider manuellement ; elles ne remplacent pas le grounding du graphe.

## 49. [Bug fix] Limitation des CT sans jeu précisé

Une demande de CT sans jeu transmettait les résultats de plusieurs versions,
jusqu'à dépasser le contexte Qwen. Le moteur sélectionne désormais uniquement
le groupe le plus récent disposant de données locales de CT pour la forme
demandée. Le résultat identifie ce groupe et l'agent doit le préciser en français.
Un jeu explicitement demandé reste prioritaire, même sans résultat.

Les tests sans LLM vérifient la sélection pour Bruyverne et la conservation d'un
jeu plus ancien pour Gouroutan. Le critère porte sur les données locales de CT,
sans prétendre établir une disponibilité exhaustive dans les jeux.

## 50. [Bug fix] Questions Web sans mémoire de l'agent

La session ADK réutilisée pouvait mêler une réponse précédente à la question
courante. L'interface garde désormais l'historique uniquement pour l'affichage.
Chaque question utilise une session ADK indépendante, supprimée après succès
ou erreur. Des tests avec runner simulé vérifient cette isolation et le maintien
de la conversation visible, sans appel au modèle.

## 51. [Bug fix] Choix documentaire pour les descriptions ADK

Une question sur l'apparence de Bastiodon avait déclenché l'outil de types,
suivie d'une description non sourcée. Les instructions ADK distinguent désormais
les sujets documentaires des propriétés structurées et demandent une recherche
RAG pour l'apparence, avec une réponse limitée aux passages récupérés ou un
signalement d'information indisponible. La description de l'outil de types
précise cette limite. Le guard conserve son rôle de protection des contraintes ;
le respect de ces consignes par Qwen reste à vérifier manuellement.

## 52. [Feature] Interface Web centrée sur l'activité de l'agent

L'interface conserve un panneau d'activité important pour montrer comment
l'agent ADK utilise les outils MCP. Elle présente le parcours de la question,
les libellés lisibles des outils, leurs noms techniques, arguments et réponses
reçues ou attendues. Une réponse d'outil reçue n'est pas présentée comme une
preuve de réussite.

La question apparaît immédiatement dans l'historique, avec la saisie sous les
réponses et un rappel de l'indépendance des questions. La saisie initiale est
vide ; un bouton d'exemple la remplit sans lancer l'agent. L'absence de réponse
finale a son propre statut. Un thème Soft et des styles adaptés aux petits
écrans améliorent la lisibilité.
L'espace de travail tient dans la fenêtre avec un défilement à l'intérieur des
panneaux. Une bulle temporaire avec des points de suspension indique que la
réponse est en préparation puis est remplacée par la réponse finale ou l'erreur,
sans rester dans l'historique de conversation.
Le titre redondant de la conversation est retiré et les lignes de saisie et
d'actions gardent leur hauteur naturelle pour réserver l'espace aux réponses.
La conversation est placée à gauche et le panneau de l'agent à droite.
Les bulles utilisateur sont à gauche et celles de l'assistant à droite. Une grille
attribue au chat toute la hauteur restante au-dessus des commandes compactes.
L'activité explique désormais les technologies au fil des appels : Qwen
interprète la question, les outils MCP consultent SQLite ou recherchent du texte
Poképédia via le RAG / Chroma, puis Qwen prépare la réponse à partir des retours
d'outils. Les textes explicatifs statiques sont remplacés par ce suivi progressif.
Les durées distinguent désormais l'analyse initiale, l'attente des outils et la
préparation de la réponse, avec un chrono par appel. Les reprises cumulent le
temps et les attentes parallèles comptent une fois dans le total de l'étape.
Ces mesures reflètent les événements reçus par l'interface, délais de transport
et de session compris.

## 53. [Feature] Recherche Pokémon et movepool filtrable

Les recherches structurées peuvent désormais combiner numéro national, types,
génération d'origine, légendaire ou fabuleux et propriétés de capacités
apprenables. Deux outils MCP exposent ces filtres SQL à ADK et au client local,
sans demander au modèle de filtrer des listes. Les talents sont reportés.

Sans forme demandée, la forme par défaut est sélectionnée. Sans jeu demandé,
le movepool le plus récent réellement disponible est choisi avant les filtres,
sans union historique. Les résultats dédupliquent les capacités, conservent les
méthodes et indiquent les totaux et pages partielles. Les lacunes du catalogue
personnalisé pour certaines formes par défaut sont signalées sans substitution.

Les tests déterministes vérifient les recherches croisées, les versions, les
formes et la distinction entre puissance inconnue et catégorie de capacité,
ainsi que le transport MCP réel et la conservation des contraintes des clients.
La base et les interfaces des anciens outils sont conservées.

Une réponse de recherche ajoutait des noms de capacités inventés et des détails
non demandés. Les instructions ADK et du client MCP exigent désormais les seuls
noms français retournés pour une liste, sans génération ou classification
supplémentaire. Une recherche Pokémon ne permet pas de nommer ses capacités
correspondantes ; celles-ci doivent être récupérées si elles sont demandées.
La couverture incomplète est signalée brièvement sans liste d'exceptions.
Le respect de ces consignes par Qwen reste à vérifier manuellement.

Une recherche par numéro national utilisait aussi l'outil d'identité avec un nom
deviné. Les deux directions sont maintenant explicites : le guard ADK refuse
cet appel et exige la recherche par numéro, tandis que le client MCP redirige
l'appel d'identité et rétablit le numéro demandé. Des tests sans LLM vérifient
ce cas, le maintien de l'identité par nom et le refus des numéros régionaux ou
multiples reconnus. Le texte final reste soumis aux consignes du modèle.

## 54. [Bug fix] Budget de contexte de l'agent ADK

Une question simple sur le Pokémon le plus rapide pouvait dépasser la
fenêtre de Qwen. Les instructions ont été raccourcies, les réponses MCP
transmises au modèle ne dupliquent plus leur JSON, et les résultats trop
volumineux sont réduits avec un signalement explicite. Un contrôle avant
chaque appel borne le contexte sérialisé et le nombre d'appels ; un budget
dépassé produit une abstention locale sans supprimer de contrainte.

La recherche structurée dispose aussi d'un tri par vitesse de base pour
obtenir directement le maximum avec une seule ligne, à partir des données
existantes. Les tests sans LLM vérifient les budgets, la compatibilité du
catalogue MCP réel et le classement SQL. Le budget en octets reste une
estimation conservatrice ; l'inférence Qwen n'a pas été exécutée.

## 55. [Feature] Classements filtrés par statistiques de base

Le premier classement ne couvrait que la Vitesse et ne distinguait pas un
superlatif avec ex aequo d'une première ligne paginée. `pokemon_search`
combine maintenant ses filtres avec les six statistiques de base ou leur
somme calculée en SQL. Le même tri sert aux top N ; un mode de superlatif
sélectionne le seuil gagnant et compte tous les ex aequo avant pagination.

La catégorie Méga utilise le flag des formes de la base, y compris leurs
variantes, avec les statistiques propres à chaque entrée. Sans demande de
forme, la sélection par défaut reste inchangée. Les schémas MCP et les
instructions orientent Qwen vers ces calculs déterministes. Des tests sans
LLM vérifient la composition des filtres, les égalités, les totaux, les
formes et la conservation des arguments dans les clients. Aucun index,
contenu ou schéma de base n'a été modifié.
Les instructions et annotations de schémas ont aussi été compactées, ainsi
que les champs techniques des classements destinés à ADK, pour transmettre
les top 10 sans dépasser le budget existant ni réduire leur nombre de lignes.

## 56. [Bug fix] Classements réconciliés avant MCP

Une demande de Méga avec le moins de Défense pouvait envoyer un type Acier
inventé et omettre le tri, puis atteindre le plafond de contexte. Les clients
restaurent maintenant les motifs de classement reconnus et les types demandés
avant SQL, sans comparer les valeurs. Les libellés statistiques sont partagés.

Après un classement complet, ADK formule avec les faits et l'historique sans
retransmettre le catalogue d'outils. Les plafonds restent inchangés. Des tests
avec le vrai runner, MCP et SQLite, mais un modèle simulé, reproduisent les
arguments incorrects et vérifient leur correction pour un superlatif et un
top 10, sans inférence.

## 57. [Bug fix] Copie alignée sous les messages

Les bulles du chat avaient été inversées sans adapter l'alignement des
boutons de copie de Gradio. Les boutons suivent désormais leur bulle,
sous le texte, au lieu de rester sur le côté opposé.

## 58. [Bug fix] Superlatifs pluriels et restitution des classements

La campagne structurée a révélé qu'un superlatif pluriel était traité comme
une liste et qu'une réponse pouvait perdre sa valeur statistique. L'extraction
conserve désormais tous les gagnants sans quantité explicite ; un top N impose
sa limite et désactive ce mode. Les instructions et descriptions MCP exigent
le nom français, la valeur et le libellé de la statistique, avec les ex aequo.
L'adaptation ADK masque les traductions anglaises lorsqu'un libellé français
existe, sauf demande explicite, sans changer SQL ni les réponses MCP originales.

Le rapport E2E distingue maintenant les propositions Qwen, les arguments
après guard, les retours bruts et adaptés, puis la réponse. Une proposition
réparée reste visible comme diagnostic sans faire échouer le verdict
fonctionnel. Les tests déterministes vérifient les quantités, les formulations
plurielles, les ex aequo et ces frontières de rapport ; l'inférence reste à
relancer par l'utilisateur.

## 59. [Bug fix] Entités explicites et présentation structurée compacte

La nouvelle campagne a révélé des substitutions d'espèces, des confusions
entre listes, identités et classifications, ainsi que des abandons sur de
petites listes SQL valides. Le guard préserve désormais les noms et formes
reconnus dans un catalogue issu de la base, refuse les cibles ambiguës et
indique l'outil d'identité lorsqu'une recherche par nom est incompatible.
Les listes simples et les classifications positives ont leurs invariants
propres, sans modifier les calculs SQL de classement.

L'adaptation ADK conserve les faits utiles, comptes et avertissements sans
répéter les identifiants ni les exceptions de catalogue. La formulation des
listes et movepools complets omet aussi le catalogue d'outils, avec les mêmes
budgets. Les capacités par niveau et les méthodes sans jeu utilisent le
dernier jeu disponible ; l'historique reste accessible explicitement.
Les libellés français de jeux connus et les paires de traductions imbriquées
sont pris en compte pour la présentation.

L'instrumentation du rapport sépare les propositions des appels exécutés et
renforce les échecs pour les erreurs, abstentions, valeurs omises, niveaux
inventés et traductions anglaises ajoutées. Les tests avec modèle simulé
vérifient ces frontières et les listes réelles ; la fidélité complète de
Qwen reste à vérifier par la campagne manuelle.

## 60. [Bug fix] Contraintes explicites indépendantes de Qwen

La campagne a montré qu'une catégorie spéciale pouvait disparaître d'un
movepool pourtant correctement ciblé. Les contraintes reconnaissables sont
désormais extraites avant de comparer les arguments : génération d'origine,
types de Pokémon et de capacités, catégorie physique/spéciale/statut et
bornes de puissance rejoignent les protections existantes. Un titre de jeu
complet prime sur ses alias courts ; les nombres de domaines distincts ne
se confondent plus, et les bornes supplémentaires d'un intervalle sont examinées.

Le guard restaure les valeurs explicites sur un outil compatible et refuse
un outil incapable de les représenter, avec les arguments à reprendre.
Les propositions refusées restent intactes et Qwen conserve le choix et la
reprise des outils. Les tests déterministes vérifient omissions, contradictions,
ambiguïtés et combinaisons, puis la transmission des arguments réparés au vrai
serveur MCP et à SQLite. La reprise effective par Qwen après un refus reste
à vérifier dans la campagne manuelle.

## 61. [Architecture] Règles d'appel portées par les schémas d'outils

Les propositions de Qwen restaient souvent réparées par le guard : quantité
d'un top N oubliée, tri absent d'une question sur les Méga, numéro national
envoyé à l'outil d'identité, catégorie de capacité omise. L'examen du catalogue
réellement transmis a montré que l'abrègement ADK ne conserve que le premier
paragraphe de chaque description : la plupart des arguments arrivaient sans
explication, tandis que la règle des classements était répétée à quatre endroits.

Chaque outil annonce désormais sa direction dans cette première phrase :
Pokémon nommé vers ses faits, ou propriétés vers des Pokémon. Les règles propres
à un argument sont placées dans sa description, avec un exemple pour distinguer
superlatif et top N et les équivalents français des catégories de capacités.
L'instruction de l'agent ne garde que les règles communes : faits prouvés par
les outils, noms français recopiés de la question, aucune contrainte inventée, réponse en
français sans identifiant technique. Le volume transmis au modèle reste le même.

Le guard conserve son rôle et n'a pas été modifié. Un test vérifie le catalogue
abrégé, sans présumer du comportement de Qwen, qui reste à mesurer par la
campagne manuelle. Le diagnostic de cette campagne compte désormais un argument
omis comme sa valeur par défaut, et deux contrôles de réponse ne confondent plus
un nom français contenant un mot anglais avec un ajout d'anglais, ni un rang de
liste avec une statistique.

## 62. [Bug fix] Petits résultats refusés par le budget de contexte

Une question de movepool filtré recevait l'abstention de budget alors que
l'outil avait renvoyé trois ou huit capacités correctes. La mesure du parcours
a montré que le résultat lui-même était petit : après une réponse de
`pokemon_moves`, le catalogue d'outils restait joint à la requête de
formulation, faute de reconnaître cette réponse comme complète, et ce
catalogue occupait à lui seul les trois quarts du plafond.

Une page complète de `pokemon_moves` est désormais formulée sans le catalogue,
comme les autres outils. Sa projection retire les identifiants techniques et
garde les faits de chaque capacité ; quand tout ne tient pas, elle se réduit aux
faits demandés avant de couper des lignes, toujours avec un signalement
explicite. La vue des schémas donnée au modèle est allégée des formes « type ou
null », ce qui laisse la place de réessayer après un refus du guard, et le
balisage qu'ADK pose autour des descriptions n'est plus laissé ouvert. Le
contrat MCP ne change pas. Les abstentions sont journalisées avec leur raison.

Les classements avaient perdu leurs valeurs dans les réponses : les projections
étaient identiques avant et après, la cause était une reformulation de
l'instruction, annulée depuis. La valeur de chaque ligne porte maintenant le
nom français de sa statistique, pour ne plus dépendre d'une clé technique.
L'effet sur les réponses de Qwen reste à mesurer par la campagne manuelle.

## 63. [Bug fix] Méthode d'apprentissage inventée retirée avant l'outil

Une question de movepool filtré a reçu une seule capacité alors que trois
répondaient à la demande. Qwen avait ajouté de lui-même la montée de niveau
comme méthode d'apprentissage ; le guard réparait le nom, la catégorie et la
borne inventée, mais laissait passer ce filtre que rien ne lui permettait de
juger. La réponse restait fidèle au résultat reçu, donc l'erreur était invisible.

Un extracteur reconnaît désormais si la question mentionne une méthode
d'apprentissage. Pour le movepool filtré et la recherche de Pokémon, le guard
ADK et la réconciliation du client MCP retirent une méthode que la question ne
nomme pas. La règle est volontairement asymétrique : au moindre mot de méthode,
la proposition du modèle est conservée, sans restauration ni remplacement.

Un test avec le vrai runner reproduit l'appel observé et retrouve les trois
capacités. Les cas de movepool de la campagne attendent maintenant l'absence de
méthode, pour que cette invention apparaisse dans le diagnostic.

## 64. [Bug fix] Jeu retenu quand une méthode d'apprentissage est demandée

Dans Pokémon Champions, les capacités se choisissent directement dans un menu :
les données n'y connaissent ni montée de niveau, ni CT, ni reproduction, seulement
une méthode propre au jeu. Comme c'est le jeu le plus récent, le movepool filtré
le retenait par défaut, et une demande de CT ou d'une plage de niveaux posée sans
nommer de jeu renvoyait une liste vide pour les Pokémon qui y figurent.

Quand une méthode d'apprentissage est demandée sans jeu, y compris par des bornes
de niveau, le movepool filtré et la recherche de Pokémon retiennent désormais le
dernier jeu où le Pokémon a cette méthode, comme le faisaient déjà les outils de
CT et de capacités par niveau. Les filtres de type, de catégorie et de puissance
ne changent toujours pas de jeu, et un jeu nommé reste strict. Le jeu et sa
méthode sont aussi présentés en français au modèle, sous les noms « Pokémon
Champions » et « entraînement ».
