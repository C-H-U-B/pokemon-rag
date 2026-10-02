from __future__ import annotations

from typing import Any
import re

from pokemon_rag.constraints.query_constraints import (
    ExplicitConstraints,
    extract_explicit_constraints, reconcile_search_args,
    extract_named_pokemon, is_named_identity_question, without_unnamed_learning_method,
    normalize,
    VERSION_ALIASES,
)
from pokemon_rag.structured.query_engine import pokemon_name_catalogue, get_pokedex_identity


VERSION_GROUP_TOOLS = {
    "pokemon_moves",
    "pokemon_search",
    "pokemon_evolutions",
    "pokemon_level_up_moves",
    "pokemon_move_learning_methods",
    "pokemon_machine_moves",
}

FORM_TOOLS = {
    "pokemon_moves",
    "pokemon_search",
    "pokemon_evolutions",
    "pokemon_level_up_moves",
    "pokemon_move_learning_methods",
    "pokemon_machine_moves",
    "pokemon_types",
    "pokemon_pokedex_identity",
    "pokemon_signature_moves",
}

MOVE_FILTER_TOOLS = {"pokemon_moves", "pokemon_search"}
LEVEL_TOOLS = MOVE_FILTER_TOOLS | {"pokemon_level_up_moves"}


def _explicit_arguments(constraints: ExplicitConstraints) -> dict[str, Any]:
    """Traduction des seuls champs reconnus, sans choisir d'outil."""
    required = {key: value for key, value in (
        ("pokedex_number", constraints.national_number),
        ("generation", constraints.generation), ("form", constraints.form),
        ("version_group", constraints.version_group), ("move_type", constraints.move_type),
        ("damage_class", constraints.damage_class), ("legendary", constraints.legendary),
        ("mythical", constraints.mythical), ("form_category", constraints.form_category),
    ) if value is not None}
    if constraints.pokemon_types:
        required.update(types=list(constraints.pokemon_types), type_match=constraints.type_match)
    if constraints.power_bounds is not None:
        required["min_power"], required["max_power"] = constraints.power_bounds
    if constraints.level_bounds is not None:
        required["min_level"], required["max_level"] = constraints.level_bounds
    if constraints.ranking:
        required.update(constraints.ranking)
    return required


def _unsupported(tool_name: str, required: dict[str, Any]) -> dict[str, Any] | None:
    """Compatibilité avec les signatures structurées ; aucune réorientation automatique."""
    groups = (
        ({"pokedex_number"}, {"pokemon_search"}, "unsupported_pokedex_number_constraint"),
        ({"version_group"}, VERSION_GROUP_TOOLS, "unsupported_version_constraint"),
        ({"form"}, FORM_TOOLS, "unsupported_form_constraint"),
        ({"min_level", "max_level"}, LEVEL_TOOLS, "unsupported_level_constraints"),
        ({"move_type", "damage_class", "min_power", "max_power"}, MOVE_FILTER_TOOLS, "unsupported_move_constraints"),
        ({"generation", "types", "type_match", "legendary", "mythical", "form_category",
          "sort_by", "sort_order", "best_only", "limit", "offset"}, {"pokemon_search"}, "unsupported_search_constraints"),
    )
    for fields, tools, error in groups:
        if fields.intersection(required) and tool_name not in tools:
            response = {"error":error, "selected_tool":tool_name,
                        "required_arguments":required,
                        "message":"Cet outil ne peut pas conserver les contraintes explicites. Retentez avec un outil compatible et ces arguments."}
            if error == "unsupported_pokedex_number_constraint":
                response["required_tool"] = "pokemon_search"
            return response
    return None


def _extract_user_text(user_content: Any) -> str:
    """Extrait le texte du message utilisateur courant fourni par ADK."""
    if user_content is None:
        return ""

    parts = getattr(user_content, "parts", None)
    if not parts:
        return ""

    texts: list[str] = []

    for part in parts:
        text = getattr(part, "text", None)
        if text:
            texts.append(str(text))

    return "\n".join(texts).strip()


