from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from typing import Any

from openai import OpenAI


from pokemon_rag.config import DB_PATH, LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES
from pokemon_rag.constraints.query_constraints import (
    BASE_STAT_NAMES,
    REGION_FORMS,
    VERSION_ALIASES,
    extract_form,
    extract_level_bounds,
    extract_version_group,
    has_explicit_game,
)
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
QUERY_MODEL = "qwen/qwen3-vl-8b"

# Source unique des identifiants, colonnes et libellés des six statistiques.
# Ces expressions SQL internes ne proviennent jamais des arguments du modèle.
BASE_STAT_FIELDS = {identifier: (column, BASE_STAT_NAMES[identifier]) for identifier, column in {
    "hp":"pv", "attack":"attaque", "defense":"defense",
    "special-attack":"attaque_speciale", "special-defense":"defense_speciale", "speed":"vitesse",
}.items()}
BASE_STAT_TOTAL = "base-stat-total"


def _stat_sort(value: str) -> tuple[str, str | None, str | None]:
    """Résout la whitelist de tri et les libellés français, sans SQL utilisateur."""
    if not isinstance(value, str):
        raise ValueError("sort_by doit désigner une statistique de base ou national_number.")
    normalized = _normalize(value)
    if normalized == "national-number":
        return "national_number", None, None
    for identifier, (column, label) in BASE_STAT_FIELDS.items():
        if normalized in {identifier, _normalize(label)}:
            return identifier, f"stats.{column}", label
    if normalized in {BASE_STAT_TOTAL, "total-des-statistiques", "total-de-base"}:
        return BASE_STAT_TOTAL, "(" + " + ".join(
            f"stats.{column}" for column, _ in BASE_STAT_FIELDS.values()) + ")", "Total des statistiques"
    raise ValueError("sort_by invalide : national_number, " + ", ".join(BASE_STAT_FIELDS) + ", " + BASE_STAT_TOTAL)

llm_client = OpenAI(
    base_url=LM_STUDIO_BASE_URL, api_key="lm-studio",
    timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES,
)

VALID_OPERATIONS = {
    "get_evolutions",
    "get_move_learning_methods",
    "get_level_up_moves",
    "get_machine_moves",
    "get_pokemon_types",
    "get_pokedex_identity",
    "get_signature_moves",
}

POKEDEX_OPERATIONS = {"get_pokemon_types", "get_pokedex_identity", "get_signature_moves"}

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

5. get_pokemon_types : types d'une entrée précise du Pokédex personnalisé.
6. get_pokedex_identity : numéro national et génération d'introduction d'une entrée.
7. get_signature_moves : capacités signature et pseudo-signature renseignées dans le tableur.
Pour ces trois opérations : clés operation, pokemon, form, version_group.
Conserve le nom COMPLET de la forme dans pokemon et utilise form=null si elle
fait déjà partie du nom. Aucun filtre historique par jeu n'est disponible :
ne supprime jamais une version explicitement demandée pour exécuter ces opérations.
Les statistiques et la liste générale des talents ne sont pas disponibles.

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


def _latest_movepool_sql(pokemon_expression: str, method_id: int | None = None) -> str:
    """Dernier jeu contenant un movepool, avant tout filtre de propriété de capacité.

    Avec une méthode d'apprentissage demandée : dernier jeu où ce Pokémon a cette
    méthode, car le jeu le plus récent peut n'en proposer qu'une autre. Sans aucun
    jeu pour cette méthode, le dernier movepool reste retenu et la liste est vide.
    pokemon_expression est une expression interne constante et method_id un
    identifiant lu en base, jamais une entrée utilisateur.
    """
    def latest(condition: str) -> str:
        return f"""(SELECT available.version_group_id FROM pokemon_moves available
        JOIN version_groups latest ON latest.id = available.version_group_id
        WHERE available.pokemon_id = {pokemon_expression}{condition}
        ORDER BY latest."order" DESC, latest.generation_id DESC, latest.id DESC LIMIT 1)"""
    if method_id is None:
        return latest("")
    return f"COALESCE({latest(f' AND available.pokemon_move_method_id = {int(method_id)}')}, {latest('')})"


