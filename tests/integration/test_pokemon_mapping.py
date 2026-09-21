from __future__ import annotations

import sqlite3

import pytest

from pokemon_rag.config import DB_PATH


EXPECTED_NATIONAL_DEX = 1025
VALID_MAPPING_STATUSES = {"EXACT", "SPECIES_ONLY"}


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


def test_national_dex_species_exist_in_pokeapi(
    db: sqlite3.Connection,
) -> None:
    count = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM pokemon_species
        WHERE id BETWEEN 1 AND ?
        """,
        (EXPECTED_NATIONAL_DEX,),
    )

    assert count == EXPECTED_NATIONAL_DEX


def test_national_dex_species_are_all_represented_in_custom_pokedex(
    db: sqlite3.Connection,
) -> None:
    count = scalar(
        db,
        """
        SELECT COUNT(DISTINCT species_id)
        FROM custom_pokedex_fr
        WHERE species_id BETWEEN 1 AND ?
        """,
        (EXPECTED_NATIONAL_DEX,),
    )

    assert count == EXPECTED_NATIONAL_DEX


def test_national_dex_species_have_default_pokemon(
    db: sqlite3.Connection,
) -> None:
    missing = db.execute(
        """
        SELECT species.id, species.identifier
        FROM pokemon_species species
        WHERE species.id BETWEEN 1 AND ?
          AND NOT EXISTS (
              SELECT 1
              FROM pokemon p
              WHERE p.species_id = species.id
                AND p.is_default = 1
          )
        ORDER BY species.id
        """,
        (EXPECTED_NATIONAL_DEX,),
    ).fetchall()

    assert missing == []


def test_national_dex_species_have_at_least_one_pokemon_mapping(
    db: sqlite3.Connection,
) -> None:
    missing = db.execute(
        """
        SELECT species_id
        FROM custom_pokedex_fr
        WHERE species_id BETWEEN 1 AND ?
        GROUP BY species_id
        HAVING SUM(CASE WHEN pokemon_id IS NOT NULL THEN 1 ELSE 0 END) = 0
        ORDER BY species_id
        """,
        (EXPECTED_NATIONAL_DEX,),
    ).fetchall()

    assert missing == []


def test_plain_entries_have_pokemon_mapping(
    db: sqlite3.Connection,
) -> None:
    unmapped = db.execute(
        """
        SELECT source_row, numero, nom, species_id
        FROM custom_pokedex_fr
        WHERE species_id BETWEEN 1 AND ?
          AND (forme IS NULL OR TRIM(CAST(forme AS TEXT)) = '')
          AND pokemon_id IS NULL
        ORDER BY species_id, source_row
        """,
        (EXPECTED_NATIONAL_DEX,),
    ).fetchall()

    assert unmapped == []


@pytest.mark.parametrize(
    ("column", "target_table"),
    [
        ("species_id", "pokemon_species"),
        ("pokemon_id", "pokemon"),
        ("pokemon_form_id", "pokemon_forms"),
    ],
    ids=["species", "pokemon", "form"],
)
def test_mapping_ids_reference_existing_pokeapi_rows(
    db: sqlite3.Connection,
    column: str,
    target_table: str,
) -> None:
    invalid = scalar(
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

    assert invalid == 0


def test_mapped_pokemon_belongs_to_mapped_species(
    db: sqlite3.Connection,
) -> None:
    inconsistent = db.execute(
        """
        SELECT
            custom.source_row,
            custom.species_id AS mapped_species_id,
            custom.pokemon_id,
            pokemon.species_id AS pokemon_species_id
        FROM custom_pokedex_fr custom
        JOIN pokemon
          ON pokemon.id = custom.pokemon_id
        WHERE custom.species_id IS NOT NULL
          AND pokemon.species_id <> custom.species_id
        ORDER BY custom.source_row
        """
    ).fetchall()

    assert inconsistent == []


def test_mapped_form_belongs_to_mapped_pokemon(
    db: sqlite3.Connection,
) -> None:
    inconsistent = db.execute(
        """
        SELECT
            custom.source_row,
            custom.pokemon_id,
            custom.pokemon_form_id,
            form.pokemon_id AS form_pokemon_id
        FROM custom_pokedex_fr custom
        JOIN pokemon_forms form
          ON form.id = custom.pokemon_form_id
        WHERE custom.pokemon_id IS NOT NULL
          AND form.pokemon_id <> custom.pokemon_id
        ORDER BY custom.source_row
        """
    ).fetchall()

    assert inconsistent == []


def test_exact_mappings_have_complete_pokeapi_ids(
    db: sqlite3.Connection,
) -> None:
    incomplete = db.execute(
        """
        SELECT source_row, numero, nom, forme
        FROM custom_pokedex_fr
        WHERE pokeapi_mapping_status = 'EXACT'
          AND (
              species_id IS NULL
              OR pokemon_id IS NULL
              OR pokemon_form_id IS NULL
          )
        ORDER BY source_row
        """
    ).fetchall()

    assert incomplete == []


def test_species_only_mappings_have_species_but_no_exact_pokemon(
    db: sqlite3.Connection,
) -> None:
    inconsistent = db.execute(
        """
        SELECT
            source_row,
            numero,
            nom,
            forme,
            species_id,
            pokemon_id,
            pokemon_form_id
        FROM custom_pokedex_fr
        WHERE pokeapi_mapping_status = 'SPECIES_ONLY'
          AND (
              species_id IS NULL
              OR pokemon_id IS NOT NULL
              OR pokemon_form_id IS NOT NULL
          )
        ORDER BY source_row
        """
    ).fetchall()

    assert inconsistent == []


def test_mapping_status_values_are_known(
    db: sqlite3.Connection,
) -> None:
    statuses = {
        row[0]
        for row in db.execute(
            """
            SELECT DISTINCT pokeapi_mapping_status
            FROM custom_pokedex_fr
            WHERE pokeapi_mapping_status IS NOT NULL
            """
        )
    }

    assert statuses <= VALID_MAPPING_STATUSES


def test_fr_and_en_mapping_columns_match_by_source_row(
    db: sqlite3.Connection,
) -> None:
    inconsistent = db.execute(
        """
        SELECT fr.source_row
        FROM custom_pokedex_fr fr
        JOIN custom_pokedex_en en
          ON en.source_row = fr.source_row
        WHERE NOT (
            fr.species_id IS en.species_id
            AND fr.pokemon_id IS en.pokemon_id
            AND fr.pokemon_form_id IS en.pokemon_form_id
            AND fr.pokeapi_pokemon_identifier IS en.pokeapi_pokemon_identifier
            AND fr.pokeapi_form_identifier IS en.pokeapi_form_identifier
            AND fr.pokeapi_is_default IS en.pokeapi_is_default
            AND fr.pokeapi_mapping_status IS en.pokeapi_mapping_status
        )
        ORDER BY fr.source_row
        """
    ).fetchall()

    assert inconsistent == []


def test_fr_and_en_have_same_source_rows(
    db: sqlite3.Connection,
) -> None:
    missing_counterparts = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM (
            SELECT source_row FROM custom_pokedex_fr
            EXCEPT
            SELECT source_row FROM custom_pokedex_en

            UNION ALL

            SELECT source_row FROM custom_pokedex_en
            EXCEPT
            SELECT source_row FROM custom_pokedex_fr
        )
        """,
    )

    assert missing_counterparts == 0


