from __future__ import annotations

import csv
import re
import sqlite3
import time
from pathlib import Path

from tqdm import tqdm


from pokemon_rag.config import POKEAPI_DB_PATH, POKEAPI_RAW_DIR

RAW_DIR = POKEAPI_RAW_DIR
DB_PATH = POKEAPI_DB_PATH
INSERT_BATCH_SIZE = 20_000

CSV_FILES = [
    "languages.csv",
    "pokemon.csv",
    "pokemon_species.csv",
    "pokemon_species_names.csv",
    "pokemon_forms.csv",
    "pokemon_form_names.csv",
    "moves.csv",
    "move_names.csv",
    "pokemon_move_methods.csv",
    "version_groups.csv",
    "versions.csv",
    "pokemon_moves.csv",
    "evolution_triggers.csv",
    "pokemon_evolution.csv",
    "items.csv",
    "item_names.csv",
    "machines.csv",
    "genders.csv",
    "locations.csv",
    "location_names.csv",
    "types.csv",
    "type_names.csv",
    "regions.csv",
    "region_names.csv",
]

# Colonnes utilisées comme IDs, nombres, niveaux, flags, etc.
# Toutes les autres restent TEXT.
INTEGER_NAMES = {
    "id", "pokemon_id", "species_id", "pokemon_species_id", "pokemon_form_id",
    "move_id", "version_id", "version_group_id", "generation_id",
    "pokemon_move_method_id", "move_damage_class_id", "type_id",
    "evolution_chain_id", "evolution_trigger_id", "evolved_species_id",
    "trigger_item_id", "gender_id", "location_id", "held_item_id",
    "known_move_id", "known_move_type_id", "party_species_id", "party_type_id",
    "trade_species_id", "region_id", "required_pokemon_form_id",
    "evolved_pokemon_form_id", "used_move_id", "item_id",
    "local_language_id", "language_id",
    "level", "order", "priority", "power", "pp", "accuracy", "effect_id",
    "effect_chance", "machine_number", "minimum_level", "minimum_happiness",
    "minimum_beauty", "minimum_affection", "relative_physical_stats",
    "minimum_move_count", "minimum_steps", "minimum_damage_taken",
    "nature_bitmask", "percentage_chance", "height", "weight", "base_experience",
    "sort_order",
    "is_default", "is_battle_only", "is_mega", "form_order",
    "needs_overworld_rain", "turn_upside_down", "needs_multiplayer",
    "near_special_rock",
}


def log(message: str = "") -> None:
    print(message, flush=True)


def sql_identifier(value: str) -> str:
    value = re.sub(r"[^0-9a-zA-Z_]+", "_", value.strip())
    if not value:
        raise ValueError("Identifiant SQL vide.")
    if value[0].isdigit():
        value = "_" + value
    return value


def table_name(filename: str) -> str:
    return sql_identifier(Path(filename).stem)


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return [sql_identifier(c) for c in next(reader)]
        except StopIteration as exc:
            raise RuntimeError(f"CSV vide : {path}") from exc


def column_type(column: str) -> str:
    if column in INTEGER_NAMES or column.endswith("_id"):
        return "INTEGER"
    return "TEXT"


def convert_value(value: str, sql_type: str):
    if value == "":
        return None
    if sql_type == "INTEGER":
        return int(value)
    return value


def import_csv(conn: sqlite3.Connection, path: Path) -> int:
    table = table_name(path.name)
    columns = read_header(path)
    types = [column_type(c) for c in columns]

    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    definition = ", ".join(
        f'"{column}" {sql_type}'
        for column, sql_type in zip(columns, types)
    )
    conn.execute(f'CREATE TABLE "{table}" ({definition})')

    placeholders = ", ".join("?" for _ in columns)
    quoted = ", ".join(f'"{c}"' for c in columns)
    insert_sql = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})'

    count = 0
    batch = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)

        for row in reader:
            if len(row) != len(columns):
                raise RuntimeError(
                    f"{path.name}: {len(row)} colonnes, {len(columns)} attendues."
                )

            batch.append(tuple(
                convert_value(value, sql_type)
                for value, sql_type in zip(row, types)
            ))

            if len(batch) >= INSERT_BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                count += len(batch)
                batch.clear()

        if batch:
            conn.executemany(insert_sql, batch)
            count += len(batch)

    return count


