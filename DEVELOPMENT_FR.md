# Notes de développement

🇬🇧 [English version](DEVELOPMENT.md)

Ce document présente le développement du projet Pokémon RAG, les problèmes rencontrés au cours des expérimentations et les choix d'architecture qui ont conduit au système actuel.

Le projet a commencé comme une expérimentation autour d'un pipeline de Retrieval-Augmented Generation local, avant d'évoluer progressivement vers un système hybride combinant données structurées et recherche documentaire.

---

## 1. Pourquoi Pokémon ?

Pokémon a été choisi comme domaine d'expérimentation car il permet de réunir, au sein d'un même sujet, une grande quantité de données textuelles et de données fortement structurées.

### Un corpus textuel important

Le Pokédex national contient **1 025 espèces de Pokémon**, auxquelles s'ajoutent de nombreuses formes et variantes.

Poképédia fournit ainsi plus d'un millier de pages contenant principalement des informations non structurées ou semi-structurées sur :

- la biologie et l'apparence ;
- le comportement ;
- les origines et inspirations ;
- les descriptions dans les différents jeux ;
- les apparitions dans l'anime et les mangas ;
- diverses anecdotes ;
- l'histoire ;
- les capacités et différentes informations contextuelles.

Cela permet de travailler sur un corpus suffisamment important pour que la recherche documentaire constitue un véritable problème, plutôt qu'une simple démonstration sur quelques documents.

Le corpus contient des dizaines de milliers de chunks répartis dans plus d'un millier de documents, dont beaucoup partagent un vocabulaire et des structures de sections similaires.

Par exemple, la plupart des pages contiennent des sections consacrées aux évolutions, aux capacités, aux apparitions ou aux données issues des jeux.

Le système doit donc être capable d'identifier non seulement le bon document, mais souvent également la bonne section à l'intérieur de celui-ci.

### Des données fortement structurées

En parallèle, Pokémon contient une quantité importante d'informations naturellement adaptées à une base de données relationnelle.

On peut notamment citer :

- les statistiques ;
- les types ;
- les talents ;
- les capacités ;
- les méthodes d'apprentissage ;
- les niveaux ;
- les CT ;
- les versions des jeux ;
- les espèces et les formes ;
- les chaînes d'évolution ;
- les conditions d'évolution ;
- les objets ;
- les localisations.

PokéAPI fournit ces informations sous la forme d'un ensemble important de données relationnelles pouvant être importées dans SQLite.

Pokémon permet donc d'étudier naturellement la frontière entre interrogation d'une base de données et recherche documentaire.

Par exemple :

```text
Quelles capacités Roitiflam apprend-il après le niveau 40 ?
```

est fondamentalement une requête structurée.

À l'inverse :

```text
Pourquoi Pikachu a-t-il les joues rouges ?
```

est une question qui se prête davantage à une recherche dans du contenu documentaire.

D'autres questions peuvent nécessiter les deux types de données.

### Un cas d'usage naturellement hybride

L'objectif n'est donc pas simplement de construire un chatbot consacré à Pokémon.

Pokémon sert de terrain d'expérimentation pour une problématique plus générale :

> Comment un système basé sur des LLM peut-il déterminer quand interroger des données structurées, quand rechercher dans des documents et quand combiner les deux ?

L'architecture étudiée peut ainsi être représentée de manière simplifiée :

```text
Données structurées ───── SQLite / PokéAPI
                               │
                               │
Question ─────── Routeur ──────┼────── Réponse
                               │
                               │
Données textuelles ─────── RAG / Poképédia
```

Le domaine présente également l'avantage de fournir de nombreuses réponses précises et vérifiables.

Cela facilite l'identification des erreurs de retrieval, des réponses incomplètes et des hallucinations.

Pokémon constitue ainsi un benchmark suffisamment accessible pour être manipulé localement, mais suffisamment complexe pour expérimenter une véritable architecture RAG hybride.

---

## 2. Objectif initial

L'objectif initial était de construire un système local capable de répondre à des questions détaillées sur Pokémon tout en déterminant la source d'information la plus appropriée pour chaque question.

Les principales contraintes étaient :

- exécution locale via LM Studio ;
- absence de dépendance à une API LLM externe ;
- recherche dans un corpus français important issu de Poképédia ;
- interrogation de données relationnelles locales ;
- réponses ancrées dans les sources disponibles ;
- prise en charge aussi bien de questions factuelles précises que de questions ouvertes ;
- temps de réponse raisonnables sur du matériel grand public.

Le projet s'est initialement concentré principalement sur le RAG à partir de Poképédia.

