from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB_PATH = Path("pokemon/corpus/pokemon.db")
EXPECTED_NATIONAL_DEX = 1025


def title(text: str) -> None:
    print("\n" + "=" * 92, flush=True)
    print(text, flush=True)
    print("=" * 92, flush=True)


def scalar(conn: sqlite3.Connection, sql: str, params=()):
    return conn.execute(sql, params).fetchone()[0]


def main() -> None:
    start = time.perf_counter()

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}")

    print(f"Base : {DB_PATH}", flush=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        title("DIAGNOSTIC DU MAPPING SPREADSHEET ↔ POKÉAPI")

        total = scalar(conn, "SELECT COUNT(*) FROM custom_pokedex_fr")
        distinct_species = scalar(
            conn,
            "SELECT COUNT(DISTINCT species_id) FROM custom_pokedex_fr "
            "WHERE species_id IS NOT NULL",
        )
        no_form = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM custom_pokedex_fr
            WHERE forme IS NULL OR TRIM(CAST(forme AS TEXT)) = ''
            """,
        )
        no_form_mapped = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM custom_pokedex_fr
            WHERE (forme IS NULL OR TRIM(CAST(forme AS TEXT)) = '')
              AND pokemon_id IS NOT NULL
            """,
        )
        with_form = total - no_form
        mapped = scalar(
            conn,
            "SELECT COUNT(*) FROM custom_pokedex_fr WHERE pokemon_id IS NOT NULL",
        )
        distinct_mapped = scalar(
            conn,
            "SELECT COUNT(DISTINCT pokemon_id) FROM custom_pokedex_fr "
            "WHERE pokemon_id IS NOT NULL",
        )

        print(f"Entrées spreadsheet                  : {total:,}", flush=True)
        print(f"species_id DISTINCT                  : {distinct_species:,}", flush=True)
        print(f"Entrées sans forme                   : {no_form:,}", flush=True)
        print(f"  ↳ avec pokemon_id                  : {no_form_mapped:,}", flush=True)
        print(f"  ↳ sans pokemon_id                  : {no_form - no_form_mapped:,}", flush=True)
        print(f"Entrées avec forme                   : {with_form:,}", flush=True)
        print(f"Entrées avec pokemon_id (total)      : {mapped:,}", flush=True)
        print(f"pokemon_id DISTINCT mappés           : {distinct_mapped:,}", flush=True)

        title("CONTRÔLE DES 1 025 ESPÈCES DU POKÉDEX NATIONAL")

        pokeapi_species = scalar(
            conn,
            "SELECT COUNT(*) FROM pokemon_species WHERE id BETWEEN 1 AND ?",
            (EXPECTED_NATIONAL_DEX,),
        )
        default_pokemon = scalar(
            conn,
            """
            SELECT COUNT(DISTINCT p.species_id)
            FROM pokemon p
            WHERE p.species_id BETWEEN 1 AND ?
              AND p.is_default = 1
            """,
            (EXPECTED_NATIONAL_DEX,),
        )
        represented = scalar(
            conn,
            """
            SELECT COUNT(DISTINCT species_id)
            FROM custom_pokedex_fr
            WHERE species_id BETWEEN 1 AND ?
            """,
            (EXPECTED_NATIONAL_DEX,),
        )
        represented_with_mapping = scalar(
            conn,
            """
            SELECT COUNT(DISTINCT species_id)
            FROM custom_pokedex_fr
            WHERE species_id BETWEEN 1 AND ?
              AND pokemon_id IS NOT NULL
            """,
            (EXPECTED_NATIONAL_DEX,),
        )

        print(f"Espèces 1–1025 présentes dans PokéAPI       : {pokeapi_species:,}", flush=True)
        print(f"Espèces 1–1025 avec Pokémon default PokéAPI  : {default_pokemon:,}", flush=True)
        print(f"Espèces 1–1025 présentes dans le spreadsheet : {represented:,}", flush=True)
        print(f"Espèces 1–1025 avec au moins un pokemon_id    : {represented_with_mapping:,}", flush=True)

        missing = conn.execute(
            """
            SELECT
                fr.species_id,
                MIN(fr.numero) AS numero,
                MIN(fr.nom) AS nom,
                GROUP_CONCAT(
                    CASE
                        WHEN fr.forme IS NULL OR TRIM(CAST(fr.forme AS TEXT)) = ''
                        THEN '[vide]'
                        ELSE CAST(fr.forme AS TEXT)
                    END,
                    ' | '
                ) AS formes,
                COUNT(*) AS nb_entrees
            FROM custom_pokedex_fr fr
            WHERE fr.species_id BETWEEN 1 AND ?
            GROUP BY fr.species_id
            HAVING SUM(CASE WHEN fr.pokemon_id IS NOT NULL THEN 1 ELSE 0 END) = 0
            ORDER BY fr.species_id
            """,
            (EXPECTED_NATIONAL_DEX,),
        ).fetchall()

        print(f"\nEspèces 1–1025 sans aucun pokemon_id : {len(missing)}", flush=True)

        if missing:
            print("\nID    N°    Nom                         Forme(s)", flush=True)
            print("-" * 92, flush=True)
            for row in missing:
                print(
                    f"{row['species_id']:<5} "
                    f"{str(row['numero']):<5} "
                    f"{str(row['nom'])[:27]:<27} "
                    f"{row['formes']}",
                    flush=True,
                )
        else:
            print("✓ Toutes les espèces 1–1025 ont un pokemon_id.", flush=True)

        title("ENTRÉES SANS FORME QUI N'ONT PAS ÉTÉ MAPPÉES")

        unmapped_plain = conn.execute(
            """
            SELECT numero, nom, forme, species_id
            FROM custom_pokedex_fr
            WHERE species_id BETWEEN 1 AND ?
              AND (forme IS NULL OR TRIM(CAST(forme AS TEXT)) = '')
              AND pokemon_id IS NULL
            ORDER BY species_id
            """,
            (EXPECTED_NATIONAL_DEX,),
        ).fetchall()

        print(f"Nombre : {len(unmapped_plain)}", flush=True)
        for row in unmapped_plain:
            print(
                f"- #{row['numero']} {row['nom']} "
                f"(species_id={row['species_id']})",
                flush=True,
            )

        title("ESPÈCES DONT TOUTES LES ENTRÉES ONT UNE FORME RENSEIGNÉE")

        only_named_forms = conn.execute(
            """
            SELECT
                species_id,
                MIN(numero) AS numero,
                MIN(nom) AS nom,
                GROUP_CONCAT(CAST(forme AS TEXT), ' | ') AS formes
            FROM custom_pokedex_fr
            WHERE species_id BETWEEN 1 AND ?
            GROUP BY species_id
            HAVING SUM(
                CASE
                    WHEN forme IS NULL OR TRIM(CAST(forme AS TEXT)) = ''
                    THEN 1 ELSE 0
                END
            ) = 0
            ORDER BY species_id
            """,
            (EXPECTED_NATIONAL_DEX,),
        ).fetchall()

        print(f"Nombre : {len(only_named_forms)}", flush=True)
        for row in only_named_forms:
            print(
                f"- #{row['numero']} {row['nom']} → {row['formes']}",
                flush=True,
            )

        title("DIAGNOSTIC")

        if pokeapi_species != EXPECTED_NATIONAL_DEX:
            print(
                f"⚠ La DB PokéAPI contient {pokeapi_species} espèces sur les "
                f"{EXPECTED_NATIONAL_DEX} attendues dans l'intervalle 1–1025.",
                flush=True,
            )
        else:
            print("✓ Les 1 025 species_id existent dans PokéAPI.", flush=True)

        if default_pokemon != EXPECTED_NATIONAL_DEX:
            print(
                f"⚠ Seulement {default_pokemon} espèces ont un pokemon is_default=1.",
                flush=True,
            )
        else:
            print("✓ Les 1 025 espèces ont un Pokémon default dans PokéAPI.", flush=True)

        if represented != EXPECTED_NATIONAL_DEX:
            print(
                f"⚠ Le spreadsheet représente seulement {represented} species_id "
                f"distincts parmi 1–1025.",
                flush=True,
            )
        else:
            print("✓ Le spreadsheet représente les 1 025 espèces.", flush=True)

        if unmapped_plain:
            print(
                "⚠ Certaines lignes sans forme n'ont pas été mappées : "
                "le problème ne vient donc pas seulement des formes.",
                flush=True,
            )
        elif missing and only_named_forms:
            print(
                "→ Les espèces manquantes semblent provenir de la règle "
                "\"forme vide uniquement\" du build.",
                flush=True,
            )
        elif not missing:
            print("✓ Aucun Pokémon standard 1–1025 ne manque.", flush=True)

        print(
            f"\nTemps total : {time.perf_counter() - start:.3f} s",
            flush=True,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
