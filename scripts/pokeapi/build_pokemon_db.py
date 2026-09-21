from __future__ import annotations

import re
import shutil
import sqlite3
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from pokemon_rag.config import DB_PATH, POKEAPI_DB_PATH, SPREADSHEET_PATH

POKEAPI_DB = POKEAPI_DB_PATH
SPREADSHEET = SPREADSHEET_PATH
OUTPUT_DB = DB_PATH

SHEETS = {
    "Pokédex FR": "custom_pokedex_fr",
    "Pokédex EN": "custom_pokedex_en",
    "Pseudo-signatures": "custom_pseudo_signatures",
    "Légende": "custom_legend",
    "Corrections": "custom_corrections",
    "PokéAPI Mapping": "custom_pokeapi_mapping",
}

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def log(s=""):
    print(s, flush=True)


def sql_name(value, fallback):
    if value is None:
        return fallback
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or fallback
    return "_" + s if s[0].isdigit() else s


def unique_headers(values):
    used, out = {}, []
    for i, value in enumerate(values, 1):
        base = sql_name(value, f"column_{i}")
        used[base] = used.get(base, 0) + 1
        out.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return out


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for c in letters:
        n = n * 26 + ord(c) - 64
    return n - 1


def shared_strings(zf):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join((t.text or "") for t in si.iter(f"{{{MAIN}}}t"))
        for si in root.findall(f"{{{MAIN}}}si")
    ]


def sheet_paths(zf):
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {
        r.attrib["Id"]: r.attrib["Target"]
        for r in rels.findall(f"{{{PKG}}}Relationship")
    }
    out = {}
    for sheet in wb.find(f"{{{MAIN}}}sheets"):
        target = targets[sheet.attrib[f"{{{REL}}}id"]].replace("\\", "/")
        out[sheet.attrib["name"]] = target.lstrip("/") if target.startswith("/") else (
            target if target.startswith("xl/") else "xl/" + target
        )
    return out


def cell_value(cell, strings):
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        node = cell.find(f"{{{MAIN}}}is")
        return None if node is None else "".join(
            (t.text or "") for t in node.iter(f"{{{MAIN}}}t")
        )
    node = cell.find(f"{{{MAIN}}}v")
    if node is None or node.text is None:
        return None
    raw = node.text
    if kind == "s":
        return strings[int(raw)]
    if kind == "b":
        return int(raw)
    if kind in ("str", "e"):
        return raw
    try:
        x = float(raw)
        return int(x) if x.is_integer() else x
    except ValueError:
        return raw


def read_sheet(zf, path, strings):
    root = ET.fromstring(zf.read(path))
    data = root.find(f"{{{MAIN}}}sheetData")
    rows = []
    for row in data.findall(f"{{{MAIN}}}row"):
        vals = {}
        for cell in row.findall(f"{{{MAIN}}}c"):
            vals[col_index(cell.attrib["r"])] = cell_value(cell, strings)
        width = max(vals, default=-1) + 1
        current = [None] * width
        for i, v in vals.items():
            current[i] = v
        rows.append(current)
    while rows and not any(v not in (None, "") for v in rows[-1]):
        rows.pop()
    return rows


def infer_type(values):
    vals = [v for v in values if v not in (None, "")]
    if vals and all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "INTEGER"
    if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "REAL"
    return "TEXT"


def import_sheet(conn, table, rows):
    if not rows:
        raise RuntimeError(f"{table}: feuille vide")

    if table == "custom_legend":
        width = max(map(len, rows))
        headers = [f"column_{i}" for i in range(1, width + 1)]
        data = rows
        first_excel_row = 1
    else:
        headers = unique_headers(rows[0])
        width = len(headers)
        data = rows[1:]
        first_excel_row = 2

    data = [
        row[:width] + [None] * max(0, width - len(row))
        for row in data
        if any(v not in (None, "") for v in row)
    ]
    types = [infer_type([r[i] for r in data]) for i in range(width)]

    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    defs = ["source_row INTEGER NOT NULL"] + [
        f'"{h}" {t}' for h, t in zip(headers, types)
    ]
    conn.execute(f'CREATE TABLE "{table}" ({", ".join(defs)})')

    cols = ", ".join(["source_row"] + [f'"{h}"' for h in headers])
    marks = ", ".join("?" for _ in range(width + 1))
    payload = [
        (rownum, *row)
        for rownum, row in enumerate(data, start=first_excel_row)
    ]
    conn.executemany(
        f'INSERT INTO "{table}" ({cols}) VALUES ({marks})',
        payload,
    )
    return len(payload)


