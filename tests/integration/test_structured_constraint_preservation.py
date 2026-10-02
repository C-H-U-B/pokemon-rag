from __future__ import annotations
import pytest

from pokemon_rag.structured.query_parser import query_structured_data


@pytest.mark.real_data
def test_french_tonnerre_is_resolved_internally() -> None:
    result = query_structured_data(
        "Par quelles méthodes Pikachu apprend-il Tonnerre dans Pokémon Rouge ?"
    )
    assert result["error"] is None
    assert result["plan"]["operation"] == "get_move_learning_methods"
    assert result["plan"]["move"] == "Tonnerre"
    assert result["plan"]["version_group"] == "red-blue"
    assert result["move"]["identifier"] == "thunderbolt"
