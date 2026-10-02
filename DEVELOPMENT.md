# Development Notes

🇫🇷 [Version française](DEVELOPMENT_FR.md)

This document traces the evolution of the Pokémon RAG project throughout
development. It is not intended to present a fixed final architecture:
it preserves the main stages, problems encountered, experiments, and
decisions that progressively shaped the system.

## 1. \[Feature\] Starting point: experimenting with a local RAG

The project began as an experiment around a locally executed
Retrieval-Augmented Generation pipeline.

Pokémon was chosen as the working domain because it naturally combines
two types of information:

-   a large documentary corpus, notably through Poképédia;
-   highly structured data, available notably through PokéAPI.

The domain is large enough to expose real retrieval problems while
remaining easy to verify manually.

The initial objective was therefore to build a system capable of
answering detailed questions from Poképédia using local models served by
LM Studio.

## 2. \[Feature\] Building the Poképédia corpus

The first step consisted of downloading and cleaning Poképédia pages to
build a usable local corpus.

The general pipeline progressively became:

``` text
Poképédia
   ↓
Download
   ↓
Raw pages
   ↓
Cleaning
   ↓
Structured documents
   ↓
Chunking
   ↓
ChromaDB
```

The corpus represents more than a thousand documents and several tens of
thousands of chunks.

From the cleaning stage onward, preserving article structure proved
important. Indexed documents therefore retain information that makes it
possible to identify, among other things, the Pokémon, the source
document, and the original section.

This decision later proved important when retrieval began to directly
use section structure.

## 3. \[Feature\] First retrieval pipeline

The first RAG architecture combined semantic and lexical search:

``` text
Question
   ↓
Vector search
   +
BM25
   ↓
Reciprocal Rank Fusion
   ↓
CrossEncoder
   ↓
Context
   ↓
LLM
```

Combining embeddings, BM25, and a reranker produced better results than
vector search alone.

However, the first experiments showed that retrieving individually
relevant chunks still did not guarantee reliable context.

Two problems quickly became important:

1.  results from the wrong Pokémon could be retrieved;
2.  a relevant chunk could contain only part of the required
    information.

## 4. \[Feature\] Restricting search to the relevant Pokémon

When a question explicitly mentions a single Pokémon, a global search
can retrieve passages about other Pokémon that use similar vocabulary.

A strict rule was therefore added:

> When exactly one Pokémon is identified unambiguously, retrieval
> remains restricted to that Pokémon.

This constraint is preserved during any additional searches performed by
the system.

The general behavior became:

``` text
One Pokémon identified
        ↓
Search restricted to that Pokémon

No Pokémon identified
        ↓
Global search

Several Pokémon or ambiguity
        ↓
Context-dependent handling
```

This step reduced a major source of context contamination.

## 5. \[Feature\] Using section structure

Poképédia articles are organized into sections and subsections.
Information can be spread across several chunks belonging to the same
logical section.

Retrieval therefore evolved to take this structure into account.

When a relevant result is selected, the system can retrieve the other
chunks belonging to exactly the same section instead of simply taking
neighboring chunks in the index.

The objective is to reconstruct coherent context:

``` text
Relevant result
      ↓
Identify its section
      ↓
Section expansion
      ↓
Complete documentary context
```

This evolution improved the coherence of the context provided to the
generator.

## 6. \[Feature\] Grounding and retry mechanism

An answer produced from retrieved context can still introduce
information absent from the sources or contradict them.

A grounding check was therefore added after generation.

It distinguishes several situations:

``` text
PASS
CONTRADICTION
UNSUPPORTED
INSUFFICIENT
```

This step also led to the introduction of a retry mechanism. Depending
on the type of failure, the system can attempt a new generation or
search for better context.

However, this experiment revealed an important distinction:

> An answer can be perfectly grounded in its context without actually
> answering the question correctly.

## 7. \[Feature\] Experimenting with context sufficiency

To address this problem, a separate context-sufficiency verification
step was tested.

The idea was to distinguish two questions:

``` text
Grounding
→ Is the answer supported by the context?

Sufficiency
→ Does the context actually contain what is needed to answer?
```

In practice, this new validation could itself produce false positives
and added an extra call to the local model.

This step reinforced an idea that would become important later in the
project: adding LLM validations does not necessarily fix a problem
located earlier in the retrieval chain.

## 8. \[Architecture\] Improving the representation used for search

Some retrieval errors came from how chunks were represented in the
index.

The system was therefore modified to distinguish:

-   the source text, preserved for delivery to the generator;
-   an enriched representation used for embeddings and search.

The search representation contains more structural context, notably the
identity of the Pokémon and the passage's position within the article.