def link_pokedex(conn, table, language):
    name = "nom" if language == "fr" else "name"

    columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    expected = {
        "pokeapi_species_id",
        "pokeapi_pokemon_id",
        "pokeapi_pokemon_identifier",
        "pokeapi_form_id",
        "pokeapi_form_identifier",
        "pokeapi_is_default",
        "pokeapi_mapping_status",
    }
    missing = sorted(expected - columns)
    if missing:
        raise RuntimeError(
            f"{table}: colonnes de mapping PokéAPI manquantes : "
            + ", ".join(missing)
        )

    # Le mapping est désormais explicite dans le spreadsheet.
    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN species_id INTEGER')
    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN pokemon_id INTEGER')
    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN pokemon_form_id INTEGER')

    conn.execute(f'''
        UPDATE "{table}"
        SET species_id = CAST(pokeapi_species_id AS INTEGER)
        WHERE pokeapi_species_id IS NOT NULL
          AND TRIM(CAST(pokeapi_species_id AS TEXT)) <> ''
    ''')
    conn.execute(f'''
        UPDATE "{table}"
        SET pokemon_id = CAST(pokeapi_pokemon_id AS INTEGER)
        WHERE pokeapi_pokemon_id IS NOT NULL
          AND TRIM(CAST(pokeapi_pokemon_id AS TEXT)) <> ''
    ''')
    conn.execute(f'''
        UPDATE "{table}"
        SET pokemon_form_id = CAST(pokeapi_form_id AS INTEGER)
        WHERE pokeapi_form_id IS NOT NULL
          AND TRIM(CAST(pokeapi_form_id AS TEXT)) <> ''
    ''')

    checks = [
        ("species_id invalides", f'''
            SELECT COUNT(*) FROM "{table}" t
            WHERE t.species_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM pokemon_species ps WHERE ps.id = t.species_id
              )
        '''),
        ("pokemon_id invalides", f'''
            SELECT COUNT(*) FROM "{table}" t
            WHERE t.pokemon_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM pokemon p WHERE p.id = t.pokemon_id
              )
        '''),
        ("pokemon_id hors species_id", f'''
            SELECT COUNT(*) FROM "{table}" t
            JOIN pokemon p ON p.id = t.pokemon_id
            WHERE t.species_id IS NOT NULL
              AND p.species_id <> t.species_id
        '''),
        ("form_id invalides", f'''
            SELECT COUNT(*) FROM "{table}" t
            WHERE t.pokemon_form_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM pokemon_forms pf WHERE pf.id = t.pokemon_form_id
              )
        '''),
        ("form_id hors pokemon_id", f'''
            SELECT COUNT(*) FROM "{table}" t
            JOIN pokemon_forms pf ON pf.id = t.pokemon_form_id
            WHERE t.pokemon_id IS NOT NULL
              AND pf.pokemon_id <> t.pokemon_id
        '''),
    ]

    for label, sql in checks:
        count = conn.execute(sql).fetchone()[0]
        if count:
            raise RuntimeError(f"{table}: {count} {label}")

    # Les identifiants textuels sont informatifs : les IDs et leurs relations
    # sont l'autorité pour le mapping. On signale les écarts sans bloquer le build.
    pokemon_identifier_diff = conn.execute(f"""
        SELECT COUNT(*) FROM "{table}" t
        JOIN pokemon p ON p.id = t.pokemon_id
        WHERE t.pokeapi_pokemon_identifier IS NOT NULL
          AND TRIM(CAST(t.pokeapi_pokemon_identifier AS TEXT)) <> ''
          AND p.identifier <> TRIM(CAST(t.pokeapi_pokemon_identifier AS TEXT))
    """).fetchone()[0]

    form_identifier_diff = conn.execute(f"""
        SELECT COUNT(*) FROM "{table}" t
        JOIN pokemon_forms pf ON pf.id = t.pokemon_form_id
        WHERE t.pokeapi_form_identifier IS NOT NULL
          AND TRIM(CAST(t.pokeapi_form_identifier AS TEXT)) <> ''
          AND pf.form_identifier <> TRIM(CAST(t.pokeapi_form_identifier AS TEXT))
    """).fetchone()[0]

    if pokemon_identifier_diff:
        log(
            f"  ⚠ {table}: {pokemon_identifier_diff} Pokémon Identifier "
            "diffèrent du texte PokéAPI (non bloquant)"
        )
    if form_identifier_diff:
        log(
            f"  ⚠ {table}: {form_identifier_diff} Form Identifier "
            "diffèrent de form_identifier PokéAPI (non bloquant)"
        )

    conn.execute(f'CREATE INDEX idx_{table}_species ON "{table}"(species_id)')
    conn.execute(f'CREATE INDEX idx_{table}_pokemon ON "{table}"(pokemon_id)')
    conn.execute(f'CREATE INDEX idx_{table}_form ON "{table}"(pokemon_form_id)')
    conn.execute(f'CREATE INDEX idx_{table}_status ON "{table}"(pokeapi_mapping_status)')
    conn.execute(f'CREATE INDEX idx_{table}_name ON "{table}"("{name}")')