def before_tool_guard(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
) -> dict[str, Any] | None:
    """Valide les contraintes explicites avant l'exécution d'un outil ADK.

    Les contraintes reconnues sont indépendantes de la proposition du modèle.
    L'appel est réparé uniquement si sa signature les représente toutes ; sinon
    une erreur structurée laisse Qwen choisir la suite. Les arguments originaux
    ne sont modifiés qu'après validation complète.

    Le callback retourne :
    - None pour laisser ADK exécuter l'outil ;
    - un dictionnaire pour court-circuiter l'exécution du tool.
    """
    question = _extract_user_text(
        getattr(tool_context, "user_content", None)
    )

    if not question:
        return None

    tool_name = getattr(tool, "name", "")
    historical = tool_name in {"pokemon_level_up_moves", "pokemon_machine_moves", "pokemon_move_learning_methods"} and bool(
        re.search(r"(?:^|-)(?:historique|toutes-les-versions|tous-les-jeux|plusieurs-versions)(?:-|$)", normalize(question)))
    padded = "-" + normalize(question) + "-"
    historical_without_named_game = historical and not any(f"-{alias}-" in padded for alias in VERSION_ALIASES)

    corrected = dict(args)
    try:
        constraints = extract_explicit_constraints(question)
        required = _explicit_arguments(constraints)
        if historical_without_named_game:
            required.pop("version_group", None)
        if constraints.form_ambiguous:
            return {"error":"ambiguous_form_constraint", "message":"Plusieurs formes régionales explicites : précisez une cible unique."}
        if constraints.version_ambiguous and not historical_without_named_game:
            return {"error":"ambiguous_version_constraint", "message":"Jeu explicite inconnu ou plusieurs jeux non représentables."}
        if constraints.level_explicit and constraints.level_bounds is None:
            return {"error":"ambiguous_level_constraints", "message":"Bornes de niveau explicites ambiguës ou non reconnues."}
        unsupported = _unsupported(tool_name, required)
        if unsupported:
            return unsupported
        entity = extract_named_pokemon(question, pokemon_name_catalogue()) if (
            tool_name in FORM_TOOLS) else None
        if entity:
            identity = is_named_identity_question(question)
            if constraints.form:
                if entity.get("form") and not normalize(entity["form"]).endswith(constraints.form):
                    raise ValueError("La forme complète et la région explicites se contredisent.")
                entity["form"] = constraints.form
            if tool_name == "pokemon_search" and constraints.national_number is None and (identity or corrected.get("pokedex_number") is None):
                required = {"required_tool":"pokemon_pokedex_identity"} if identity else {}
                return {"error":"unsupported_named_pokemon_constraint", **required,
                        "required_arguments":entity,
                        "message":"Cet outil ne filtre pas par nom. Choisissez un outil compatible avec le Pokémon explicite."}
            if tool_name == "pokemon_search":
                # Conserver une recherche ciblée par numéro, même après un outil
                # d'identité, mais ne jamais accepter un numéro d'une autre espèce.
                known = get_pokedex_identity(**entity)
                number = known["rows"][0]["national_number"]
                if constraints.national_number is not None and constraints.national_number != number:
                    raise ValueError("Le nom et le numéro national explicites désignent des cibles différentes.")
                corrected["pokedex_number"] = number
                if entity.get("form"):
                    required["form"] = entity["form"]
            else:
                corrected.update(entity)
        if tool_name == "pokemon_search":
            corrected = reconcile_search_args(question, corrected)
        corrected.update(required)
        if tool_name in MOVE_FILTER_TOOLS:
            corrected = without_unnamed_learning_method(question, corrected)
        if constraints.level_bounds is not None and tool_name in MOVE_FILTER_TOOLS:
            if corrected.get("learning_method") not in (None, "level-up"):
                return {"error":"incompatible_learning_method", "required_arguments":required,
                        "message":"Les bornes de niveau exigent la montée de niveau ; choisissez un outil compatible."}
            corrected["learning_method"] = "level-up"
        if tool_name in {"pokemon_level_up_moves", "pokemon_machine_moves", "pokemon_move_learning_methods"}:
            if historical or "all_versions" in corrected:
                corrected["all_versions"] = historical
            if historical_without_named_game:
                corrected.pop("version_group", None)
    except ValueError as exc:
        return {
            "error": "invalid_explicit_constraints",
            "message": str(exc),
        }

    args.clear()
    args.update(corrected)
    return None