def _bounded_integer(name: str, value: Any, minimum: int, maximum: int | None = None) -> None:
    if value is not None and (
        type(value) is not int or value < minimum or (maximum is not None and value > maximum)
    ):
        raise ValueError(f"{name} doit être un entier entre {minimum} et {maximum or '∞'}.")


def _page_arguments(limit: int, offset: int) -> None:
    _bounded_integer("limit", limit, 0, 100)
    _bounded_integer("offset", offset, 0)
    if limit is None or offset is None:
        raise ValueError("limit et offset ne peuvent pas être null.")


def _page_result(rows: list[dict[str, Any]], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"results": rows, "total_count": total, "returned_count": len(rows),
            "limit": limit, "offset": offset, "truncated": total > len(rows),
            "has_more": offset + len(rows) < total}


def _resolve_type(conn: sqlite3.Connection, value: str) -> sqlite3.Row:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Le type doit être une chaîne non vide.")
    matches = [row for row in conn.execute("SELECT * FROM type_display")
               if _normalize(value) in {_normalize(row[key]) for key in ("identifier", "name_fr", "name_en")}]
    if len(matches) != 1:
        raise ValueError(f"Type inconnu ou ambigu : {value!r}")
    return matches[0]


def _resolve_version_id(conn: sqlite3.Connection, version_group: str | None) -> int | None:
    if version_group is None:
        return None
    if not isinstance(version_group, str) or not version_group.strip():
        raise ValueError("version_group doit être un identifiant non vide.")
    row = conn.execute("SELECT id FROM version_groups WHERE identifier=?", (version_group,)).fetchone()
    if row is None:
        raise ValueError(f"Groupe de versions inconnu : {version_group!r}")
    return row["id"]


def _movepool_filters(
    conn: sqlite3.Connection, move_type: str | None, damage_class: str | None,
    min_power: int | None, max_power: int | None, learning_method: str | None,
    min_level: int | None, max_level: int | None,
) -> tuple[str, list[Any], int | None]:
    """Clause, paramètres et identifiant de la méthode demandée ou impliquée par des niveaux."""
    clauses, params, method_id = [], [], None
    for name, value in (("min_power", min_power), ("max_power", max_power),
                        ("min_level", min_level), ("max_level", max_level)):
        _bounded_integer(name, value, 0)
    for low, high in ((min_power, max_power), (min_level, max_level)):
        if low is not None and high is not None and low > high:
            raise ValueError("La borne minimale dépasse la borne maximale.")
    if move_type is not None:
        clauses.append("m.type_id=?")
        params.append(_resolve_type(conn, move_type)["type_id"])
    if damage_class is not None:
        classes = {"status": 1, "physical": 2, "special": 3,
                   "statut": 1, "physique": 2, "speciale": 3}
        if not isinstance(damage_class, str) or _normalize(damage_class) not in classes:
            raise ValueError("damage_class doit être status, physical ou special.")
        clauses.append("m.damage_class_id=?")
        params.append(classes[_normalize(damage_class)])
    for value, column, operator in ((min_power, "m.power", ">="), (max_power, "m.power", "<="),
                                    (min_level, "pm.level", ">="), (max_level, "pm.level", "<=")):
        if value is not None:
            clauses.append(f"{column}{operator}?")
            params.append(value)
    if min_level is not None or max_level is not None:
        if learning_method not in (None, "level-up"):
            raise ValueError("Les bornes de niveau exigent learning_method=level-up.")
        learning_method = "level-up"
    if learning_method is not None:
        if not isinstance(learning_method, str):
            raise ValueError("learning_method doit être un identifiant.")
        method = conn.execute("SELECT id FROM pokemon_move_methods WHERE identifier=?", (learning_method,)).fetchone()
        if method is None:
            raise ValueError(f"Méthode inconnue : {learning_method!r}")
        method_id = method["id"]
        clauses.append("pm.pokemon_move_method_id=?")
        params.append(method_id)
    return " AND ".join(clauses) or "1", params, method_id