This separation improves search without polluting the documentary text
ultimately passed to the LLM.

## 9. \[Architecture\] RAG limitations for structured data

Over the course of testing, some questions proved poorly suited to RAG.

Requests concerning, for example:

-   an evolution;
-   moves learned at certain levels;
-   TMs available in a version;
-   a learning method;

are closer to relational queries than documentary search.

Systematically routing these questions through RAG introduced several
risks:

-   incomplete retrieval;
-   wrong section;
-   approximate filtering by the LLM;
-   loss of information contained in tables;
-   unnecessary latency.

The project therefore began evolving from a pure RAG system toward a
hybrid architecture.

## 10. \[Feature\] Introducing PokéAPI data

PokéAPI data was downloaded and imported into SQLite.

The objective was not to reproduce the entire PokéAPI structure in the
application code, but to have a sufficiently complete local relational
source for deterministically answering structured questions.

During this stage, the imported schema was progressively completed when
some required relationships were not yet available locally.

This phase also demonstrated the value of validating the actual PokéAPI
schema rather than compensating for its particularities in higher layers
of the system.

## 11. \[Feature\] Integrating the custom Pokédex

In parallel, a bilingual spreadsheet is used to store project-specific
information that is not directly available in PokéAPI.

It contains the species from the National Pokédex as well as forms
relevant to the project and various additional information.

An explicit mapping to PokéAPI was added to link spreadsheet rows
unambiguously to entities in the official database.

This step prepared the merge between custom data and PokéAPI data.

## 12. \[Architecture\] Moving to a unified SQLite database

At one point in development, the runtime used both SQLite and the
spreadsheet through Pandas.

This organization created two different access paths to structured data.

The architecture was therefore simplified around a single database:

``` text
PokéAPI
   ↓
Intermediate database
   │
   ├──── Custom Pokédex data
   ↓
pokemon.db
```

The spreadsheet remains a build source but is no longer queried directly
at runtime.

The rule is now simple:

> Structured runtime queries go through `pokemon.db`.

This unification reduces runtime dependencies and provides a single
interface for structured data.

## 13. \[Feature\] Creating the structured query engine

The system does not allow the LLM to freely generate SQL.

Instead, a structured question is transformed into a constrained
semantic operation, then validated by Python before a predefined SQL
query is executed.

The principle is:

``` text
Question
   ↓
Interpretation
   ↓
Validated structured plan
   ↓
Predefined SQL function
   ↓
Deterministic result
```

The first query families concern evolutions and moves, notably level-up
learning, TMs, and learning methods.

This choice preserves natural-language understanding while avoiding
arbitrary SQL generation.

## 14. \[Bug fix\] Stabilizing evolutions and forms

Evolutions were one of the first complex parts of the structured engine.

The data can depend on a form, version, item, level, or other
conditions.

Several problems were discovered during this phase, notably around the
distinction between:

-   the species;
-   the Pokémon form;
-   the game version.

The engine was progressively corrected to keep these concepts separate
and prevent a rule associated with one specific form from being applied
to another.

This phase was also used to strengthen regression tests for the
structured engine.

## 15. \[Feature\] Extending structured queries to moves

The structured engine was then extended to the main questions about move
learning.

It can notably handle:

``` text
moves learned by level
TMs
learning methods
```

This step confirmed that PokéAPI data was better suited than RAG for
this type of question.

It also made it possible to identify and correct several assumptions
initially made about the relational schema.

## 16. \[Feature\] Emergence of the three execution routes

At this stage, the architecture took a more general form with three
paths:

``` text
                     Question
                        │
                      Router
               ┌─────────┼─────────┐
               │         │         │
         STRUCTURED      RAG     HYBRID
               │         │         │
          pokemon.db  Poképédia   combination
```

**STRUCTURED**

Used when the answer can be obtained directly from relational data.

**RAG**

Used when the answer requires documentary, explanatory, or contextual
content.

**HYBRID**

Used when both sources can contribute to the answer.

This separation is a major change from the initial RAG: the system no
longer tries to make every question go through the same pipeline.

## 17. \[Architecture\] Refactoring the project structure

As the number of components increased, the project was reorganized
around a `src/pokemon_rag` package.

Responsibilities were separated into several groups:

``` text
graph/       orchestration and routing
structured/  queries against pokemon.db
rag/         retrieval and documentary validations
scripts/     data construction and ingestion
tests/       regressions
```

Paths to data, databases, and indexes were also centralized.

This refactoring clarified the separation between:

-   data construction;
-   runtime;
-   tests.

## 18. \[Performance\] First targeted performance work

