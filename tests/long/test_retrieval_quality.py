from __future__ import annotations

import pytest

import pokemon_rag.rag.retrieval as retrieval


pytestmark = pytest.mark.long


CASES = [
    {
        "question": "Comment Pikachu évolue-t-il ?",
        "pokemon": "Pikachu",
        "expected_terms": {"évolution", "raichu"},
    },
    {
        "question": "Quelles capacités Bulbizarre peut-il apprendre ?",
        "pokemon": "Bulbizarre",
        "expected_terms": {"capacité", "capacités"},
    },
]


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=["pikachu-evolution", "bulbizarre-moves"],
)
def test_retrieval_quality_cases(case: dict) -> None:
    pokemon = case["pokemon"]
    if pokemon not in retrieval.POKEMON_TO_INDICES:
        pytest.skip(f"{pokemon} absent de l'index réel")

    results = retrieval.retrieve(
        case["question"],
        n_results=5,
        rerank=True,
        pokemon=pokemon,
    )

    assert results
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in results
    )

    context = results[0].get("context_results") or results
    searchable = " ".join(
        [
            str(item.get("document") or "")
            + " "
            + retrieval.metadata_section_path(item.get("metadata"))
            for item in context
        ]
    ).lower()

    assert any(term in searchable for term in case["expected_terms"])
