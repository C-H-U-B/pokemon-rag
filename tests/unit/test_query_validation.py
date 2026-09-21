from __future__ import annotations

import pytest

from pokemon_rag.structured.query_engine import validate_plan


@pytest.mark.parametrize(
    "plan",
    [
        # Opération absente
        {
            "pokemon": "Pikachu",
            "form": None,
            "version_group": None,
        },

        # Opération inconnue
        {
            "operation": "unknown_operation",
            "pokemon": "Pikachu",
            "form": None,
            "version_group": None,
        },

        # Clé obligatoire manquante
        {
            "operation": "get_evolutions",
            "pokemon": "Pikachu",
            "form": None,
        },

        # Clé supplémentaire interdite
        {
            "operation": "get_evolutions",
            "pokemon": "Pikachu",
            "form": None,
            "version_group": None,
            "unexpected": True,
        },

        # Pokémon vide
        {
            "operation": "get_evolutions",
            "pokemon": "",
            "form": None,
            "version_group": None,
        },

        # Forme de mauvais type
        {
            "operation": "get_evolutions",
            "pokemon": "Pikachu",
            "form": 123,
            "version_group": None,
        },

        # Version vide
        {
            "operation": "get_evolutions",
            "pokemon": "Pikachu",
            "form": None,
            "version_group": "",
        },

        # Capacité vide
        {
            "operation": "get_move_learning_methods",
            "pokemon": "Pikachu",
            "form": None,
            "move": "",
            "version_group": None,
        },

        # Niveau négatif
        {
            "operation": "get_level_up_moves",
            "pokemon": "Pikachu",
            "form": None,
            "version_group": None,
            "min_level": -1,
            "max_level": None,
        },

        # Intervalle impossible
        {
            "operation": "get_level_up_moves",
            "pokemon": "Pikachu",
            "form": None,
            "version_group": None,
            "min_level": 50,
            "max_level": 20,
        },
    ],
    ids=[
        "missing-operation",
        "unknown-operation",
        "missing-required-key",
        "unexpected-key",
        "empty-pokemon",
        "invalid-form-type",
        "empty-version",
        "empty-move",
        "negative-level",
        "min-greater-than-max",
    ],
)
def test_validate_plan_rejects_invalid_plans(plan: dict) -> None:
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_validate_plan_normalizes_strings() -> None:
    result = validate_plan(
        {
            "operation": "get_move_learning_methods",
            "pokemon": "  Pikachu  ",
            "form": None,
            "move": "  Électacle  ",
            "version_group": "  scarlet-violet  ",
        }
    )

    assert result == {
        "operation": "get_move_learning_methods",
        "pokemon": "Pikachu",
        "form": None,
        "version_group": "scarlet-violet",
        "move": "Électacle",
    }


@pytest.mark.parametrize(
    "value",
    [True, False],
    ids=["true-is-not-a-level", "false-is-not-a-level"],
)
def test_validate_plan_rejects_boolean_levels(value: bool) -> None:
    plan = {
        "operation": "get_level_up_moves",
        "pokemon": "Pikachu",
        "form": None,
        "version_group": None,
        "min_level": value,
        "max_level": None,
    }

    with pytest.raises(ValueError):
        validate_plan(plan)