def create_indexes(conn: sqlite3.Connection) -> None:
    statements = [
        "CREATE UNIQUE INDEX idx_languages_id ON languages(id)",
        "CREATE INDEX idx_languages_identifier ON languages(identifier)",

        "CREATE UNIQUE INDEX idx_pokemon_id ON pokemon(id)",
        "CREATE INDEX idx_pokemon_identifier ON pokemon(identifier)",
        "CREATE INDEX idx_pokemon_species ON pokemon(species_id)",

        "CREATE UNIQUE INDEX idx_species_id ON pokemon_species(id)",
        "CREATE INDEX idx_species_identifier ON pokemon_species(identifier)",
        "CREATE INDEX idx_species_parent ON pokemon_species(evolves_from_species_id)",

        """CREATE INDEX idx_species_names_lookup
           ON pokemon_species_names(pokemon_species_id, local_language_id)""",
        "CREATE INDEX idx_species_names_name ON pokemon_species_names(name)",

        "CREATE UNIQUE INDEX idx_moves_id ON moves(id)",
        "CREATE INDEX idx_moves_identifier ON moves(identifier)",
        "CREATE INDEX idx_move_names_lookup ON move_names(move_id, local_language_id)",
        "CREATE INDEX idx_move_names_name ON move_names(name)",

        "CREATE UNIQUE INDEX idx_move_methods_id ON pokemon_move_methods(id)",
        "CREATE INDEX idx_move_methods_identifier ON pokemon_move_methods(identifier)",

        "CREATE UNIQUE INDEX idx_version_groups_id ON version_groups(id)",
        "CREATE INDEX idx_version_groups_identifier ON version_groups(identifier)",
        "CREATE INDEX idx_versions_group ON versions(version_group_id)",

        """CREATE INDEX idx_pokemon_moves_lookup
           ON pokemon_moves(pokemon_id, version_group_id, pokemon_move_method_id, level, move_id)""",
        """CREATE INDEX idx_pokemon_moves_move
           ON pokemon_moves(move_id, pokemon_id, version_group_id, pokemon_move_method_id)""",

        "CREATE INDEX idx_evolution_species ON pokemon_evolution(evolved_species_id)",
        "CREATE INDEX idx_evolution_trigger ON pokemon_evolution(evolution_trigger_id)",

        "CREATE UNIQUE INDEX idx_items_id ON items(id)",
        "CREATE INDEX idx_items_identifier ON items(identifier)",
        "CREATE INDEX idx_item_names_lookup ON item_names(item_id, local_language_id)",

        "CREATE INDEX idx_machines_lookup ON machines(version_group_id, move_id)",
        "CREATE INDEX idx_machines_item ON machines(item_id)",

        "CREATE INDEX idx_forms_pokemon ON pokemon_forms(pokemon_id)",

        "CREATE UNIQUE INDEX idx_genders_id ON genders(id)",
        "CREATE INDEX idx_genders_identifier ON genders(identifier)",

        "CREATE UNIQUE INDEX idx_locations_id ON locations(id)",
        "CREATE INDEX idx_locations_identifier ON locations(identifier)",
        "CREATE INDEX idx_locations_region ON locations(region_id)",
        "CREATE INDEX idx_location_names_lookup ON location_names(location_id, local_language_id)",

        "CREATE UNIQUE INDEX idx_types_id ON types(id)",
        "CREATE INDEX idx_types_identifier ON types(identifier)",
        "CREATE INDEX idx_type_names_lookup ON type_names(type_id, local_language_id)",

        "CREATE UNIQUE INDEX idx_regions_id ON regions(id)",
        "CREATE INDEX idx_regions_identifier ON regions(identifier)",
        "CREATE INDEX idx_region_names_lookup ON region_names(region_id, local_language_id)",
    ]

    for statement in tqdm(
        statements,
        desc="Index SQLite",
        unit="index",
        dynamic_ncols=True,
    ):
        conn.execute(statement)