def test_pokemon_identifier_matches_pokeapi(
    db: sqlite3.Connection,
) -> None:
    inconsistent = db.execute(
        """
        SELECT
            custom.source_row,
            custom.pokemon_id,
            custom.pokeapi_pokemon_identifier,
            pokemon.identifier AS expected_identifier
        FROM custom_pokedex_fr custom
        JOIN pokemon
          ON pokemon.id = custom.pokemon_id
        WHERE custom.pokeapi_pokemon_identifier IS NULL
           OR custom.pokeapi_pokemon_identifier <> pokemon.identifier
        ORDER BY custom.source_row
        """
    ).fetchall()

    assert inconsistent == []


def test_form_identifier_matches_pokeapi(
    db: sqlite3.Connection,
) -> None:
    inconsistent = db.execute(
        """
        SELECT
            custom.source_row,
            custom.pokemon_form_id,
            custom.pokeapi_form_identifier,
            form.identifier AS expected_identifier
        FROM custom_pokedex_fr custom
        JOIN pokemon_forms form
          ON form.id = custom.pokemon_form_id
        WHERE custom.pokeapi_form_identifier IS NULL
           OR custom.pokeapi_form_identifier <> form.identifier
        ORDER BY custom.source_row
        """
    ).fetchall()

    assert inconsistent == []


def test_is_default_matches_pokeapi(
    db: sqlite3.Connection,
) -> None:
    inconsistent = db.execute(
        """
        SELECT
            custom.source_row,
            custom.pokemon_id,
            custom.pokeapi_is_default,
            pokemon.is_default AS expected_is_default
        FROM custom_pokedex_fr custom
        JOIN pokemon
          ON pokemon.id = custom.pokemon_id
        WHERE custom.pokeapi_is_default IS NULL
           OR CAST(custom.pokeapi_is_default AS INTEGER) <> pokemon.is_default
        ORDER BY custom.source_row
        """
    ).fetchall()

    assert inconsistent == []
