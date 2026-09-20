# Pokémon RAG

🇬🇧 [English version](README.md)

Système local de questions-réponses sur Pokémon combinant requêtes structurées et Retrieval-Augmented Generation (RAG).

Le système utilise deux sources de données complémentaires :

- **PokéAPI + données Pokédex personnalisées**, stockées dans une base SQLite locale pour les requêtes structurées.
- **Poképédia**, indexé localement pour les questions documentaires et ouvertes.

L'application détermine automatiquement quelle source utiliser selon la question.

## Pourquoi Pokémon ?

Pokémon constitue un cas d'étude particulièrement adapté à une architecture hybride mêlant données structurées et recherche documentaire.

Avec **1 025 espèces** dans le Pokédex national, auxquelles s'ajoutent de nombreuses formes alternatives, Poképédia fournit plus d'un millier de pages contenant des informations textuelles sur la biologie, l'apparence, les inspirations, l'histoire ou encore les apparitions des Pokémon.

Cela permet de travailler sur un corpus suffisamment important pour que la recherche documentaire constitue un véritable problème de RAG.

En parallèle, l'univers Pokémon contient une grande quantité de données naturellement structurées : statistiques, types, talents, capacités, niveaux d'apprentissage, CT, versions des jeux, évolutions, objets ou encore localisations. Ces informations se prêtent particulièrement bien à une représentation relationnelle avec PokéAPI et SQLite.

Le projet permet ainsi d'expérimenter trois approches complémentaires :

- interrogation déterministe de données structurées ;
- recherche documentaire par RAG ;
- combinaison des deux approches.

## Architecture

Trois chemins de traitement sont disponibles :

- **STRUCTURED** — interroge la base SQLite locale.
- **RAG** — recherche les informations pertinentes dans le corpus Poképédia.
- **HYBRID** — combine les données structurées et le contexte provenant de Poképédia.

Les requêtes structurées prennent actuellement en charge :

- les évolutions et leurs conditions ;
- les capacités apprises par niveau ;
- les capacités apprises par machine ;
- les méthodes d'apprentissage des capacités ;
- les informations de profil des Pokémon.

Le pipeline RAG utilise une recherche hybride, une recherche tenant compte de la structure des sections et un reranking avant la génération de la réponse.

## Technologies

- Python
- LangGraph
- SQLite
- ChromaDB
- Sentence Transformers
- BM25
- CrossEncoder reranking
- LM Studio
- LLM locaux
- PokéAPI
- Poképédia

## Structure du projet

```text
pokemon-rag/
├── corpus/
│   └── pokedex_particularites.xlsx
├── pokeapi/
│   ├── download_pokeapi.py
│   ├── build_pokeapi_db.py
│   └── build_pokemon_db.py
├── tests/
├── clean_pokepedia.py
├── context_sufficiency.py
├── download_pokepedia.py
├── grounding_checker.py
├── ingest_pokemon.py
├── pokemon_graph.py
├── pokemon_nodes.py
├── pokemon_query_engine.py
├── pokemon_router.py
├── rag_pokemon.py
├── README.md
└── README_FR.md
```

Les bases de données générées, les pages Poképédia téléchargées et les index vectoriels ne sont pas stockés dans le dépôt Git.

## Installation

Créer et activer un environnement Python, puis installer les dépendances :

```bash
pip install -r requirements.txt
```

LM Studio doit être lancé localement avec les modèles attendus par l'application.

## Construction des données

Télécharger les données PokéAPI :

```bash
python pokeapi/download_pokeapi.py
```

Construire la base PokéAPI :

```bash
python pokeapi/build_pokeapi_db.py
```

Construire la base Pokémon unifiée :

```bash
python pokeapi/build_pokemon_db.py
```

Télécharger puis nettoyer le corpus Poképédia :

```bash
python download_pokepedia.py
python clean_pokepedia.py
```

Construire l'index RAG :

```bash
python ingest_pokemon.py
```

## Lancement

Lancer LM Studio, charger les modèles locaux nécessaires, puis exécuter :

```bash
python pokemon_graph.py
```

## Tests

Les tests sont regroupés dans :

```text
tests/
```

Ils couvrent notamment :

- la construction des données PokéAPI ;
- le mapping entre le Pokédex personnalisé et PokéAPI ;
- la base SQLite unifiée ;
- les évolutions et leurs conditions ;
- les requêtes sur les capacités ;
- le moteur de requêtes structurées.

## Documentation

Le développement du projet, les choix d'architecture, les problèmes rencontrés et les différents tests sont détaillés dans :

```text
DEVELOPMENT_FR.md
```

La version anglaise correspondante est disponible dans :

```text
DEVELOPMENT.md
```