def get_pokemon_moves(
    pokemon: str, form: str | None = None, version_group: str | None = None,
    move_type: str | None = None, damage_class: str | None = None,
    min_power: int | None = None, max_power: int | None = None,
    learning_method: str | None = None, min_level: int | None = None,
    max_level: int | None = None, limit: int = 30, offset: int = 0,
) -> dict[str, Any]:
    """Movepool unique d'une forme, avec propriétés actuelles, sans union historique."""
    _page_arguments(limit, offset)
    if not isinstance(pokemon, str) or not pokemon.strip():
        raise ValueError("pokemon doit être un nom non vide.")
    if form is not None and (not isinstance(form, str) or not form.strip()):
        raise ValueError("form doit être un identifiant non vide.")
    with closing(_connect()) as conn:
        species, forms = _move_pokemon_rows(conn, pokemon, form)
        if form is None:
            forms = [row for row in forms if row["is_default"] == 1 and row["is_default_form"] == 1]
        if not forms:
            raise ValueError("Forme par défaut introuvable dans les données locales.")
        pokemon_ids = {row["pokemon_id"] for row in forms}
        if len(pokemon_ids) != 1:
            raise ValueError("Forme ambiguë : précisez une seule forme du Pokémon.")
        pokemon_id = pokemon_ids.pop()
        version_id = _resolve_version_id(conn, version_group)
        where, filter_params, method_id = _movepool_filters(conn, move_type, damage_class, min_power,
                                                          max_power, learning_method, min_level, max_level)
        if version_id is None:
            latest_sql = _latest_movepool_sql("?", method_id)
            version_id = conn.execute(f"SELECT {latest_sql}", [pokemon_id] * latest_sql.count("?")).fetchone()[0]
        selected = conn.execute("SELECT identifier FROM version_groups WHERE id=?", (version_id,)).fetchone()
        context = {"operation": "get_pokemon_moves", "pokemon": species["name_fr"],
                   "pokemon_id": pokemon_id, "form": form,
                   "form_identifier": forms[0]["identifier"],
                   "form_selection": "explicit" if form is not None else "default",
                   "version_group": selected["identifier"] if selected else None,
                   "version_group_explicit": version_group is not None,
                   "version_selection": "explicit" if version_group is not None else "latest_available",
                   "movepool_available": bool(conn.execute(
                       "SELECT 1 FROM pokemon_moves WHERE pokemon_id=? AND version_group_id=? LIMIT 1",
                       (pokemon_id, version_id)).fetchone()),
                   "move_properties": "current_not_historicized"}
        source = f"""FROM pokemon_moves pm JOIN moves m ON m.id=pm.move_id
            WHERE pm.pokemon_id=? AND pm.version_group_id=? AND {where}"""
        params = [pokemon_id, version_id, *filter_params]
        total = conn.execute(f"SELECT COUNT(DISTINCT m.id) {source}", params).fetchone()[0]
        rows = conn.execute(f"""SELECT DISTINCT m.id AS move_id, m.identifier, md.name_fr,
            md.name_en, td.name_fr AS type_fr, m.power, m.accuracy, m.pp,
            CASE m.damage_class_id WHEN 1 THEN 'statut' WHEN 2 THEN 'physique'
            WHEN 3 THEN 'spéciale' END AS damage_class_fr,
            m.damage_class_id
            FROM pokemon_moves pm JOIN moves m ON m.id=pm.move_id
            JOIN move_display md ON md.move_id=m.id JOIN type_display td ON td.type_id=m.type_id
            WHERE pm.pokemon_id=? AND pm.version_group_id=? AND {where}
            ORDER BY md.name_fr COLLATE NOCASE, m.id LIMIT ? OFFSET ?""", [*params, limit, offset]).fetchall()
        results = [dict(row) for row in rows]
        if results:
            ids = [row["move_id"] for row in results]
            placeholders = ",".join("?" for _ in ids)
            methods = conn.execute(f"""SELECT DISTINCT pm.move_id, method.identifier AS learning_method, pm.level
                FROM pokemon_moves pm JOIN moves m ON m.id=pm.move_id
                JOIN pokemon_move_methods method ON method.id=pm.pokemon_move_method_id
                WHERE pm.pokemon_id=? AND pm.version_group_id=? AND {where}
                AND pm.move_id IN ({placeholders}) ORDER BY pm.move_id, method.identifier, pm.level""",
                [*params, *ids]).fetchall()
            by_move = {row["move_id"]: [] for row in results}
            for method in methods:
                by_move[method["move_id"]].append({"method": method["learning_method"], "level": method["level"]})
            for row in results:
                row["learning"] = by_move[row["move_id"]]
        return {**context, **_page_result(results, total, limit, offset)}


