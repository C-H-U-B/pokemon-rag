"""Question → plan structuré : analyse rapide déterministe, puis repli LLM.

Seul module de `structured` qui crée un client LLM. Le SQL et la validation du
plan restent dans `query_engine`, importable sans aucun code d'inférence.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import OpenAI

from pokemon_rag.config import LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES
from pokemon_rag.constraints.query_constraints import (
    extract_form,
    extract_level_bounds,
    extract_version_group,
    has_explicit_game,
    normalize as _normalize,
)
# Référence au module et non à ses fonctions : les tests y substituent la connexion.
from pokemon_rag.structured import query_engine as engine

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
QUERY_MODEL = "qwen/qwen3-vl-8b"

llm_client = OpenAI(
    base_url=LM_STUDIO_BASE_URL, api_key="lm-studio",
    timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES,
)

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


def _fast_species(question: str) -> str | None:
    conn = engine._connect()
    try:
        candidates = engine._fast_db_names(
            conn, "pokemon_species", "pokemon_species_names", "pokemon_species_id"
        )
    finally:
        conn.close()
    return engine._fast_find_unique(_normalize(question), candidates)


def _fast_move(question: str) -> str | None:
    normalized_question = _normalize(question)
    padded = f"-{normalized_question}-"
    for french_name, identifier in engine._MOVE_INTERNAL_ALIASES.items():
        if f"-{french_name}-" in padded:
            return french_name.capitalize()

    conn = engine._connect()
    try:
        candidates = engine._fast_db_names(conn, "moves", "move_names", "move_id")
    finally:
        conn.close()
    return engine._fast_find_unique(normalized_question, candidates)


def _fast_form(question: str) -> str | None:
    return extract_form(question)


def _known_version_groups() -> set[str]:
    conn = engine._connect()
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
        conn = engine._connect()
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
        return engine.validate_plan(pokedex_plan)
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
        return engine.validate_plan({
            "operation": "get_evolutions",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
        })

    if machine:
        return engine.validate_plan({
            "operation": "get_machine_moves",
            "pokemon": pokemon,
            "form": form,
            "version_group": version_group,
        })

    if level_request:
        min_level, max_level = level_bounds
        return engine.validate_plan({
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
            return engine.validate_plan({
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
    if plan.get("operation") in engine.POKEDEX_OPERATIONS and re.search(
        r"(?:^|-)(?:dans|en|in|version|versions|g\d+|generation-\d+)(?:-|$)", _normalize(question)
    ):
        raise ValueError("Les informations du Pokédex personnalisé ne sont pas filtrables par jeu ou époque.")
    return {
        "plan": engine.validate_plan(plan),
        "raw_text": raw,
        "parse_time": time.perf_counter() - start,
        "parser_mode": "LLM",
    }


def query_structured_data(question: str) -> dict[str, Any]:
    """Interprète et exécute une question, en renvoyant les erreurs dans le résultat.

    Vérifier ``error`` avant d'interpréter ``count`` : une erreur peut aussi
    produire un compte nul. Les appels directs aux fonctions get_* ne passent
    pas par cette enveloppe ni par les contrôles du parseur de questions.
    """
    total_start = time.perf_counter()
    try:
        parsed = parse_query(question)
        result = engine.execute_plan(parsed["plan"])
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
