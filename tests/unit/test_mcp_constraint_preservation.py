from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokemon_rag.client.mcp_client import ConstraintResolutionError, reconcile_tool_call
from pokemon_rag.constraints.query_constraints import extract_explicit_constraints, extract_national_pokedex_number


def tool(name: str, *properties: str):
    return SimpleNamespace(
        name=name,
        input_schema={
            "type": "object",
            "properties": {key: {} for key in properties},
        },
    )


LEVEL_TOOL = tool(
    "pokemon_level_up_moves",
    "pokemon",
    "form",
    "version_group",
    "min_level",
    "max_level",
)
TYPES_TOOL = tool("pokemon_types", "pokemon", "form")


@pytest.mark.parametrize("question,number", [
    ("Quel est le Pokémon numéro 369 du Pokédex national ?", 369),
    ("Quel Pokémon n° 428 ?", 428),
    ("Pokédex national : numéro 25", 25),
    ("Quel est le numéro national de Lockpin ?", None),
    ("Quelles attaques Relicanth apprend au niveau 40 ?", None),
    ("Quels Pokémon de 7G ?", None),
    ("Quel est le numéro 369 de cette facture ?", None),
])
def test_extract_number_in_pokedex_context_only(question, number):
    assert extract_national_pokedex_number(question) == number


@pytest.mark.parametrize("question", [
    "Pokémon numéro 0", "Pokémon numéro -1",
    "Pokémon numéros 369 et 428", "Pokémon numéro 369 ou 428",
    "Pokémon numéro 369 du Pokédex de Hoenn",
])
def test_invalid_or_regional_numbers_are_not_national(question):
    with pytest.raises(ValueError):
        extract_national_pokedex_number(question)


def test_number_lookup_redirects_guessed_identity_to_search():
    search = tool("pokemon_search", "pokedex_number", "form")
    identity = tool("pokemon_pokedex_identity", "pokemon", "form")
    name, args = reconcile_tool_call(
        "Quel est le Pokémon numéro 369 du Pokédex national ?",
        "pokemon_pokedex_identity", {"pokemon": "Lopunny", "form": None}, [search, identity])
    assert name == "pokemon_search"
    assert args == {"pokedex_number": 369, "form": None}


def test_number_lookup_fails_when_search_is_unavailable():
    with pytest.raises(ConstraintResolutionError, match="numéro national"):
        reconcile_tool_call("Quel Pokémon numéro 369 ?", "pokemon_pokedex_identity",
                            {"pokemon": "Lopunny"}, [tool("pokemon_pokedex_identity", "pokemon")])


def test_search_requires_no_individual_pokemon_and_preserves_move_filters():
    search = tool("pokemon_search", "types", "move_type", "damage_class", "version_group",
                  "learning_method", "min_level", "max_level", "form")
    name, args = reconcile_tool_call(
        "Quels Pokémon Eau apprennent une attaque Glace spéciale jusqu'au niveau 30 dans Pokémon Soleil ?",
        "pokemon_search", {"types": ["Eau"], "move_type": "Glace", "damage_class": "special"},
        [search, LEVEL_TOOL])
    assert name == "pokemon_search"
    assert args["types"] == ["Eau"] and args["move_type"] == "Glace"
    assert args["max_level"] == 30 and args["learning_method"] == "level-up"
    assert args["version_group"] == "sun-moon"


def test_client_preserves_stat_ranking_category_and_other_filters():
    args = {"types":["fire"], "generation":1, "legendary":False, "sort_by":"attack",
            "sort_order":"desc", "best_only":True, "form_category":"mega", "limit":5}
    search = tool("pokemon_search", *args, "offset", "type_match")
    name, actual = reconcile_tool_call(
        "Quels sont les 5 Pokémon Méga Feu avec le plus d'Attaque ?", "pokemon_search", args, [search])
    assert name == "pokemon_search"
    assert actual == {**args, "type_match":"all", "best_only":False, "offset":0}