Once the main routes were functional, timing measurements showed that
SQLite was not the main bottleneck.

SQL queries generally executed in a few tens of milliseconds, while some
calls to local models took several seconds.

The router was the first component targeted.

**Fast Router**

A deterministic router was added before the LLM router.

Its principle is deliberately conservative:

``` text
Question
   ↓
Fast Router
   ├── certain decision → direct route
   └── uncertainty      → LLM router
```

Sufficiently explicit structured questions can therefore be sent to
`STRUCTURED` without a model call.

The LLM router remains available as a fallback for ambiguous,
documentary, or hybrid questions.

For simple structured cases, this change reduced routing time from
several seconds to a few tens of milliseconds.

## 19. \[Performance\] Fast Parser for structured queries

After optimizing the router, measurements showed that the main remaining
cost for a simple structured query came from the semantic parser.

A deterministic Fast Parser was therefore added before the LLM parser.

The architecture becomes:

``` text
Question
   ↓
Fast Router
   ↓
Fast Parser
   ├── certain plan → SQL
   └── uncertainty  → LLM parser → SQL
```

The Fast Parser does not try to understand every possible phrasing.

It only takes over when it can identify the operation and its parameters
with sufficient confidence. In all other cases, the existing LLM
behavior is preserved.

This approach follows the same principle as the Fast Router: reserve
models for situations where their interpretation capabilities actually
add value.

## 20. \[Architecture\] Removing the separate sufficiency check

The pre-generation context check added a model call and partially
duplicated the faithfulness check performed after the answer. It was
removed from documentary and hybrid paths.

The post-generation check then decides whether the answer can be
accepted, whether a new search is required, or whether the answer must
be regenerated. Graph tests verify that these retries remain bounded and
that retrieval preserves the targeted Pokémon.

## 21. \[Performance\] Lazy loading of retrieval

Importing graph modules triggered loading of the corpus and retrieval
models even when the query or test did not use them.

This initialization was moved to the first actual access to documentary
retrieval. Structured processing and tests using simulated dependencies
therefore avoid this cost.

## 22. \[Bug fix\] Separating retry budgets

A shared counter limited both new searches and regenerations. An
additional search could therefore prevent a later correction of the
answer.

The two mechanisms were given independent budgets, each allowing one
retry. Regression tests verify that they can occur sequentially without
causing a loop. An unrecognized control decision stops processing.

## 23. \[Bug fix\] Distinguishing insufficient context from an incomplete answer

The faithfulness check could accept an answer consistent with the
sources even when those sources did not actually make it possible to
answer the question. Its instructions and Python checks were
strengthened to explicitly examine context sufficiency and unsupported
claims.

An answer could also omit information that was nevertheless available.
The `INCOMPLETE` decision was added to trigger regeneration in this
case, without unnecessarily rerunning documentary retrieval.

## 24. \[Feature\] Setting up benchmarks

Separate benchmarks were added to evaluate documentary retrieval,
routing, and the faithfulness check, followed by a full-graph benchmark
linking these checks together.

For retrieval, questions were written from real corpus sections, with an
expected source for each case. For the faithfulness check, synthetic
contexts make it possible to isolate the model's decision from retrieval
quality.

The graph benchmark verifies structured, documentary, and hybrid paths,
as well as rejection of multiple requests. It distinguishes a structured
answer produced directly from a generated answer subjected to the
faithfulness check.

Durations observed on the full graph motivated the addition of per-stage
measurements to locate processing costs.

## 25. \[Feature\] Tracking executions and their performance

The overall duration of a query did not explain why it was slow. A
per-execution trace was added to the graph to connect the path taken,
retries, final decision, and time spent in each stage.

Traces are stored as JSONL and a script aggregates them to compare paths
and identify slow queries. Initial observations confirmed the weight of
model calls compared with SQL execution and context construction.

## 26. \[Feature\] Measuring model usage

Call duration alone was not enough to distinguish a long response from a
model slowdown. Traces were therefore enriched with token volumes and
throughput for generation, checking, and regeneration calls.

Throughput is calculated over the total duration of the call: it
includes prompt processing and does not measure text generation alone.
The analysis script uses this information while preserving support for
older traces.

## 27. \[Bug fix\] Aligning the router with available operations

The router sent questions about types, abilities, and stats to
`STRUCTURED`, even though the engine did not provide an operation for
answering them.

The fast rules and prompt were aligned with the available operations:
evolutions, level-up moves, machine moves, and learning methods. At this
stage, other targeted questions go through documentary retrieval.
General presentations retain the hybrid path, which uses the profile
from the spreadsheet.