def create_view(conn):
    """
    Crée la vue bilingue à partir des colonnes réellement présentes dans
    les feuilles FR/EN. Les colonnes éditoriales facultatives sont résolues
    par alias et deviennent NULL si elles sont absentes.
    """
    def columns(table):
        return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}

    fr_cols = columns("custom_pokedex_fr")
    en_cols = columns("custom_pokedex_en")

    def expr(alias, available, candidates, output, required=False):
        for column in candidates:
            if column in available:
                return f'{alias}."{column}" AS "{output}"'
        if required:
            raise RuntimeError(
                f"custom_pokedex: colonne requise introuvable pour {output}: "
                + " / ".join(candidates)
            )
        return f'NULL AS "{output}"'

    fields = [
        'fr.source_row AS source_row',
        'fr.species_id AS species_id',
        'fr.pokemon_id AS pokemon_id',
        'fr.pokemon_form_id AS pokemon_form_id',
        'fr.pokeapi_pokemon_identifier AS pokemon_identifier',
        'fr.pokeapi_form_identifier AS form_identifier',
        'fr.pokeapi_is_default AS is_default',
        'fr.pokeapi_mapping_status AS mapping_status',

        expr("fr", fr_cols, ["nom"], "name_fr", True),
        expr("en", en_cols, ["name"], "name_en", True),
        expr("fr", fr_cols, ["numero"], "national_number", True),
        expr("fr", fr_cols, ["forme"], "form_fr"),
        expr("en", en_cols, ["form"], "form_en"),

        expr("fr", fr_cols, ["type_1"], "type_1_fr"),
        expr("fr", fr_cols, ["type_2"], "type_2_fr"),
        expr("en", en_cols, ["type_1"], "type_1_en"),
        expr("en", en_cols, ["type_2"], "type_2_en"),

        expr(
            "fr", fr_cols,
            ["generation_d_introduction", "generation_introduction"],
            "introduction_generation_fr",
        ),
        expr(
            "en", en_cols,
            ["introduction_generation", "generation_of_introduction"],
            "introduction_generation_en",
        ),

        # Cette colonne a changé de nom dans le spreadsheet au fil des versions.
        expr(
            "fr", fr_cols,
            [
                "stade_et_evolution_s",
                "stade_et_evolutions",
                "stade_et_evolution",
                "evolution_s",
                "evolutions",
            ],
            "evolution_summary_fr",
        ),
        expr(
            "en", en_cols,
            [
                "stage_and_evolution_s",
                "stage_and_evolutions",
                "stage_and_evolution",
                "evolution_s",
                "evolutions",
            ],
            "evolution_summary_en",
        ),

        expr(
            "fr", fr_cols,
            ["capacite_signature", "capacites_signature"],
            "signature_move_fr",
        ),
        expr(
            "en", en_cols,
            ["signature_move", "signature_moves"],
            "signature_move_en",
        ),
        expr(
            "fr", fr_cols,
            ["talent_signature", "talents_signature"],
            "signature_ability_fr",
        ),
        expr(
            "en", en_cols,
            ["signature_ability", "signature_abilities"],
            "signature_ability_en",
        ),
        expr(
            "fr", fr_cols,
            ["capacite_pseudo_signature", "capacites_pseudo_signature"],
            "pseudo_signature_move_fr",
        ),
        expr(
            "en", en_cols,
            ["pseudo_signature_move", "pseudo_signature_moves"],
            "pseudo_signature_move_en",
        ),
        expr(
            "fr", fr_cols,
            ["particularite_du_movepool", "particularites_du_movepool"],
            "movepool_distinction_fr",
        ),
        expr(
            "en", en_cols,
            ["movepool_distinction", "movepool_distinctions"],
            "movepool_distinction_en",
        ),
        expr(
            "fr", fr_cols,
            ["sous_groupe", "sous_groupes"],
            "subgroup_fr",
        ),
        expr(
            "en", en_cols,
            ["subgroup", "subgroups"],
            "subgroup_en",
        ),
        expr(
            "fr", fr_cols,
            ["autre_particularite", "autres_particularites"],
            "other_distinction_fr",
        ),
        expr(
            "en", en_cols,
            ["other_distinction", "other_distinctions"],
            "other_distinction_en",
        ),
        expr(
            "fr", fr_cols,
            [
                "differences_physiques_selon_le_sexe",
                "difference_physique_selon_le_sexe",
            ],
            "gender_differences_fr",
        ),
        expr(
            "en", en_cols,
            [
                "physical_gender_differences",
                "physical_gender_difference",
            ],
            "gender_differences_en",
        ),
        expr(
            "fr", fr_cols,
            ["synthese_des_particularites", "resume", "synthese"],
            "summary_fr",
        ),
        expr(
            "en", en_cols,
            ["distinctive_features_summary", "summary"],
            "summary_en",
        ),
    ]

    conn.execute("DROP VIEW IF EXISTS custom_pokedex")
    conn.execute(
        "CREATE VIEW custom_pokedex AS\n"
        "SELECT\n    "
        + ",\n    ".join(fields)
        + "\nFROM custom_pokedex_fr fr\n"
          "LEFT JOIN custom_pokedex_en en ON en.source_row = fr.source_row"
    )

    # Important : SQLite peut accepter une vue contenant une mauvaise colonne
    # et ne lever l'erreur qu'au premier SELECT. On force donc sa résolution ici.
    try:
        conn.execute("SELECT * FROM custom_pokedex LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"custom_pokedex invalide immédiatement après sa création: {exc}"
        ) from exc

    log("✓ Vue custom_pokedex résolue et testée.")