def search_pokemon(
    pokedex_number: int | None = None, generation: int | None = None,
    types: list[str] | None = None, type_match: str = "all",
    legendary: bool | None = None, mythical: bool | None = None,
    form: str | None = None, version_group: str | None = None,
    move_type: str | None = None, damage_class: str | None = None,
    min_power: int | None = None, max_power: int | None = None,
    learning_method: str | None = None, min_level: int | None = None,
    max_level: int | None = None, limit: int = 30, offset: int = 0,
    sort_by: str = "national_number", sort_order: str = "asc",
    best_only: bool = False, form_category: str | None = None,
) -> dict[str, Any]:
    """Recherche SQL sur le catalogue personnalisé lié, génération de l'espèce.

    Une forme par défaut par espèce sans form ; une forme explicite ne replie
    jamais vers la forme par défaut. Les filtres de capacités sont existentiels
    et portent tous sur une même relation d'apprentissage.
    """
    _page_arguments(limit, offset)
    _bounded_integer("pokedex_number", pokedex_number, 1)
    _bounded_integer("generation", generation, 1)
    sort_by, stat_expression, stat_label = _stat_sort(sort_by)
    if not isinstance(sort_order, str) or sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order invalide : asc ou desc.")
    if type(best_only) is not bool:
        raise ValueError("best_only doit être un booléen.")
    if best_only and stat_expression is None:
        raise ValueError("best_only exige un tri par statistique de base.")
    if form_category is not None and form_category != "mega":
        raise ValueError("form_category invalide : mega ou null.")
    for name, value in (("legendary", legendary), ("mythical", mythical)):
        if value is not None and type(value) is not bool:
            raise ValueError(f"{name} doit être un booléen ou null.")
    if type_match not in ("all", "any", "exact"):
        raise ValueError("type_match doit être all, any ou exact.")
    if types is not None and (not isinstance(types, list) or not 1 <= len(types) <= 2):
        raise ValueError("types doit contenir un ou deux types.")
    if form is not None and (not isinstance(form, str) or not form.strip()):
        raise ValueError("form doit être une chaîne non vide.")
    with closing(_connect()) as conn:
        conn.create_function("normalize", 1, _normalize, deterministic=True)
        clauses, params = [], []
        # Le flag custom is_default décrit parfois le Pokémon partagé par plusieurs
        # formes (Arceus). pokemon_forms.is_default distingue alors la forme réelle.
        if form is None and form_category is None:
            clauses.extend(["p.is_default=1", "pf.is_default=1"])
        elif form is not None:
            clauses.append("(normalize(pf.form_identifier)=? OR normalize(pf.identifier)=?)")
            params.extend([_normalize(form)] * 2)
        if form_category == "mega":
            clauses.append("pf.is_mega=1")
        for value, column in ((pokedex_number, "cp.national_number"), (generation, "ps.generation_id"),
                              (legendary, "CAST(ps.is_legendary AS INTEGER)"),
                              (mythical, "CAST(ps.is_mythical AS INTEGER)")):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        if types:
            resolved = list(dict.fromkeys(_resolve_type(conn, value)["name_fr"] for value in types))
            membership = ["(? IN (cp.type_1_fr, cp.type_2_fr))" for _ in resolved]
            clauses.append("(" + (" OR " if type_match == "any" else " AND ").join(membership) + ")")
            params.extend(resolved)
            if type_match == "exact":
                clauses.append("(CASE WHEN cp.type_1_fr IS NULL THEN 0 ELSE 1 END + "
                               "CASE WHEN cp.type_2_fr IS NULL THEN 0 ELSE 1 END)=?")
                params.append(len(resolved))
        version_id = _resolve_version_id(conn, version_group)
        move_where, move_params, method_id = _movepool_filters(conn, move_type, damage_class, min_power,
                                                  max_power, learning_method, min_level, max_level)
        has_movepool_filter = any(value is not None for value in (
            version_group, move_type, damage_class, min_power, max_power, learning_method, min_level, max_level))
        if has_movepool_filter:
            version_sql = "?" if version_id is not None else _latest_movepool_sql("p.id", method_id)
            clauses.append(f"""EXISTS (SELECT 1 FROM pokemon_moves pm JOIN moves m ON m.id=pm.move_id
                WHERE pm.pokemon_id=p.id AND pm.version_group_id={version_sql} AND {move_where})""")
            if version_id is not None:
                params.append(version_id)
            params.extend(move_params)
        stats_join = "JOIN custom_pokedex_fr stats ON stats.source_row=cp.source_row" if stat_expression else ""
        if stat_expression:
            clauses.append(f"{stat_expression} IS NOT NULL")
        source = f"""FROM custom_pokedex cp JOIN pokemon p ON p.id=cp.pokemon_id
            JOIN pokemon_forms pf ON pf.id=cp.pokemon_form_id AND pf.pokemon_id=p.id
            JOIN pokemon_species ps ON ps.id=p.species_id
            {stats_join}
            WHERE {' AND '.join(clauses) or '1'}"""
        ranking = {}
        if best_only:
            aggregate = "MAX" if sort_order == "desc" else "MIN"
            candidates = conn.execute(
                f"SELECT COUNT(*) AS matching_count, {aggregate}({stat_expression}) AS best_value {source}",
                params).fetchone()
            source += f" AND {stat_expression}=?"
            params.append(candidates["best_value"])
            ranking = dict(candidates)
        total = conn.execute(f"SELECT COUNT(*) {source}", params).fetchone()[0]
        if best_only:
            ranking.update(tie=total > 1, tie_count=total)
        version_projection = ("?" if version_id is not None else _latest_movepool_sql("p.id", method_id)) if has_movepool_filter else "NULL"
        select_params = ([version_id] if has_movepool_filter and version_id is not None else [])
        stat_projection = f", {stat_expression} AS base_stat_value" if stat_expression else ""
        if sort_by == "speed":
            stat_projection += ", stats.vitesse AS base_speed"  # Compatibilité du premier tri.
        if sort_by == BASE_STAT_TOTAL:
            stat_projection += f", {stat_expression} AS base_stat_total"
        order_column = stat_expression or "cp.national_number"
        rows = conn.execute(f"""SELECT cp.name_fr, cp.name_en, cp.national_number,
            p.id AS pokemon_id, pf.id AS form_id, pf.identifier AS form_identifier,
            cp.type_1_fr, cp.type_2_fr, ps.generation_id AS generation,
            CAST(ps.is_legendary AS INTEGER) AS legendary,
            CAST(ps.is_mythical AS INTEGER) AS mythical,
            (SELECT identifier FROM version_groups WHERE id={version_projection}) AS version_group
            {stat_projection}
            {source} ORDER BY {order_column} {sort_order}, cp.national_number, p.id, pf.id LIMIT ? OFFSET ?""",
            [*select_params, *params, limit, offset]).fetchall()
        fr_id, _ = _language_ids(conn)
        missing = conn.execute("""SELECT ps.id AS species_id, COALESCE(names.name,ps.identifier) AS name_fr
            FROM pokemon_species ps JOIN pokemon p ON p.species_id=ps.id AND p.is_default=1
            JOIN pokemon_forms pf ON pf.pokemon_id=p.id AND pf.is_default=1
            LEFT JOIN pokemon_species_names names ON names.pokemon_species_id=ps.id AND names.local_language_id=?
            WHERE NOT EXISTS (SELECT 1 FROM custom_pokedex cp
                WHERE cp.pokemon_id=p.id AND cp.pokemon_form_id=pf.id)
            ORDER BY ps.id""", (fr_id,)).fetchall()
        return {"operation": "search_pokemon",
                "form_selection": "explicit" if form else ("category" if form_category else "default"),
                "form_category": form_category,
                "sort_by": sort_by, "sort_order": sort_order,
                "best_only": best_only, "stat_name_fr": stat_label, **ranking,
                "version_selection": ("explicit" if version_group is not None else "latest_available") if has_movepool_filter else None,
                "catalogue": "custom_pokedex_linked_forms", "type_match": type_match,
                "catalogue_complete": not missing,
                "catalogue_missing_default_forms": [dict(row) for row in missing],
                "move_properties": "current_not_historicized" if has_movepool_filter else None,
                **_page_result([dict(row) for row in rows], total, limit, offset)}


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


