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
- les capacités apprises par CT ou CS ;
- les méthodes d'apprentissage des capacités ;
- les types, le numéro national et la génération d'introduction ;
- les capacités signature et pseudo-signature.

Les profils personnalisés alimentent également les présentations générales.

Le pipeline RAG utilise une recherche hybride, une recherche tenant compte de la structure des sections et un reranking avant la génération de la réponse.

Un [agent ADK indépendant](src/pokemon_rag/agent/README.md) utilise Qwen local via
LiteLLM et LM Studio. Ce parcours comporte un seul agent et expose
les dix outils MCP ; le graphe et le client MCP existants restent disponibles.
Son guard déterministe préserve les contraintes reconnues de niveaux, de jeux
et de formes avant l'appel d'outil, en refusant les outils incompatibles.
La configuration locale validée utilise une fenêtre Qwen de 16384 tokens dans
LM Studio pour les dix schémas ; les prérequis sont dans le guide de l'agent.

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
├── src/pokemon_rag/    # application Python
│   └── constraints/    # extraction commune des formes, jeux et niveaux
├── scripts/            # préparation des données, batch et analyse
├── tests/              # tests isolés et validations avec ressources locales
├── benchmarks/         # évaluations et références factuelles
├── docs/               # guides de contribution et de transmission
├── data/               # ressources locales, hors versionnement
└── DEVELOPMENT_FR.md   # historique de développement
```

Les bases de données générées, les pages Poképédia téléchargées et les index vectoriels ne sont pas stockés dans le dépôt Git.

## Installation

Le [guide des contraintes](src/pokemon_rag/constraints/README.md) décrit les extracteurs partagés et leurs limites.

Créer et activer un environnement Python, puis installer les dépendances :

```bash
pip install -e .
```

LM Studio doit être lancé localement avec les modèles attendus par l'application.
L'installation inclut Gradio, déclaré dans `pyproject.toml`, pour l'interface Web.

## Construction des données

Ces commandes préparent ou reconstruisent les ressources locales ; elles ne sont pas nécessaires au lancement si les données existent déjà. Lire [scripts/README.md](scripts/README.md) avant de les exécuter.

Télécharger les données PokéAPI :

```bash
python scripts/pokeapi/download_pokeapi.py
```

Construire la base PokéAPI :

```bash
python scripts/pokeapi/build_pokeapi_db.py
```

Construire la base Pokémon unifiée :

```bash
python scripts/pokeapi/build_pokemon_db.py
```

Télécharger puis nettoyer le corpus Poképédia :

```bash
python scripts/pokepedia/download.py
python scripts/pokepedia/clean.py
```

Construire l'index RAG :

```bash
python scripts/pokepedia/ingest.py
```

## Lancement

Pour la [conversation Web Gradio](src/pokemon_rag/web/README.md), avec Qwen
disponible dans LM Studio et les données locales déjà préparées :

```powershell
python -m pokemon_rag.web.app
```

Le navigateur s'ouvre automatiquement. L'interface réutilise l'agent ADK,
conserve la conversation à l'écran et affiche l'activité des outils et le chrono.
Chaque question est envoyée à l'agent sans l'historique des messages précédents.

Lancer LM Studio, charger les modèles locaux nécessaires, puis exécuter :

```bash
python -m pokemon_rag.graph.graph
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

Consulter [le guide de navigation](docs/README.md) pour contribuer. Les [commandes de test](tests/README.md) distinguent les validations légères de celles nécessitant des ressources locales.

La [carte d'architecture](ARCHITECTURE.md) décrit les flux actuels, les points
d'entrée et les modules à modifier selon le comportement concerné.

Le développement du projet, les choix d'architecture, les problèmes rencontrés et les différents tests sont détaillés dans :

```text
DEVELOPMENT_FR.md
```

Un historique anglais plus ancien, non synchronisé avec la version française,
est disponible dans :

```text
DEVELOPMENT.md
```