Tests and benchmark expectations were adapted to this behavior.

## 28. \[Bug fix\] Abstention after grounding failure

An answer rejected by grounding could still be displayed after retries
were exhausted.

An abstention node now replaces that answer with a message indicating
that the sources do not support a sufficiently reliable answer. The
checker's decision and justification remain available for diagnostics.

## 29. \[Bug fix\] Handling processing errors

A retrieval or generation failure could interrupt the graph before its
trace was saved.

Nodes are now protected so that already acquired state is preserved and
the failing stage can be identified. The `run_graph()` function also
handles LangGraph engine errors. The terminal, batch, and benchmark use
this common entry point.

In case of failure, the system returns an explicit message and attempts
to save the trace. A checker error is distinguished from insufficient
context, preventing an unnecessary documentary search retry. Network
timeouts for LLM clients were also made explicit.

## 30. \[Bug fix\] Non-blocking trace persistence

An error while writing the trace file must not prevent an already
produced answer from being returned.

Persistence is now protected: the answer and trace remain available in
memory, and the write result is reported separately. The error is logged
without an automatic retry to avoid duplicating a partial write.

## 31. \[Bug fix\] Accumulating metrics across attempts

Retries replaced previous measurements with those from the latest call,
underestimating processing cost.

A history now preserves measurements for each attempt. Finalization sums
durations and tokens for instrumented generation, grounding, and
regeneration calls, then recalculates throughput from the totals.

Unknown usage is reported rather than counted as zero. Display and the
analysis script were adapted while preserving support for older traces.

## 32. \[Architecture\] Test isolation and factual evaluation

Fast tests sometimes depended on the real database or local models.
Router and parser tests now use a small in-memory SQLite catalog. The
`real_data`, `models`, and `llm` markers make it possible to select
tests according to their prerequisites.

The graph benchmark was also supplemented with factual references from
local sources. It exports answers with a review rubric covering
accuracy, completeness, and unsupported claims. A comparator verifies
the structured fields of the reference case for Pikachu evolutions.

A `PASS` verdict from the faithfulness check is therefore no longer
enough for an answer to count as factually correct.

As part of this work, one test expected `CONTRADICTION` even though its
context did not exclude the method proposed by the answer. The model's
`UNSUPPORTED` classification was therefore defensible.

The context was clarified to make the contradiction explicit. A separate
case verifies the addition of a condition absent from the sources. This
distinction was validated with the local model without modifying the
prompt.

## 33. \[Bug fix\] Correcting level ranges

The Fast Parser stopped at the first recognized bound. A request such as
"after level 20 but before level 40" could therefore lose its upper
bound.

It now collects constraints before calculating their intersection: this
request produces bounds 21 through 39. Inclusive bounds are also
supported, impossible intervals are rejected, and partially understood
phrasings are left to the LLM parser.

Regression tests verify that level constraints are preserved.

## 34. \[Feature\] Extending structured queries to the custom Pokédex

The custom Pokédex contains data that can be returned directly, without
LLM generation: types, National Pokédex number, introduction generation,
and signature moves.

The structured engine was extended to these requests, with appropriate
routing and direct data output. French or English names and explicitly
named forms are supported.

Answers report missing values and preserve source annotations. Since
these data cannot be filtered by game, that filter is rejected. Tests
and factual benchmark references cover the new operations.

## 35. \[Bug fix\] Preserving game constraints

The Fast Parser could ignore an unknown game and answer across all
versions.

It now detects explicit mentions of unrecognized games, and processing
rejects them before falling back to the LLM, preserving the question's
constraint. Regression tests verify that the game constraint is
preserved.

## 36. \[Feature\] Exposing project capabilities through MCP

To use the project from MCP-compatible clients, a server exposes
structured operations and documentary retrieval as typed tools. It
reuses the existing engine and retrieval pipeline without duplicating
business logic.

Search can cover the entire corpus or be restricted to one Pokémon. It
returns passages and their source references. Tools call the underlying
components directly, without going through the graph's checks and
retries.

A client discovers the available tools and their schemas, then lets Qwen
choose a tool and its arguments from the question. It executes that tool
through MCP and passes the result to Qwen to formulate an answer in
French. This first loop therefore allows the model to choose between
structured data and documentary retrieval.

The integration was validated on questions using both sources.

## 37. \[Bug fix\] Separating RAG diagnostics from the MCP protocol

On the first documentary call, RAG initialization wrote its diagnostics
to stdout, which was also used for MCP messages.

These diagnostics and progress bars are now directed to stderr. A
regression test using a simulated collection and models verifies that
initialization leaves stdout empty while retaining diagnostic
information.

