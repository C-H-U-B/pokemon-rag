from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from openai import OpenAI
from pokemon_rag.rag.grounding import check_grounding
from pokemon_rag.rag.retrieval import retrieve, retrieve_retry_context
from pokemon_rag.graph.router import route_question
from pokemon_rag.structured.query_engine import query_structured_data
from pokemon_rag.config import DB_PATH

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
MAIN_MODEL = "mn-chinofun-12b-4-heretic-i1"
TOP_K = 5


llm_client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key="lm-studio")

def vlog(state: dict, *args) -> None:
    if state.get("verbose", False):
        print(*args)



def route_query(state: dict) -> dict:
    vlog(state, "\n[ROUTER]")
    start = time.perf_counter()
    result = route_question(state["question"])
    elapsed = time.perf_counter() - start
    route = str(result.get("route", "RAG")).upper()
    if route not in {"RAG", "STRUCTURED", "HYBRID"}:
        route = "RAG"
    return {
        "route": route,
        "single_question": bool(result.get("single_question", True)),
        "router_reason": result.get("reason", ""),
        "information_need": result.get("information_need", "") or state["question"],
        "intent": str(result.get("intent", "DOCUMENT_SEARCH")).upper(),
        "pokemon": result.get("pokemon"),
        "pokemon_validated": bool(result.get("pokemon_validated", False)),
        "router_time": elapsed,
    }


def reject_multi_question(state: dict) -> dict:
    """Arrête le pipeline lorsqu'une requête contient plusieurs besoins."""
    vlog(state, "\n[REJECTED — MULTI QUESTION]")
    return {
        "answer": (
            "Cette version du projet traite une seule question à la fois. "
            "Merci de séparer la demande en questions indépendantes."
        ),
        "grounding_decision": "NOT_RUN",
        "grounding_reason": "Requête multi-question rejetée avant retrieval.",
        "llm_time": 0.0,
        "grounding_time": 0.0,
    }


def _structured_result_to_context(result: dict) -> str:
    if result.get("error"):
        return f"[SOURCE STRUCTURÉE]\nErreur : {result['error']}"

    plan = result.get("plan") or {}
    operation = result.get("operation") or plan.get("operation")
    blocks = [f"[PLAN STRUCTURÉ VALIDÉ]\n{plan}"] if plan else []

    if operation == "get_evolutions":
        entries = result.get("evolutions") or []
    elif operation == "get_move_learning_methods":
        entries = result.get("methods") or []
    elif operation in {"get_level_up_moves", "get_machine_moves"}:
        entries = result.get("moves") or []
    else:
        # Compatibilité avec les anciennes opérations structurées.
        entries = result.get("rows") or []

    if not entries:
        return "\n\n---\n\n".join(blocks + [
            "[SOURCE STRUCTURÉE]\nAucune entrée ne correspond à la requête."
        ])

    for i, entry in enumerate(entries, 1):
        blocks.append(f"[ENTRÉE STRUCTURÉE {i}]\n{entry}")

    return "\n\n---\n\n".join(blocks)



def _build_profile_context_from_db(pokemon: str) -> str:
    """Construit le contexte PROFILE depuis pokemon.db uniquement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM custom_pokedex
            WHERE lower(name_fr) = lower(?)
               OR lower(name_en) = lower(?)
            ORDER BY source_row
            """,
            (pokemon, pokemon),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return ""

    blocks = []
    for index, row in enumerate(rows, 1):
        fields = []
        for key in row.keys():
            value = row[key]
            if value is None:
                continue
            text = str(value).strip()
            if not text or text.lower() == "nan":
                continue
            fields.append(f"{key} : {text}")
        blocks.append(
            f"[PROFIL STRUCTURÉ {index} — pokemon.db]\n" + "\n".join(fields)
        )

    return "\n\n---\n\n".join(blocks)

