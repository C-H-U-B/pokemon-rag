from __future__ import annotations

from unittest.mock import patch

import pytest

from pokemon_rag.structured.query_parser import _fast_parse_query, parse_query


@pytest.mark.parametrize(
    ("question", "operation", "pokemon", "expected"),
    [
        (
            "Comment Pikachu peut-il apprendre Électacle ?",
            "get_move_learning_methods",
            "Pikachu",
            {"move": "Électacle", "form": None, "version_group": None},
        ),
        (
            "Quelles CT Pikachu apprend-il dans EV ?",
            "get_machine_moves",
            "Pikachu",
            {"form": None, "version_group": "scarlet-violet"},
        ),
        (
            "Quelles capacités Roitiflam apprend-il après le niveau 40 ?",
            "get_level_up_moves",
            "Roitiflam",
            {"form": None, "version_group": None, "min_level": 41, "max_level": None},
        ),
        (
            "Comment Tutafeh de Galar évolue-t-il ?",
            "get_evolutions",
            "Tutafeh",
            {"form": "galar", "version_group": None},
        ),
        (
            "Comment Rattata d'Alola évolue-t-il ?",
            "get_evolutions",
            "Rattata",
            {"form": "alola", "version_group": None},
        ),
        (
            "Comment Tutafeh de Galar évolue-t-il dans Épée et Bouclier ?",
            "get_evolutions",
            "Tutafeh",
            {"form": "galar", "version_group": "sword-shield"},
        ),
        (
            "Comment Pikachu évolue-t-il dans Rouge et Bleu ?",
            "get_evolutions",
            "Pikachu",
            {"form": None, "version_group": "red-blue"},
        ),
    ],
    ids=[
        "move-learning",
        "ct-with-version",
        "level-after",
        "galar-form",
        "alola-form",
        "galar-form-with-version",
        "old-version",
    ],
)
def test_fast_parser_structured(question, operation, pokemon, expected):
    plan = _fast_parse_query(question)

    assert plan is not None
    assert plan["operation"] == operation
    assert plan["pokemon"] == pokemon
    for key, value in expected.items():
        assert plan[key] == value


def test_fast_parser_exact_level():
    plan = _fast_parse_query("Quelle capacité Pikachu apprend-il au niveau 20 ?")

    assert plan is not None
    assert plan["operation"] == "get_level_up_moves"
    assert plan["min_level"] == 20
    assert plan["max_level"] == 20


def test_fast_parser_from_level_is_inclusive():
    plan = _fast_parse_query(
        "Quelles capacités Roitiflam apprend-il à partir du niveau 40 ?"
    )

    assert plan is not None
    assert plan["min_level"] == 40
    assert plan["max_level"] is None


def test_fast_parser_before_level_is_exclusive():
    plan = _fast_parse_query(
        "Quelles capacités Roitiflam apprend-il avant le niveau 40 ?"
    )

    assert plan is not None
    assert plan["min_level"] is None
    assert plan["max_level"] == 39


def test_fast_parser_preserves_both_level_bounds():
    plan = _fast_parse_query("Quelles capacités Pikachu apprend-il après le niveau 20 mais avant le niveau 40 ?")
    assert plan is not None
    assert (plan["min_level"], plan["max_level"]) == (21, 39)


@pytest.mark.parametrize("bounds, expected", [
    ("avant le niveau 40 mais après le niveau 20", (21, 39)),
    ("à partir du niveau 20 jusqu'au niveau 40", (20, 40)),
    ("après le niveau 20 jusqu'au niveau 40", (21, 40)),
    ("après le niveau 20 mais après le niveau 30", (31, None)),
    ("au niveau 20", (20, 20)),
])
def test_fast_parser_level_intersections(bounds, expected):
    plan = _fast_parse_query(f"Quelles capacités Pikachu apprend-il {bounds} ?")
    assert plan is not None
    assert (plan["min_level"], plan["max_level"]) == expected


@pytest.mark.parametrize("bounds", ["après le niveau 40 avant le niveau 20", "avant le niveau 0"])
def test_fast_parser_rejects_impossible_interval(bounds):
    with pytest.raises(ValueError, match="Intervalle"):
        _fast_parse_query(f"Quelles capacités Pikachu apprend-il {bounds} ?")


@pytest.mark.parametrize("bounds", ["au niveau 20 ou au niveau 40", "après le niveau 20 mais avant 40"])
def test_fast_parser_defers_incomplete_or_disjoint_interval(bounds):
    assert _fast_parse_query(f"Quelles capacités Pikachu apprend-il {bounds} ?") is None


