# Pokémon RAG

Local question-answering system for Pokémon data combining structured queries and Retrieval-Augmented Generation (RAG).

The system uses two complementary data sources:

- **PokéAPI + custom Pokédex data** stored in a local SQLite database for structured queries.
- **Poképédia** pages indexed locally for documentary and open-ended questions.

The application automatically routes each question to the appropriate source.

## Architecture

Three query paths are available:

- **STRUCTURED** — queries the local SQLite database.
- **RAG** — retrieves relevant Poképédia content.
- **HYBRID** — combines structured data and Poképédia context.

Structured queries currently support:

- Pokémon evolutions and evolution conditions
- level-up moves
- machine moves
- move learning methods
- Pokémon types, national number and introduction generation
- signature and pseudo-signature moves

Custom profiles also support general presentations.

The RAG pipeline uses hybrid retrieval, section-aware retrieval and reranking before generating an answer.

A separate [ADK agent](src/pokemon_rag/agent/README.md) uses local Qwen through
LiteLLM and LM Studio. This single-agent path exposes all ten MCP tools;
the existing graph and MCP client remain available.
Its deterministic guard preserves recognized level, game and form constraints
before tool execution, rejecting tools that cannot support them.
The validated local setup uses a 16384-token Qwen context window in LM Studio
to accommodate the ten tool schemas; see the agent guide for prerequisites.

## Stack

- Python
- LangGraph
- SQLite
- ChromaDB
- Sentence Transformers
- BM25
- CrossEncoder reranking
- LM Studio
- Local LLMs
- PokéAPI
- Poképédia

## Project structure

```text
pokemon-rag/
├── src/pokemon_rag/    # application Python
│   └── constraints/    # shared extraction of form, game and level constraints
├── scripts/            # préparation des données, batch et analyse
├── tests/              # tests isolés et validations avec ressources locales
├── benchmarks/         # évaluations et références factuelles
├── docs/               # guides de contribution et de transmission
├── data/               # ressources locales, hors versionnement
└── DEVELOPMENT_FR.md   # historique de développement
```

Generated databases, Poképédia pages and vector indexes are not stored in the repository.

## Setup

See the [constraints guide](src/pokemon_rag/constraints/README.md) for the shared extractors and their limits.

Create and activate a Python environment, then install the dependencies:

```bash
pip install -e .
```

LM Studio must be running locally with the models expected by the application.
Installation includes Gradio, declared in `pyproject.toml`, for the Web UI.

For the [Gradio Web conversation](src/pokemon_rag/web/README.md), with Qwen
available in LM Studio and local data already prepared:

```powershell
python -m pokemon_rag.web.app
```

The browser opens automatically. The interface reuses the ADK agent, retains
the conversation on screen and displays tool activity and elapsed time.
Each question is sent to the agent without previous message history.

## Build the data

These commands prepare or rebuild local resources; skip them when the data already exists. Read [the scripts guide (French)](scripts/README.md) before running them.

Download the PokéAPI data:

```bash
python scripts/pokeapi/download_pokeapi.py
```

Build the PokéAPI database:

```bash
python scripts/pokeapi/build_pokeapi_db.py
```

Build the unified Pokémon database:

```bash
python scripts/pokeapi/build_pokemon_db.py
```

Download and clean the Poképédia corpus:

```bash
python scripts/pokepedia/download.py
python scripts/pokepedia/clean.py
```

Build the RAG index:

```bash
python scripts/pokepedia/ingest.py
```

## Run

Start LM Studio, load the required local models, then run:

```bash
python -m pokemon_rag.graph.graph
```

## Tests

Tests are located in:

```text
tests/
```

They cover the PokéAPI database, mappings, evolutions, move queries and the structured query engine.

## Documentation

See [the architecture map](ARCHITECTURE.md) for current entry points and module
boundaries. [The French development history](DEVELOPMENT_FR.md) records past changes;
the older [English history](DEVELOPMENT.md) is not a synchronized translation.
## Contributor guides

See [documentation navigation](docs/README.md) and [test prerequisites](tests/README.md). These contributor guides are maintained in French.
