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
- Pokémon profile information

The RAG pipeline uses hybrid retrieval, section-aware retrieval and reranking before generating an answer.

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
└── README.md
```

Generated databases, Poképédia pages and vector indexes are not stored in the repository.

## Setup

Create and activate a Python environment, then install the dependencies:

```bash
pip install -r requirements.txt
```

LM Studio must be running locally with the models expected by the application.

## Build the data

Download the PokéAPI data:

```bash
python pokeapi/download_pokeapi.py
```

Build the PokéAPI database:

```bash
python pokeapi/build_pokeapi_db.py
```

Build the unified Pokémon database:

```bash
python pokeapi/build_pokemon_db.py
```

Download and clean the Poképédia corpus:

```bash
python download_pokepedia.py
python clean_pokepedia.py
```

Build the RAG index:

```bash
python ingest_pokemon.py
```

## Run

Start LM Studio, load the required local models, then run:

```bash
python pokemon_graph.py
```

## Tests

Tests are located in:

```text
tests/
```

They cover the PokéAPI database, mappings, evolutions, move queries and the structured query engine.

## Documentation

A separate document will describe the design decisions, development process, experiments and benchmark results.