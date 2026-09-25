from __future__ import annotations
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from tqdm import tqdm
from pokemon_rag.rag.grounding import check_grounding

DATASET_PATH = Path(__file__).resolve().parent / "data" / "grounding_cases.json"

def main() -> None:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]
    unreviewed = [c["id"] for c in cases if c.get("status") != "APPROVED"]
    if unreviewed:
        raise RuntimeError(f"Cas non APPROVED : {', '.join(unreviewed)}")

    correct = 0
    timings = []
    by_label = defaultdict(lambda: [0, 0])
    confusion = Counter()
    failures = []

    for case in tqdm(cases, desc="Benchmark grounding", unit="cas", dynamic_ncols=True):
        result = check_grounding(case["question"], case["context"], case["answer"])
        expected = case["expected_decision"]
        got = result["decision"]
        ok = got == expected

        correct += int(ok)
        by_label[expected][0] += int(ok)
        by_label[expected][1] += 1
        confusion[(expected, got)] += 1
        timings.append(float(result["time"]))

        if not ok:
            failures.append({
                "id": case["id"], "question": case["question"],
                "expected": expected, "got": got, "reason": result["reason"],
            })

    n = len(cases)
    print("\n" + "=" * 72)
    print("BENCHMARK GROUNDING")
    print("=" * 72)
    print(f"Cas               : {n}")
    print(f"Accuracy          : {correct/n:.3f} ({correct}/{n})")
    for label in ("PASS","INSUFFICIENT","CONTRADICTION","UNSUPPORTED","INCOMPLETE"):
        good, total = by_label[label]
        print(f"{label:<18}: {good/total:.3f} ({good}/{total})")
    print(f"Temps moyen       : {statistics.fmean(timings)*1000:.1f} ms")
    print(f"Temps médian      : {statistics.median(timings)*1000:.1f} ms")
    print("=" * 72)

    if failures:
        print("\nCAS À ANALYSER")
        for f in failures:
            print(f"\n[{f['id']}] {f['question']}")
            print(f"Attendu : {f['expected']}")
            print(f"Obtenu  : {f['got']}")
            print(f"Raison  : {f['reason']}")

        print("\nCONFUSIONS")
        for (expected, got), count in sorted(confusion.items()):
            if expected != got:
                print(f"- {expected} -> {got}: {count}")

if __name__ == "__main__":
    main()