def pokemon_name_catalogue() -> list[tuple[str, str, str | None]]:
    """Alias disponibles dans pokemon.db, espèce canonique et forme éventuelle."""
    with closing(_connect()) as conn:
        entries = [(alias, name, None) for name, alias in _fast_db_names(
            conn, "pokemon_species", "pokemon_species_names", "pokemon_species_id")]
        fr_id, _ = _language_ids(conn)
        rows = conn.execute("""SELECT cp.name_fr, cp.name_en, pf.identifier,
                pf.form_identifier, names.name AS species_name
            FROM custom_pokedex cp JOIN pokemon p ON p.id=cp.pokemon_id
            JOIN pokemon_forms pf ON pf.id=cp.pokemon_form_id
            JOIN pokemon_species_names names ON names.pokemon_species_id=p.species_id
                AND names.local_language_id=?""", (fr_id,)).fetchall()
        for row in rows:
            for key in ("name_fr", "name_en", "identifier"):
                alias = _normalize(row[key])
                if alias and not any(alias == token and row["species_name"] == name
                                     for token, name, _ in entries):
                    entries.append((alias, row["species_name"], row["identifier"]))
        return entries


def _legacy_movepool_version(conn, pokemon_ids, version_group, all_versions, method=None):
    if type(all_versions) is not bool:
        raise ValueError("all_versions doit être un booléen.")
    if version_group and all_versions:
        raise ValueError("all_versions est incompatible avec un jeu unique.")
    if version_group or all_versions:
        return version_group, "explicit" if version_group else "all_versions"
    placeholders = ",".join("?" for _ in pokemon_ids)
    method_sql = " AND pmm.identifier=?" if method else ""
    row = conn.execute(f"""SELECT vg.identifier FROM pokemon_moves pm
        JOIN version_groups vg ON vg.id=pm.version_group_id
        JOIN pokemon_move_methods pmm ON pmm.id=pm.pokemon_move_method_id
        WHERE pm.pokemon_id IN ({placeholders}){method_sql}
        ORDER BY vg.\"order\" DESC, vg.id DESC LIMIT 1""",
        [*pokemon_ids, *([method] if method else [])]).fetchone()
    return (row[0] if row else None), "latest_available"


