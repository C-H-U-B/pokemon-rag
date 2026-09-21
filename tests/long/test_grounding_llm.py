from __future__ import annotations

import pytest

from pokemon_rag.rag.grounding import check_grounding


pytestmark = pytest.mark.long


CASES = [
    pytest.param(
        "Comment Pikachu évolue-t-il ?",
        "Pikachu évolue en Raichu lorsqu'une Pierre Foudre est utilisée sur lui.",
        "Pikachu évolue en Raichu avec une Pierre Foudre.",
        "PASS",
        id="pass-supported-answer",
    ),
    pytest.param(
        "Comment Pikachu évolue-t-il ?",
        "Pikachu évolue en Raichu lorsqu'une Pierre Foudre est utilisée sur lui.",
        "Pikachu évolue en Raichu au niveau 30.",
        "CONTRADICTION",
        id="contradiction",
    ),
    pytest.param(
        "Comment Pikachu évolue-t-il ?",
        "Pikachu est un Pokémon de type Électrik.",
        "Pikachu évolue en Raichu avec une Pierre Foudre.",
        "INSUFFICIENT",
        id="insufficient-context",
    ),
    pytest.param(
        "Comment Pikachu évolue-t-il ?",
        "Pikachu évolue en Raichu lorsqu'une Pierre Foudre est utilisée sur lui.",
        "Pikachu évolue en Raichu avec une Pierre Foudre et apprend ensuite une attaque exclusive.",
        "UNSUPPORTED",
        id="unsupported-addition",
    ),
]


@pytest.mark.parametrize(
    ("question", "context", "answer", "expected_decision"),
    CASES,
)
def test_grounding_llm_decisions(
    question: str,
    context: str,
    answer: str,
    expected_decision: str,
) -> None:
    result = check_grounding(question, context, answer)

    assert result["decision"] == expected_decision
    assert result["grounded"] is (expected_decision == "PASS")
    assert result["reason"]
    assert result["time"] >= 0