Les tests ont cependant progressivement montré les limites de la recherche documentaire pour les questions intrinsèquement structurées, ce qui a conduit à l'architecture actuelle combinant `STRUCTURED`, `RAG` et `HYBRID`.

---

## 3. Construction du corpus Poképédia

Les pages Poképédia sont téléchargées puis converties en documents locaux avant leur indexation.

Le pipeline de traitement est le suivant :

```text
Poképédia
    ↓
download_pokepedia.py
    ↓
pages brutes
    ↓
clean_pokepedia.py
    ↓
documents nettoyés
    ↓
ingest_pokemon.py
    ↓
index ChromaDB
```

Le corpus nettoyé contient actuellement environ 1 200 documents Pokémon et plusieurs dizaines de milliers de chunks.

Une contrainte importante du prétraitement était de préserver la structure des articles d'origine.

Les chunks contiennent donc notamment des métadonnées telles que :

```text
pokemon
source_file
section_path
section_chunk_number
```

Cette structure s'est ensuite révélée importante pour améliorer le retrieval.

---

## 4. Première architecture RAG

Le premier système de retrieval combinait plusieurs techniques :

```text
Question
   ↓
Recherche vectorielle
   +
Recherche BM25
   ↓
Reciprocal Rank Fusion
   ↓
Reranking CrossEncoder
   ↓
Meilleurs résultats
   ↓
LLM
```

Le pipeline de retrieval utilise notamment :

- des embeddings Sentence Transformer multilingues ;
- ChromaDB pour la recherche vectorielle ;
- BM25 pour la recherche lexicale ;
- Reciprocal Rank Fusion pour fusionner les résultats ;
- un CrossEncoder pour le reranking.

Cette approche a fourni de meilleurs résultats qu'une recherche reposant uniquement sur la similarité vectorielle.

Cependant, obtenir de bons chunks individuellement ne suffisait pas.

---

## 5. Recherche limitée au Pokémon concerné

Un problème récurrent concernait la contamination entre les pages de différents Pokémon.

Lorsqu'une question concernait explicitement un seul Pokémon, une recherche globale dans tout le corpus pouvait récupérer des informations provenant d'un autre Pokémon utilisant un vocabulaire similaire.

Une règle stricte a donc été introduite :

> Lorsqu'un seul Pokémon est explicitement identifié, toute la recherche reste limitée à ce Pokémon.

Cette règle s'applique également aux nouvelles recherches effectuées lors d'un retry.

Le comportement devient donc :

```text
Un Pokémon identifié
        ↓
Recherche uniquement sur ce Pokémon

Aucun Pokémon identifié
        ↓
Recherche globale

Plusieurs Pokémon / ambiguïté
        ↓
Traitement spécifique ou recherche globale
```

Cette modification a fortement réduit les résultats provenant de documents non pertinents.

---

## 6. Recherche tenant compte des sections

Les pages Poképédia possèdent une structure importante avec des sections telles que :

```text
Évolution
Capacités apprises
Capacités apprises > Par montée en niveau
Capacités apprises > Par CT
Capacités apprises > Par reproduction
Localisations
Statistiques
```

La récupération de chunks isolés pouvait fournir un contexte incomplet.

Le système a donc été modifié afin de conserver et d'exploiter `section_path`.

Lorsqu'un chunk pertinent est sélectionné, le système peut reconstruire la section logique complète à partir de :

```text
source_file
+
section_path
+
section_chunk_number
```

Au lieu de simplement récupérer les chunks voisins selon leur identifiant numérique, le pipeline étend donc le contexte à la section exacte.

Cela évite notamment de réunir accidentellement des parties sans rapport entre elles au sein d'un même document.

---

## 7. Validation de l'ancrage des réponses

Générer une réponse à partir d'un contexte récupéré ne garantit pas que cette réponse soit réellement supportée par ce contexte.

Un vérificateur de grounding a donc été ajouté après la génération.

Il peut retourner :

```text
PASS
CONTRADICTION
UNSUPPORTED
INSUFFICIENT
```

Il permet notamment de détecter les réponses qui introduisent des informations absentes du contexte ou qui contredisent celui-ci.

Un cas de régression utile concernait Roitiflam.

Pour une question demandant les capacités apprises après le niveau 40, une première réponse incluait incorrectement des capacités apprises avant ce niveau.

Le pipeline de grounding et de retry a finalement permis d'obtenir :

```text
Lance-Flammes — 43
Fracass’Tête — 50
Hurlement — 55
Boutefeu — 62
```

Ce test a également mis en évidence un problème plus profond : vérifier l'ancrage d'une réponse et vérifier qu'elle répond réellement à la question sont deux problèmes différents.

