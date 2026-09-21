from __future__ import annotations

import pytest

from pokemon_rag.structured.query_engine import get_evolutions


def find_evolution(
    result: dict,
    target_identifier: str,
    version_group: str | None = None,
) -> dict | None:
    for evolution in result["evolutions"]:
        if evolution["to"]["identifier"] != target_identifier:
            continue
        if version_group is not None and evolution["version_group"] != version_group:
            continue
        return evolution
    return None


def test_pikachu_regional_target() -> None:
    result = get_evolutions("Pikachu")

    assert result["operation"] == "get_evolutions"
    assert result["count"] == 2

    normal = find_evolution(result, "raichu", "red-blue")
    alola = find_evolution(result, "raichu", "sun-moon")

    assert normal is not None
    assert alola is not None
    assert normal["conditions"].get("trigger_item", {}).get("fr") == "Pierre Foudre"
    assert alola["to"].get("form", {}).get("form_identifier") == "alola"
    assert alola["conditions"].get("region", {}).get("fr") == "Alola"


def test_dinoclier_level_evolution() -> None:
    result = get_evolutions("Dinoclier")
    evolution = find_evolution(result, "bastiodon")

    assert result["count"] == 1
    assert evolution is not None
    assert evolution["trigger"] == "level-up"
    assert evolution["conditions"].get("minimum_level") == 30


def test_debugant_stat_branches() -> None:
    result = get_evolutions("Debugant")

    kicklee = find_evolution(result, "hitmonlee")
    tygnon = find_evolution(result, "hitmonchan")
    kapoera = find_evolution(result, "hitmontop")

    assert result["count"] == 3
    assert kicklee is not None
    assert tygnon is not None
    assert kapoera is not None

    assert kicklee["conditions"].get("relative_physical_stats") == 1
    assert tygnon["conditions"].get("relative_physical_stats") == -1

    # Dans la représentation actuelle, l'égalité (0) est omise des
    # conditions non nulles plutôt que sérialisée explicitement à 0.
    assert kapoera["conditions"].get("relative_physical_stats") == 0


def test_sepiatop_special_condition() -> None:
    result = get_evolutions("Sepiatop")
    evolution = find_evolution(result, "malamar")

    assert result["count"] == 1
    assert evolution is not None
    assert evolution["conditions"].get("minimum_level") == 30
    assert evolution["conditions"].get("turn_upside_down") == 1


def test_tutafeh_galar_form_isolation() -> None:
    result = get_evolutions("Tutafeh", form="Galar")

    assert result["operation"] == "get_evolutions"
    assert result["form"] == "Galar"
    assert result["count"] == 1

    assert all(
        evolution.get("from", {}).get("form", {}).get("form_identifier") == "galar"
        or evolution["conditions"].get("required_pokemon_form", {}).get("form_identifier") == "galar"
        for evolution in result["evolutions"]
    )


def test_dofin_multiplayer_condition() -> None:
    result = get_evolutions("Dofin")
    evolution = find_evolution(result, "palafin")

    assert result["count"] == 1
    assert evolution is not None
    assert evolution["conditions"].get("needs_multiplayer") == 1


def test_evoli_has_multiple_historical_evolution_rules() -> None:
    result = get_evolutions("Évoli")

    assert result["count"] > 1
    targets = {evolution["to"]["identifier"] for evolution in result["evolutions"]}

    assert "vaporeon" in targets
    assert "jolteon" in targets
    assert "flareon" in targets


def test_version_filter_is_strict() -> None:
    result = get_evolutions("Évoli", version_group="sword-shield")

    assert result["version_group"] == "sword-shield"
    assert result["count"] > 0
    assert all(
        evolution["version_group"] == "sword-shield"
        for evolution in result["evolutions"]
    )


def test_unknown_version_returns_no_rule() -> None:
    result = get_evolutions(
        "Pikachu",
        version_group="version-inexistante",
    )

    assert result["count"] == 0
    assert result["evolutions"] == []


@pytest.mark.parametrize(
    ("pokemon", "form"),
    [
        ("PokémonQuiNExistePas", None),
        ("Tutafeh", "FormeQuiNExistePas"),
    ],
    ids=[
        "unknown-pokemon",
        "unknown-form",
    ],
)
def test_invalid_inputs_raise_value_error(
    pokemon: str,
    form: str | None,
) -> None:
    with pytest.raises(ValueError):
        get_evolutions(pokemon, form=form)