@pytest.mark.parametrize("game_filter", [
    "dans Pokémon JeuInexistant", "dans JeuInexistant",
    "en Pokémon JeuInexistant", "sur Pokémon JeuInexistant",
    "version JeuInexistant",
])
def test_fast_parser_does_not_drop_unknown_game(game_filter):
    plan = _fast_parse_query(f"Quelles CT Pikachu apprend-il {game_filter} ?")
    assert plan is None


def test_parse_query_rejects_unknown_game_before_llm():
    with patch("pokemon_rag.structured.query_parser.llm_client.chat.completions.create") as mocked:
        with pytest.raises(ValueError, match="Jeu inconnu ou ambigu"):
            parse_query("Quelles CT Pikachu apprend-il dans Pokémon JeuInexistant ?")
    mocked.assert_not_called()


def test_fast_parser_rejects_unknown_pokemon():
    assert _fast_parse_query(
        "Comment PokémonQuiNExistePas évolue-t-il ?"
    ) is None


def test_fast_parser_rejects_multiple_operations():
    assert _fast_parse_query(
        "Comment Pikachu évolue-t-il et quelles CT apprend-il dans EV ?"
    ) is None


def test_parse_query_skips_llm_when_fast_parser_matches():
    with patch(
        "pokemon_rag.structured.query_parser.llm_client.chat.completions.create"
    ) as mocked:
        result = parse_query("Comment Pikachu peut-il apprendre Électacle ?")

    mocked.assert_not_called()
    assert result["parser_mode"] == "FAST"
    assert result["plan"]["operation"] == "get_move_learning_methods"


def test_parse_query_keeps_llm_fallback():
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
                            {
                                "content": (
                                    '{"operation":"get_evolutions",'
                                    '"pokemon":"Pikachu","form":null,'
                                    '"version_group":null}'
                                )
                            },
                        )()
                    },
                )()
            ]
        },
    )()

    with patch(
        "pokemon_rag.structured.query_parser.llm_client.chat.completions.create",
        return_value=fake_response,
    ) as mocked:
        result = parse_query("Donne-moi les informations structurées sur Pikachu.")

    mocked.assert_called_once()
    assert result["parser_mode"] == "LLM"
    assert result["plan"]["operation"] == "get_evolutions"


@pytest.mark.parametrize(
    ("question", "operation", "pokemon"),
    [
        (
            "comment pikachu évolue-t-il ?",
            "get_evolutions",
            "Pikachu",
        ),
        (
            "COMMENT PIKACHU ÉVOLUE-T-IL ?",
            "get_evolutions",
            "Pikachu",
        ),
        (
            "Comment Pikachu evolue-t-il ?",
            "get_evolutions",
            "Pikachu",
        ),
        (
            "Quelles CT Pikachu apprend-il dans EV ?",
            "get_machine_moves",
            "Pikachu",
        ),
        (
            "quelles ct pikachu apprend il dans ev",
            "get_machine_moves",
            "Pikachu",
        ),
        (
            "Quelles capacités Roitiflam apprend-il après le niveau 40 ?",
            "get_level_up_moves",
            "Roitiflam",
        ),
        (
            "Comment Rattata d'Alola évolue-t-il ?",
            "get_evolutions",
            "Rattata",
        ),
    ],
    ids=[
        "lowercase",
        "uppercase",
        "without-accents",
        "ct-standard",
        "ct-without-punctuation",
        "level-filter",
        "regional-form",
    ],
)
def test_fast_parser_is_robust_to_common_formulations(
    question: str,
    operation: str,
    pokemon: str,
) -> None:
    plan = _fast_parse_query(question)

    assert plan is not None
    assert plan["operation"] == operation
    assert plan["pokemon"] == pokemon


@pytest.mark.parametrize(
    "question",
    [
        # Aucun Pokémon explicite
        "Comment apprendre Électacle ?",

        # Plusieurs Pokémon
        "Comment Pikachu et Raichu évoluent-ils ?",

        # Question documentaire
        "Pourquoi les joues de Pikachu produisent-elles de l'électricité ?",

        # Question générale / ambiguë
        "Parle-moi de Pikachu.",

        # Comparaison
        "Pikachu est-il plus rapide que Raichu ?",

        # Deux besoins structurés différents
        "Comment Pikachu évolue-t-il et quelles CT apprend-il ?",
    ],
    ids=[
        "missing-pokemon",
        "multiple-pokemon",
        "documentary-question",
        "generic-question",
        "comparison",
        "multiple-intents",
    ],
)
def test_fast_parser_defers_unsafe_or_unsupported_questions(
    question: str,
) -> None:
    assert _fast_parse_query(question) is None