---

## 8. Une réponse ancrée n'est pas nécessairement pertinente

L'une des observations les plus importantes du développement est apparue avec la question :

> Comment Pikachu peut-il apprendre Électacle ?

Plusieurs sections récupérées mentionnaient Électacle.

La section la mieux classée parlait d'Électacle en tant que capacité signature, tandis qu'une autre section contenait réellement des informations concernant son apprentissage.

Le générateur a produit une réponse à partir de la première section.

Cette réponse était factuellement supportée par le contexte fourni. Le grounding checker a donc retourné :

```text
PASS
```

Pourtant, la réponse ne répondait pas réellement à la question posée.

Cela a permis de mettre en évidence une distinction importante :

```text
Grounding :
"La réponse est-elle supportée par le contexte ?"

Répondabilité :
"Le contexte contient-il les informations nécessaires
pour répondre à la question ?"
```

Un contrôle séparé de suffisance du contexte a donc été expérimenté.

Cependant, celui-ci pouvait également considérer comme suffisant un contexte sémantiquement proche mais ne contenant pas réellement la réponse.

Il ajoutait également un nouvel appel au LLM et plusieurs secondes de latence.

Cette expérimentation a montré que les problèmes de retrieval et de sélection de l'information ne peuvent pas simplement être compensés par l'ajout de nouvelles validations basées sur des prompts.

---

## 9. Limites d'un RAG pur pour les questions structurées

Une autre observation importante était que de nombreuses questions sur Pokémon correspondent fondamentalement à des requêtes de base de données.

Par exemple :

```text
Quelles capacités Roitiflam apprend après le niveau 40 ?

Quelles CT Pikachu peut-il apprendre dans Écarlate et Violet ?

Comment Tutafeh de Galar évolue-t-il ?
```

Utiliser du retrieval documentaire et un LLM pour ces questions introduit plusieurs sources d'erreur inutiles :

- retrieval incomplet ;
- sélection de la mauvaise section ;
- filtrage incorrect par le LLM ;
- lignes manquantes provenant de tableaux ;
- latence supplémentaire.

Cette observation a conduit à l'introduction d'une branche dédiée aux données structurées.

---

## 10. Base de données structurée PokéAPI

Les données PokéAPI sont téléchargées localement puis converties en SQLite.

La base structurée contient notamment des informations concernant :

- les Pokémon et les espèces ;
- les formes ;
- les capacités ;
- les méthodes d'apprentissage ;
- les groupes de versions ;
- les machines ;
- les relations d'évolution ;
- les conditions d'évolution ;
- les objets ;
- les localisations ;
- les types ;
- les régions.

Au cours du développement, l'analyse des tables d'évolution a révélé plusieurs tables de référence manquantes.

Des données PokéAPI supplémentaires ont donc été importées pour :

```text
genders
locations
location_names
types
type_names
regions
region_names
```

Après cette extension, l'ensemble des références utilisées dans les données d'évolution pouvait être résolu sans références orphelines.

L'analyse a également permis de vérifier que l'ensemble des champs de conditions présents dans le schéma d'évolution importé étaient effectivement utilisés.

---

## 11. Données Pokédex personnalisées

PokéAPI ne contient pas toutes les informations utiles au projet.

Un tableur bilingue personnalisé est donc maintenu :

```text
corpus/pokedex_particularites.xlsx
```

Il contient 1 272 lignes représentant les 1 025 espèces du Pokédex national ainsi que leurs différentes formes pertinentes pour le projet.

Le tableur contient notamment :

- les noms français et anglais ;
- les formes ;
- les types ;
- les générations ;
- les capacités signature ;
- les talents signature ;
- certaines particularités de movepool ;
- les sous-groupes ;
- les différences liées au sexe ;
- diverses autres particularités propres aux Pokémon.

Des colonnes de mapping explicites vers PokéAPI ont été ajoutées afin que chaque ligne puisse être identifiée sans ambiguïté.

Le mapping contient :

```text
PokéAPI Species ID
PokéAPI Pokémon ID
PokéAPI Pokémon Identifier
PokéAPI Form ID
PokéAPI Form Identifier
PokéAPI Is Default
PokéAPI Mapping Status
```

Le mapping obtenu comprend :

```text
1 272 entrées dans le tableur
1 025 espèces distinctes
1 267 mappings exacts Pokémon / forme
5 mappings au niveau de l'espèce uniquement
```

Les cinq cas `SPECIES_ONLY` correspondent à des formes qui ne disposent pas d'une correspondance Pokémon/forme indépendante dans les données PokéAPI utilisées.

