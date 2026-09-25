from __future__ import annotations

import argparse
import time
from pathlib import Path

from tqdm import tqdm

from pokemon_rag.config import PROJECT_ROOT
from pokemon_rag.graph.graph import graph


DEFAULT_QUESTIONS_FILE = PROJECT_ROOT / "scripts" / "batch" / "questions.txt"


def load_questions(path: Path) -> list[str]:
    """Charge une question par ligne en ignorant les lignes vides et commentaires."""
    if not path.exists():
        raise FileNotFoundError(f"Fichier de questions introuvable : {path}")

    questions = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            question = line.strip()
            if not question or question.startswith("#"):
                continue
            questions.append(question)

    return questions


def run_question(question: str, *, verbose: bool = False) -> dict:
    """Exécute une question à travers le vrai graphe end-to-end."""
    return graph.invoke(
        {
            "question": question,
            "verbose": verbose,
            "retrieval_retry_count": 0,
            "generation_retry_count": 0,
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exécute un batch de vraies questions end-to-end."
    )
    parser.add_argument(
        "questions_file",
        nargs="?",
        type=Path,
        default=DEFAULT_QUESTIONS_FILE,
        help=f"Fichier texte avec une question par ligne (défaut : {DEFAULT_QUESTIONS_FILE})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre de questions exécutées.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Active les sorties détaillées des composants du graphe.",
    )

    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit doit être supérieur ou égal à 1.")

    return args


def main() -> None:
    args = parse_args()
    questions = load_questions(args.questions_file)

    if args.limit is not None:
        questions = questions[: args.limit]

    if not questions:
        print("Aucune question à exécuter.")
        return

    print(f"Questions chargées : {len(questions)}")
    print(f"Source             : {args.questions_file}")
    print()

    batch_start = time.perf_counter()
    completed = 0
    failures = 0

    progress = tqdm(
        questions,
        desc="Questions",
        unit="question",
        dynamic_ncols=True,
    )

    for index, question in enumerate(progress, start=1):
        progress.set_postfix_str(question[:45])

        start = time.perf_counter()

        try:
            result = run_question(question, verbose=args.verbose)
        except Exception as exc:
            failures += 1
            elapsed = time.perf_counter() - start
            tqdm.write(
                f"[{index}/{len(questions)}] ERREUR | {elapsed:.2f} s | {question}\n"
                f"  {type(exc).__name__}: {exc}"
            )
            continue

        completed += 1
        elapsed = time.perf_counter() - start

        route = str(result.get("route") or "N/A")
        decision = str(result.get("grounding_decision") or "N/A")

        tqdm.write(
            f"[{index}/{len(questions)}] "
            f"{route} | {decision} | {elapsed:.2f} s | {question}"
        )

    total_time = time.perf_counter() - batch_start

    print()
    print("=" * 72)
    print("BATCH TERMINÉ")
    print("=" * 72)
    print(f"Questions prévues : {len(questions)}")
    print(f"Réussies           : {completed}")
    print(f"Erreurs            : {failures}")
    print(f"Temps total        : {total_time:.2f} s")

    if completed:
        print(f"Temps moyen        : {total_time / completed:.2f} s")


if __name__ == "__main__":
    main()