def validate(conn):
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError(f"integrity_check: {result}")

    fr = conn.execute("SELECT COUNT(*) FROM custom_pokedex_fr").fetchone()[0]
    en = conn.execute("SELECT COUNT(*) FROM custom_pokedex_en").fetchone()[0]
    species = conn.execute(
        "SELECT COUNT(*) FROM custom_pokedex_fr WHERE species_id IS NOT NULL"
    ).fetchone()[0]
    distinct_species = conn.execute(
        "SELECT COUNT(DISTINCT species_id) FROM custom_pokedex_fr "
        "WHERE species_id IS NOT NULL"
    ).fetchone()[0]
    pokemon = conn.execute(
        "SELECT COUNT(*) FROM custom_pokedex_fr WHERE pokemon_id IS NOT NULL"
    ).fetchone()[0]
    forms = conn.execute(
        "SELECT COUNT(*) FROM custom_pokedex_fr WHERE pokemon_form_id IS NOT NULL"
    ).fetchone()[0]

    mismatched_languages = conn.execute('''
        SELECT COUNT(*)
        FROM custom_pokedex_fr fr
        JOIN custom_pokedex_en en ON en.source_row = fr.source_row
        WHERE COALESCE(CAST(fr.pokeapi_species_id AS TEXT), '') <>
              COALESCE(CAST(en.pokeapi_species_id AS TEXT), '')
           OR COALESCE(CAST(fr.pokeapi_pokemon_id AS TEXT), '') <>
              COALESCE(CAST(en.pokeapi_pokemon_id AS TEXT), '')
           OR COALESCE(CAST(fr.pokeapi_form_id AS TEXT), '') <>
              COALESCE(CAST(en.pokeapi_form_id AS TEXT), '')
           OR COALESCE(CAST(fr.pokeapi_mapping_status AS TEXT), '') <>
              COALESCE(CAST(en.pokeapi_mapping_status AS TEXT), '')
    ''').fetchone()[0]
    if mismatched_languages:
        raise RuntimeError(
            f"{mismatched_languages} lignes FR/EN ont des mappings PokéAPI différents"
        )

    statuses = conn.execute('''
        SELECT COALESCE(pokeapi_mapping_status, '[vide]'), COUNT(*)
        FROM custom_pokedex_fr
        GROUP BY pokeapi_mapping_status
        ORDER BY COUNT(*) DESC
    ''').fetchall()

    log(f"✓ Pokédex FR : {fr:,} entrées")
    log(f"✓ Pokédex EN : {en:,} entrées")
    log(f"✓ species_id renseignés : {species:,}/{fr:,}")
    log(f"✓ species_id distincts : {distinct_species:,}")
    log(f"✓ pokemon_id renseignés : {pokemon:,}/{fr:,}")
    log(f"✓ form_id renseignés : {forms:,}/{fr:,}")
    log("✓ Mapping FR/EN cohérent")
    log("→ Statuts de mapping :")
    for status, count in statuses:
        log(f"  - {status}: {count:,}")

    if distinct_species != 1025:
        raise RuntimeError(
            f"1025 species_id distincts attendus, obtenu {distinct_species}"
        )