---

## 12. Base SQLite unifiée

À l'origine, les requêtes structurées accédaient directement au tableur avec Pandas.

Cela créait deux systèmes de données différents à l'exécution :

```text
Excel / Pandas
PokéAPI / SQLite
```

L'architecture a ensuite été simplifiée autour d'une seule base générée :

```text
pokemon.db
```

Le processus de construction est désormais :

```text
CSV PokéAPI
    ↓
pokeapi.db
    ↓
         + pokedex_particularites.xlsx
         ↓
      pokemon.db
```

Le tableur est donc uniquement une source utilisée lors de la construction de la base.

À l'exécution :

> Toutes les requêtes structurées passent par `pokemon.db`.

Cela supprime notamment le chargement du fichier Excel au démarrage et fournit une interface unique pour l'ensemble des données structurées.

---

## 13. Moteur de requêtes structurées sécurisé

Le moteur de requêtes structurées n'autorise pas le LLM à générer directement du SQL arbitraire.

Le LLM transforme plutôt la question de l'utilisateur en une opération sémantique contrainte.

Par exemple :

```json
{
  "operation": "get_level_up_moves",
  "pokemon": "Roitiflam",
  "version_group": "scarlet-violet",
  "min_level": 41
}
```

Python valide ensuite ce plan et exécute des requêtes SQL prédéfinies.

Les opérations actuellement prises en charge sont :

```text
get_evolutions
get_level_up_moves
get_machine_moves
get_move_learning_methods
```

Cette architecture conserve la flexibilité du langage naturel pour comprendre la question tout en gardant l'exécution de la base de données déterministe.

---

## 14. Validation des requêtes d'évolution

Les évolutions ont nécessité une attention particulière, car PokéAPI représente de nombreuses conditions différentes.

Les tests couvrent notamment des conditions concernant :

- les objets ;
- les niveaux ;
- les localisations ;
- le sexe ;
- les capacités connues ;
- les types de capacités connues ;
- les Pokémon présents dans l'équipe ;
- les types présents dans l'équipe ;
- les objets tenus ;
- les régions ;
- le moment de la journée ;
- les relations entre statistiques physiques ;
- les dégâts subis ;
- les formes ;
- les groupes de versions.

Deux erreurs d'implémentation ont notamment été découvertes pendant les tests.

### Formes régionales

Une requête concernant :

```text
Comment Tutafeh de Galar évolue-t-il ?
```

permettait initialement de récupérer des évolutions ne correspondant pas à la forme source demandée.

Un filtrage strict sur la forme source a corrigé ce comportement.

### Relations entre statistiques

PokéAPI utilise notamment les valeurs :

```text
1
0
-1
```

pour certaines conditions d'évolution basées sur les statistiques.

Un test booléen classique éliminait incorrectement la valeur `0`.

Le code a donc été modifié afin de tester explicitement la différence avec `None`.

La suite de tests dédiée aux requêtes d'évolution a ensuite atteint :

```text
44 / 44 tests réussis
```

---

## 15. Validation des requêtes sur les capacités

Les requêtes structurées sur les capacités ont ensuite été ajoutées.

Elles couvrent notamment :

### Capacités apprises par niveau

Exemple :

```text
Quelles capacités Roitiflam apprend après le niveau 40
dans Écarlate et Violet ?
```

### Capacités apprises par machine

Exemple :

```text
Quelles CT Pikachu peut-il apprendre
dans Écarlate et Violet ?
```

### Méthodes d'apprentissage

Exemple :

```text
Comment Pikachu peut-il apprendre Électacle ?
```

Les tests couvrent notamment :

- les niveaux ;
- les machines ;
- les méthodes d'apprentissage ;
- les formes ;
- les groupes de versions ;
- les identifiants français et anglais ;
- les entrées invalides.

Une hypothèse incorrecte concernant le schéma a également été découverte pendant les tests : la table PokéAPI `machines` ne contenait pas la colonne générique `id` attendue par la première implémentation.

La requête a été corrigée afin d'utiliser directement les champs réellement présents dans la table.

---

## 16. Architecture actuelle du routage

Le projet utilise désormais trois chemins d'exécution :

```text
                       Question
                          │
                        Routeur
              ┌───────────┼───────────┐
              │           │           │
         STRUCTURED      RAG        HYBRID
              │           │           │
         pokemon.db   Poképédia   pokemon.db
                                      +
                                  Poképédia
```

### STRUCTURED

Utilisé lorsque la réponse peut être obtenue de manière déterministe depuis la base locale.

Cela concerne notamment :

- les évolutions ;
- les capacités apprises par niveau ;
- les machines ;
- les méthodes d'apprentissage.

