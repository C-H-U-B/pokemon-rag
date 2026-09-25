from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from pokemon_rag.graph.graph import graph


DATASET_PATH = Path(__file__).resolve().parent / "data" / "graph_cases.json"


def main() -> None:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]
    unreviewed = [c["id"] for c in cases if c.get("status") != "APPROVED"]
    if unreviewed:
        raise RuntimeError(f"Cas non APPROVED : {', '.join(unreviewed)}")

    route_ok = route_total = 0
    single_ok = 0
    terminal_ok = 0
    exact_ok = 0
    timings = []
    routes = Counter()
    terminals = Counter()
    retries = Counter()
    failures = []

    for case in tqdm(cases, desc="Benchmark graph", unit="question", dynamic_ncols=True):
        start = time.perf_counter()
        result = graph.invoke({
            "question": case["question"],
            "verbose": False,
            "retrieval_retry_count": 0,
            "generation_retry_count": 0,
        })
        elapsed = time.perf_counter() - start
        timings.append(elapsed)

        got_route = result.get("route")
        got_single = result.get("single_question")
        got_terminal = result.get("grounding_decision")

        route_match = True
        if "expected_route" in case:
            route_total += 1
            route_match = got_route == case["expected_route"]
            route_ok += int(route_match)

        single_match = got_single == case["expected_single_question"]
        terminal_match = got_terminal == case["expected_terminal"]

        single_ok += int(single_match)
        terminal_ok += int(terminal_match)
        exact_ok += int(route_match and single_match and terminal_match)

        routes[str(got_route)] += 1
        terminals[str(got_terminal)] += 1
        retries["retrieval"] += int(result.get("retrieval_retry_count", 0))
        retries["generation"] += int(result.get("generation_retry_count", 0))

        if not (route_match and single_match and terminal_match):
            failures.append({
                "id": case["id"],
                "question": case["question"],
                "expected": (
                    case.get("expected_route", "<non évaluée>"),
                    case["expected_single_question"],
                    case["expected_terminal"],
                ),
                "got": (got_route, got_single, got_terminal),
                "answer": result.get("answer", ""),
                "retrieval_retries": result.get("retrieval_retry_count", 0),
                "generation_retries": result.get("generation_retry_count", 0),
            })

    n = len(cases)
    print()
    print("=" * 72)
    print("BENCHMARK GRAPH END-TO-END")
    print("=" * 72)
    print(f"Cas               : {n}")
    if route_total:
        print(f"Route accuracy    : {route_ok / route_total:.3f} ({route_ok}/{route_total})")
    print(f"Single accuracy   : {single_ok / n:.3f} ({single_ok}/{n})")
    print(f"Terminal accuracy : {terminal_ok / n:.3f} ({terminal_ok}/{n})")
    print(f"Exact accuracy    : {exact_ok / n:.3f} ({exact_ok}/{n})")
    print(f"Routes obtenues   : {dict(routes)}")
    print(f"Décisions finales : {dict(terminals)}")
    print(f"Retries retrieval : {retries['retrieval']}")
    print(f"Retries génération: {retries['generation']}")
    print(f"Temps moyen       : {statistics.fmean(timings):.2f} s")
    print(f"Temps médian      : {statistics.median(timings):.2f} s")
    print(f"Temps min/max     : {min(timings):.2f} / {max(timings):.2f} s")
    print("=" * 72)

    if failures:
        print("\nCAS À ANALYSER")
        for f in failures:
            print()
            print(f"[{f['id']}] {f['question']}")
            print(f"Attendu : {f['expected']}")
            print(f"Obtenu  : {f['got']}")
            print(
                f"Retries : retrieval={f['retrieval_retries']} "
                f"generation={f['generation_retries']}"
            )
            print(f"Réponse : {f['answer'][:500]}")


if __name__ == "__main__":
    main()
