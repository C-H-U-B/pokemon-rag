## 1. Why Pokémon?

Pokémon was chosen as the domain for this project because it provides a particularly useful environment for experimenting with both Retrieval-Augmented Generation and structured data querying.

The domain combines two very different types of information.

### Large-scale textual data

There are 1,025 Pokémon species in the National Pokédex, with many additional forms and variants.

Poképédia therefore provides more than a thousand substantial pages containing mostly unstructured or semi-structured information about:

- biology and appearance;
- behavior;
- origins and inspirations;
- descriptions across games;
- anime and manga appearances;
- trivia;
- history;
- move descriptions and contextual information.

This creates a sufficiently large document corpus to make retrieval a real problem rather than a small demonstration.

The corpus contains tens of thousands of chunks distributed across more than a thousand documents, with many pages sharing similar vocabulary and section structures.

For example, almost every Pokémon page contains sections about evolution, moves, appearances and game data. The system must therefore identify not only the correct document, but often the correct section within that document.

### Highly structured data

At the same time, Pokémon contains a large amount of information naturally suited to relational databases.

Examples include:

- base statistics;
- types;
- abilities;
- moves;
- move learning methods;
- levels;
- Technical Machines;
- game versions;
- species and forms;
- evolution chains;
- evolution conditions;
- items;
- locations.

PokéAPI provides this information through a large relational dataset that can be imported into SQLite.

This makes Pokémon particularly interesting for testing the boundary between database queries and document retrieval.

For example:

```text
"What moves does Emboar learn after level 40?"
```

is fundamentally a structured database query.

By contrast:

```text
"Why does Pikachu have red cheeks?"
```

is better answered from documentary text.

Other questions may require both types of information.

### A natural hybrid use case

The objective is therefore not simply to build a Pokémon chatbot.

Pokémon serves as a practical test domain for a more general problem:

> How should an LLM-based system decide when to query structured data, when to search documents, and when to combine both?

The domain provides enough data and enough variety to experiment with:

```text
Structured data ──────── SQLite / PokéAPI
                              │
                              │
User question ── Router ──────┼────── Hybrid answer
                              │
                              │
Textual knowledge ─────── RAG / Poképédia
```

It also provides useful ground truth for testing. Many questions have precise, verifiable answers, which makes retrieval errors, incomplete answers and hallucinations easier to identify.

For these reasons, Pokémon provides a manageable but non-trivial benchmark for developing and evaluating a local hybrid RAG architecture.

---

## 2. Initial goal

The initial objective was to build a local system capable of answering detailed Pokémon questions while determining the most appropriate source of information for each question.

The main constraints were:

- local inference through LM Studio;
- no dependency on an external LLM API;
- retrieval over a large French Pokémon corpus;
- structured queries over a local relational database;
- answers grounded in the available sources;
- support for precise factual questions as well as open-ended questions;
- reasonable response times on consumer hardware.

The project initially focused primarily on RAG over Poképédia. As testing exposed the limitations of using document retrieval for inherently structured questions, the architecture progressively evolved toward the current STRUCTURED / RAG / HYBRID system.

## 3. Building the Poképédia corpus

Poképédia pages are downloaded and converted into local documents before indexing.

The processing pipeline is:

```text
Poképédia
    ↓
download_pokepedia.py
    ↓
raw pages
    ↓
clean_pokepedia.py
    ↓
cleaned documents
    ↓
ingest_pokemon.py
    ↓
ChromaDB index
```

The cleaned corpus currently contains approximately 1,200 Pokémon documents and tens of thousands of chunks.

A major requirement during preprocessing was to preserve the structure of the original articles.

Chunks therefore contain metadata such as:

```text
pokemon
source_file
section_path
section_chunk_number
```

This structure later became important for retrieval.

---

## 4. First RAG architecture

The initial retrieval system combined several techniques:

```text
Question
   ↓
Vector retrieval
   +
BM25 retrieval
   ↓
Reciprocal Rank Fusion
   ↓
CrossEncoder reranking
   ↓
Top results
   ↓
LLM
```

