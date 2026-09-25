from __future__ import annotations

import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from pokemon_rag.graph.nodes import (
    build_context,
    build_hybrid_context,
    call_main_llm,
    format_structured_answer,
    grounding_check,
    reject_multi_question,
    retrieve_documents,
    retrieve_structured_data,
    retry_answer,
    retry_retrieval,
    route_query,
)

from pokemon_rag.observability.tracing import (
    create_trace,
    finalize_trace,
    save_trace,
    set_retrieval_metrics,
    set_retry_counts,
    set_timing,
    set_trace_value,
)


class PokemonState(TypedDict, total=False):
    question: str
    verbose: bool
    route: str
    intent: str
    router_mode: str | None
    information_need: str
    pokemon: str | None
    pokemon_validated: bool
    single_question: bool
    router_reason: str
    router_time: float
    retrieved_documents: list[dict]
    context_documents: list[dict]
    structured_result: dict
    structured_context: str
    rag_context: str
    answer: str
    retrieval_time: float
    retry_retrieval_time: float
    structured_time: float
    structured_parse_time: float
    structured_execution_time: float
    structured_format_time: float
    context_time: float
    llm_time: float
    grounding_decision: str
    grounding_reason: str
    grounding_time: float
    retrieval_retry_count: int
    generation_retry_count: int
    retry_llm_time: float
    trace: dict[str, Any]


def initialize_trace(state: PokemonState) -> dict:
    """Crée une trace au début de chaque exécution du graphe."""
    return {"trace": create_trace(state["question"])}


def finalize_observability(state: PokemonState) -> dict:
    """Construit et persiste la trace finale à partir de l'état du graphe."""
    trace = state.get("trace")
    if trace is None:
        trace = create_trace(state["question"])

    set_trace_value(trace, "route", state.get("route"))
    set_trace_value(trace, "intent", state.get("intent"))
    set_trace_value(trace, "router_mode", state.get("router_mode"))
    set_trace_value(trace, "pokemon", state.get("pokemon"))
    set_trace_value(trace, "single_question", state.get("single_question"))
    set_trace_value(
        trace,
        "grounding_decision",
        state.get("grounding_decision"),
    )

    timing_fields = {
        "router": "router_time",
        "retrieval": "retrieval_time",
        "retry_retrieval": "retry_retrieval_time",
        "structured": "structured_time",
        "structured_parse": "structured_parse_time",
        "structured_execution": "structured_execution_time",
        "structured_format": "structured_format_time",
        "context": "context_time",
        "main_llm": "llm_time",
        "grounding": "grounding_time",
        "retry_llm": "retry_llm_time",
    }
    for trace_name, state_name in timing_fields.items():
        value = state.get(state_name)
        if value is not None:
            set_timing(trace, trace_name, value)

    retrieved_documents = state.get("retrieved_documents") or []
    context_documents = state.get("context_documents") or []
    context = state.get("rag_context") or ""

    set_retrieval_metrics(
        trace,
        retrieved_chunks=len(retrieved_documents),
        context_chunks=len(context_documents),
        context_chars=len(context),
    )
    set_retry_counts(
        trace,
        retrieval=state.get("retrieval_retry_count", 0),
        generation=state.get("generation_retry_count", 0),
    )

    finalize_trace(trace)
    save_trace(trace)

    return {"trace": trace}


def route_after_router(state: PokemonState) -> str:
    if not state.get("single_question", True):
        return "reject"
    return state.get("route", "RAG").lower()


def route_after_structured(state: PokemonState) -> str:
    return "documents" if state.get("route") == "HYBRID" else "fast_path"


def route_after_documents(state: PokemonState) -> str:
    return "hybrid" if state.get("route") == "HYBRID" else "rag"


def route_after_retry_retrieval(state: PokemonState) -> str:
    return "hybrid" if state.get("route") == "HYBRID" else "rag"


def route_after_grounding(state: PokemonState) -> str:
    decision = state.get("grounding_decision")

    if decision == "PASS":
        return "pass"

    if decision == "INSUFFICIENT":
        if state.get("retrieval_retry_count", 0) < 1:
            return "retry_retrieval"
        return "fail"

    if decision in {"UNSUPPORTED", "CONTRADICTION", "INCOMPLETE"}:
        if state.get("generation_retry_count", 0) < 1:
            return "retry_answer"
        return "fail"

    return "fail"


def mark_generation_retry(state: PokemonState) -> dict:
    return {
        "generation_retry_count": state.get("generation_retry_count", 0) + 1
    }


builder = StateGraph(PokemonState)

builder.add_node("initialize_trace", initialize_trace)
builder.add_node("router", route_query)
builder.add_node("reject_multi_question", reject_multi_question)
builder.add_node("retrieve_documents", retrieve_documents)
builder.add_node("retrieve_structured_data", retrieve_structured_data)
builder.add_node("build_context", build_context)
builder.add_node("build_hybrid_context", build_hybrid_context)
builder.add_node("format_structured_answer", format_structured_answer)
builder.add_node("main_llm", call_main_llm)
builder.add_node("grounding_check", grounding_check)
builder.add_node("mark_generation_retry", mark_generation_retry)
builder.add_node("retry_answer", retry_answer)
builder.add_node("retry_retrieval", retry_retrieval)
builder.add_node("finalize_observability", finalize_observability)