### RAG

Utilisé pour les questions documentaires nécessitant le contenu textuel de Poképédia.

Cela concerne par exemple des explications sur :

- l'apparence ;
- la biologie ;
- l'histoire ;
- les descriptions ;
- différentes informations contextuelles.

### HYBRID

Utilisé lorsque les données structurées et le contexte documentaire peuvent tous les deux contribuer à la réponse.

---

## 17. Validation de bout en bout

Les trois chemins d'exécution ont été validés indépendamment.

### STRUCTURED

Des questions ont notamment permis de valider :

- les capacités de Roitiflam apprises par niveau ;
- les CT de Pikachu ;
- les méthodes d'apprentissage d'Électacle par Pikachu ;
- l'évolution de Tutafeh de Galar.

### HYBRID

Une question portant sur les particularités de Lovdisc a permis de combiner avec succès les informations structurées de la base et le contenu récupéré depuis Poképédia.

### RAG

Une question documentaire portant sur les joues rouges de Pikachu a été traitée uniquement à partir du retrieval Poképédia et a passé la validation de grounding.

---

## 18. Observations sur les performances

SQLite ne constitue pas un goulot d'étranglement significatif.

Lors des tests, l'exécution SQL des requêtes structurées se situait généralement autour de quelques dizaines de millisecondes.

La majeure partie de la latence provient actuellement des appels aux modèles locaux :

```text
Routeur
Parsing de la requête
Génération
Vérification de suffisance du contexte
Grounding
```

Une requête SQL exécutée en quelques millisecondes peut donc nécessiter plusieurs secondes de traitement au total à cause du routage et de l'interprétation sémantique.

Les questions `RAG` et `HYBRID` sont plus coûteuses puisqu'elles peuvent également nécessiter :

- le retrieval ;
- le reranking ;
- la validation du contexte ;
- la génération ;
- le grounding.

L'optimisation des performances a volontairement été repoussée afin de stabiliser en priorité l'architecture et la correction des réponses.

---

## 19. État actuel

L'architecture actuelle comprend désormais :

- un corpus Poképédia local ;
- une recherche hybride lexicale/vectorielle ;
- une recherche limitée au Pokémon identifié ;
- une recherche tenant compte des sections ;
- l'expansion exacte des sections ;
- un reranking par CrossEncoder ;
- une validation locale du grounding ;
- une base SQLite construite à partir de PokéAPI ;
- l'intégration du Pokédex personnalisé ;
- une base unifiée `pokemon.db` ;
- un moteur déterministe de requêtes structurées ;
- un routage `STRUCTURED` / `RAG` / `HYBRID` ;
- une suite de tests de régression pour les données structurées.

Le runtime ne dépend désormais plus directement du fichier Excel.

Celui-ci intervient uniquement lors de la construction de `pokemon.db`.

---

## 20. Travaux restants

Plusieurs éléments restent volontairement en cours de développement.

### Sélection des sections RAG

La sélection de la bonne section reste l'un des principaux problèmes du retrieval.

Un document peut contenir plusieurs sections lexicalement proches de la question alors qu'une seule contient réellement l'information recherchée.

Une prochaine étape consiste donc à améliorer la sélection sémantique entre ces sections sans multiplier inutilement les appels au LLM.

### Suffisance du contexte

L'étape actuelle de vérification de suffisance du contexte ajoute de la latence et a déjà produit des faux positifs.

Lorsque le retrieval et la sélection des sections seront suffisamment fiables, l'intérêt de cette étape devra être réévalué.

### Performances

Le routeur et le parseur sémantique reposent actuellement sur de l'inférence LLM locale et représentent une part importante de la latence des requêtes structurées.

Une stratégie de routage plus rapide pourra être étudiée une fois la correction du système stabilisée.

### Tests de régression

La suite de tests doit continuer à évoluer au fur et à mesure que de nouveaux cas limites et échecs de retrieval sont identifiés.

---

## 21. Principe de développement

Un principe général s'est progressivement dégagé du développement :

> Utiliser des données structurées déterministes lorsque la question est fondamentalement structurée, et utiliser le RAG lorsque la réponse nécessite réellement des documents.

L'objectif n'est donc pas de faire passer toutes les questions par un LLM.

Chaque composant doit être utilisé là où il apporte réellement quelque chose :

```text
SQLite       → faits structurés précis
Retrieval    → preuves documentaires pertinentes
LLM          → compréhension du langage et génération
Grounding    → validation des réponses
LangGraph    → orchestration
```

Ce principe constitue aujourd'hui la base de l'architecture du projet.