_MOVE_INTERNAL_ALIASES = {
    "tonnerre": "thunderbolt",
}


def _fast_move(question: str) -> str | None:
    normalized_question = _normalize(question)
    padded = f"-{normalized_question}-"
    for french_name, identifier in _MOVE_INTERNAL_ALIASES.items():
        if f"-{french_name}-" in padded:
            return french_name.capitalize()

    conn = _connect()
    try:
        candidates = _fast_db_names(conn, "moves", "move_names", "move_id")
    finally:
        conn.close()
    return _fast_find_unique(normalized_question, candidates)


_REGION_FORMS = REGION_FORMS
_VERSION_ALIASES = VERSION_ALIASES


def _fast_form(question: str) -> str | None:
    return extract_form(question)


def _known_version_groups() -> set[str]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT identifier FROM version_groups WHERE identifier IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return {str(row["identifier"]) for row in rows}


def _fast_version_group(question: str) -> tuple[str | None, bool]:
    return extract_version_group(question, known_version_groups=_known_version_groups())


def _has_explicit_game(question: str) -> bool:
    return has_explicit_game(question)


def _fast_level_bounds(question: str) -> tuple[int | None, int | None] | None:
    return extract_level_bounds(question)


def parse_pokedex_query(question: str) -> dict[str, Any] | None:
    """Reconnaît uniquement des demandes simples portant sur une entrée exacte."""
    normalized = _normalize(question)
    patterns = {
        "get_pokemon_types": r"(?:quel-est-le-type|quels-sont-les-types|type|types)-(?:(?:de|du|d)-)?(.+)",
        "get_pokedex_identity": r"(?:quel-est-le-numero(?:-national)?(?:-du-pokedex)?|numero(?:-national)?|quelle-est-la-generation(?:-d-introduction)?|generation-d-introduction)-(?:(?:de|du|d)-)?(.+)",
        "get_signature_moves": r"(?:quelle-est-la-capacite-signature|quelles-sont-les-capacites-signature|capacite-signature|capacites-signature)-(?:(?:de|du|d)-)?(.+)",
    }
    for operation, pattern in patterns.items():
        match = re.fullmatch(pattern, normalized)
        if not match:
            continue
        conn = _connect()
        try:
            rows = conn.execute("SELECT DISTINCT name_fr, name_en FROM custom_pokedex").fetchall()
        finally:
            conn.close()
        names = {row["name_fr"] or row["name_en"] for row in rows
                 if match.group(1) in {_normalize(row["name_fr"]), _normalize(row["name_en"])}}
        if len(names) == 1:
            return {"operation": operation, "pokemon": names.pop(), "form": None, "version_group": None}
    return None


