from __future__ import annotations

from unittest.mock import patch

import pytest

from pokemon_rag.graph.router import _fast_route_question, route_question


@pytest.mark.parametrize(
    ("question", "pokemon"),
    [
        ("Comment Pikachu peut-il apprendre Électacle ?", "Pikachu"),
        ("Quelles CT Pikachu apprend-il dans EV ?", "Pikachu"),
        ("Quelles capacités Roitiflam apprend-il après le niveau 40 ?", "Roitiflam"),
        ("Comment Tutafeh de Galar évolue-t-il ?", "Tutafeh"),
        ("Quels sont les talents de Dracaufeu ?", "Dracaufeu"),
        ("Quelles sont les statistiques de Caratroc ?", "Caratroc"),
    ],
)
def test_fast_router_structured(question: str, pokemon: str) -> None:
    result = _fast_route_question(question)

    assert result is not None
    assert result["route"] == "STRUCTURED"
    assert result["intent"] == "STRUCTURED_QUERY"
    assert result["pokemon"] == pokemon
    assert result["pokemon_validated"] is True
    assert result["single_question"] is True
    assert result["router_mode"] == "FAST"


@pytest.mark.parametrize(
    "question",
    [
        "Pourquoi les joues de Pikachu produisent-elles de l'électricité ?",
        "Explique-moi la biologie de Pikachu.",
        "Qu'est-ce que tu peux me dire sur Lovdisc ?",
        "Qu'est-ce qui rend Lovdisc unique ?",
        "Comment Pikachu évolue-t-il et quelles CT apprend-il dans EV ?",
        "Quels sont les talents de Dracaufeu et où peut-on le capturer ?",
        "Quel Pokémon a la meilleure Vitesse ?",
    ],
)
def test_fast_router_defers_ambiguous_or_documentary_questions(question: str) -> None:
    assert _fast_route_question(question) is None


def test_route_question_skips_llm_when_fast_router_matches() -> None:
    with patch("pokemon_rag.graph.router.llm_client.chat.completions.create") as llm_call:
        result = route_question("Comment Pikachu peut-il apprendre Électacle ?")

    llm_call.assert_not_called()
    assert result["route"] == "STRUCTURED"
    assert result["router_mode"] == "FAST"
    assert result["router_time"] >= 0


def test_fast_router_requires_a_unique_explicit_pokemon() -> None:
    assert _fast_route_question("Comment apprendre Électacle ?") is None
    assert _fast_route_question("Comment Pikachu et Raichu évoluent-ils ?") is None

@pytest.mark.parametrize(
    ("question", "pokemon"),
    [
        ("comment pikachu évolue-t-il ?", "Pikachu"),
        ("COMMENT PIKACHU ÉVOLUE-T-IL ?", "Pikachu"),
        ("Comment Pikachu evolue-t-il ?", "Pikachu"),
        ("Comment Pikachu évolue t il", "Pikachu"),
        ("Quelles CT Dracaufeu apprend-il ?", "Dracaufeu"),
        ("quelles ct dracaufeu apprend il", "Dracaufeu"),
        ("Quelles capacités Roitiflam apprend-il au niveau 50 ?", "Roitiflam"),
        ("Comment Rattata d'Alola évolue-t-il ?", "Rattata"),
    ],
)
def test_fast_router_is_robust_to_common_formulations(
    question: str,
    pokemon: str,
) -> None:
    result = _fast_route_question(question)

    assert result is not None
    assert result["route"] == "STRUCTURED"
    assert result["pokemon"] == pokemon
    assert result["pokemon_validated"] is True
    assert result["router_mode"] == "FAST"

def test_route_question_falls_back_to_rag_when_llm_fails() -> None:
    with patch(
        "pokemon_rag.graph.router.llm_client.chat.completions.create",
        side_effect=RuntimeError("LLM unavailable"),
    ):
        result = route_question(
            "Pourquoi les joues de Pikachu produisent-elles de l'électricité ?"
        )

    assert result["route"] == "RAG"
    assert result["intent"] == "DOCUMENT_SEARCH"
    assert result["pokemon"] is None
    assert result["pokemon_validated"] is False
    assert result["router_mode"] == "FALLBACK"
    assert result["router_error"] is not None
    assert result["router_time"] >= 0


def test_route_question_falls_back_to_rag_on_invalid_llm_output() -> None:
    fake_response = type(
        "Response",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {
                        "message": type(
                            "Message",
                            (),
                            {"content": "ceci n'est pas du JSON"},
                        )()
                    },
                )()
            ]
        },
    )()

    with patch(
        "pokemon_rag.graph.router.llm_client.chat.completions.create",
        return_value=fake_response,
    ):
        result = route_question(
            "Pourquoi les joues de Pikachu produisent-elles de l'électricité ?"
        )

    assert result["route"] == "RAG"
    assert result["intent"] == "DOCUMENT_SEARCH"
    assert result["router_mode"] == "FALLBACK"
    assert result["router_error"] is not None