def retrieve_structured_data(state: dict) -> dict:
    vlog(state, "\n[STRUCTURED]")
    start = time.perf_counter()
    intent = state.get("intent", "STRUCTURED_QUERY")
    pokemon = state.get("pokemon")

    if intent == "PROFILE" and pokemon:
        context = _build_profile_context_from_db(pokemon)
        result = {"mode": "PROFILE", "pokemon": pokemon, "error": None if context else "Profil introuvable."}
        parse_time = 0.0
        execution_time = time.perf_counter() - start
    else:
        result = query_structured_data(state["question"])
        context = _structured_result_to_context(result)
        parse_time = result.get("parse_time") or 0.0
        execution_time = result.get("execution_time") or 0.0

    elapsed = time.perf_counter() - start
    return {
        "structured_result": result,
        "structured_context": context,
        "structured_time": elapsed,
        "structured_parse_time": parse_time,
        "structured_execution_time": execution_time,
    }


def _format_structured_value(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_structured_answer(state: dict) -> dict:
    """Fast path STRUCTURED : réponse déterministe, sans Main LLM ni grounding LLM."""
    vlog(state, "\n[STRUCTURED FAST PATH]")
    start = time.perf_counter()
    result = state.get("structured_result") or {}
    plan = result.get("plan") or {}
    operation = result.get("operation") or plan.get("operation")

    if result.get("error"):
        answer = f"La requête structurée n’a pas pu être exécutée : {result['error']}"

    elif result.get("mode") == "PROFILE":
        answer = state.get("structured_context", "").strip() or "Aucun profil trouvé."

    elif operation == "get_level_up_moves":
        moves = result.get("moves") or []
        if not moves:
            answer = "Aucune capacité correspondant à ces critères n'a été trouvée."
        else:
            lines = [
                f" • {move.get('name_fr') or move.get('name_en') or move.get('identifier')} "
                f"— niveau {move.get('level')}"
                for move in moves
            ]
            answer = f"{len(moves)} capacité(s) trouvée(s) :\n" + "\n".join(lines)

    elif operation == "get_machine_moves":
        moves = result.get("moves") or []
        if not moves:
            answer = "Aucune capacité par machine correspondant à ces critères n'a été trouvée."
        else:
            lines = []
            for move in moves:
                name = move.get("name_fr") or move.get("name_en") or move.get("identifier")
                number = move.get("machine_number")
                machine = f"machine {number}" if number is not None else "machine"
                lines.append(f" • {name} — {machine}")
            answer = f"{len(moves)} capacité(s) par machine trouvée(s) :\n" + "\n".join(lines)

    elif operation == "get_move_learning_methods":
        methods = result.get("methods") or []
        move = result.get("move") or {}
        move_name = move.get("name_fr") or move.get("name_en") or move.get("identifier") or "cette capacité"
        if not methods:
            answer = f"Aucune méthode d'apprentissage de {move_name} n'a été trouvée pour ce Pokémon."
        else:
            lines = []
            for item in methods:
                method = item.get("method", "méthode inconnue")
                version = item.get("version_group")
                level = item.get("level")
                details = method
                if level not in (None, 0):
                    details += f", niveau {level}"
                if version:
                    details += f", {version}"
                lines.append(f" • {details}")
            answer = f"Méthodes d'apprentissage de {move_name} :\n" + "\n".join(lines)

    elif operation == "get_evolutions":
        evolutions = result.get("evolutions") or []
        if not evolutions:
            answer = "Aucune évolution correspondant à ces critères n'a été trouvée."
        else:
            lines = []
            for evolution in evolutions:
                target = evolution.get("to") or {}
                name = target.get("name_fr") or target.get("name_en") or target.get("identifier") or "?"
                trigger = evolution.get("trigger")
                version = evolution.get("version_group")
                conditions = evolution.get("conditions") or {}
                details = [f"déclencheur : {trigger}"] if trigger else []
                if version:
                    details.append(f"version : {version}")
                if conditions:
                    details.append(f"conditions : {conditions}")
                suffix = " — " + " — ".join(details) if details else ""
                lines.append(f" • {name}{suffix}")
            answer = f"{len(evolutions)} évolution(s) trouvée(s) :\n" + "\n".join(lines)

    else:
        # Compatibilité avec les anciennes opérations structurées basées sur rows.
        rows = result.get("rows") or []
        if not rows:
            answer = "Aucun Pokémon ne correspond à cette requête."
        elif len(rows) == 1:
            row = rows[0]
            items = [
                (k, v) for k, v in row.items()
                if v is not None and str(v).strip().lower() not in {"", "nan"}
            ]
            if len(items) == 1:
                answer = f"{items[0][0]} : {_format_structured_value(items[0][1])}."
            else:
                answer = " — ".join(
                    f"{k} : {_format_structured_value(v)}" for k, v in items
                ) + "."
        else:
            lines = []
            for row in rows:
                items = [
                    (k, v) for k, v in row.items()
                    if v is not None and str(v).strip().lower() not in {"", "nan"}
                ]
                lines.append(
                    " • " + " — ".join(
                        f"{k} : {_format_structured_value(v)}" for k, v in items
                    )
                )
            answer = f"{len(rows)} résultats :\n" + "\n".join(lines)

    elapsed = time.perf_counter() - start
    vlog(state, f"Formatage déterministe : {elapsed * 1000:.2f} ms")
    return {
        "answer": answer,
        "structured_format_time": elapsed,
        "llm_time": 0.0,
        "grounding_time": 0.0,
        "grounding_decision": "DETERMINISTIC",
        "grounding_reason": (
            "Réponse produite directement à partir du résultat structuré validé "
            "de pokemon.db ; aucun LLM de génération ou de grounding utilisé."
        ),
    }


def build_structured_context(state: dict) -> dict:
    start = time.perf_counter()
    context = state.get("structured_context", "").strip()
    return {"rag_context": context, "context_time": time.perf_counter() - start}


def build_hybrid_context(state: dict) -> dict:
    vlog(state, "\n[HYBRID CONTEXT]")
    start = time.perf_counter()
    parts = []
    structured = state.get("structured_context", "").strip()
    if structured:
        parts.append("[DONNÉES STRUCTURÉES DU POKÉDEX]\n" + structured)

    docs = []
    source_chunks = state.get("context_documents", state.get("retrieved_documents", []))
    for i, chunk in enumerate(source_chunks, 1):
        m = chunk.get("metadata", {})
        docs.append(
            f"[SOURCE DOCUMENTAIRE {i}]\n"
            f"Pokémon : {m.get('pokemon', 'Inconnu')}\n"
            f"Numéro national : {m.get('national_number', 'Inconnu')}\n"
            f"Fichier : {m.get('source_file', 'Inconnu')}\n"
            f"Chunk : {m.get('chunk_number', 'Inconnu')}\n"
            f"Contenu :\n{chunk.get('document', '')}"
        )
    if docs:
        parts.append("[DOCUMENTS POKÉPÉDIA RÉCUPÉRÉS]\n" + "\n\n---\n\n".join(docs))

    context = "\n\n==========\n\n".join(parts)
    return {"rag_context": context, "context_time": time.perf_counter() - start}

def grounding_check(state: dict) -> dict:
    question = state["question"]
    context = state["rag_context"]
    answer = state["answer"]

    result = check_grounding(
        question=question,
        context=context,
        answer=answer,
    )

    if state.get("verbose", False):
        print()
        print("[GROUNDING]")
        print(f"Décision : {result['decision']}")
        print(f"Raison   : {result['reason']}")
        print(f"Temps    : {result['time']:.3f} s")

    return {
        "grounding_decision": result["decision"],
        "grounding_reason": result["reason"],
        "grounding_time": result["time"],
    }

def retry_answer(state: dict) -> dict:
    start = time.perf_counter()

    question = state["question"]
    context = state["rag_context"]
    previous_answer = state["answer"]
    grounding_reason = state["grounding_reason"]

    prompt = f"""
Réponds à la question en utilisant UNIQUEMENT le contexte documentaire fourni.

Une réponse précédente a échoué à une vérification de fidélité aux sources.

QUESTION
--------
{question}

CONTEXTE
--------
{context}

RÉPONSE PRÉCÉDENTE
------------------
{previous_answer}

PROBLÈME DÉTECTÉ PAR LE VÉRIFICATEUR
------------------------------------
{grounding_reason}

Produis une nouvelle réponse.

Règles :
- utilise uniquement le contexte ;
- corrige le problème signalé ;
- n'ajoute aucune connaissance externe ;
- n'invente aucune information ;
- si le contexte ne permet pas de répondre, dis-le explicitement ;
- réponds directement et brièvement.
""".strip()

    response = llm_client.chat.completions.create(
        model=MAIN_MODEL,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    answer = response.choices[0].message.content.strip()

    elapsed = time.perf_counter() - start

    if state.get("verbose", False):
        print()
        print("[RETRY]")
        print(f"Nouvelle génération : {elapsed:.3f} s")

    return {
        "answer": answer,
        "retry_llm_time": elapsed,
    }

def retrieve_documents(state: dict) -> dict:
    vlog(state, "\n[RETRIEVAL]")
    start = time.perf_counter()
    scoped_pokemon = (
        state.get("pokemon")
        if state.get("pokemon_validated", False)
        else None
    )
    chunks = retrieve(
        state["question"],
        n_results=TOP_K,
        pokemon=scoped_pokemon,
        information_need=state.get("information_need"),
    )
    elapsed = time.perf_counter() - start
    if state.get("verbose", False):
        if chunks:
            print(f"Scope  : {chunks[0].get('retrieval_scope', 'GLOBAL')}")
            timings = chunks[0].get("timings", {})
            print(f"Vector : {timings.get('vector', 0) * 1000:.2f} ms")
            print(f"BM25   : {timings.get('bm25', 0) * 1000:.2f} ms")
            print(f"RRF    : {timings.get('rrf', 0) * 1000:.2f} ms")
            print(f"Total  : {elapsed * 1000:.2f} ms")
            print("\nTop résultats :")
            for i, chunk in enumerate(chunks, 1):
                m = chunk.get("metadata", {})
                print(
                    f"\n{'=' * 80}\n"
                    f"RÉSULTAT {i}\n"
                    f"Pokémon       : #{m.get('national_number', '?')} "
                    f"{m.get('pokemon', '?')}\n"
                    f"Chunk         : {m.get('chunk_number', '?')}\n"
                    f"Fichier       : {m.get('source_file', '?')}\n"
                    f"RRF rank      : {chunk.get('rrf_rank', '?')}\n"
                    f"RRF score     : {chunk.get('rrf_score', 0):.6f}\n"
                    f"Reranker rank : {chunk.get('reranker_rank', '?')}\n"
                    f"Reranker score: {chunk.get('reranker_score', 0):.6f}\n"
                    f"{'-' * 80}\n"
                    f"{chunk.get('document', '')}\n"
                    f"{'=' * 80}"
                )
        else:
            print("Aucun chunk récupéré.")
    context_documents = chunks[0].get("context_results", chunks) if chunks else []

    if state.get("verbose", False) and chunks:
        expansion = chunks[0].get("section_expansion") or {}
        selector_candidates = expansion.get("selector_candidates") or []

        if selector_candidates:
            print("\n[SECTION SELECTOR]")
            print(
                f"Focus : "
                f"{selector_candidates[0].get('information_need', state.get('information_need', state['question']))}"
            )

            for i, candidate in enumerate(selector_candidates, 1):
                print(
                    f"{i}. {candidate['section_path']}\n"
                    f"   contenu    : {candidate['content_score']:.6f}\n"
                    f"   focus      : {candidate['focus_score']:.6f}\n"
                    f"   structural : {candidate['structural_score']:.6f}\n"
                    f"   rang initial : {candidate.get('original_reranker_rank', '?')}"
                )

            print(
                f"\nSection retenue : "
                f"{expansion.get('section_path', '?')}"
            )
        if expansion.get("section_path"):
            print(
                f"Section contexte : {expansion.get('section_chunks', len(context_documents))} chunk(s) | "
                f"{expansion['section_path']}"
            )

    return {
        "retrieved_documents": chunks,
        "context_documents": context_documents,
        "retrieval_time": elapsed,
    }


def retry_retrieval(state: dict) -> dict:
    """Après INSUFFICIENT, cherche une meilleure section pour la même question."""
    vlog(state, "\n[RETRY RETRIEVAL]")
    start = time.perf_counter()

    scoped_pokemon = (
        state.get("pokemon")
        if state.get("pokemon_validated", False)
        else None
    )

    previous_docs = state.get("context_documents") or []
    previous_section = None
    if previous_docs:
        metadata = previous_docs[0].get("metadata") or {}
        previous_section = (
            metadata.get("section_path")
            or metadata.get("section")
        )

    chunks = retrieve_retry_context(
        question=state["question"],
        grounding_reason=state.get("grounding_reason", ""),
        pokemon=scoped_pokemon,
        excluded_section_path=previous_section,
    )
    elapsed = time.perf_counter() - start

    if state.get("verbose", False):
        print(f"Scope retry : {scoped_pokemon or 'GLOBAL'}")
        print(f"Section précédente : {previous_section or '?'}")
        if chunks:
            metadata = chunks[0].get("metadata") or {}
            new_section = (
                metadata.get("section_path")
                or metadata.get("section")
                or "?"
            )
            print(f"Nouvelle section : {new_section}")
            print(f"Chunks de la section : {len(chunks)}")
        else:
            print("Aucune meilleure section trouvée.")
        print(f"Temps retry retrieval : {elapsed:.3f} s")

    return {
        "context_documents": chunks,
        "retry_retrieval_time": elapsed,
        "retrieval_retry_count": state.get("retrieval_retry_count", 0) + 1,
    }


def build_context(state: dict) -> dict:
    vlog(state, "\n[CONTEXT]")
    start = time.perf_counter()
    blocks = []
    source_chunks = state.get("context_documents", state.get("retrieved_documents", []))
    for i, chunk in enumerate(source_chunks, 1):
        m = chunk.get("metadata", {})
        blocks.append(
            f"[SOURCE {i}]\nPokémon : {m.get('pokemon','Inconnu')}\n"
            f"Numéro national : {m.get('national_number','Inconnu')}\n"
            f"Fichier : {m.get('source_file','Inconnu')}\n"
            f"Chunk : {m.get('chunk_number','Inconnu')}\n"
            f"Contenu :\n{chunk.get('document','')}"
        )
    context = "\n\n---\n\n".join(blocks)
    elapsed = time.perf_counter() - start
    vlog(state, f"{len(blocks)} chunks — {len(context):,} caractères — {elapsed*1000:.2f} ms")
    return {"rag_context": context, "context_time": elapsed}

def call_main_llm(state: dict) -> dict:
    vlog(state, "\n[LLM]")
    start = time.perf_counter()
    context = state.get("rag_context", "").strip()
    if not context:
        answer = "Je ne dispose pas de suffisamment d'informations dans les documents récupérés pour répondre."
        elapsed = time.perf_counter() - start
        return {"answer": answer, "llm_time": elapsed}
    response = llm_client.chat.completions.create(
        model=MAIN_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content":
             "Tu es un assistant spécialisé dans le corpus Pokémon fourni. "
             "Réponds uniquement à partir du CONTEXTE récupéré. N'utilise pas tes connaissances externes "
             "pour compléter une information absente. Si le contexte ne permet pas de répondre correctement, "
             "indique clairement que l'information n'est pas présente dans les documents récupérés. "
             "Réponds en français, de manière précise et concise. N'invente aucune source."},
            {"role": "user", "content": f"QUESTION :\n{state['question']}\n\nCONTEXTE :\n{context}"}
        ],
    )
    answer = response.choices[0].message.content.strip()
    elapsed = time.perf_counter() - start
    vlog(state, f"Génération : {elapsed:.3f} s")
    return {"answer": answer, "llm_time": elapsed}
