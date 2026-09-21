from __future__ import annotations

import sqlite3

import pytest

from pokemon_rag.config import DB_PATH
from pokemon_rag.structured.query_engine import (
    get_level_up_moves,
    get_machine_moves,
    get_move_learning_methods,
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def find_example(method: str) -> sqlite3.Row:
    """Trouve un exemple réel dans pokemon.db pour tester une méthode sans hardcoding."""
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT
                ps.identifier AS pokemon,
                m.identifier AS move,
                vg.identifier AS version_group
            FROM pokemon_moves pm
            JOIN pokemon p ON p.id = pm.pokemon_id
            JOIN pokemon_species ps ON ps.id = p.species_id
            JOIN moves m ON m.id = pm.move_id
            JOIN pokemon_move_methods pmm ON pmm.id = pm.pokemon_move_method_id
            JOIN version_groups vg ON vg.id = pm.version_group_id
            WHERE p.is_default = 1
              AND pmm.identifier = ?
            ORDER BY pm.pokemon_id, pm.version_group_id, pm.move_id
            LIMIT 1
            """,
            (method,),
        ).fetchone()

        assert row is not None, f"Aucun exemple {method!r} présent dans pokemon.db"
        return row
    finally:
        conn.close()


def test_roïtiflam_level_up() -> None:
    result = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=41,
    )
    by_name = {m["name_fr"]: m["level"] for m in result["moves"]}

    assert result["operation"] == "get_level_up_moves"
    assert result["count"] == 4
    assert by_name.get("Lance-Flammes") == 43
    assert by_name.get("Fracass’Tête") == 50
    assert by_name.get("Hurlement") == 55
    assert by_name.get("Boutefeu") == 62
    assert all(m["level"] >= 41 for m in result["moves"])
    assert all(
        m["version_group"] == "scarlet-violet"
        for m in result["moves"]
    )


def test_level_boundaries() -> None:
    exact = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=50,
        max_level=50,
    )
    assert exact["count"] == 1
    assert exact["moves"][0]["identifier"] == "head-smash"

    interval = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=43,
        max_level=50,
    )
    assert interval["count"] == 2
    assert {m["level"] for m in interval["moves"]} == {43, 50}

    empty = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=100,
    )
    assert empty["count"] == 0
    assert empty["moves"] == []


def test_version_isolation() -> None:
    old = get_level_up_moves("Pikachu", version_group="red-blue")
    new = get_level_up_moves("Pikachu", version_group="scarlet-violet")

    assert old["count"] > 0
    assert new["count"] > 0
    assert all(m["version_group"] == "red-blue" for m in old["moves"])
    assert all(
        m["version_group"] == "scarlet-violet"
        for m in new["moves"]
    )

    old_signature = {(m["identifier"], m["level"]) for m in old["moves"]}
    new_signature = {(m["identifier"], m["level"]) for m in new["moves"]}
    assert old_signature != new_signature


def test_no_version_filter() -> None:
    result = get_level_up_moves("Pikachu")
    groups = {m["version_group"] for m in result["moves"]}

    assert result["count"] > 0
    assert len(groups) > 1
    assert result["count"] == len(
        {
            (m["move_id"], m["level"], m["order"], m["version_group"])
            for m in result["moves"]
        }
    )


def test_machine_pikachu() -> None:
    result = get_machine_moves("Pikachu", version_group="scarlet-violet")

    assert result["operation"] == "get_machine_moves"
    assert result["count"] > 0
    assert all(
        m["version_group"] == "scarlet-violet"
        for m in result["moves"]
    )
    assert all(m["move_id"] is not None for m in result["moves"])
    assert all(m["identifier"] for m in result["moves"])
    assert result["count"] == len(
        {
            (m["move_id"], m["version_group"], m["machine_number"])
            for m in result["moves"]
        }
    )


def test_machine_version_isolation() -> None:
    old = get_machine_moves("Pikachu", version_group="red-blue")
    new = get_machine_moves("Pikachu", version_group="scarlet-violet")

    assert old["count"] > 0
    assert new["count"] > 0
    assert all(m["version_group"] == "red-blue" for m in old["moves"])
    assert all(
        m["version_group"] == "scarlet-violet"
        for m in new["moves"]
    )


@pytest.mark.parametrize(
    "method",
    ["level-up", "machine", "egg", "tutor"],
    ids=["level-up", "ct", "egg", "tutor"],
)
def test_methods_from_real_db_examples(method: str) -> None:
    example = find_example(method)

    result = get_move_learning_methods(
        example["pokemon"],
        example["move"],
        version_group=example["version_group"],
    )

    methods = {row["method"] for row in result["methods"]}
    assert result["count"] > 0
    assert method in methods


def test_electacle_contract() -> None:
    result = get_move_learning_methods("Pikachu", "Électacle")

    assert result["operation"] == "get_move_learning_methods"
    assert result["move"]["identifier"] == "volt-tackle"
    assert result["count"] > 0
    assert all(m["method"] for m in result["methods"])

    # On n'attend volontairement PAS la condition Balle Lumière :
    # elle n'est pas encodée dans les tables PokéAPI intégrées.


def test_french_english_resolution() -> None:
    fr = get_move_learning_methods("Dracaufeu", "Lance-Flammes")
    en = get_move_learning_methods("Charizard", "Flamethrower")

    assert fr["move"]["move_id"] == en["move"]["move_id"]
    assert fr["move"]["identifier"] == "flamethrower"

    fr_rows = {
        (r["pokemon_id"], r["level"], r["method"], r["version_group"])
        for r in fr["methods"]
    }
    en_rows = {
        (r["pokemon_id"], r["level"], r["method"], r["version_group"])
        for r in en["methods"]
    }
    assert fr_rows == en_rows


def test_form_isolation_meowth_galar() -> None:
    normal = get_level_up_moves(
        "Miaouss",
        version_group="sword-shield",
    )
    galar = get_level_up_moves(
        "Miaouss",
        form="Galar",
        version_group="sword-shield",
    )

    assert normal["count"] > 0
    assert galar["count"] > 0

    normal_signature = {
        (m["identifier"], m["level"])
        for m in normal["moves"]
    }
    galar_signature = {
        (m["identifier"], m["level"])
        for m in galar["moves"]
    }
    assert normal_signature != galar_signature


def test_move_learning_methods_form_isolation() -> None:
    normal = get_move_learning_methods(
        "Miaouss",
        "Griffe",
        version_group="sword-shield",
    )
    galar = get_move_learning_methods(
        "Miaouss",
        "Griffe",
        form="Galar",
        version_group="sword-shield",
    )

    assert normal["operation"] == "get_move_learning_methods"
    assert galar["operation"] == "get_move_learning_methods"

    assert all(
        row["version_group"] == "sword-shield"
        for row in normal["methods"]
    )
    assert all(
        row["version_group"] == "sword-shield"
        for row in galar["methods"]
    )

    normal_rows = {
        (row["pokemon_id"], row["level"], row["method"])
        for row in normal["methods"]
    }
    galar_rows = {
        (row["pokemon_id"], row["level"], row["method"])
        for row in galar["methods"]
    }
    assert normal_rows != galar_rows


def test_valid_move_not_learned() -> None:
    result = get_move_learning_methods(
        "Magicarpe",
        "Tonnerre",
        version_group="scarlet-violet",
    )

    assert result["move"]["identifier"] == "thunderbolt"
    assert result["count"] == 0
    assert result["methods"] == []


def test_invalid_pokemon() -> None:
    with pytest.raises(ValueError):
        get_move_learning_methods("Pikachouuu", "Tonnerre")


def test_invalid_move() -> None:
    with pytest.raises(ValueError):
        get_move_learning_methods("Pikachu", "CapacitéQuiNExistePas")


def test_invalid_form() -> None:
    with pytest.raises(ValueError):
        get_level_up_moves("Pikachu", form="Galar")


def test_invalid_level_interval() -> None:
    with pytest.raises(ValueError):
        get_level_up_moves("Pikachu", min_level=50, max_level=40)


def test_negative_level() -> None:
    with pytest.raises(ValueError):
        get_level_up_moves("Pikachu", min_level=-1)


def test_unknown_version_contract() -> None:
    level = get_level_up_moves(
        "Pikachu",
        version_group="version-inexistante",
    )
    machine = get_machine_moves(
        "Pikachu",
        version_group="version-inexistante",
    )
    methods = get_move_learning_methods(
        "Pikachu",
        "Tonnerre",
        version_group="version-inexistante",
    )

    assert level["count"] == 0
    assert level["moves"] == []

    assert machine["count"] == 0
    assert machine["moves"] == []

    assert methods["count"] == 0
    assert methods["methods"] == []