## 38. [Feature] Consecutive questions in one MCP session

The client opened a new server for each question, preventing loaded retrieval
resources from being retained between calls.

The terminal now accepts multiple questions within one session. The server,
tool catalog and LLM client are reused; each question remains independent.
A reusable context is also available in Python, while the one-shot function
preserves its existing behavior.

Resources are closed on exit, error or cancellation. Tests with simulated
dependencies verify cleanup and session reuse. The latency improvement with
real models remains to be measured.

## 39. [Bug fix] Explicit termination after router failure

A router failure triggered a global documentary search and its diagnostic
disappeared from the graph state. The targeted Pokémon could therefore be
lost without being reported.

Failures in fast routing, model calls and output validation now stop processing
before retrieval. The diagnostic is retained in the state and traces, along
with any previously validated Pokémon. Documentary fallback after valid output
remains separate from this failure policy.

Tests with simulated dependencies verify scope preservation, diagnostic tracing
and the absence of downstream calls after a failure.

## 40. [Bug fix] Checking constraints before an MCP call

The MCP client and the structured engine need to interpret the same form, game
and level mentions. The `constraints` package now groups their deterministic
extraction rules, without data access or model calls.

The engine retains plan validation and SQLite access; the client retains argument
reconciliation before tool execution. The module guide documents this separation
and recognition limits, so shared extraction is not mistaken for complete request
validation.

The client restores recognized filters and rejects constraints that cannot be
resolved or supported by the tool. Level ranges expressed with “between” in French
are recognized, and the engine maps Tonnerre to its internal `thunderbolt`
identifier without changing the interface language. Deterministic tests cover
reconciliation; full validation with Qwen remains pending. Restrictions on general
documentary questions are described in the MCP guide.

## 41. [Architecture] Separating MCP validation paths

Scenarios using real Qwen calls are grouped under `tests/long`, separately from
simulated client journeys. A server integration test checks tool discovery and a
structured query over stdio without LLM generation. This separation allows
validation to be selected according to its actual dependencies.

## 42. [Architecture] Introducing a local ADK agent

ADK is introduced to experiment with an additional orchestration layer without
replacing existing business components. Qwen remains the model that generates
text; ADK defines the agent and its instructions; MCP is the protocol that
exposes project capabilities to clients.

The first implementation deliberately uses a single agent answering in French,
with local Qwen through LiteLLM and LM Studio's OpenAI-compatible API. The
endpoint is explicit to prevent an external OpenAI configuration from redirecting
calls. The locally validated ADK and LiteLLM versions are declared in the project
dependencies.

The agent has no tools yet. Access to existing capabilities through MCP is
deferred to a separate integration. The graph, MCP client and server remain
available; SQLite, Chroma, the structured engine, RAG and grounding retain their
responsibilities.

## 43. [Feature] Connecting the ADK agent to Pokémon types through MCP

ADK/LiteLLM/Qwen function calling was first validated manually with a simple
Python tool, without MCP. The agent was then connected to the Pokémon server
through `McpToolset`, limiting visible tools to `pokemon_types`.

Discovery failed because MCP initialization took approximately 9.2 seconds,
exceeding ADK's 5-second timeout. Diagnosis identified the eager import of
`pokemon_rag.rag.retrieval`, including `sentence_transformers`, as the main
cause. This import now occurs only inside the RAG tool: structured tools start
without loading that heavy module.

Initialization measured after the fix was approximately 1.7 seconds on the same
machine. These measurements motivated lazy loading without becoming test
thresholds. Discovery of `pokemon_types` through `McpToolset` and the complete
Qwen → ADK → MCP → `pokemon_types` → response path were validated manually.
Tests retain distinct boundaries: stdio protocol, ADK discovery, function
calling and the complete path.

## 44. [Feature] Deterministic level guard in the ADK agent

A callback before tool execution reuses shared constraint extraction to restore
numeric bounds in `pokemon_level_up_moves`. It blocks ambiguous or invalid
levels and tools that cannot preserve them. This initial protection covers
levels only, without replacing graph or MCP client checks.

Detection through `level_explicit` now requires a number alongside the word
level, allowing general requests such as the French “en montant de niveau”.
Unit tests with a simulated ADK context verify these decisions without an LLM.

## 45. [Feature] Extending the ADK guard to games and forms

The guard now also reuses version groups and regional forms recognized by the
shared extractor. It restores these arguments when the tool supports them,
overrides incorrect values proposed by the model and blocks incompatible tools.
Unknown or ambiguous games are rejected.

Unit tests cover these constraints and combined game/level filters without
calling the model. Form recognition retains the shared extractor's limitations;
the guard does not change the exposed tool catalog.