def test_restores_game_and_max_level_before_execution() -> None:
    name, arguments = reconcile_tool_call(
        "Quelles capacités Pikachu apprend-il jusqu'au niveau 30 dans Pokémon Rouge ?",
        "pokemon_level_up_moves",
        {"pokemon": "Pikachu", "min_level": None, "max_level": None},
        [LEVEL_TOOL],
    )

    assert name == "pokemon_level_up_moves"
    assert arguments == {
        "pokemon": "Pikachu",
        "min_level": None,
        "max_level": 30,
        "version_group": "red-blue",
    }


def test_switches_to_level_tool_instead_of_dropping_level_constraint() -> None:
    name, arguments = reconcile_tool_call(
        "Quelles capacités Pikachu apprend-il jusqu'au niveau 30 ?",
        "pokemon_types",
        {"pokemon": "Pikachu"},
        [TYPES_TOOL, LEVEL_TOOL],
    )

    assert name == "pokemon_level_up_moves"
    assert arguments["pokemon"] == "Pikachu"
    assert arguments["max_level"] == 30


def test_restores_explicit_form() -> None:
    name, arguments = reconcile_tool_call(
        "Quels sont les types de Noadkoko d'Alola ?",
        "pokemon_types",
        {"pokemon": "Noadkoko", "form": None},
        [TYPES_TOOL],
    )

    assert name == "pokemon_types"
    assert arguments["form"] == "alola"


def test_blocks_unresolved_game_before_execution() -> None:
    with pytest.raises(ConstraintResolutionError, match="jeu demandé"):
        reconcile_tool_call(
            "Quelles capacités Pikachu apprend-il dans Pokémon version inconnue ?",
            "pokemon_level_up_moves",
            {"pokemon": "Pikachu"},
            [LEVEL_TOOL],
        )


def test_blocks_tool_that_cannot_honor_explicit_game() -> None:
    with pytest.raises(ConstraintResolutionError, match="pas filtrable"):
        reconcile_tool_call(
            "Quels sont les types de Pikachu dans Pokémon Rouge ?",
            "pokemon_types",
            {"pokemon": "Pikachu"},
            [TYPES_TOOL],
        )


def test_blocks_missing_pokemon_instead_of_simplifying_request() -> None:
    with pytest.raises(ConstraintResolutionError, match="Pokémon"):
        reconcile_tool_call(
            "Quelles capacités Pikachu apprend-il jusqu'au niveau 30 ?",
            "pokemon_level_up_moves",
            {"max_level": 30},
            [LEVEL_TOOL],
        )

def test_extract_level_range_between_levels() -> None:
    constraints = extract_explicit_constraints(
        "Quelles capacités Pikachu apprend-il par niveau "
        "entre les niveaux 10 et 20 dans Pokémon Rouge et Bleu ?"
    )

    assert constraints.level_explicit is True
    assert constraints.level_bounds == (10, 20)
    assert constraints.explicit_game is True
    assert constraints.version_ambiguous is False
    assert constraints.version_group == "red-blue"


def test_common_word_champions_is_not_a_game_but_the_full_title_is():
    from pokemon_rag.constraints.query_constraints import extract_version_group
    assert extract_version_group("Quels Pokémon utilisent les champions d'arène ?") == (None, False)
    assert extract_version_group("Quelles capacités apprend-il dans Pokémon Champions ?") == ("champions", False)


def test_client_removes_learning_method_absent_from_the_question_and_keeps_a_named_one():
    moves = tool("pokemon_moves", "pokemon", "damage_class", "learning_method")
    _, args = reconcile_tool_call("Quelles capacités physiques Krakos peut-il apprendre ?", "pokemon_moves",
        {"pokemon": "Krakos", "damage_class": "physical", "learning_method": "level-up"}, [moves])
    assert args == {"pokemon": "Krakos", "damage_class": "physical"}
    _, args = reconcile_tool_call("Quelles capacités physiques Krakos apprend-il par CT ?", "pokemon_moves",
        {"pokemon": "Krakos", "damage_class": "physical", "learning_method": "machine"}, [moves])
    assert args["learning_method"] == "machine"
