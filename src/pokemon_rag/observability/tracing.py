from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pokemon_rag.config import PROJECT_ROOT


TRACE_DIR = PROJECT_ROOT / "traces"
TRACE_FILE = TRACE_DIR / "graph_traces.jsonl"


def create_trace(question: str) -> dict[str, Any]:
    """
    Crée la structure initiale d'une trace pour une exécution du graphe.

    La trace reste un simple dictionnaire afin de pouvoir être stockée
    directement dans l'état LangGraph.
    """
    return {
        "trace_id": uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "started_at": time.perf_counter(),
        "route": None,
        "intent": None,
        "router_mode": None,
        "pokemon": None,
        "single_question": None,
        "timings": {},
        "retrieval": {
            "retrieved_chunks": 0,
            "context_chunks": 0,
            "context_chars": 0,
        },
        "retries": {
            "retrieval": 0,
            "generation": 0,
        },
        "grounding_decision": None,
    }


def set_trace_value(
    trace: dict[str, Any],
    key: str,
    value: Any,
) -> None:
    """
    Modifie une valeur de premier niveau de la trace.
    """
    trace[key] = value


def set_timing(
    trace: dict[str, Any],
    name: str,
    seconds: float,
) -> None:
    """
    Enregistre la durée d'une étape du pipeline.
    """
    trace["timings"][name] = float(seconds)


def set_retrieval_metrics(
    trace: dict[str, Any],
    *,
    retrieved_chunks: int,
    context_chunks: int,
    context_chars: int,
) -> None:
    """
    Enregistre les principales métriques liées au retrieval et au contexte.
    """
    trace["retrieval"] = {
        "retrieved_chunks": int(retrieved_chunks),
        "context_chunks": int(context_chunks),
        "context_chars": int(context_chars),
    }


def set_retry_counts(
    trace: dict[str, Any],
    *,
    retrieval: int,
    generation: int,
) -> None:
    """
    Enregistre le nombre de retries effectués pendant l'exécution.
    """
    trace["retries"] = {
        "retrieval": int(retrieval),
        "generation": int(generation),
    }


def finalize_trace(
    trace: dict[str, Any],
    *,
    total_time: float | None = None,
) -> dict[str, Any]:
    """
    Finalise la trace avant son affichage ou sa sauvegarde.

    Si total_time n'est pas fourni, il est calculé à partir du compteur
    monotone créé dans create_trace().
    """
    started_at = trace.get("started_at")

    if total_time is None:
        if started_at is None:
            raise ValueError(
                "Impossible de calculer total_time : started_at absent."
            )
        total_time = time.perf_counter() - started_at

    trace["total_time"] = float(total_time)

    # Valeur interne utile uniquement pendant l'exécution.
    trace.pop("started_at", None)

    return trace


def save_trace(
    trace: dict[str, Any],
    path: Path = TRACE_FILE,
) -> None:
    """
    Ajoute une trace au fichier JSONL.

    Une ligne correspond à une exécution complète du graphe.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(
            json.dumps(
                trace,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        file.write("\n")


def format_trace(trace: dict[str, Any]) -> str:
    """
    Produit un résumé lisible d'une trace pour le terminal.
    """
    timings = trace.get("timings", {})
    retrieval = trace.get("retrieval", {})
    retries = trace.get("retries", {})

    lines = [
        "=" * 72,
        "TRACE",
        "=" * 72,
        f"Trace ID           : {trace.get('trace_id', '?')}",
        f"Route              : {trace.get('route') or '?'}",
        f"Intent             : {trace.get('intent') or '?'}",
        f"Router mode        : {trace.get('router_mode') or '?'}",
        f"Pokémon            : {trace.get('pokemon') or '?'}",
        f"Single question    : {trace.get('single_question')}",
        "",
        "TIMINGS",
    ]

    for name, seconds in timings.items():
        lines.append(f"{name:<19}: {seconds:.3f} s")

    lines.extend(
        [
            f"{'total':<19}: {trace.get('total_time', 0.0):.3f} s",
            "",
            "RETRIEVAL",
            (
                "Chunks             : "
                f"{retrieval.get('retrieved_chunks', 0)} récupérés / "
                f"{retrieval.get('context_chunks', 0)} contexte"
            ),
            (
                "Contexte           : "
                f"{retrieval.get('context_chars', 0):,} caractères"
            ),
            "",
            "RETRIES",
            f"Retrieval          : {retries.get('retrieval', 0)}",
            f"Génération         : {retries.get('generation', 0)}",
            "",
            (
                "Grounding final    : "
                f"{trace.get('grounding_decision') or '?'}"
            ),
            "=" * 72,
        ]
    )

    return "\n".join(lines)