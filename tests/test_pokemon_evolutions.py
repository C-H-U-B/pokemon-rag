from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB_PATH = Path("pokemon/corpus/pokemon.db")

# Colonnes de pokemon_evolution qui portent une condition ou une cible
# et qu'on veut comprendre avant de construire get_evolutions().
FIELDS = [
    "evolution_trigger_id",
    "version_group_id",
    "trigger_item_id",
    "minimum_level",
    "gender_id",
    "location_id",
    "held_item_id",
    "time_of_day",
    "known_move_id",
    "known_move_type_id",
    "minimum_happiness",
    "minimum_beauty",
    "minimum_affection",
    "relative_physical_stats",
    "party_species_id",
    "party_type_id",
    "trade_species_id",
    "needs_overworld_rain",
    "turn_upside_down",
    "needs_multiplayer",
    "near_special_rock",
    "region_id",
    "required_pokemon_form_id",
    "evolved_pokemon_form_id",
    "used_move_id",
    "minimum_move_count",
    "minimum_steps",
    "minimum_damage_taken",
    "nature_bitmask",
    "condition_expression",
    "percentage_chance",
]


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone() is not None


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def count_used(conn: sqlite3.Connection, field: str) -> int:
    # Les booléens 0 ne constituent pas une condition active.
    if field in {
        "needs_overworld_rain",
        "turn_upside_down",
        "needs_multiplayer",
        "near_special_rock",
    }:
        sql = f"SELECT COUNT(*) FROM pokemon_evolution WHERE {field} = 1"
    elif field == "time_of_day":
        sql = (
            "SELECT COUNT(*) FROM pokemon_evolution "
            "WHERE time_of_day IS NOT NULL AND TRIM(time_of_day) <> ''"
        )
    else:
        sql = f"SELECT COUNT(*) FROM pokemon_evolution WHERE {field} IS NOT NULL"
    return conn.execute(sql).fetchone()[0]


def distinct_examples(conn: sqlite3.Connection, field: str, limit: int = 8):
    if field in {
        "needs_overworld_rain",
        "turn_upside_down",
        "needs_multiplayer",
        "near_special_rock",
    }:
        where = f"{field} = 1"
    elif field == "time_of_day":
        where = f"{field} IS NOT NULL AND TRIM({field}) <> ''"
    else:
        where = f"{field} IS NOT NULL"

    return [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT {field} FROM pokemon_evolution "
            f"WHERE {where} ORDER BY {field} LIMIT ?",
            (limit,),
        )
    ]