def _fast_parse_query(question: str) -> dict[str, Any] | None:
    """Construit un plan uniquement pour les formulations non ambiguës."""
    normalized = _normalize(question)
    pokedex_plan = parse_pokedex_query(question)
    if pokedex_plan is not None:
        return validate_plan(pokedex_plan)
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
    if level_bounds is None and re.search(r"(?:^|-)(?:niveau|niveaux|level|levels)(?:-|$)", normalized):
        return None
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

    if _has_explicit_game(question):
        _, unresolved_version = _fast_version_group(question)
        if unresolved_version:
            raise ValueError("Jeu inconnu ou ambigu : précisez un groupe de versions reconnu.")

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
    if plan.get("operation") in POKEDEX_OPERATIONS and re.search(
        r"(?:^|-)(?:dans|en|in|version|versions|g\d+|generation-\d+)(?:-|$)", _normalize(question)
    ):
        raise ValueError("Les informations du Pokédex personnalisé ne sont pas filtrables par jeu ou époque.")
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
        **{operation: {"operation", "pokemon", "form", "version_group"}
           for operation in POKEDEX_OPERATIONS},
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

    if operation in POKEDEX_OPERATIONS and version_group is not None:
        raise ValueError("Le Pokédex personnalisé ne permet pas de filtrer ces informations par version.")

    if operation == "get_move_learning_methods":
        move = plan.get("move")
        if not isinstance(move, str) or not move.strip():
            raise ValueError("move doit être une chaîne non vide.")
        result["move"] = move.strip()

    if operation == "get_level_up_moves":
        for key in ("min_level", "max_level"):
            value = plan.get(key)

            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"{key} doit être null ou un entier positif.")

            result[key] = value

        if (
            result["min_level"] is not None
            and result["max_level"] is not None
            and result["min_level"] > result["max_level"]
        ):
            raise ValueError(
                "min_level ne peut pas être supérieur à max_level."
            )

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
            pf.is_default AS is_default_form,
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
    internal_identifier = _MOVE_INTERNAL_ALIASES.get(normalized)
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
        } or (internal_identifier is not None and row["identifier"] == internal_identifier)
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
    all_versions: bool = False,
) -> dict[str, Any]:
    start = time.perf_counter()
    conn = _connect()
    try:
        species, forms = _move_pokemon_rows(conn, pokemon, form)
        pokemon_ids = [row["pokemon_id"] for row in forms]
        move_row = _resolve_move(conn, move)
        version_group, version_selection = _legacy_movepool_version(
            conn, pokemon_ids, version_group, all_versions)

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
            "version_selection": version_selection,
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
    all_versions: bool = False,
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
        version_group, version_selection = _legacy_movepool_version(
            conn, pokemon_ids, version_group, all_versions, "level-up")
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
            "version_selection": version_selection,
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
    all_versions: bool = False,
) -> dict[str, Any]:
    """CT du jeu demandé, ou du plus récent avec des données de CT pour la forme."""
    start = time.perf_counter()
    conn = _connect()
    try:
        species, forms = _move_pokemon_rows(conn, pokemon, form)
        pokemon_ids = [row["pokemon_id"] for row in forms]
        placeholders = ",".join("?" for _ in pokemon_ids)
        params: list[Any] = [*pokemon_ids]
        version_group, version_selection = _legacy_movepool_version(
            conn, pokemon_ids, version_group, all_versions, "machine")
        if not version_group and not all_versions:
            return {
                "operation": "get_machine_moves", "pokemon": pokemon,
                "form": form, "version_group": None, "version_selection": version_selection,
                "count": 0, "moves": [], "execution_time": time.perf_counter() - start,
            }
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
            "version_selection": version_selection,
            "count": len(moves),
            "moves": moves,
            "execution_time": time.perf_counter() - start,
        }
    finally:
        conn.close()