def main():
    start = time.perf_counter()

    if not POKEAPI_DB.exists():
        raise FileNotFoundError(f"{POKEAPI_DB} introuvable")
    if not SPREADSHEET.exists():
        raise FileNotFoundError(f"{SPREADSHEET} introuvable")

    OUTPUT_DB.parent.mkdir(parents=True, exist_ok=True)

    log("=" * 88)
    log("CONSTRUCTION DE pokemon.db")
    log("=" * 88)
    log(f"PokéAPI     : {POKEAPI_DB}")
    log(f"Spreadsheet : {SPREADSHEET}")
    log(f"Sortie      : {OUTPUT_DB}")

    log("\n→ Copie de pokeapi.db...")
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()
    shutil.copy2(POKEAPI_DB, OUTPUT_DB)
    log("✓ Copie terminée.")

    log("\n→ Lecture du spreadsheet...")
    with zipfile.ZipFile(SPREADSHEET) as zf:
        strings = shared_strings(zf)
        paths = sheet_paths(zf)
        missing = [s for s in SHEETS if s not in paths]
        if missing:
            raise RuntimeError("Feuilles manquantes : " + ", ".join(missing))

        data = {}
        for sheet in SHEETS:
            log(f"  → {sheet}")
            data[sheet] = read_sheet(zf, paths[sheet], strings)
            log(f"  ✓ {sheet}")

    conn = sqlite3.connect(OUTPUT_DB)
    try:
        log("\n→ Import dans SQLite...")
        for sheet, table in SHEETS.items():
            t0 = time.perf_counter()
            count = import_sheet(conn, table, data[sheet])
            conn.commit()
            log(f"✓ {table}: {count:,} lignes ({time.perf_counter()-t0:.2f} s)")

        log("\n→ Liaison avec les IDs PokéAPI...")
        link_pokedex(conn, "custom_pokedex_fr", "fr")
        link_pokedex(conn, "custom_pokedex_en", "en")
        conn.commit()
        log("✓ IDs liés.")

        log("→ Création de la vue bilingue custom_pokedex...")
        create_view(conn)
        conn.commit()
        log("✓ Vue créée.")

        log("→ ANALYZE...")
        conn.execute("ANALYZE")
        conn.commit()

        log("→ Validation...")
        validate(conn)
    finally:
        conn.close()

    log("\n" + "=" * 88)
    log("BUILD TERMINÉ")
    log("=" * 88)
    log(f"Base finale : {OUTPUT_DB}")
    log(f"Taille      : {OUTPUT_DB.stat().st_size / 1024 / 1024:.2f} MiB")
    log(f"Temps total : {time.perf_counter() - start:.2f} s")
    log("✓ PokéAPI + spreadsheet sont maintenant dans une seule base.")


if __name__ == "__main__":
    main()
