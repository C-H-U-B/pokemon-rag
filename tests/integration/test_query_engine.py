from __future__ import annotations

from unittest.mock import patch

import pytest

from pokemon_rag.structured.query_engine import execute_plan


@pytest.mark.parametrize(
    ("plan", "function_name"),
    [
        (
            {
                "operation": "get_evolutions",
                "pokemon": "Pikachu",
                "form": None,
                "version_group": None,
            },
            "get_evolutions",
        ),
        (
            {
                "operation": "get_move_learning_methods",
                "pokemon": "Pikachu",
                "form": None,
                "move": "Électacle",
                "version_group": None,
            },
            "get_move_learning_methods",
        ),
        (
            {
                "operation": "get_level_up_moves",
                "pokemon": "Pikachu",
                "form": None,
                "version_group": None,
                "min_level": 20,
                "max_level": 40,
            },
            "get_level_up_moves",
        ),
        (
            {
                "operation": "get_machine_moves",
                "pokemon": "Pikachu",
                "form": None,
                "version_group": "scarlet-violet",
            },
            "get_machine_moves",
        ),
    ],
    ids=[
        "evolutions",
        "move-learning-methods",
        "level-up-moves",
        "ct-moves",
    ],
)
def test_execute_plan_dispatches_to_correct_operation(
    plan: dict,
    function_name: str,
) -> None:
    expected = {"operation": plan["operation"], "count": 123}

    with patch(
        f"pokemon_rag.structured.query_engine.{function_name}",
        return_value=expected,
    ) as mocked_function:
        result = execute_plan(plan)

    mocked_function.assert_called_once()
    assert result == expected