## 46. [Feature] ADK access to all eight MCP tools

The agent now exposes all eight Pokémon server tools, covering structured data
and documentary retrieval. The deterministic before-tool guard retains
protection for recognized levels, version groups and forms. Instructions guide
Qwen toward the appropriate tool and allow it to correct its choice after a refusal.

The ADK → local Qwen → MCP → local data path was validated manually with routing
and constraint scenarios. The eight schemas revealed an insufficient context
window: Qwen's context in LM Studio was increased from 8192 to 16384 tokens.

Differences in processing time were observed for large tool results. Their
cause has not been established; this observation does not isolate a component
or explain its cost.

## 47. [Feature] Gradio Web conversation interface

A Gradio interface makes the existing ADK root_agent available locally in the
browser, without creating another agent or bypassing MCP. The ADK session is
retained between messages; an action starts a new conversation.

An activity panel progressively displays tool calls and arguments, receipt of
their responses and an elapsed-time counter updated during execution. It uses
function_call and function_response events. Example questions are randomly
selected from a separate file. Local startup requests automatic browser opening.

## 48. [Bug fix] Resolving species with forms and ADK response instructions

Tatsugiri existed in the custom Pokédex under its complete form name, but its
species name matched no entry. Resolution now uses the species catalog and
default form when the complete name does not match, without replacing an
explicitly requested form. Deterministic tests cover other species and MCP error
propagation as well.

Diagnosis for Barbaracle confirms that French and English move names are present
in results, while games remain technical identifiers. ADK instructions prefer
French names without unsolicited English parentheses and require reporting
unavailable information after source retrieval fails rather than answering from
memory. These generation instructions still require manual validation and do
not replace graph grounding.

## 49. [Bug fix] Limiting machine moves without a specified game

A machine-move request without a game sent results from multiple versions,
potentially exceeding Qwen's context. The engine now selects only the latest
group with local machine-move data for the requested form. The result identifies
that group, and the agent must state it in French. An explicitly requested game
remains authoritative, even if it has no results.

Tests without an LLM verify selection for Noivern and preservation of an older
game for Oranguru. The criterion uses local machine-move data and does not claim
exhaustive availability across games.

## 50. [Bug fix] Web questions without agent memory

Reusing the ADK session could mix a previous answer into the current question.
The interface now retains history only for display. Each question uses an
independent ADK session, deleted after success or failure. Tests with a simulated
runner verify this isolation and preservation of visible conversation history
without calling the model.

## 51. [Bug fix] Documentary tool selection for ADK descriptions

An appearance question about Bastiodon triggered the types tool, followed by an
unsupported description. ADK instructions now distinguish documentary subjects
from structured properties and require RAG retrieval for appearance, with an
answer limited to retrieved passages or an explicit unavailable-information
response. The types tool description states this limit. The guard retains its
constraint-protection responsibility; Qwen's adherence still requires manual
validation.

## 52. [Feature] Web interface highlighting agent activity

The interface keeps a prominent activity panel to show how the ADK agent uses
MCP tools. It presents the request path, readable tool labels, technical names,
arguments and received or pending responses. Receiving a tool response is not
presented as proof of success.

The question appears immediately in the history, with input below the answers
and a reminder that questions are independent. The initial input is empty;
an example button fills it without running the agent. A missing final response
has its own status. A Soft theme and responsive panel styles improve readability.
The workspace fits the window with scrolling inside the panels. A temporary
ellipsis bubble indicates that a response is being prepared and is replaced by
the final answer or error, without persisting in the conversation history.
The redundant conversation heading is removed, and input and action rows keep
their natural height so that the remaining space is allocated to the answers.
The conversation is placed on the left and the agent panel on the right.
User bubbles are aligned on the left and assistant bubbles on the right. A grid
allocates all remaining height to the chat above the compact input controls.
Activity now explains each technology as calls occur: Qwen interprets the
question, MCP tools query SQLite or search Poképédia text via RAG / Chroma,
and Qwen prepares the answer from tool returns. Static explanatory text is
replaced by this progressive account.
Elapsed times now distinguish initial analysis, tool waiting and response
preparation, with a timer for each call. Retries accumulate time, while parallel
tool waits count once in the phase total. Measurements reflect events received
by the interface, including transport and session overhead.

## 53. [Feature] Pokémon search and filterable movepools

Structured searches can now combine national number, types, species origin
generation, legendary or mythical classification and properties of learnable
moves. Two MCP tools expose these SQL filters to ADK and the local client,
without asking the model to filter lists. Abilities are deferred.

