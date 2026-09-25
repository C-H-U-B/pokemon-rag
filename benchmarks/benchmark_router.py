from __future__ import annotations
import json
import statistics
from collections import Counter
from pathlib import Path
from tqdm import tqdm
from pokemon_rag.graph.router import route_question

DATASET_PATH = Path(__file__).resolve().parent / "data" / "router_cases.json"

def main() -> None:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]
    unreviewed = [c["id"] for c in cases if c.get("status") != "APPROVED"]
    if unreviewed:
        raise RuntimeError(f"Cas non APPROVED : {', '.join(unreviewed)}")

    scores = {"route": 0, "intent": 0, "single": 0, "exact": 0}
    timings, failures, errors = [], [], []
    modes = Counter()

    for case in tqdm(cases, desc="Benchmark router", unit="question", dynamic_ncols=True):
        result = route_question(case["question"])
        checks = {
            "route": result.get("route") == case["expected_route"],
            "intent": result.get("intent") == case["expected_intent"],
            "single": result.get("single_question") == case["expected_single_question"],
        }
        for key, ok in checks.items():
            scores[key] += int(ok)
        scores["exact"] += int(all(checks.values()))
        modes[str(result.get("router_mode", "UNKNOWN"))] += 1
        timings.append(float(result.get("router_time", 0.0)))

        if result.get("router_error"):
            errors.append((case["id"], result["router_error"]))
        if not all(checks.values()):
            failures.append({
                "id": case["id"], "question": case["question"],
                "expected": (case["expected_route"], case["expected_intent"], case["expected_single_question"]),
                "got": (result.get("route"), result.get("intent"), result.get("single_question")),
                "mode": result.get("router_mode"),
            })

    n = len(cases)
    print("\n" + "=" * 72)
    print("BENCHMARK ROUTER")
    print("=" * 72)
    print(f"Cas               : {n}")
    print(f"Route accuracy    : {scores['route']/n:.3f} ({scores['route']}/{n})")
    print(f"Intent accuracy   : {scores['intent']/n:.3f} ({scores['intent']}/{n})")
    print(f"Single accuracy   : {scores['single']/n:.3f} ({scores['single']}/{n})")
    print(f"Exact accuracy    : {scores['exact']/n:.3f} ({scores['exact']}/{n})")
    print(f"Modes             : {dict(modes)}")
    print(f"Temps moyen       : {statistics.fmean(timings)*1000:.1f} ms")
    print(f"Temps médian      : {statistics.median(timings)*1000:.1f} ms")
    print(f"Erreurs runtime   : {len(errors)}")
    print("=" * 72)

    if failures:
        print("\nCAS À ANALYSER")
        for f in failures:
            print(f"\n[{f['id']}] {f['question']}")
            print(f"Attendu : {f['expected']}")
            print(f"Obtenu  : {f['got']}")
            print(f"Mode    : {f['mode']}")
    if errors:
        print("\nERREURS RUNTIME")
        for case_id, error in errors:
            print(f"- {case_id}: {error}")

if __name__ == "__main__":
    main()