builder.add_edge(START, "initialize_trace")
builder.add_edge("initialize_trace", "router")
builder.add_conditional_edges(
    "router",
    route_after_router,
    {
        "reject": "reject_multi_question",
        "rag": "retrieve_documents",
        "structured": "retrieve_structured_data",
        "hybrid": "retrieve_structured_data",
    },
)
builder.add_edge("reject_multi_question", "finalize_observability")

builder.add_conditional_edges(
    "retrieve_structured_data",
    route_after_structured,
    {
        "documents": "retrieve_documents",
        "fast_path": "format_structured_answer",
    },
)
builder.add_edge("format_structured_answer", "finalize_observability")

builder.add_conditional_edges(
    "retrieve_documents",
    route_after_documents,
    {
        "rag": "build_context",
        "hybrid": "build_hybrid_context",
    },
)

builder.add_edge("build_context", "main_llm")
builder.add_edge("build_hybrid_context", "main_llm")

builder.add_conditional_edges(
    "retry_retrieval",
    route_after_retry_retrieval,
    {
        "rag": "build_context",
        "hybrid": "build_hybrid_context",
    },
)

builder.add_edge("main_llm", "grounding_check")
builder.add_conditional_edges(
    "grounding_check",
    route_after_grounding,
    {
        "pass": "finalize_observability",
        "retry_answer": "mark_generation_retry",
        "retry_retrieval": "retry_retrieval",
        "fail": "finalize_observability",
    },
)
builder.add_edge("mark_generation_retry", "retry_answer")
builder.add_edge("retry_answer", "grounding_check")
builder.add_edge("finalize_observability", END)

graph = builder.compile()


def print_answer(result: PokemonState, total_time: float) -> None:
    print()
    print("=" * 84)
    print("RÉPONSE")
    print("=" * 84)
    print(f"Route   : {result.get('route', '?')}")
    print(f"Intent  : {result.get('intent', '?')}")
    if result.get("pokemon"):
        print(f"Pokémon : {result['pokemon']}")
    print("\nRÉPONSE :")
    print(result.get("answer", "Aucune réponse."))

    print("\n" + "-" * 84)
    print("TIMINGS DU GRAPHE")
    print(f"Router      : {result.get('router_time', 0.0):.3f} s")
    if result.get("route") in {"RAG", "HYBRID"}:
        print(f"Retrieval   : {result.get('retrieval_time', 0.0):.3f} s")
        if result.get("retry_retrieval_time", 0.0):
            print(f"Retry retr. : {result.get('retry_retrieval_time', 0.0):.3f} s")
    if result.get("route") in {"STRUCTURED", "HYBRID"}:
        print(f"Structured  : {result.get('structured_time', 0.0):.3f} s")
        print(f"  ↳ Parser  : {result.get('structured_parse_time', 0.0):.3f} s")
        print(f"  ↳ SQL     : {result.get('structured_execution_time', 0.0):.6f} s")
        if result.get("route") == "STRUCTURED":
            print(f"  ↳ Format  : {result.get('structured_format_time', 0.0):.6f} s")
    if result.get("route") != "STRUCTURED":
        print(f"Context     : {result.get('context_time', 0.0):.3f} s")
        print(f"LLM         : {result.get('llm_time', 0.0):.3f} s")
        print(f"Grounding   : {result.get('grounding_time', 0.0):.3f} s")
    if result.get("retry_llm_time", 0.0):
        print(f"Retry LLM   : {result.get('retry_llm_time', 0.0):.3f} s")
    print(f"TOTAL       : {total_time:.3f} s")
    print("-" * 84)

    if result.get("grounding_decision"):
        print(
            f"Grounding final : {result['grounding_decision']} — "
            f"{result.get('grounding_reason', '')}"
        )


def main() -> None:
    verbose = False
    print("Agent Pokémon hybride prêt.")
    print("Routes : STRUCTURED | RAG | HYBRID")
    print("Commandes : /verbose on | /verbose off | quit")

    while True:
        try:
            question = input("\nQuestion > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue

        command = question.lower()
        if command in {"quit", "exit", "q"}:
            break
        if command == "/verbose on":
            verbose = True
            print("Verbose activé.")
            continue
        if command == "/verbose off":
            verbose = False
            print("Verbose désactivé.")
            continue

        start = time.perf_counter()
        result = graph.invoke(
            {
                "question": question,
                "verbose": verbose,
                "retrieval_retry_count": 0,
                "generation_retry_count": 0,
            }
        )
        print_answer(result, time.perf_counter() - start)


if __name__ == "__main__":
    main()
