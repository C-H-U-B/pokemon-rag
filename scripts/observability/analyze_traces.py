from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from pokemon_rag.config import PROJECT_ROOT


DEFAULT_TRACE_FILE = PROJECT_ROOT / "traces" / "graph_traces.jsonl"


def load_traces(path: Path) -> list[dict[str, Any]]:
    """Charge les traces JSONL valides depuis un fichier."""
    if not path.exists():
        raise FileNotFoundError(f"Fichier de traces introuvable : {path}")

    traces: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                trace = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSON invalide dans {path} à la ligne {line_number} : {exc}"
                ) from exc

            if not isinstance(trace, dict):
                raise ValueError(
                    f"Trace invalide dans {path} à la ligne {line_number} : "
                    "un objet JSON était attendu."
                )

            traces.append(trace)

    return traces


def percentile(values: Iterable[float], percentile_value: float) -> float:
    """Calcule un percentile par interpolation linéaire."""
    ordered = sorted(float(value) for value in values)

    if not ordered:
        return 0.0

    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * percentile_value
    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    weight = position - lower_index
    return (
        ordered[lower_index] * (1.0 - weight)
        + ordered[upper_index] * weight
    )


def summarize_values(values: Iterable[float]) -> dict[str, float]:
    values = [float(value) for value in values]

    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def get_total_time(trace: dict[str, Any]) -> float:
    return float(trace.get("total_time") or 0.0)


def get_timing(trace: dict[str, Any], name: str) -> float:
    timings = trace.get("timings") or {}
    return float(timings.get(name) or 0.0)


