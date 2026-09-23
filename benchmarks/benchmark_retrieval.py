from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from tqdm import tqdm

from pokemon_rag.rag import retrieval


DATASET_PATH = Path(__file__).resolve().parent / "data" / "retrieval_cases.json"
TOP_K = (1, 3, 5)


def section_key(result: dict) -> tuple[str, str]:
    metadata = result.get("metadata") or {}
    return (
        str(metadata.get("source_file", "")).strip(),
        retrieval.metadata_section_path(metadata),
    )


def reciprocal_rank(
    results: list[dict],
    expected_key: tuple[str, str],
) -> float:
    for rank, result in enumerate(results, start=1):
        if section_key(result) == expected_key:
            return 1.0 / rank
    return 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


def main() -> None:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]

    unreviewed = [case["id"] for case in cases if case.get("status") != "APPROVED"]
    if unreviewed:
        raise RuntimeError(
            "Benchmark refusé : certains cas ne sont pas APPROVED. "
            "Relire d'abord retrieval_cases.json. "
            f"Cas concernés : {', '.join(unreviewed[:10])}"
        )

    print("Initialisation du vrai moteur de retrieval...")
    startup_start = time.perf_counter()
    retrieval.ensure_retrieval_initialized()
    startup_time = time.perf_counter() - startup_start

    hits = {k: 0 for k in TOP_K}
    reciprocal_ranks = []
    timings = []
    failures = []

    for case in tqdm(cases, desc="Benchmark retrieval", unit="question", dynamic_ncols=True):
        start = time.perf_counter()
        results = retrieval.retrieve(
            case["question"],
            n_results=max(TOP_K),
            rerank=True,
            pokemon=case.get("pokemon"),
        )
        elapsed = time.perf_counter() - start
        timings.append(elapsed)

        expected_key = (
            case["expected_source_file"],
            case["expected_section_path"],
        )
        ranked_keys = [section_key(result) for result in results]

        for k in TOP_K:
            if expected_key in ranked_keys[:k]:
                hits[k] += 1

        rr = reciprocal_rank(results, expected_key)
        reciprocal_ranks.append(rr)

        if rr == 0.0:
            failures.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "pokemon": case.get("pokemon"),
                    "expected": expected_key,
                    "returned": ranked_keys,
                }
            )

    n = len(cases)

    print()
    print("=" * 72)
    print("BENCHMARK RETRIEVAL")
    print("=" * 72)
    print(f"Cas               : {n}")
    print(f"Cold start        : {startup_time:.3f} s")
    for k in TOP_K:
        print(f"Recall@{k:<2}         : {hits[k] / n:.3f} ({hits[k]}/{n})")
    print(f"MRR               : {statistics.fmean(reciprocal_ranks):.3f}")
    print()
    print(f"Warm mean         : {statistics.fmean(timings) * 1000:.1f} ms")
    print(f"Warm median       : {statistics.median(timings) * 1000:.1f} ms")
    print(f"Warm p95          : {percentile(timings, 0.95) * 1000:.1f} ms")
    print(f"Warm min/max      : {min(timings) * 1000:.1f} / {max(timings) * 1000:.1f} ms")
    print(f"Échecs Top-{max(TOP_K)}      : {len(failures)}")
    print("=" * 72)

    if failures:
        print("\nÉCHECS À ANALYSER")
        for failure in failures:
            print()
            print(f"[{failure['id']}] {failure['question']}")
            print(f"Pokémon  : {failure['pokemon']}")
            print(f"Attendu  : {failure['expected'][1]}")
            print("Retourné :")
            for source_file, section_path in failure["returned"]:
                print(f"  - {section_path} ({source_file})")


if __name__ == "__main__":
    main()
