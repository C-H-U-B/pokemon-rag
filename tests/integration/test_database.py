from __future__ import annotations

import sqlite3

import pytest

from pokemon_rag.config import DB_PATH


EXPECTED_OBJECTS = {
    "pokemon",
    "pokemon_species",
    "pokemon_forms",
    "pokemon_moves",
    "moves",
    "machines",
    "pokemon_evolution",
    "custom_pokedex_fr",
    "custom_pokedex_en",
    "custom_pokedex",
    "custom_pokeapi_mapping",
}


@pytest.fixture
def db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        pytest.fail(f"Base introuvable : {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")

    try:
        yield conn
    finally:
        conn.close()


def scalar(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple = (),
):
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def test_database_integrity(db: sqlite3.Connection) -> None:
    assert scalar(db, "PRAGMA integrity_check") == "ok"


def test_required_tables_and_views_exist(db: sqlite3.Connection) -> None:
    objects = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }

    missing = EXPECTED_OBJECTS - objects
    assert not missing, f"Objets SQLite manquants : {sorted(missing)}"


@pytest.mark.parametrize(
    "table",
    [
        "pokemon",
        "pokemon_species",
        "pokemon_forms",
        "pokemon_moves",
        "moves",
        "pokemon_evolution",
        "custom_pokedex_fr",
        "custom_pokedex_en",
        "custom_pokedex",
        "custom_pokeapi_mapping",
    ],
    ids=[
        "pokemon",
        "species",
        "forms",
        "pokemon-moves",
        "moves",
        "evolutions",
        "custom-fr",
        "custom-en",
        "custom-bilingual",
        "custom-mapping",
    ],
)
def test_core_objects_are_not_empty(
    db: sqlite3.Connection,
    table: str,
) -> None:
    assert scalar(db, f'SELECT COUNT(*) FROM "{table}"') > 0


def test_custom_pokedex_fr_and_en_have_same_row_count(
    db: sqlite3.Connection,
) -> None:
    fr = scalar(db, "SELECT COUNT(*) FROM custom_pokedex_fr")
    en = scalar(db, "SELECT COUNT(*) FROM custom_pokedex_en")

    assert fr == en
    assert fr > 0


def test_custom_pokedex_source_rows_are_unique(
    db: sqlite3.Connection,
) -> None:
    for table in ("custom_pokedex_fr", "custom_pokedex_en"):
        duplicates = scalar(
            db,
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT source_row
                FROM "{table}"
                GROUP BY source_row
                HAVING COUNT(*) > 1
            )
            """,
        )

        assert duplicates == 0, f"source_row dupliqué dans {table}"


@pytest.mark.parametrize(
    ("child_table", "child_column", "parent_table", "parent_column"),
    [
        ("pokemon", "species_id", "pokemon_species", "id"),
        ("pokemon_forms", "pokemon_id", "pokemon", "id"),
        ("pokemon_moves", "pokemon_id", "pokemon", "id"),
        ("pokemon_moves", "move_id", "moves", "id"),
        ("pokemon_evolution", "evolved_species_id", "pokemon_species", "id"),
    ],
    ids=[
        "pokemon-to-species",
        "forms-to-pokemon",
        "pokemon-moves-to-pokemon",
        "pokemon-moves-to-moves",
        "evolutions-to-species",
    ],
)
def test_core_references_are_not_orphaned(
    db: sqlite3.Connection,
    child_table: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
) -> None:
    orphan_count = scalar(
        db,
        f"""
        SELECT COUNT(*)
        FROM "{child_table}" child
        WHERE child."{child_column}" IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM "{parent_table}" parent
              WHERE parent."{parent_column}" = child."{child_column}"
          )
        """,
    )

    assert orphan_count == 0


@pytest.mark.parametrize(
    ("column", "target_table"),
    [
        ("evolution_trigger_id", "evolution_triggers"),
        ("version_group_id", "version_groups"),
        ("trigger_item_id", "items"),
        ("held_item_id", "items"),
        ("known_move_id", "moves"),
        ("party_species_id", "pokemon_species"),
        ("trade_species_id", "pokemon_species"),
        ("required_pokemon_form_id", "pokemon_forms"),
        ("evolved_pokemon_form_id", "pokemon_forms"),
        ("used_move_id", "moves"),
    ],
    ids=[
        "evolution-trigger",
        "version-group",
        "trigger-item",
        "held-item",
        "known-move",
        "party-species",
        "trade-species",
        "required-form",
        "evolved-form",
        "used-move",
    ],
)
def test_evolution_references_are_not_orphaned(
    db: sqlite3.Connection,
    column: str,
    target_table: str,
) -> None:
    orphan_count = scalar(
        db,
        f"""
        SELECT COUNT(*)
        FROM pokemon_evolution evolution
        WHERE evolution."{column}" IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM "{target_table}" target
              WHERE target.id = evolution."{column}"
          )
        """,
    )

    assert orphan_count == 0


def test_default_pokemon_are_unique_per_species(
    db: sqlite3.Connection,
) -> None:
    duplicates = db.execute(
        """
        SELECT species_id, COUNT(*) AS count
        FROM pokemon
        WHERE is_default = 1
        GROUP BY species_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    assert duplicates == []


def test_pokemon_identifiers_are_unique(
    db: sqlite3.Connection,
) -> None:
    duplicates = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM (
            SELECT identifier
            FROM pokemon
            GROUP BY identifier
            HAVING COUNT(*) > 1
        )
        """,
    )

    assert duplicates == 0


def test_species_identifiers_are_unique(
    db: sqlite3.Connection,
) -> None:
    duplicates = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM (
            SELECT identifier
            FROM pokemon_species
            GROUP BY identifier
            HAVING COUNT(*) > 1
        )
        """,
    )

    assert duplicates == 0


def test_custom_mapping_references_existing_pokeapi_rows(
    db: sqlite3.Connection,
) -> None:
    checks = [
        ("species_id", "pokemon_species"),
        ("pokemon_id", "pokemon"),
        ("pokemon_form_id", "pokemon_forms"),
    ]

    for column, target_table in checks:
        orphan_count = scalar(
            db,
            f"""
            SELECT COUNT(*)
            FROM custom_pokedex_fr custom
            WHERE custom."{column}" IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM "{target_table}" target
                  WHERE target.id = custom."{column}"
              )
            """,
        )

        assert orphan_count == 0, (
            f"{orphan_count} référence(s) orpheline(s) pour {column}"
        )