def _pokedex_entry(pokemon: str, form: str | None) -> dict[str, Any]:
    if not isinstance(pokemon, str) or not _normalize(pokemon):
        raise ValueError("pokemon doit être un nom non vide.")
    if form is not None and (not isinstance(form, str) or not _normalize(form)):
        raise ValueError("form doit être null ou un nom de forme non vide.")
    conn = _connect()
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM custom_pokedex")]
        # Les noms d'espèce peuvent différer du nom complet de l'entrée de forme.
        # Réutiliser le catalogue canonique, sans retirer des suffixes heuristiques.
        species_id = None
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", ("pokemon_species",)
        ).fetchone():
            try:
                species_id = _resolve_species(conn, pokemon)["species_id"]
            except ValueError:
                pass
    finally:
        conn.close()
    wanted = _normalize(pokemon)
    matches = [row for row in rows if wanted in {
        _normalize(row.get(key)) for key in ("name_fr", "name_en", "pokemon_identifier", "form_identifier")
    }]
    if not matches and species_id is not None:
        matches = [row for row in rows if row["species_id"] == species_id]
        if not form:
            # Ne choisir la forme par défaut que pour un vrai nom d'espèce.
            matches = [row for row in matches if row.get("is_default")]
    if form:
        # Accepte une espèce de base + un libellé explicite de forme, sans fallback.
        species = {row["species_id"] for row in matches}
        target = _normalize(form)
        candidates = rows if any(row.get("is_default") for row in matches) else matches
        matches = [row for row in candidates if row["species_id"] in species and (target in {
            _normalize(row.get(key)) for key in ("form_fr", "form_en", "form_identifier", "name_fr", "name_en")
        } or (target in _REGION_FORMS and _normalize(row.get("form_identifier")).endswith("-" + target)))]
    if len(matches) != 1:
        raise ValueError("Entrée Pokédex introuvable ou ambiguë ; précisez le nom complet de la forme.")
    return matches[0]


def _pokedex_result(operation: str, pokemon: str, form: str | None) -> dict[str, Any]:
    start = time.perf_counter()
    row = _pokedex_entry(pokemon, form)
    fields = {
        "get_pokemon_types": ("type_1_fr", "type_2_fr"),
        "get_pokedex_identity": ("national_number", "introduction_generation_fr"),
        "get_signature_moves": ("signature_move_fr", "pseudo_signature_move_fr"),
    }[operation]
    entry = {"name_fr": row["name_fr"], **{key: row.get(key) for key in fields}}
    return {"operation": operation, "pokemon": row["name_fr"], "form": row.get("form_fr"),
            "source": "Pokédex personnalisé", "rows": [entry], "count": 1,
            "execution_time": time.perf_counter() - start}


def get_pokemon_types(pokemon: str, form: str | None = None) -> dict[str, Any]:
    return _pokedex_result("get_pokemon_types", pokemon, form)


def get_pokedex_identity(pokemon: str, form: str | None = None) -> dict[str, Any]:
    return _pokedex_result("get_pokedex_identity", pokemon, form)


def get_signature_moves(pokemon: str, form: str | None = None) -> dict[str, Any]:
    return _pokedex_result("get_signature_moves", pokemon, form)


def execute_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan = validate_plan(plan)
    operation = plan["operation"]
    pokedex_functions = {"get_pokemon_types": get_pokemon_types,
                         "get_pokedex_identity": get_pokedex_identity,
                         "get_signature_moves": get_signature_moves}
    if operation in pokedex_functions:
        return pokedex_functions[operation](pokemon=plan["pokemon"], form=plan["form"])

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
    """Interprète et exécute une question, en renvoyant les erreurs dans le résultat.

    Vérifier ``error`` avant d'interpréter ``count`` : une erreur peut aussi
    produire un compte nul. Les appels directs aux fonctions get_* ne passent
    pas par cette enveloppe ni par les contrôles du parseur de questions.
    """
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
            "error_type": type(exc).__name__,
        }