def create_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS language_ids;
        CREATE VIEW language_ids AS
        SELECT
            MAX(CASE WHEN identifier = 'fr' THEN id END) AS fr,
            MAX(CASE WHEN identifier = 'en' THEN id END) AS en
        FROM languages;

        DROP VIEW IF EXISTS pokemon_display;
        CREATE VIEW pokemon_display AS
        SELECT
            p.id AS pokemon_id,
            p.species_id,
            p.identifier,
            COALESCE(fr.name, en.name, p.identifier) AS name_fr,
            COALESCE(en.name, p.identifier) AS name_en,
            p.is_default
        FROM pokemon p
        LEFT JOIN pokemon_species_names fr
          ON fr.pokemon_species_id = p.species_id
         AND fr.local_language_id = (SELECT fr FROM language_ids)
        LEFT JOIN pokemon_species_names en
          ON en.pokemon_species_id = p.species_id
         AND en.local_language_id = (SELECT en FROM language_ids);

        DROP VIEW IF EXISTS move_display;
        CREATE VIEW move_display AS
        SELECT
            m.id AS move_id,
            m.identifier,
            COALESCE(fr.name, en.name, m.identifier) AS name_fr,
            COALESCE(en.name, m.identifier) AS name_en
        FROM moves m
        LEFT JOIN move_names fr
          ON fr.move_id = m.id
         AND fr.local_language_id = (SELECT fr FROM language_ids)
        LEFT JOIN move_names en
          ON en.move_id = m.id
         AND en.local_language_id = (SELECT en FROM language_ids);

        DROP VIEW IF EXISTS item_display;
        CREATE VIEW item_display AS
        SELECT
            i.id AS item_id,
            i.identifier,
            COALESCE(fr.name, en.name, i.identifier) AS name_fr,
            COALESCE(en.name, i.identifier) AS name_en
        FROM items i
        LEFT JOIN item_names fr
          ON fr.item_id = i.id
         AND fr.local_language_id = (SELECT fr FROM language_ids)
        LEFT JOIN item_names en
          ON en.item_id = i.id
         AND en.local_language_id = (SELECT en FROM language_ids);


        DROP VIEW IF EXISTS location_display;
        CREATE VIEW location_display AS
        SELECT
            l.id AS location_id,
            l.region_id,
            l.identifier,
            COALESCE(fr.name, en.name, l.identifier) AS name_fr,
            COALESCE(en.name, l.identifier) AS name_en
        FROM locations l
        LEFT JOIN location_names fr
          ON fr.location_id = l.id
         AND fr.local_language_id = (SELECT fr FROM language_ids)
        LEFT JOIN location_names en
          ON en.location_id = l.id
         AND en.local_language_id = (SELECT en FROM language_ids);

        DROP VIEW IF EXISTS type_display;
        CREATE VIEW type_display AS
        SELECT
            t.id AS type_id,
            t.identifier,
            COALESCE(fr.name, en.name, t.identifier) AS name_fr,
            COALESCE(en.name, t.identifier) AS name_en
        FROM types t
        LEFT JOIN type_names fr
          ON fr.type_id = t.id
         AND fr.local_language_id = (SELECT fr FROM language_ids)
        LEFT JOIN type_names en
          ON en.type_id = t.id
         AND en.local_language_id = (SELECT en FROM language_ids);

        DROP VIEW IF EXISTS region_display;
        CREATE VIEW region_display AS
        SELECT
            r.id AS region_id,
            r.identifier,
            COALESCE(fr.name, en.name, r.identifier) AS name_fr,
            COALESCE(en.name, r.identifier) AS name_en
        FROM regions r
        LEFT JOIN region_names fr
          ON fr.region_id = r.id
         AND fr.local_language_id = (SELECT fr FROM language_ids)
        LEFT JOIN region_names en
          ON en.region_id = r.id
         AND en.local_language_id = (SELECT en FROM language_ids);
        """
    )


def validate(conn: sqlite3.Connection) -> None:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"PRAGMA integrity_check : {integrity}")

    fr, en = conn.execute("SELECT fr, en FROM language_ids").fetchone()
    if fr is None or en is None:
        raise RuntimeError("Langues FR/EN introuvables.")

    # Vérifie que la grosse table est réellement typée.
    info = {
        row[1]: row[2]
        for row in conn.execute("PRAGMA table_info(pokemon_moves)")
    }
    for column in (
        "pokemon_id", "version_group_id", "move_id",
        "pokemon_move_method_id", "level",
    ):
        if info.get(column) != "INTEGER":
            raise RuntimeError(
                f"pokemon_moves.{column} devrait être INTEGER, obtenu {info.get(column)!r}"
            )


def main() -> None:
    start = time.perf_counter()

    missing = [name for name in CSV_FILES if not (RAW_DIR / name).exists()]
    if missing:
        raise FileNotFoundError(
            "CSV manquants. Lance download_pokeapi.py : " + ", ".join(missing)
        )

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    log("=" * 88)
    log("CONSTRUCTION OPTIMISÉE DE LA BASE SQLITE POKÉAPI")
    log("=" * 88)
    log(f"Source : {RAW_DIR}")
    log(f"Base   : {DB_PATH}")
    log("→ Les IDs/niveaux/flags sont importés directement en INTEGER.")
    log()

    conn = sqlite3.connect(DB_PATH)

    # Optimisations uniquement pendant la construction.
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")

    counts = {}

    try:
        for index, filename in enumerate(CSV_FILES, start=1):
            table = table_name(filename)
            log(f"[{index}/{len(CSV_FILES)}] Import de {filename}...")
            t0 = time.perf_counter()
            count = import_csv(conn, RAW_DIR / filename)
            conn.commit()
            counts[table] = count
            log(f"✓ {table}: {count:,} lignes en {time.perf_counter() - t0:.2f} s")

        log()
        log("→ Création des index...")
        t0 = time.perf_counter()
        create_indexes(conn)
        conn.commit()
        log(f"✓ Index créés en {time.perf_counter() - t0:.2f} s")

        log("→ Création des vues FR/EN...")
        create_views(conn)
        conn.commit()
        log("✓ Vues créées.")

        log("→ ANALYZE...")
        conn.execute("ANALYZE")
        conn.commit()
        log("✓ Statistiques SQLite calculées.")

        log("→ Vérification de la base...")
        validate(conn)
        log("✓ Base valide.")

    finally:
        conn.close()

    elapsed = time.perf_counter() - start
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)

    log()
    log("=" * 88)
    log("BUILD TERMINÉ")
    log("=" * 88)
    log(f"Taille DB   : {size_mb:.2f} MiB")
    log(f"Temps total : {elapsed:.2f} s")
    log("✓ pokeapi.db prête pour les tests.")


if __name__ == "__main__":
    main()