def group_by(
    traces: Iterable[dict[str, Any]],
    key: str,
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for trace in traces:
        value = trace.get(key)
        label = str(value) if value is not None else "N/A"
        groups[label].append(trace)

    return dict(groups)


def format_seconds(value: float) -> str:
    return f"{value:.3f} s"


def print_time_summary(title: str, traces: list[dict[str, Any]]) -> None:
    summary = summarize_values(get_total_time(trace) for trace in traces)

    print(title)
    print(f"  traces   : {int(summary['count'])}")
    print(f"  moyenne  : {format_seconds(summary['mean'])}")
    print(f"  médiane  : {format_seconds(summary['median'])}")
    print(f"  p95      : {format_seconds(summary['p95'])}")
    print(f"  min/max  : {format_seconds(summary['min'])} / {format_seconds(summary['max'])}")


def print_component_summary(traces: list[dict[str, Any]]) -> None:
    component_names = [
        "router",
        "retrieval",
        "retry_retrieval",
        "structured",
        "structured_parse",
        "structured_execution",
        "structured_format",
        "context",
        "main_llm",
        "grounding",
        "retry_llm",
    ]

    present_components = [
        name
        for name in component_names
        if any(name in (trace.get("timings") or {}) for trace in traces)
    ]

    print("Temps par composant")

    if not present_components:
        print("  aucune métrique de timing")
        return

    for name in present_components:
        values = [
            get_timing(trace, name)
            for trace in traces
            if name in (trace.get("timings") or {})
        ]
        summary = summarize_values(values)

        print(
            f"  {name:<22}"
            f"n={int(summary['count']):<3}"
            f" | médiane {format_seconds(summary['median']):>10}"
            f" | moyenne {format_seconds(summary['mean']):>10}"
            f" | p95 {format_seconds(summary['p95']):>10}"
        )


def print_group_summary(
    title: str,
    traces: list[dict[str, Any]],
    key: str,
) -> None:
    print(title)

    groups = group_by(traces, key)

    for label, group in sorted(groups.items()):
        summary = summarize_values(get_total_time(trace) for trace in group)
        print(
            f"  {label:<18}"
            f"{int(summary['count']):>3} trace(s)"
            f" | médiane {format_seconds(summary['median']):>10}"
            f" | moyenne {format_seconds(summary['mean']):>10}"
            f" | p95 {format_seconds(summary['p95']):>10}"
        )


def print_retry_summary(traces: list[dict[str, Any]]) -> None:
    retrieval_retries = [
        int((trace.get("retries") or {}).get("retrieval") or 0)
        for trace in traces
    ]
    generation_retries = [
        int((trace.get("retries") or {}).get("generation") or 0)
        for trace in traces
    ]

    traces_with_retry = sum(
        1
        for retrieval, generation in zip(retrieval_retries, generation_retries)
        if retrieval > 0 or generation > 0
    )

    print("Retries")
    print(f"  traces avec retry    : {traces_with_retry}/{len(traces)}")
    print(f"  retrieval retries    : {sum(retrieval_retries)}")
    print(f"  generation retries   : {sum(generation_retries)}")


def print_decision_summary(traces: list[dict[str, Any]]) -> None:
    decisions = Counter(
        str(trace.get("grounding_decision") or "N/A")
        for trace in traces
    )

    print("Décisions finales")

    for decision, count in decisions.most_common():
        print(f"  {decision:<18}: {count}")


def print_slowest_traces(
    traces: list[dict[str, Any]],
    limit: int,
) -> None:
    print(f"Requêtes les plus lentes — Top {limit}")

    for index, trace in enumerate(
        sorted(traces, key=get_total_time, reverse=True)[:limit],
        start=1,
    ):
        question = str(trace.get("question") or "")
        route = str(trace.get("route") or "N/A")
        router_mode = str(trace.get("router_mode") or "N/A")
        pokemon = str(trace.get("pokemon") or "N/A")
        total_time = get_total_time(trace)

        print(
            f"  {index:>2}. {format_seconds(total_time):>10}"
            f" | {route:<10}"
            f" | {router_mode:<4}"
            f" | Pokémon: {pokemon}"
        )
        print(f"      {question}")


def print_retrieval_summary(traces: list[dict[str, Any]]) -> None:
    retrieval_traces = [
        trace
        for trace in traces
        if get_timing(trace, "retrieval") > 0
        or int((trace.get("retrieval") or {}).get("retrieved_chunks") or 0) > 0
    ]

    print("Retrieval")

    if not retrieval_traces:
        print("  aucune trace avec retrieval")
        return

    retrieved_chunks = [
        int((trace.get("retrieval") or {}).get("retrieved_chunks") or 0)
        for trace in retrieval_traces
    ]
    context_chunks = [
        int((trace.get("retrieval") or {}).get("context_chunks") or 0)
        for trace in retrieval_traces
    ]
    context_chars = [
        int((trace.get("retrieval") or {}).get("context_chars") or 0)
        for trace in retrieval_traces
    ]

    print(f"  traces concernées    : {len(retrieval_traces)}")
    print(f"  chunks récupérés     : médiane {statistics.median(retrieved_chunks):.1f}")
    print(f"  chunks de contexte   : médiane {statistics.median(context_chunks):.1f}")
    print(f"  caractères contexte  : médiane {statistics.median(context_chars):.1f}")


def analyze_traces(
    traces: list[dict[str, Any]],
    *,
    slowest_limit: int = 5,
) -> None:
    if not traces:
        print("Aucune trace à analyser.")
        return

    print("=" * 72)
    print("PROFILING DU GRAPHE")
    print("=" * 72)
    print(f"Traces analysées : {len(traces)}")
    print()

    print_time_summary("Temps total", traces)
    if len(traces) < 20:
        print("  note     : p95 indicatif — échantillon très faible")
    print()

    print_component_summary(traces)
    print()

    print_group_summary("Par route", traces, "route")
    print()

    print_group_summary("Par mode de router", traces, "router_mode")
    print()

    print_retrieval_summary(traces)
    print()

    print_retry_summary(traces)
    print()

    print_decision_summary(traces)
    print()

    print_slowest_traces(traces, slowest_limit)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyse les traces JSONL du graphe Pokémon RAG."
    )
    parser.add_argument(
        "trace_file",
        nargs="?",
        type=Path,
        default=DEFAULT_TRACE_FILE,
        help=f"Fichier JSONL à analyser (défaut : {DEFAULT_TRACE_FILE})",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Nombre de requêtes lentes à afficher (défaut : 5).",
    )

    args = parser.parse_args()

    if args.top < 1:
        parser.error("--top doit être supérieur ou égal à 1.")

    return args


def main() -> None:
    args = parse_args()
    traces = load_traces(args.trace_file)
    analyze_traces(traces, slowest_limit=args.top)


if __name__ == "__main__":
    main()