Without a requested form, the default form is selected. Without a requested
game, the latest actually available movepool is selected before filtering,
without a historical union. Results deduplicate moves, preserve learning
methods and indicate totals and partial pages. Gaps in the custom catalogue
for some default forms are reported without substituting another form.

Deterministic tests verify combined searches, versions, forms and the
distinction between unknown power and move category, as well as real MCP
transport and client constraint preservation. The database and existing tool
interfaces are preserved.

A search response added invented move names and unrequested details. ADK and
MCP client instructions now require only the returned French names for a list,
without extra generations or classifications. A Pokémon search cannot identify
its matching moves by name; those must be retrieved if requested. Incomplete
coverage is reported briefly without listing exceptions. Qwen's adherence to
these instructions still requires manual verification.

A national-number lookup also used the identity tool with a guessed name.
Both directions are now explicit: the ADK guard rejects that call and requires
number-based search, while the MCP client redirects the identity call and
restores the requested number. Tests without an LLM verify this case,
preservation of name-based identity and rejection of recognized regional or
multiple numbers. Final wording still depends on model instructions.

## 54. [Bug fix] ADK agent context budget

A simple question about the fastest Pokémon could exceed Qwen's context
window. Instructions were shortened, MCP responses sent to the model no
longer duplicate their JSON, and oversized results are reduced with an
explicit truncation notice. A check before each call bounds serialized
context and the number of calls; exceeding the budget produces a local
abstention without removing constraints.

Structured search also supports sorting by base speed to retrieve the
maximum as a single row from existing data. Tests without an LLM verify
budgets, compatibility with the real MCP catalogue and SQL ranking. The
byte budget remains a conservative estimate; Qwen inference was not run.

## 55. [Feature] Filtered base-stat rankings

The first ranking covered only Speed and did not distinguish a tied
superlative from a paginated first row. `pokemon_search` now combines its
filters with the six base stats or their SQL-calculated sum. The same sort
supports top N lists; a superlative mode selects the winning threshold and
counts all tied winners before pagination.

The Mega category uses the database form flag, including its variants,
with statistics belonging to each entry. Without a requested form, default
selection remains unchanged. MCP schemas and instructions direct Qwen to
these deterministic calculations. Tests without an LLM verify filter
composition, ties, totals, forms and preservation of client arguments. No
index, database content or database schema was modified.
Instructions and schema annotations were also compacted, along with technical
ranking fields sent to ADK, so top 10 results fit the existing context budget
without reducing their number of rows.

## 56. [Bug fix] Rankings reconciled before MCP

A request for the Mega with the lowest Defense could send an invented Steel
filter and omit sorting, then reach the context limit. Clients now restore
recognized ranking patterns and requested types before SQL, without comparing
values. Statistic labels are shared.

After a complete ranking, ADK formulates with the facts and history without
resending the tool catalogue. Limits remain unchanged. Tests using the real
runner, MCP and SQLite, but a simulated model, reproduce incorrect arguments
and verify their correction for a superlative and a top 10, without inference.

## 57. [Bug fix] Copy buttons aligned below messages

Chat bubbles had been reversed without adapting the alignment of Gradio's
copy buttons. The buttons now follow their bubble, below the text,
instead of remaining on the opposite side.

## 58. [Bug fix] Plural superlatives and ranking responses

The structured campaign revealed that a plural superlative was treated as a
list and that a response could omit its statistic value. Extraction now keeps
all winners when no quantity is specified; an explicit top N enforces its
limit and disables that mode. Instructions and MCP descriptions require the
French name, statistic value and label, including ties. The ADK adaptation
hides English translations when a French label exists, unless explicitly
requested, without changing SQL or original MCP responses.

The E2E report now separates Qwen proposals, arguments after the guard, raw
and adapted results, and the answer. A repaired proposal remains visible as
a diagnostic without failing the functional verdict. Deterministic tests
verify quantities, plural formulations, ties and these reporting boundaries;
inference remains for the user to rerun.

## 59. [Bug fix] Explicit entities and compact structured presentation

The new campaign revealed species substitutions, confusion between lists,
identity and classifications, and failures on small valid SQL lists. The
guard now preserves names and forms recognized from a database-backed
catalogue, rejects ambiguous targets, and identifies the identity tool when
a name-based search is incompatible. Simple lists and positive classifications
have their own invariants, without changing SQL ranking calculations.

The ADK adaptation retains useful facts, counts and warnings without repeating
identifiers or catalogue exceptions. Formulation of complete lists and
movepools also omits the tool catalogue, within the same budgets. Level-up
moves and learning methods without a game use the latest available game;
history remains explicitly accessible. Known French game labels and nested
translation pairs are included in presentation handling.

