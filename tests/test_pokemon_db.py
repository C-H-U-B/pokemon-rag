from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB_PATH = Path("pokemon/corpus/pokemon.db")


def title(text: str) -> None:
    print("\n" + "=" * 96, flush=True)
    print(text, flush=True)
    print("=" * 96, flush=True)


def rows(conn: sqlite3.Connection, sql: str, params=()):
    return conn.execute(sql, params).fetchall()


def scalar(conn: sqlite3.Connection, sql: str, params=()):
    return conn.execute(sql, params).fetchone()[0]


def timed_query(conn, label, sql, params=()):
    print(f"\n→ {label}", flush=True)
    start = time.perf_counter()
    result = rows(conn, sql, params)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"✓ {len(result)} résultat(s) en {elapsed:.2f} ms", flush=True)
    return result, elapsed


def print_rows(result, columns=None, limit=20):
    if not result:
        print("  Aucun résultat.", flush=True)
        return
    shown = result[:limit]
    if columns is None:
        columns = shown[0].keys()
    for row in shown:
        values = [f"{col}={row[col]!r}" for col in columns]
        print("  - " + " | ".join(values), flush=True)
    if len(result) > limit:
        print(f"  ... {len(result) - limit} résultat(s) supplémentaire(s)", flush=True)


def main() -> None:
    global_start = time.perf_counter()

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}")

    print(f"Base : {DB_PATH}", flush=True)
    print(f"Taille : {DB_PATH.stat().st_size / 1024 / 1024:.2f} MiB", flush=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        title("1. INTÉGRITÉ ET SOURCES")

        integrity = scalar(conn, "PRAGMA integrity_check")
        print(f"PRAGMA integrity_check : {integrity}", flush=True)
        if integrity != "ok":
            raise RuntimeError(f"Base SQLite invalide : {integrity}")

        expected = [
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
        ]
        objects = {
            row["name"]
            for row in rows(
                conn,
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        missing = [name for name in expected if name not in objects]
        if missing:
            raise RuntimeError("Objets SQLite manquants : " + ", ".join(missing))
        print("✓ Tables/vues principales présentes.", flush=True)

        fr = scalar(conn, "SELECT COUNT(*) FROM custom_pokedex_fr")
        en = scalar(conn, "SELECT COUNT(*) FROM custom_pokedex_en")
        species = scalar(
            conn,
            "SELECT COUNT(DISTINCT species_id) FROM custom_pokedex_fr"
        )
        exact = scalar(
            conn,
            "SELECT COUNT(*) FROM custom_pokedex_fr "
            "WHERE pokeapi_mapping_status='EXACT'"
        )
        species_only = scalar(
            conn,
            "SELECT COUNT(*) FROM custom_pokedex_fr "
            "WHERE pokeapi_mapping_status='SPECIES_ONLY'"
        )
        print(
            f"✓ Spreadsheet : FR={fr:,}, EN={en:,}, "
            f"espèces={species:,}, EXACT={exact:,}, SPECIES_ONLY={species_only:,}",
            flush=True,
        )

        title("2. SPREADSHEET — PIKACHU")

        result, _ = timed_query(
            conn,
            "Lecture de Pikachu dans la vue bilingue",
            """
            SELECT
                national_number, name_fr, name_en, form_fr,
                species_id, pokemon_id, pokemon_form_id,
                pokemon_identifier, mapping_status,
                type_1_fr, type_2_fr,
                evolution_summary_fr,
                signature_move_fr,
                signature_ability_fr,
                pseudo_signature_move_fr,
                subgroup_fr,
                summary_fr
            FROM custom_pokedex
            WHERE species_id = 25
            ORDER BY source_row
            """,
        )
        print_rows(result)

        title("3. POKÉAPI — ROITIFLAM : CAPACITÉS PAR NIVEAU > 40")

        result, _ = timed_query(
            conn,
            "Learnset de Roitiflam après le niveau 40",
            """
            SELECT
                pd.name_fr AS pokemon,
                md.name_fr AS move,
                pm.level,
                vg.identifier AS version_group,
                pmm.identifier AS method
            FROM pokemon_moves pm
            JOIN pokemon_display pd ON pd.pokemon_id = pm.pokemon_id
            JOIN move_display md ON md.move_id = pm.move_id
            JOIN version_groups vg ON vg.id = pm.version_group_id
            JOIN pokemon_move_methods pmm ON pmm.id = pm.pokemon_move_method_id
            WHERE pm.pokemon_id = (
                SELECT id FROM pokemon WHERE identifier = 'emboar' LIMIT 1
            )
              AND pmm.identifier = 'level-up'
              AND pm.level > 40
            ORDER BY vg.id, pm.level, md.name_fr
            """,
        )
        print_rows(result, ["pokemon", "move", "level", "version_group", "method"], 40)

        title("4. POKÉAPI — PIKACHU : MACHINES DANS SCARLET/VIOLET")

        result, _ = timed_query(
            conn,
            "Machines de Pikachu dans Scarlet/Violet",
            """
            SELECT DISTINCT
                pd.name_fr AS pokemon,
                md.name_fr AS move,
                i.identifier AS machine_item,
                vg.identifier AS version_group
            FROM pokemon_moves pm
            JOIN pokemon_display pd ON pd.pokemon_id = pm.pokemon_id
            JOIN move_display md ON md.move_id = pm.move_id
            JOIN pokemon_move_methods pmm ON pmm.id = pm.pokemon_move_method_id
            JOIN version_groups vg ON vg.id = pm.version_group_id
            LEFT JOIN machines ma
              ON ma.move_id = pm.move_id
             AND ma.version_group_id = pm.version_group_id
            LEFT JOIN items i ON i.id = ma.item_id
            WHERE pm.pokemon_id = (
                SELECT id FROM pokemon WHERE identifier = 'pikachu' LIMIT 1
            )
              AND pmm.identifier = 'machine'
              AND vg.identifier = 'scarlet-violet'
            ORDER BY md.name_fr
            """,
        )
        print_rows(result, ["pokemon", "move", "machine_item", "version_group"], 60)

        title("5. ÉVOLUTION — PIKACHU → RAICHU (LIGNES BRUTES)")

        result, _ = timed_query(
            conn,
            "Conditions d'évolution vers Raichu",
            """
            SELECT
                pe.id AS evolution_row_id,
                ps_from.identifier AS from_species,
                ps_to.identifier AS to_species,
                et.identifier AS trigger,
                idis.name_fr AS trigger_item_fr,
                pe.minimum_level,
                pe.minimum_happiness,
                pe.minimum_beauty,
                pe.minimum_affection,
                pe.gender_id,
                pe.location_id,
                pe.time_of_day,
                pe.needs_overworld_rain,
                pe.turn_upside_down
            FROM pokemon_evolution pe
            JOIN pokemon_species ps_to
              ON ps_to.id = pe.evolved_species_id
            LEFT JOIN pokemon_species ps_from
              ON ps_from.id = ps_to.evolves_from_species_id
            LEFT JOIN evolution_triggers et
              ON et.id = pe.evolution_trigger_id
            LEFT JOIN item_display idis
              ON idis.item_id = pe.trigger_item_id
            WHERE ps_to.identifier = 'raichu'
            ORDER BY pe.id
            """,
        )
        print_rows(result)

        if len(result) > 1:
            print(
                "\nℹ Plusieurs lignes brutes existent pour Raichu : "
                "elles sont volontairement affichées sans DISTINCT.",
                flush=True,
            )

        title("6. JOINTURE UNIFIÉE — SPREADSHEET + POKÉAPI")

        result, _ = timed_query(
            conn,
            "Pikachu : particularités éditoriales + learnset Scarlet/Violet",
            """
            SELECT DISTINCT
                cp.name_fr,
                cp.form_fr,
                cp.pokemon_id,
                cp.mapping_status,
                cp.signature_move_fr,
                cp.signature_ability_fr,
                cp.subgroup_fr,
                md.name_fr AS move,
                pmm.identifier AS method,
                pm.level,
                vg.identifier AS version_group
            FROM custom_pokedex cp
            JOIN pokemon_moves pm
              ON pm.pokemon_id = cp.pokemon_id
            JOIN move_display md
              ON md.move_id = pm.move_id
            JOIN pokemon_move_methods pmm
              ON pmm.id = pm.pokemon_move_method_id
            JOIN version_groups vg
              ON vg.id = pm.version_group_id
            WHERE cp.species_id = 25
              AND cp.pokemon_id IS NOT NULL
              AND vg.identifier = 'scarlet-violet'
            ORDER BY method, pm.level, move
            """,
        )
        print_rows(
            result,
            [
                "name_fr", "form_fr", "pokemon_id", "mapping_status",
                "signature_move_fr", "signature_ability_fr",
                "subgroup_fr", "move", "method", "level"
            ],
            30,
        )

        title("7. JOINTURE DE FORME — DEOXYS")

        result, _ = timed_query(
            conn,
            "Mapping précis des formes de Deoxys",
            """
            SELECT
                cp.name_fr,
                cp.form_fr,
                cp.species_id,
                cp.pokemon_id,
                cp.pokemon_form_id,
                cp.pokemon_identifier,
                cp.form_identifier,
                cp.is_default,
                cp.mapping_status,
                p.identifier AS pokemon_identifier_db,
                pf.identifier AS form_identifier_db,
                pf.form_identifier AS form_suffix_db
            FROM custom_pokedex cp
            LEFT JOIN pokemon p
              ON p.id = cp.pokemon_id
            LEFT JOIN pokemon_forms pf
              ON pf.id = cp.pokemon_form_id
            WHERE cp.species_id = 386
            ORDER BY cp.source_row
            """,
        )
        print_rows(result)

        title("8. EXCEPTIONS SPECIES_ONLY")

        result, _ = timed_query(
            conn,
            "Lignes sans pokemon_id exact",
            """
            SELECT
                source_row, numero, nom, forme,
                species_id, pokemon_id, pokemon_form_id,
                pokeapi_mapping_status
            FROM custom_pokedex_fr
            WHERE pokeapi_mapping_status <> 'EXACT'
               OR pokemon_id IS NULL
            ORDER BY species_id, source_row
            """,
        )
        print_rows(result, limit=50)

        title("9. PLAN D'EXÉCUTION D'UNE JOINTURE STRUCTURED")

        plan = rows(
            conn,
            """
            EXPLAIN QUERY PLAN
            SELECT md.name_fr, pm.level
            FROM custom_pokedex cp
            JOIN pokemon_moves pm ON pm.pokemon_id = cp.pokemon_id
            JOIN move_display md ON md.move_id = pm.move_id
            WHERE cp.species_id = 25
              AND pm.version_group_id = (
                  SELECT id FROM version_groups
                  WHERE identifier = 'scarlet-violet'
              )
            """,
        )
        for row in plan:
            print("  - " + str(tuple(row)), flush=True)

        title("RÉSUMÉ")
        print("✓ Intégrité SQLite OK", flush=True)
        print(f"✓ {species:,} espèces distinctes dans le spreadsheet", flush=True)
        print(f"✓ {exact:,} mappings EXACT", flush=True)
        print(f"✓ {species_only:,} mappings SPECIES_ONLY", flush=True)
        print("✓ Requêtes PokéAPI exécutées", flush=True)
        print("✓ Jointure spreadsheet ↔ PokéAPI exécutée", flush=True)
        print("✓ Test de mapping de formes exécuté", flush=True)
        print(
            f"✓ Temps total : {time.perf_counter() - global_start:.3f} s",
            flush=True,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
