from __future__ import annotations

import sqlite3
import time
from pathlib import Path


DB_PATH = Path("pokemon/corpus/pokeapi/pokeapi.db")


def log(message: str = "") -> None:
    print(message, flush=True)


def one(conn: sqlite3.Connection, sql: str, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def pokemon_id(conn: sqlite3.Connection, french_name: str) -> int:
    value = one(
        conn,
        """
        SELECT p.id
        FROM pokemon p
        JOIN pokemon_species_names n
          ON n.pokemon_species_id = p.species_id
        WHERE n.local_language_id = (SELECT fr FROM language_ids)
          AND n.name = ?
          AND p.is_default = 1
        LIMIT 1
        """,
        (french_name,),
    )
    if value is None:
        raise LookupError(f"Pokémon introuvable : {french_name}")
    return value


def species_id(conn: sqlite3.Connection, french_name: str) -> int:
    value = one(
        conn,
        """
        SELECT s.id
        FROM pokemon_species s
        JOIN pokemon_species_names n
          ON n.pokemon_species_id = s.id
        WHERE n.local_language_id = (SELECT fr FROM language_ids)
          AND n.name = ?
        LIMIT 1
        """,
        (french_name,),
    )
    if value is None:
        raise LookupError(f"Espèce introuvable : {french_name}")
    return value


def move_id(conn: sqlite3.Connection, french_name: str) -> int:
    value = one(
        conn,
        """
        SELECT m.id
        FROM moves m
        JOIN move_names n ON n.move_id = m.id
        WHERE n.local_language_id = (SELECT fr FROM language_ids)
          AND n.name = ?
        LIMIT 1
        """,
        (french_name,),
    )
    if value is None:
        raise LookupError(f"Capacité introuvable : {french_name}")
    return value


def version_group_id(conn: sqlite3.Connection, identifier: str) -> int:
    value = one(
        conn,
        "SELECT id FROM version_groups WHERE identifier = ? LIMIT 1",
        (identifier,),
    )
    if value is None:
        raise LookupError(f"Version group introuvable : {identifier}")
    return value


def method_id(conn: sqlite3.Connection, identifier: str) -> int:
    value = one(
        conn,
        "SELECT id FROM pokemon_move_methods WHERE identifier = ? LIMIT 1",
        (identifier,),
    )
    if value is None:
        raise LookupError(f"Méthode introuvable : {identifier}")
    return value


def timed_test(title: str, function, conn: sqlite3.Connection):
    log()
    log("=" * 88)
    log(title)
    log("=" * 88)
    log("→ Résolution des identifiants et exécution SQL...")
    start = time.perf_counter()
    rows = function(conn)
    elapsed = time.perf_counter() - start
    log(f"✓ Terminé en {elapsed * 1000:.2f} ms")
    log(f"→ {len(rows)} résultat(s)")

    if not rows:
        log("⚠ Aucun résultat.")
    else:
        for index, row in enumerate(rows, 1):
            log(f"  [{index}/{len(rows)}] {dict(row)}")

    return rows


def electacle(conn: sqlite3.Connection):
    pid = pokemon_id(conn, "Pikachu")
    mid = move_id(conn, "Électacle")

    return conn.execute(
        """
        SELECT DISTINCT
            pd.name_fr AS pokemon,
            md.name_fr AS capacite,
            pmm.identifier AS methode,
            vg.identifier AS version_group,
            pm.level AS niveau
        FROM pokemon_moves pm
        JOIN pokemon_display pd ON pd.pokemon_id = pm.pokemon_id
        JOIN move_display md ON md.move_id = pm.move_id
        JOIN pokemon_move_methods pmm ON pmm.id = pm.pokemon_move_method_id
        JOIN version_groups vg ON vg.id = pm.version_group_id
        WHERE pm.pokemon_id = ?
          AND pm.move_id = ?
        ORDER BY pm.version_group_id, pm.pokemon_move_method_id, pm.level
        """,
        (pid, mid),
    ).fetchall()


def ct_ev(conn: sqlite3.Connection):
    pid = pokemon_id(conn, "Pikachu")
    vgid = version_group_id(conn, "scarlet-violet")
    machine_method = method_id(conn, "machine")

    return conn.execute(
        """
        SELECT DISTINCT
            pd.name_fr AS pokemon,
            md.name_fr AS capacite,
            vg.identifier AS version_group,
            ma.machine_number AS numero_machine,
            it.name_fr AS objet_machine
        FROM pokemon_moves pm
        JOIN pokemon_display pd ON pd.pokemon_id = pm.pokemon_id
        JOIN move_display md ON md.move_id = pm.move_id
        JOIN version_groups vg ON vg.id = pm.version_group_id
        LEFT JOIN machines ma
          ON ma.move_id = pm.move_id
         AND ma.version_group_id = pm.version_group_id
        LEFT JOIN item_display it ON it.item_id = ma.item_id
        WHERE pm.pokemon_id = ?
          AND pm.version_group_id = ?
          AND pm.pokemon_move_method_id = ?
        ORDER BY ma.machine_number, md.name_fr
        """,
        (pid, vgid, machine_method),
    ).fetchall()


def pikachu_evolution(conn: sqlite3.Connection):
    sid = species_id(conn, "Pikachu")

    return conn.execute(
        """
        SELECT
            src_name.name AS depuis,
            dst_name.name AS vers,
            et.identifier AS declencheur,
            pe.minimum_level AS niveau_minimum,
            trigger_item.name_fr AS objet_declencheur,
            held_item.name_fr AS objet_tenu,
            known_move.name_fr AS capacite_connue,
            pe.time_of_day AS moment,
            pe.minimum_happiness AS bonheur_minimum,
            pe.condition_expression
        FROM pokemon_species dst
        JOIN pokemon_species_names dst_name
          ON dst_name.pokemon_species_id = dst.id
         AND dst_name.local_language_id = (SELECT fr FROM language_ids)
        JOIN pokemon_species_names src_name
          ON src_name.pokemon_species_id = ?
         AND src_name.local_language_id = (SELECT fr FROM language_ids)
        LEFT JOIN pokemon_evolution pe
          ON pe.evolved_species_id = dst.id
        LEFT JOIN evolution_triggers et
          ON et.id = pe.evolution_trigger_id
        LEFT JOIN item_display trigger_item
          ON trigger_item.item_id = pe.trigger_item_id
        LEFT JOIN item_display held_item
          ON held_item.item_id = pe.held_item_id
        LEFT JOIN move_display known_move
          ON known_move.move_id = pe.known_move_id
        WHERE dst.evolves_from_species_id = ?
        ORDER BY dst.id, pe.id
        """,
        (sid, sid),
    ).fetchall()


def roitiflam_level(conn: sqlite3.Connection):
    pid = pokemon_id(conn, "Roitiflam")
    level_method = method_id(conn, "level-up")

    return conn.execute(
        """
        SELECT DISTINCT
            pd.name_fr AS pokemon,
            md.name_fr AS capacite,
            pm.level AS niveau,
            vg.identifier AS version_group
        FROM pokemon_moves pm
        JOIN pokemon_display pd ON pd.pokemon_id = pm.pokemon_id
        JOIN move_display md ON md.move_id = pm.move_id
        JOIN version_groups vg ON vg.id = pm.version_group_id
        WHERE pm.pokemon_id = ?
          AND pm.pokemon_move_method_id = ?
          AND pm.level > 40
        ORDER BY pm.version_group_id, pm.level, md.name_fr
        """,
        (pid, level_method),
    ).fetchall()


def show_query_plan(conn: sqlite3.Connection) -> None:
    pid = pokemon_id(conn, "Pikachu")
    mid = move_id(conn, "Électacle")
    rows = conn.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT *
        FROM pokemon_moves
        WHERE pokemon_id = ? AND move_id = ?
        """,
        (pid, mid),
    ).fetchall()

    log("→ Plan SQLite de contrôle :")
    for row in rows:
        log(f"  {tuple(row)}")


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} introuvable. Lance d'abord build_pokeapi_db.py."
        )

    total_start = time.perf_counter()

    log("=" * 88)
    log("TESTS SQLITE POKÉAPI — VERSION OPTIMISÉE")
    log("=" * 88)
    log(f"Base : {DB_PATH}")
    log("→ Ouverture SQLite...")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Réglages lecture locale.
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA cache_size=-100000")
    conn.execute("PRAGMA temp_store=MEMORY")

    try:
        log("✓ Base ouverte.")
        show_query_plan(conn)

        tests = [
            ("1/4 — Comment Pikachu peut-il apprendre Électacle ?", electacle),
            ("2/4 — Capacités de Pikachu par machine dans Écarlate/Violet", ct_ev),
            ("3/4 — En quoi Pikachu évolue-t-il et sous quelles conditions ?", pikachu_evolution),
            ("4/4 — Capacités apprises par Roitiflam après le niveau 40", roitiflam_level),
        ]

        for title, function in tests:
            timed_test("TEST " + title, function, conn)

    finally:
        log()
        log("→ Fermeture SQLite...")
        conn.close()
        log("✓ Base fermée.")

    elapsed = time.perf_counter() - total_start
    log()
    log("=" * 88)
    log(f"✓ TESTS TERMINÉS — {elapsed:.3f} s")
    log("=" * 88)


if __name__ == "__main__":
    main()