The current retrieval pipeline uses:

- multilingual Sentence Transformer embeddings;
- ChromaDB for vector search;
- BM25 lexical retrieval;
- Reciprocal Rank Fusion;
- CrossEncoder reranking.

This provided significantly better retrieval than relying on vector similarity alone.

However, good chunk-level retrieval was not sufficient.

---

## 5. Pokémon-scoped retrieval

A recurring problem was contamination between Pokémon pages.

When a question explicitly concerned a single Pokémon, globally searching the entire corpus could retrieve information about another Pokémon with similar terminology.

A strict retrieval rule was therefore introduced:

> When exactly one Pokémon is explicitly identified, retrieval remains restricted to that Pokémon.

This applies both to the initial retrieval and to retrieval retries.

The resulting behavior is:

```text
One identified Pokémon
        ↓
Search only this Pokémon

No identified Pokémon
        ↓
Global search

Ambiguous / multiple Pokémon
        ↓
Dedicated or global handling
```

This considerably reduced irrelevant retrieval results.

---

## 6. Section-aware retrieval

Poképédia pages contain structured sections such as:

```text
Évolution
Capacités apprises
Capacités apprises > Par montée en niveau
Capacités apprises > Par CT
Capacités apprises > Par reproduction
Localisations
Statistiques
```

Retrieving isolated chunks could provide incomplete context.

The system was therefore changed to preserve and exploit `section_path`.

When a relevant chunk is selected, the system can recover the complete logical section using:

```text
source_file
+
section_path
+
section_chunk_number
```

Instead of simply retrieving neighboring chunk IDs, the RAG pipeline expands the exact section.

This avoids accidentally joining unrelated portions of the same document.

---

## 7. Grounding validation

Generating an answer from retrieved context does not guarantee that the answer is actually supported by that context.

A grounding checker was therefore introduced after generation.

The checker can return:

```text
PASS
CONTRADICTION
UNSUPPORTED
INSUFFICIENT
```

This made it possible to detect answers where the model introduced information absent from or contradictory to the retrieved documents.

One useful regression case involved Roitiflam.

For a question asking which moves it learns after level 40, an early answer incorrectly included moves learned before level 40.

The grounding and retry pipeline eventually produced the expected subset:

```text
Lance-Flammes — 43
Fracass’Tête — 50
Hurlement — 55
Boutefeu — 62
```

This test also highlighted a deeper problem: grounding and question answering are not the same thing.

---

## 8. Grounded does not mean relevant

One of the most important findings during development came from the question:

> Comment Pikachu peut-il apprendre Électacle ?

Several retrieved sections mentioned Électacle.

The highest-ranked section discussed Électacle as a signature move, while another section contained actual information about how the move could be learned.

The generator produced an answer based on the first section.

The answer was factually supported by the supplied context, so the grounding checker returned:

```text
PASS
```

But it did not actually answer the question.

This exposed an important distinction:

```text
Grounding:
"Is the answer supported by the context?"

Answerability:
"Does the context contain the information needed to answer the question?"
```

A separate context sufficiency check was experimented with, but it could also incorrectly classify semantically related context as sufficient.

It additionally introduced another LLM call and several seconds of latency.

The experiment showed that retrieval quality and information selection cannot simply be replaced by additional validation prompts.

---

## 9. Limits of pure RAG for structured questions

Another important observation was that many Pokémon questions are fundamentally database queries.

Examples include:

```text
Quelles capacités Roitiflam apprend après le niveau 40 ?

Quelles CT Pikachu peut-il apprendre dans Écarlate et Violet ?

Comment Tutafeh de Galar évolue-t-il ?
```

Using document retrieval and an LLM for these questions introduces several unnecessary sources of error:

- incomplete retrieval;
- wrong section selection;
- hallucinated filtering;
- missing rows from tables;
- additional latency.

This motivated the introduction of a structured data path.

---

## 10. PokéAPI structured database

PokéAPI data is downloaded locally and converted into SQLite.

The structured database contains information such as:

- Pokémon and species;
- forms;
- moves;
- move learning methods;
- version groups;
- machines;
- evolution relationships;
- evolution conditions;
- items;
- locations;
- types;
- regions.

During development, the evolution tables revealed several missing reference datasets.

Additional PokéAPI tables were therefore imported for:

```text
genders
locations
location_names
types
type_names
regions
region_names
```

After this extension, all evolution reference fields could be resolved without orphaned references.

The evolution dataset currently uses all of the condition fields present in the imported schema.

---

## 11. Custom Pokédex data

PokéAPI does not contain every piece of information useful to the project.

A custom bilingual spreadsheet is therefore maintained:

```text
corpus/pokedex_particularites.xlsx
```

It contains 1,272 rows representing the 1,025 National Pokédex species and their relevant forms.

The spreadsheet includes additional information such as:

- French and English names;
- forms;
- types;
- generation information;
- signature moves and abilities;
- unusual movepools;
- subgroups;
- gender differences;
- other Pokémon-specific distinctions.

Explicit PokéAPI mapping columns were added to make each spreadsheet row unambiguous.

The mapping contains:

```text
PokéAPI Species ID
PokéAPI Pokémon ID
PokéAPI Pokémon Identifier
PokéAPI Form ID
PokéAPI Form Identifier
PokéAPI Is Default
PokéAPI Mapping Status
```

The resulting mapping contains:

```text
1,272 spreadsheet entries
1,025 distinct species
1,267 exact Pokémon/form mappings
5 species-only mappings
```

The five species-only cases correspond to forms not represented as independent PokéAPI Pokémon entries in the imported data.

---

## 12. Unified SQLite database

Originally, structured queries accessed the spreadsheet directly with Pandas.

This created two different runtime data systems:

```text
Excel / Pandas
PokéAPI / SQLite
```

The architecture was simplified by creating a single generated database:

```text
pokemon.db
```

The build process is now:

```text
PokéAPI CSV
    ↓
pokeapi.db
    ↓
         + pokedex_particularites.xlsx
         ↓
      pokemon.db
```

The spreadsheet is therefore a build-time source only.

At runtime:

> All structured queries access `pokemon.db`.

This removed the need to load the Excel spreadsheet during application startup and provides a single structured data interface.

---

## 13. Safe structured query engine

The structured query engine does not allow the LLM to generate arbitrary SQL.

Instead, the LLM converts the user question into a constrained semantic operation.

For example:

```json
{
  "operation": "get_level_up_moves",
  "pokemon": "Roitiflam",
  "version_group": "scarlet-violet",
  "min_level": 41
}
```

Python then validates this plan and executes predefined SQL.

The currently supported operations are:

```text
get_evolutions
get_level_up_moves
get_machine_moves
get_move_learning_methods
```

This design provides the flexibility of natural-language parsing while keeping database execution deterministic.

---

## 14. Evolution query validation

Evolution queries required careful handling because PokéAPI represents many different conditions.

Tests were added for conditions involving:

- items;
- levels;
- locations;
- gender;
- known moves;
- known move types;
- party Pokémon;
- party types;
- held items;
- regions;
- time of day;
- physical-stat relationships;
- damage taken;
- forms;
- version groups.

Two implementation bugs were discovered during testing.

### Regional forms

A query for:

```text
Comment Tutafeh de Galar évolue-t-il ?
```

initially allowed evolution rows that did not correspond to the requested source form.

Strict source-form filtering fixed the issue.

### Physical stat relationships

PokéAPI uses values including:

```text
1
0
-1
```

for some evolution conditions.

An ordinary truth-value check incorrectly discarded `0`.

The code was changed to explicitly test against `None`.

The dedicated evolution query suite subsequently reached:

```text
44 / 44 tests passing
```

---

## 15. Move query validation

Structured move queries were then added.

They support:

### Level-up moves

Example:

```text
Quelles capacités Roitiflam apprend après le niveau 40
dans Écarlate et Violet ?
```

### Machine moves

Example:

```text
Quelles CT Pikachu peut-il apprendre
dans Écarlate et Violet ?
```

### Learning methods

Example:

```text
Comment Pikachu peut-il apprendre Électacle ?
```

The move query tests cover:

- levels;
- machines;
- learning methods;
- forms;
- version groups;
- French and English identifiers;
- invalid inputs.

One schema assumption was discovered during testing: the PokéAPI `machines` table does not contain the expected generic `id` column.

The query was corrected to use the actual machine fields instead of relying on an assumed schema.

---

## 16. Current routing architecture

The project now uses three execution paths:

```text
                       Question
                          │
                        Router
              ┌───────────┼───────────┐
              │           │           │
         STRUCTURED      RAG        HYBRID
              │           │           │
         pokemon.db   Poképédia   pokemon.db
                                      +
                                  Poképédia
```

### STRUCTURED

Used when the answer can be deterministically obtained from the local database.

Examples:

- evolution;
- level-up moves;
- machines;
- move learning methods.

### RAG

Used for documentary questions that require Poképédia text.

Examples include explanations about:

- appearance;
- biology;
- history;
- descriptions;
- contextual information.

### HYBRID

Used when both structured Pokémon information and documentary context are useful.

---

## 17. End-to-end validation

The three execution paths have been validated independently.

### STRUCTURED

Validated with questions covering:

- Roitiflam level-up moves;
- Pikachu machine moves;
- Pikachu move learning methods;
- Tutafeh de Galar evolution.

### HYBRID

A profile-style question about Lovdisc successfully combined structured database information with Poképédia retrieval.

### RAG

A documentary question about Pikachu's red cheeks was answered using Poképédia retrieval and passed grounding validation.

---

## 18. Performance observations

SQLite itself is not a performance bottleneck.

Typical structured SQL execution during testing was on the order of a few tens of milliseconds.

Most latency currently comes from local LLM calls:

```text
Router
Query parsing
Answer generation
Context sufficiency
Grounding validation
```

A structured query that takes only milliseconds to execute can therefore still take several seconds end-to-end because of routing and semantic parsing.

RAG and HYBRID questions are slower because they may additionally involve:

- retrieval;
- reranking;
- context validation;
- generation;
- grounding.

Performance optimization has intentionally been postponed until the architecture and correctness are stable.

---

## 19. Current state

The current architecture has reached the following stage:

- local Poképédia corpus;
- hybrid lexical/vector retrieval;
- Pokémon-scoped retrieval;
- section-aware retrieval;
- exact section expansion;
- CrossEncoder reranking;
- local grounding validation;
- PokéAPI SQLite database;
- custom Pokédex integration;
- unified `pokemon.db`;
- deterministic structured query engine;
- STRUCTURED / RAG / HYBRID routing;
- dedicated structured-data regression tests.

The runtime no longer depends directly on the Excel spreadsheet.

The spreadsheet is used only when building `pokemon.db`.

---

## 20. Remaining work

Several areas are intentionally still under development.

### RAG section selection

Section selection remains one of the main retrieval problems.

A document can contain several sections that are lexically related to a question while only one contains the requested information.

Future work should improve semantic selection between these sections without adding unnecessary LLM calls.

### Context sufficiency

The current context sufficiency stage adds latency and has produced false-positive results.

Once retrieval and section selection are sufficiently reliable, its usefulness should be reevaluated.

### Performance

The Router and semantic query parser currently rely on local LLM inference and account for most of the latency of structured questions.

A faster routing strategy can be investigated after correctness is stable.

### Regression suite

The test suite should continue growing as new retrieval failures and edge cases are discovered.

---

## 21. Development principle

A general principle emerged during the project:

> Use deterministic structured data when the question is fundamentally structured, and use RAG when the answer genuinely requires documents.

The goal is not to make every question pass through an LLM.

The goal is to use each component only where it provides value:

```text
SQLite       → precise structured facts
Retrieval    → relevant documentary evidence
LLM          → language understanding and generation
Grounding    → answer validation
LangGraph    → orchestration
```

This principle is the basis of the current architecture.