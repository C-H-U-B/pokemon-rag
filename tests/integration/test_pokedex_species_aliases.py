"""Régressions sur la vraie base, sans parsing de question ni appel modèle."""

import pytest

from pokemon_rag.mcp.server import pokemon_types
from pokemon_rag.structured.query_engine import get_level_up_moves, get_pokedex_identity

pytestmark = pytest.mark.real_data


@pytest.mark.parametrize("name, types", [
    ("Nigirigon", ("Dragon", "Eau")),
    ("Tatsugiri", ("Dragon", "Eau")),
    ("Giratina", ("Spectre", "Dragon")),
    ("Shaymin", ("Plante", None)),
])
def test_species_name_resolves_default_custom_form(name, types):
    result = pokemon_types(name)
    row = result["rows"][0]
    assert (row["type_1_fr"], row["type_2_fr"]) == types
    assert result["count"] == 1


def test_full_form_name_and_identity_are_preserved():
    result = pokemon_types("Nigirigon Forme Courbée")
    assert result["pokemon"] == "Nigirigon Forme Courbée"
    assert get_pokedex_identity("Nigirigon")["rows"][0]["national_number"] == 978


@pytest.mark.parametrize("pokemon, form", [
    ("Nigirigon", "forme inexistante"),
    ("Espèce inexistante", None),
])
def test_missing_species_or_requested_form_remains_an_error(pokemon, form):
    with pytest.raises(ValueError):
        pokemon_types(pokemon, form)


def test_moves_retain_french_names_and_technical_identifiers():
    # Sans jeu, seul le dernier jeu est renvoyé : l'historique multijeux se demande explicitement.
    result = get_level_up_moves("Opermine", min_level=10, max_level=25, all_versions=True)
    names = {move["identifier"]: move["name_fr"] for move in result["moves"]}
    assert names["fury-swipes"] == "Combo-Griffe"
    assert names["slash"] == "Tranche"
    assert names["clamp"] == "Claquoir"
    assert names["rock-polish"] == "Poliroche"
    assert all(10 <= move["level"] <= 25 for move in result["moves"])
    assert "omega-ruby-alpha-sapphire" in {
        move["version_group"] for move in result["moves"]
    }