def reference_check(
    conn: sqlite3.Connection,
    field: str,
    target_table: str,
    target_col: str = "id",
) -> tuple[int, int]:
    if not table_exists(conn, target_table):
        return -1, -1

    used = count_used(conn, field)
    missing = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM pokemon_evolution pe
        WHERE pe.{field} IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM "{target_table}" t
              WHERE t."{target_col}" = pe.{field}
          )
        """
    ).fetchone()[0]
    return used, missing


def main() -> None:
    start = time.perf_counter()

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        title("DIAGNOSTIC EXHAUSTIF DE pokemon_evolution")

        evo_cols = columns(conn, "pokemon_evolution")
        missing_fields = [f for f in FIELDS if f not in evo_cols]
        if missing_fields:
            raise RuntimeError(
                "Colonnes attendues absentes de pokemon_evolution : "
                + ", ".join(missing_fields)
            )

        total = conn.execute("SELECT COUNT(*) FROM pokemon_evolution").fetchone()[0]
        species = conn.execute(
            "SELECT COUNT(DISTINCT evolved_species_id) FROM pokemon_evolution"
        ).fetchone()[0]

        print(f"Base                 : {DB_PATH}")
        print(f"Lignes évolution     : {total:,}")
        print(f"Espèces cibles       : {species:,}")

        title("1. UTILISATION DES COLONNES")

        used_fields = []
        unused_fields = []

        for field in FIELDS:
            n = count_used(conn, field)
            examples = distinct_examples(conn, field)
            if n:
                used_fields.append(field)
                sample = ", ".join(repr(x) for x in examples)
                print(f"✓ {field:<30} {n:>5} ligne(s) | exemples: {sample}")
            else:
                unused_fields.append(field)
                print(f"· {field:<30}     0 ligne")

        title("2. TABLES DE RÉFÉRENCE")

        refs = [
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
        ]

        # Ces tables peuvent ne pas faire partie du sous-ensemble CSV téléchargé.
        optional_refs = [
            ("gender_id", "genders"),
            ("location_id", "locations"),
            ("known_move_type_id", "types"),
            ("party_type_id", "types"),
            ("region_id", "regions"),
        ]

        problems = []

        for field, table in refs + optional_refs:
            if not table_exists(conn, table):
                active = count_used(conn, field)
                status = "REQUIS" if active else "non utilisé"
                print(
                    f"⚠ {field:<30} → {table:<22} "
                    f"TABLE ABSENTE | {active} valeur(s) | {status}"
                )
                if active:
                    problems.append((field, table, active, "table absente"))
                continue

            used, missing = reference_check(conn, field, table)
            if missing:
                print(
                    f"✗ {field:<30} → {table:<22} "
                    f"{missing} référence(s) orpheline(s)"
                )
                problems.append((field, table, missing, "orphelines"))
            else:
                print(
                    f"✓ {field:<30} → {table:<22} "
                    f"{used} valeur(s), 0 orpheline"
                )

        title("3. FORMES SOURCE ET CIBLE")

        form_rows = conn.execute(
            """
            SELECT
                pe.id,
                src.identifier AS source_form,
                ps.identifier AS target_species,
                dst.identifier AS target_form,
                pe.region_id,
                pe.version_group_id
            FROM pokemon_evolution pe
            LEFT JOIN pokemon_forms src
              ON src.id = pe.required_pokemon_form_id
            JOIN pokemon_species ps
              ON ps.id = pe.evolved_species_id
            LEFT JOIN pokemon_forms dst
              ON dst.id = pe.evolved_pokemon_form_id
            WHERE pe.required_pokemon_form_id IS NOT NULL
               OR pe.evolved_pokemon_form_id IS NOT NULL
            ORDER BY pe.id
            """
        ).fetchall()

        print(f"Évolutions avec information de forme : {len(form_rows):,}")
        for row in form_rows[:40]:
            print(
                f"  - #{row['id']}: "
                f"{row['source_form'] or '—'} → "
                f"{row['target_form'] or row['target_species']} "
                f"| region_id={row['region_id']} "
                f"| version_group_id={row['version_group_id']}"
            )
        if len(form_rows) > 40:
            print(f"  ... {len(form_rows) - 40} autre(s)")

        title("4. CAS RAICHU")

        raichu = conn.execute(
            """
            SELECT
                pe.id,
                src.identifier AS source_form,
                ps.identifier AS target_species,
                dst.identifier AS target_form,
                et.identifier AS trigger,
                i.identifier AS item,
                vg.identifier AS version_group,
                pe.region_id
            FROM pokemon_evolution pe
            JOIN pokemon_species ps
              ON ps.id = pe.evolved_species_id
            LEFT JOIN pokemon_forms src
              ON src.id = pe.required_pokemon_form_id
            LEFT JOIN pokemon_forms dst
              ON dst.id = pe.evolved_pokemon_form_id
            LEFT JOIN evolution_triggers et
              ON et.id = pe.evolution_trigger_id
            LEFT JOIN items i
              ON i.id = pe.trigger_item_id
            LEFT JOIN version_groups vg
              ON vg.id = pe.version_group_id
            WHERE ps.identifier = 'raichu'
            ORDER BY pe.id
            """
        ).fetchall()

        for row in raichu:
            print(
                f"  - #{row['id']} "
                f"{row['source_form']} → "
                f"{row['target_form'] or row['target_species']} "
                f"| trigger={row['trigger']} "
                f"| item={row['item']} "
                f"| version_group={row['version_group']} "
                f"| region_id={row['region_id']}"
            )

        title("5. COLONNES AVANCÉES À SUPPORTER")

        advanced = [
            "needs_multiplayer",
            "near_special_rock",
            "region_id",
            "required_pokemon_form_id",
            "evolved_pokemon_form_id",
            "used_move_id",
            "minimum_move_count",
            "minimum_steps",
            "minimum_damage_taken",
            "nature_bitmask",
            "condition_expression",
            "percentage_chance",
        ]

        for field in advanced:
            n = count_used(conn, field)
            print(f"{field:<30}: {n:>5} ligne(s)")

        title("RÉSUMÉ")

        print(f"✓ {total:,} lignes d'évolution analysées")
        print(f"✓ {len(used_fields)} colonnes utilisées")
        print(f"· {len(unused_fields)} colonnes actuellement inutilisées")

        if problems:
            print("\n⚠ Références à compléter avant get_evolutions() :")
            for field, table, n, reason in problems:
                print(f"  - {field} → {table}: {n} ({reason})")
        else:
            print("✓ Toutes les tables de référence nécessaires sont présentes.")

        print(f"\nTemps total : {time.perf_counter() - start:.3f} s")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