Report instrumentation separates proposals from executed calls and strengthens
failures for errors, abstentions, omitted values, invented levels and added
English translations. Simulated-model tests verify these boundaries and real
lists; Qwen's full factual fidelity remains for the manual campaign to check.

## 60. [Bug fix] Explicit constraints independent of Qwen

The campaign showed that a special category could disappear from an otherwise
correctly targeted movepool. Recognizable constraints are now extracted before
comparing arguments: origin generation, Pokémon and move types, physical/special/
status category and power bounds join the existing protections. A complete game
title takes priority over its short aliases; numbers belonging to distinct
domains no longer interfere, and additional bounds after an interval are checked.

The guard restores explicit values on a compatible tool and refuses a tool
that cannot represent them, with the arguments to preserve on retry.
Rejected proposals remain intact, and Qwen retains tool selection and retry.
Deterministic tests check omissions, contradictions, ambiguities and combinations,
then transmission of repaired arguments to the real MCP server and SQLite.
Qwen's actual retry after a refusal remains for the manual campaign to verify.

## 61. [Architecture] Call rules carried by tool schemas

Qwen's proposals were still often repaired by the guard: a forgotten top N
quantity, no sort on a question about Mega forms, a national number sent to the
identity tool, an omitted move category. Inspecting the catalogue actually sent
showed that ADK abridgement keeps only the first paragraph of each description:
most arguments arrived without explanation, while the ranking rule was repeated
in four places.

Each tool now states its direction in that first sentence: a named Pokémon to
its facts, or properties to Pokémon. Rules specific to an argument live in its
description, with an example distinguishing a superlative from a top N and the
French equivalents of move categories. The agent instruction keeps only the
shared rules: facts proven by tools, French names copied from the question, no invented
constraint, a French answer without technical identifiers. The volume sent to
the model stays the same.

The guard keeps its role and was not modified. A test checks the abridged
catalogue without presuming Qwen's behaviour, which remains to be measured by
the manual campaign. That campaign's diagnostic now counts an omitted argument
as its default value, and two answer checks no longer mistake a French name
containing an English word for added English, or a list rank for a statistic.

## 62. [Bug fix] Small results rejected by the context budget

A filtered movepool question received the budget abstention although the tool
had returned three or eight correct moves. Measuring the path showed that the
result itself was small: after a `pokemon_moves` response, the tool catalogue
stayed attached to the formulation request, because that response was not
recognised as complete, and the catalogue alone took three quarters of the cap.

A complete `pokemon_moves` page is now formulated without the catalogue, like
the other tools. Its projection drops technical identifiers and keeps the facts
of each move; when everything does not fit, it narrows to the requested facts
before cutting rows, always with an explicit signal. The schema view given to
the model no longer carries the "type or null" forms, which leaves room to
retry after a guard refusal, and the fence ADK puts around descriptions is no
longer left open. The MCP contract is unchanged. Abstentions are logged with
their reason.

Rankings had lost their values in answers: projections were identical before
and after, the cause was a rewording of the instruction, since reverted. Each
row's value now carries the French name of its statistic, so it no longer
depends on a technical key. The effect on Qwen's answers remains to be measured
by the manual campaign.

## 63. [Bug fix] Invented learning method removed before the tool

A filtered movepool question received a single move although three matched the
request. Qwen had added level-up as a learning method on its own; the guard
repaired the name, the category and the invented bound, but let through this
filter that nothing allowed it to judge. The answer stayed faithful to the
result it received, so the error was invisible.

An extractor now recognises whether the question mentions a learning method.
For the filtered movepool and the Pokémon search, the ADK guard and the MCP
client reconciliation remove a method the question does not name. The rule is
deliberately asymmetric: at the slightest method word, the model's proposal is
kept, with no restoration or replacement.

A test with the real runner reproduces the observed call and gets the three
moves back. The campaign's movepool cases now expect no method, so that this
invention shows up in the diagnostic.

## 64. [Bug fix] Game selected when a learning method is requested

In Pokémon Champions, moves are picked directly from a menu: the data there has
no level-up, machine or egg moves, only a method specific to the game. As it is
the most recent game, the filtered movepool selected it by default, and a request
for machines or a level range asked without naming a game returned an empty list
for the Pokémon present in it.

When a learning method is requested without a game, including through level
bounds, the filtered movepool and the Pokémon search now select the latest game
in which the Pokémon has that method, as the machine and level-up tools already
did. Type, category and power filters still never change the game, and a named
game stays strict. The game and its method are also presented to the model in
French, as "Pokémon Champions" and "entraînement".
