from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from typing import Any

from openai import OpenAI


from pokemon_rag.config import DB_PATH
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
QUERY_MODEL = "qwen/qwen3-vl-8b"

llm_client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key="lm-studio")

VALID_OPERATIONS = {
    "get_evolutions",
    "get_move_learning_methods",
    "get_level_up_moves",
    "get_machine_moves",
}

QUERY_SYSTEM_PROMPT = r"""
Tu es le planificateur du moteur STRUCTURED d'un Pokédex.

Ton rôle UNIQUE est de transformer UNE question Pokémon en UNE opération
structurée. Tu ne réponds jamais toi-même à la question.

Opérations disponibles :

1. get_evolutions
- Évolution d'un Pokémon.
- Clés : operation, pokemon, form, version_group
- Ne confonds jamais une forme ou une région avec un version_group.
- Si un nom de région qualifie directement le Pokémon (ex. "de Galar",
  "d'Alola", "de Hisui", "de Paldea"), il décrit la forme du Pokémon :
  utilise form avec l'identifiant correspondant et laisse version_group à null,
  sauf si un jeu ou groupe de versions est explicitement demandé séparément.

2. get_move_learning_methods
- Demande comment/par quelles méthodes un Pokémon apprend UNE capacité.
- Clés : operation, pokemon, form, move, version_group

3. get_level_up_moves
- Capacités apprises par montée de niveau.
- Clés : operation, pokemon, form, version_group, min_level, max_level
- min_level/max_level sont inclusifs. Utilise null si absent.
- "après le niveau 40" signifie min_level=41.
- "à partir du niveau 40" signifie min_level=40.

4. get_machine_moves
- Capacités apprises par machine (CT/CS).
- Clés : operation, pokemon, form, version_group

Utilise les identifiants PokéAPI pour version_group quand la version est précisée
(ex. scarlet-violet, sword-shield, sun-moon).

Exemples :
Question : "Comment Pikachu évolue-t-il ?"
{"operation":"get_evolutions","pokemon":"Pikachu","form":null,"version_group":null}

Question : "Comment Pikachu peut-il apprendre Électacle ?"
{"operation":"get_move_learning_methods","pokemon":"Pikachu","form":null,"move":"Électacle","version_group":null}

Question : "Quelles capacités Roitiflam apprend après le niveau 40 dans Écarlate et Violet ?"
{"operation":"get_level_up_moves","pokemon":"Roitiflam","form":null,"version_group":"scarlet-violet","min_level":41,"max_level":null}

Question : "Quelles CT Pikachu peut-il apprendre dans Écarlate et Violet ?"
{"operation":"get_machine_moves","pokemon":"Pikachu","form":null,"version_group":"scarlet-violet"}

Retourne UNIQUEMENT l'objet JSON.
"""


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base introuvable : {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize(text: str | None) -> str:
    if text is None:
        return ""
    value = unicodedata.normalize("NFKD", str(text))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.casefold()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Aucun objet JSON trouvé.")
        result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("Le plan doit être un objet JSON.")
    return result



def _fast_db_names(
    conn: sqlite3.Connection,
    base_table: str,
    names_table: str,
    names_id_column: str,
) -> list[tuple[str, str]]:
    """Retourne les noms FR/EN/identifiants disponibles dans pokemon.db."""
    fr_id, en_id = _language_ids(conn)
    rows = conn.execute(
        f"""
        SELECT DISTINCT base.identifier, fr.name AS name_fr, en.name AS name_en
        FROM "{base_table}" base
        LEFT JOIN "{names_table}" fr
          ON fr."{names_id_column}" = base.id AND fr.local_language_id = ?
        LEFT JOIN "{names_table}" en
          ON en."{names_id_column}" = base.id AND en.local_language_id = ?
        """,
        (fr_id, en_id),
    ).fetchall()

    values: list[tuple[str, str]] = []
    for row in rows:
        display = row["name_fr"] or row["name_en"] or row["identifier"]
        for candidate in (row["name_fr"], row["name_en"], row["identifier"]):
            if candidate:
                values.append((str(display), _normalize(str(candidate))))
    return values


def _fast_find_unique(
    normalized_question: str,
    candidates: list[tuple[str, str]],
) -> str | None:
    padded = f"-{normalized_question}-"
    matches = [
        (display, token)
        for display, token in candidates
        if token and f"-{token}-" in padded
    ]
    unique = list(dict.fromkeys(matches))
    if len(unique) == 1:
        return unique[0][0]
    return None


def _fast_species(question: str) -> str | None:
    conn = _connect()
    try:
        candidates = _fast_db_names(
            conn, "pokemon_species", "pokemon_species_names", "pokemon_species_id"
        )
    finally:
        conn.close()
    return _fast_find_unique(_normalize(question), candidates)


def _fast_move(question: str) -> str | None:
    conn = _connect()
    try:
        candidates = _fast_db_names(conn, "moves", "move_names", "move_id")
    finally:
        conn.close()
    return _fast_find_unique(_normalize(question), candidates)


_REGION_FORMS = {
    "alola": "alola",
    "galar": "galar",
    "hisui": "hisui",
    "paldea": "paldea",
}


def _fast_form(question: str) -> str | None:
    normalized = _normalize(question)
    matches = [
        form for token, form in _REGION_FORMS.items()
        if re.search(rf"(?:^|-){re.escape(token)}(?:-|$)", normalized)
    ]
    return matches[0] if len(matches) == 1 else None


_VERSION_ALIASES = {
    "rouge-et-bleu": "red-blue",
    "red-and-blue": "red-blue",
    "diamant-et-perle": "diamond-pearl",
    "diamond-and-pearl": "diamond-pearl",
    "soleil-et-lune": "sun-moon",
    "sun-and-moon": "sun-moon",
    "epee-et-bouclier": "sword-shield",
    "sword-and-shield": "sword-shield",
    "ecarlate-et-violet": "scarlet-violet",
    "scarlet-and-violet": "scarlet-violet",
    "ev": "scarlet-violet",
}


def _fast_version_group(question: str) -> tuple[str | None, bool]:
    normalized = _normalize(question)
    matches = {
        value for alias, value in _VERSION_ALIASES.items()
        if f"-{alias}-" in f"-{normalized}-"
    }
    if len(matches) > 1:
        return None, True
    if len(matches) == 1:
        return next(iter(matches)), False

    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT identifier FROM version_groups WHERE identifier IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    direct = {
        str(row["identifier"])
        for row in rows
        if f"-{_normalize(row['identifier'])}-" in f"-{normalized}-"
    }
    if len(direct) > 1:
        return None, True
    return (next(iter(direct)), False) if direct else (None, False)


def _fast_level_bounds(question: str) -> tuple[int | None, int | None] | None:
    normalized = _normalize(question)

    match = re.search(
        r"(?:apres|after)-+(?:le-+)?(?:niveau|level)-+(\d+)", normalized
    )
    if match:
        return int(match.group(1)) + 1, None

    match = re.search(
        r"(?:a-+partir-+du|a-+partir-+de|from)-+(?:niveau|level)-+(\d+)",
        normalized,
    )
    if match:
        return int(match.group(1)), None

    match = re.search(
        r"(?:avant|before)-+(?:le-+)?(?:niveau|level)-+(\d+)", normalized
    )
    if match:
        return None, max(0, int(match.group(1)) - 1)

    match = re.search(r"(?:au|a|at)-+(?:niveau|level)-+(\d+)", normalized)
    if match:
        level = int(match.group(1))
        return level, level

    return None


def _fast_parse_query(question: str) -> dict[str, Any] | None:
    """Construit un plan uniquement pour les formulations non ambiguës."""
    normalized = _normalize(question)
    pokemon = _fast_species(question)
    if pokemon is None:
        return None

    form = _fast_form(question)
    version_group, ambiguous_version = _fast_version_group(question)
    if ambiguous_version:
        return None

    evolution = bool(re.search(
        r"(?:^|-)(?:evolue|evoluent|evoluer|evolution|evolutions)(?:-|$)",
        normalized,
    ))
    machine = bool(re.search(
        r"(?:^|-)(?:ct|cs|machine|machines)(?:-|$)", normalized
    ))
    level_bounds = _fast_level_bounds(question)
    level_request = level_bounds is not None
    learning = bool(re.search(
        r"(?:^|-)(?:apprendre|apprend|apprennent|appris|apprise|apprises)(?:-|$)",
        normalized,
    ))

    if sum((evolution, machine, level_request)) > 1:
        return None

    if evolution:
        return validate_plan({
            "operation": "get_evolutions",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
        })

    if machine:
        return validate_plan({
            "operation": "get_machine_moves",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
        })

    if level_request:
        min_level, max_level = level_bounds
        return validate_plan({
            "operation": "get_level_up_moves",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
            "min_level": min_level,
            "max_level": max_level,
        })

    if learning:
        move = _fast_move(question)
        if move is not None:
            return validate_plan({
                "operation": "get_move_learning_methods",
                "pokemon": pokemon,
                "form": form,
                "move": move,
                "version_group": version_group,
            })

    return None


def parse_query(question: str) -> dict[str, Any]:
    start = time.perf_counter()

    fast_plan = _fast_parse_query(question)
    if fast_plan is not None:
        return {
            "plan": fast_plan,
            "raw_text": None,
            "parse_time": time.perf_counter() - start,
            "parser_mode": "FAST",
        }

    response = llm_client.chat.completions.create(
        model=QUERY_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": QUERY_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    raw = response.choices[0].message.content or ""
    plan = _extract_json(raw)
    return {
        "plan": validate_plan(plan),
        "raw_text": raw,
        "parse_time": time.perf_counter() - start,
        "parser_mode": "LLM",
    }


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    operation = plan.get("operation")
    if operation not in VALID_OPERATIONS:
        raise ValueError(f"Opération non supportée : {operation!r}")

    schemas = {
        "get_evolutions": {"operation", "pokemon", "form", "version_group"},
        "get_move_learning_methods": {
            "operation", "pokemon", "form", "move", "version_group"
        },
        "get_level_up_moves": {
            "operation", "pokemon", "form", "version_group", "min_level", "max_level"
        },
        "get_machine_moves": {"operation", "pokemon", "form", "version_group"},
    }
    expected = schemas[operation]
    if set(plan) != expected:
        raise ValueError(
            f"Plan invalide pour {operation}: clés attendues exactement "
            + ", ".join(sorted(expected))
        )

    pokemon = plan.get("pokemon")
    if not isinstance(pokemon, str) or not pokemon.strip():
        raise ValueError("pokemon doit être une chaîne non vide.")

    form = plan.get("form")
    if form is not None and (not isinstance(form, str) or not form.strip()):
        raise ValueError("form doit être null ou une chaîne non vide.")

    version_group = plan.get("version_group")
    if version_group is not None and (
        not isinstance(version_group, str) or not version_group.strip()
    ):
        raise ValueError("version_group doit être null ou une chaîne non vide.")

    result = {
        "operation": operation,
        "pokemon": pokemon.strip(),
        "form": form.strip() if isinstance(form, str) else None,
        "version_group": (
            version_group.strip() if isinstance(version_group, str) else None
        ),
    }

    if operation == "get_move_learning_methods":
        move = plan.get("move")
        if not isinstance(move, str) or not move.strip():
            raise ValueError("move doit être une chaîne non vide.")
        result["move"] = move.strip()

    if operation == "get_level_up_moves":
        for key in ("min_level", "max_level"):
            value = plan.get(key)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{key} doit être null ou un entier positif.")
            result[key] = value
        if (
            result["min_level"] is not None
            and result["max_level"] is not None
            and result["min_level"] > result["max_level"]
        ):
            raise ValueError("min_level ne peut pas être supérieur à max_level.")

    return result


def _language_ids(conn: sqlite3.Connection) -> tuple[int | None, int | None]:
    row = conn.execute("SELECT fr, en FROM language_ids").fetchone()
    return (row["fr"], row["en"]) if row else (None, None)


def _resolve_species(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    fr_id, en_id = _language_ids(conn)
    normalized = _normalize(name)

    rows = conn.execute(
        """
        SELECT DISTINCT
            ps.id AS species_id,
            ps.identifier,
            fr.name AS name_fr,
            en.name AS name_en
        FROM pokemon_species ps
        LEFT JOIN pokemon_species_names fr
          ON fr.pokemon_species_id = ps.id
         AND fr.local_language_id = ?
        LEFT JOIN pokemon_species_names en
          ON en.pokemon_species_id = ps.id
         AND en.local_language_id = ?
        """,
        (fr_id, en_id),
    ).fetchall()

    matches = [
        row for row in rows
        if normalized in {
            _normalize(row["identifier"]),
            _normalize(row["name_fr"]),
            _normalize(row["name_en"]),
        }
    ]

    if not matches:
        raise ValueError(f"Pokémon introuvable dans pokemon.db : {name!r}")
    if len(matches) > 1:
        raise ValueError(f"Nom de Pokémon ambigu : {name!r}")
    return matches[0]


def _resolve_source_forms(
    conn: sqlite3.Connection,
    species_id: int,
    form_query: str | None,
) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
            pf.id AS form_id,
            pf.identifier,
            pf.form_identifier,
            p.id AS pokemon_id,
            p.is_default
        FROM pokemon p
        JOIN pokemon_forms pf ON pf.pokemon_id = p.id
        WHERE p.species_id = ?
        ORDER BY p.is_default DESC, pf.is_default DESC, pf.id
        """,
        (species_id,),
    ).fetchall()

    if not form_query:
        return rows

    wanted = _normalize(form_query)
    matches = []
    for row in rows:
        values = {
            _normalize(row["identifier"]),
            _normalize(row["form_identifier"]),
        }
        if wanted in values or any(
            wanted and (v.endswith("-" + wanted) or wanted in v.split("-"))
            for v in values
        ):
            matches.append(row)

    if not matches:
        raise ValueError(
            f"Forme {form_query!r} introuvable pour species_id={species_id}."
        )
    return matches


def _name_from_table(
    conn: sqlite3.Connection,
    table: str,
    id_column: str,
    object_id: int | None,
    fallback_table: str | None = None,
    fallback_column: str = "identifier",
) -> dict[str, str | None] | None:
    if object_id is None:
        return None

    fr_id, en_id = _language_ids(conn)
    rows = conn.execute(
        f"""
        SELECT local_language_id, name
        FROM "{table}"
        WHERE "{id_column}" = ?
          AND local_language_id IN (?, ?)
        """,
        (object_id, fr_id, en_id),
    ).fetchall()

    by_lang = {r["local_language_id"]: r["name"] for r in rows}
    fallback = None
    if fallback_table:
        row = conn.execute(
            f'SELECT "{fallback_column}" AS value FROM "{fallback_table}" WHERE id = ?',
            (object_id,),
        ).fetchone()
        fallback = row["value"] if row else None

    return {
        "fr": by_lang.get(fr_id) or by_lang.get(en_id) or fallback,
        "en": by_lang.get(en_id) or fallback,
    }


def _identifier(conn: sqlite3.Connection, table: str, object_id: int | None) -> str | None:
    if object_id is None:
        return None
    row = conn.execute(
        f'SELECT identifier FROM "{table}" WHERE id = ?',
        (object_id,),
    ).fetchone()
    return row["identifier"] if row else None


def _form_info(conn: sqlite3.Connection, form_id: int | None) -> dict[str, Any] | None:
    if form_id is None:
        return None
    row = conn.execute(
        """
        SELECT
            pf.id AS form_id,
            pf.identifier,
            pf.form_identifier,
            pf.pokemon_id,
            p.species_id,
            p.is_default
        FROM pokemon_forms pf
        JOIN pokemon p ON p.id = pf.pokemon_id
        WHERE pf.id = ?
        """,
        (form_id,),
    ).fetchone()
    return dict(row) if row else None


def _species_info(conn: sqlite3.Connection, species_id: int | None) -> dict[str, Any] | None:
    if species_id is None:
        return None
    fr_id, en_id = _language_ids(conn)
    row = conn.execute(
        """
        SELECT
            ps.id AS species_id,
            ps.identifier,
            fr.name AS name_fr,
            en.name AS name_en
        FROM pokemon_species ps
        LEFT JOIN pokemon_species_names fr
          ON fr.pokemon_species_id = ps.id
         AND fr.local_language_id = ?
        LEFT JOIN pokemon_species_names en
          ON en.pokemon_species_id = ps.id
         AND en.local_language_id = ?
        WHERE ps.id = ?
        """,
        (fr_id, en_id, species_id),
    ).fetchone()
    return dict(row) if row else None


def _condition_details(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    details: dict[str, Any] = {}

    simple = [
        "minimum_level",
        "time_of_day",
        "minimum_happiness",
        "minimum_beauty",
        "minimum_affection",
        "needs_overworld_rain",
        "turn_upside_down",
        "needs_multiplayer",
        "near_special_rock",
        "minimum_move_count",
        "minimum_steps",
        "minimum_damage_taken",
        "nature_bitmask",
        "condition_expression",
        "percentage_chance",
    ]
    if row["relative_physical_stats"] is not None:
        details["relative_physical_stats"] = row["relative_physical_stats"]
    for key in simple:
        value = row[key]
        if value not in (None, 0, ""):
            details[key] = value

    details["trigger_item"] = _name_from_table(
        conn, "item_names", "item_id", row["trigger_item_id"], "items"
    )
    details["held_item"] = _name_from_table(
        conn, "item_names", "item_id", row["held_item_id"], "items"
    )
    details["known_move"] = _name_from_table(
        conn, "move_names", "move_id", row["known_move_id"], "moves"
    )
    details["used_move"] = _name_from_table(
        conn, "move_names", "move_id", row["used_move_id"], "moves"
    )
    details["location"] = _name_from_table(
        conn, "location_names", "location_id", row["location_id"], "locations"
    )
    details["region"] = _name_from_table(
        conn, "region_names", "region_id", row["region_id"], "regions"
    )
    details["known_move_type"] = _name_from_table(
        conn, "type_names", "type_id", row["known_move_type_id"], "types"
    )
    details["party_type"] = _name_from_table(
        conn, "type_names", "type_id", row["party_type_id"], "types"
    )

    if row["gender_id"] is not None:
        details["gender"] = _identifier(conn, "genders", row["gender_id"])

    details["party_species"] = _species_info(conn, row["party_species_id"])
    details["trade_species"] = _species_info(conn, row["trade_species_id"])

    return {k: v for k, v in details.items() if v is not None}


def get_evolutions(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    conn = _connect()

    try:
        source_species = _resolve_species(conn, pokemon)
        source_forms = _resolve_source_forms(
            conn, source_species["species_id"], form
        )
        source_form_ids = {r["form_id"] for r in source_forms}

        params: list[Any] = [source_species["species_id"]]
        version_sql = ""
        if version_group:
            version_sql = " AND vg.identifier = ?"
            params.append(version_group)

        rows = conn.execute(
            f"""
            SELECT
                pe.*,
                et.identifier AS trigger_identifier,
                vg.identifier AS version_group_identifier
            FROM pokemon_evolution pe
            JOIN pokemon_species target
              ON target.id = pe.evolved_species_id
            LEFT JOIN evolution_triggers et
              ON et.id = pe.evolution_trigger_id
            LEFT JOIN version_groups vg
              ON vg.id = pe.version_group_id
            WHERE target.evolves_from_species_id = ?
            {version_sql}
            ORDER BY pe.version_group_id, pe.id
            """,
            params,
        ).fetchall()

        evolutions = []
        for row in rows:
            required_form_id = row["required_pokemon_form_id"]

            # Une règle explicitement liée à une forme source doit correspondre
            # à la forme demandée. Sans filtre de forme, on conserve toutes les
            # règles afin de ne perdre aucune branche.
            if form:
                # Une forme explicitement demandée doit avoir une règle
                # explicitement liée à cette forme. Une règle sans
                # required_pokemon_form_id appartient à la forme générique
                # et ne doit pas "déborder" sur une forme régionale.
                if required_form_id is None:
                    continue
                if required_form_id not in source_form_ids:
                    continue

            target_species = _species_info(conn, row["evolved_species_id"])
            source_form = _form_info(conn, required_form_id)
            target_form = _form_info(conn, row["evolved_pokemon_form_id"])

            evolutions.append(
                {
                    "evolution_id": row["id"],
                    "from": {
                        "species_id": source_species["species_id"],
                        "identifier": source_species["identifier"],
                        "name_fr": source_species["name_fr"],
                        "name_en": source_species["name_en"],
                        "form": source_form,
                    },
                    "to": {
                        **(target_species or {}),
                        "form": target_form,
                    },
                    "trigger": row["trigger_identifier"],
                    "version_group": row["version_group_identifier"],
                    "conditions": _condition_details(conn, row),
                }
            )

        return {
            "operation": "get_evolutions",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
            "count": len(evolutions),
            "evolutions": evolutions,
            "execution_time": time.perf_counter() - start,
        }
    finally:
        conn.close()



def _resolve_move(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    fr_id, en_id = _language_ids(conn)
    normalized = _normalize(name)
    rows = conn.execute(
        """
        SELECT DISTINCT
            m.id AS move_id,
            m.identifier,
            fr.name AS name_fr,
            en.name AS name_en
        FROM moves m
        LEFT JOIN move_names fr
          ON fr.move_id = m.id AND fr.local_language_id = ?
        LEFT JOIN move_names en
          ON en.move_id = m.id AND en.local_language_id = ?
        """,
        (fr_id, en_id),
    ).fetchall()
    matches = [
        row for row in rows
        if normalized in {
            _normalize(row["identifier"]),
            _normalize(row["name_fr"]),
            _normalize(row["name_en"]),
        }
    ]
    if not matches:
        raise ValueError(f"Capacité introuvable dans pokemon.db : {name!r}")
    if len(matches) > 1:
        raise ValueError(f"Nom de capacité ambigu : {name!r}")
    return matches[0]


def _move_pokemon_rows(
    conn: sqlite3.Connection,
    pokemon: str,
    form: str | None,
) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    species = _resolve_species(conn, pokemon)
    forms = _resolve_source_forms(conn, species["species_id"], form)
    if not form:
        default_forms = [row for row in forms if row["is_default"] == 1]
        if default_forms:
            forms = default_forms
    return species, forms


def _move_info(conn: sqlite3.Connection, move_id: int) -> dict[str, Any]:
    fr_id, en_id = _language_ids(conn)
    row = conn.execute(
        """
        SELECT m.id AS move_id, m.identifier,
               fr.name AS name_fr, en.name AS name_en
        FROM moves m
        LEFT JOIN move_names fr
          ON fr.move_id = m.id AND fr.local_language_id = ?
        LEFT JOIN move_names en
          ON en.move_id = m.id AND en.local_language_id = ?
        WHERE m.id = ?
        """,
        (fr_id, en_id, move_id),
    ).fetchone()
    return dict(row) if row else {"move_id": move_id}


def get_move_learning_methods(
    pokemon: str,
    move: str,
    form: str | None = None,
    version_group: str | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    conn = _connect()
    try:
        species, forms = _move_pokemon_rows(conn, pokemon, form)
        pokemon_ids = [row["pokemon_id"] for row in forms]
        move_row = _resolve_move(conn, move)

        placeholders = ",".join("?" for _ in pokemon_ids)
        params: list[Any] = [*pokemon_ids, move_row["move_id"]]
        version_sql = ""
        if version_group:
            version_sql = " AND vg.identifier = ?"
            params.append(version_group)

        rows = conn.execute(
            f"""
            SELECT DISTINCT
                pm.pokemon_id,
                pm.level,
                pm."order" AS move_order,
                pmm.identifier AS method,
                vg.identifier AS version_group
            FROM pokemon_moves pm
            JOIN pokemon_move_methods pmm
              ON pmm.id = pm.pokemon_move_method_id
            JOIN version_groups vg
              ON vg.id = pm.version_group_id
            WHERE pm.pokemon_id IN ({placeholders})
              AND pm.move_id = ?
              {version_sql}
            ORDER BY vg.id, pmm.id, pm.level, pm."order"
            """,
            params,
        ).fetchall()

        methods = [dict(row) for row in rows]
        return {
            "operation": "get_move_learning_methods",
            "pokemon": pokemon,
            "form": form,
            "move": {
                "move_id": move_row["move_id"],
                "identifier": move_row["identifier"],
                "name_fr": move_row["name_fr"],
                "name_en": move_row["name_en"],
            },
            "version_group": version_group,
            "count": len(methods),
            "methods": methods,
            "execution_time": time.perf_counter() - start,
        }
    finally:
        conn.close()


def get_level_up_moves(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
    min_level: int | None = None,
    max_level: int | None = None,
) -> dict[str, Any]:
    if min_level is not None and min_level < 0:
        raise ValueError("min_level doit être positif.")
    if max_level is not None and max_level < 0:
        raise ValueError("max_level doit être positif.")
    if min_level is not None and max_level is not None and min_level > max_level:
        raise ValueError("min_level ne peut pas être supérieur à max_level.")

    start = time.perf_counter()
    conn = _connect()
    try:
        species, forms = _move_pokemon_rows(conn, pokemon, form)
        pokemon_ids = [row["pokemon_id"] for row in forms]
        placeholders = ",".join("?" for _ in pokemon_ids)
        params: list[Any] = [*pokemon_ids]

        filters = []
        if version_group:
            filters.append("vg.identifier = ?")
            params.append(version_group)
        if min_level is not None:
            filters.append("pm.level >= ?")
            params.append(min_level)
        if max_level is not None:
            filters.append("pm.level <= ?")
            params.append(max_level)

        extra_sql = "".join(f" AND {condition}" for condition in filters)
        rows = conn.execute(
            f"""
            SELECT DISTINCT
                pm.move_id,
                pm.level,
                pm."order" AS move_order,
                vg.identifier AS version_group
            FROM pokemon_moves pm
            JOIN pokemon_move_methods pmm
              ON pmm.id = pm.pokemon_move_method_id
            JOIN version_groups vg
              ON vg.id = pm.version_group_id
            WHERE pm.pokemon_id IN ({placeholders})
              AND pmm.identifier = 'level-up'
              {extra_sql}
            ORDER BY vg.id, pm.level, pm."order", pm.move_id
            """,
            params,
        ).fetchall()

        moves = []
        for row in rows:
            info = _move_info(conn, row["move_id"])
            moves.append({
                **info,
                "level": row["level"],
                "order": row["move_order"],
                "version_group": row["version_group"],
            })

        return {
            "operation": "get_level_up_moves",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
            "min_level": min_level,
            "max_level": max_level,
            "count": len(moves),
            "moves": moves,
            "execution_time": time.perf_counter() - start,
        }
    finally:
        conn.close()


def get_machine_moves(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    conn = _connect()
    try:
        species, forms = _move_pokemon_rows(conn, pokemon, form)
        pokemon_ids = [row["pokemon_id"] for row in forms]
        placeholders = ",".join("?" for _ in pokemon_ids)
        params: list[Any] = [*pokemon_ids]
        version_sql = ""
        if version_group:
            version_sql = " AND vg.identifier = ?"
            params.append(version_group)

        # Une capacité apprise par "machine" peut avoir une entrée dans machines.
        # LEFT JOIN : on conserve l'information PokéAPI même si aucun numéro de
        # machine n'est défini pour un ancien jeu/version.
        rows = conn.execute(
            f"""
            SELECT DISTINCT
                pm.move_id,
                vg.id AS version_group_id,
                vg.identifier AS version_group,
                ma.machine_number,
                ma.item_id
            FROM pokemon_moves pm
            JOIN pokemon_move_methods pmm
              ON pmm.id = pm.pokemon_move_method_id
            JOIN version_groups vg
              ON vg.id = pm.version_group_id
            LEFT JOIN machines ma
              ON ma.move_id = pm.move_id
             AND ma.version_group_id = pm.version_group_id
            WHERE pm.pokemon_id IN ({placeholders})
              AND pmm.identifier = 'machine'
              {version_sql}
            ORDER BY vg.id, ma.machine_number, pm.move_id
            """,
            params,
        ).fetchall()

        moves = []
        for row in rows:
            info = _move_info(conn, row["move_id"])
            item = _name_from_table(
                conn, "item_names", "item_id", row["item_id"], "items"
            )
            moves.append({
                **info,
                "version_group": row["version_group"],
                "machine_number": row["machine_number"],
                "machine_item": item,
            })

        return {
            "operation": "get_machine_moves",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
            "count": len(moves),
            "moves": moves,
            "execution_time": time.perf_counter() - start,
        }
    finally:
        conn.close()


def execute_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan = validate_plan(plan)
    operation = plan["operation"]

    if operation == "get_evolutions":
        return get_evolutions(
            pokemon=plan["pokemon"],
            form=plan["form"],
            version_group=plan["version_group"],
        )
    if operation == "get_move_learning_methods":
        return get_move_learning_methods(
            pokemon=plan["pokemon"],
            move=plan["move"],
            form=plan["form"],
            version_group=plan["version_group"],
        )
    if operation == "get_level_up_moves":
        return get_level_up_moves(
            pokemon=plan["pokemon"],
            form=plan["form"],
            version_group=plan["version_group"],
            min_level=plan["min_level"],
            max_level=plan["max_level"],
        )
    if operation == "get_machine_moves":
        return get_machine_moves(
            pokemon=plan["pokemon"],
            form=plan["form"],
            version_group=plan["version_group"],
        )
    raise ValueError(f"Opération non exécutée : {operation!r}")


def query_structured_data(question: str) -> dict[str, Any]:
    total_start = time.perf_counter()
    try:
        parsed = parse_query(question)
        result = execute_plan(parsed["plan"])
        result["plan"] = parsed["plan"]
        result["raw_plan"] = parsed["raw_text"]
        result["parse_time"] = parsed["parse_time"]
        result["parser_mode"] = parsed["parser_mode"]
        result["total_time"] = time.perf_counter() - total_start
        result["error"] = None
        return result
    except Exception as exc:
        return {
            "plan": None,
            "count": 0,
            "parse_time": None,
            "parser_mode": None,
            "execution_time": None,
            "total_time": time.perf_counter() - total_start,
            "error": f"{type(exc).__name__}: {exc}",
        }

