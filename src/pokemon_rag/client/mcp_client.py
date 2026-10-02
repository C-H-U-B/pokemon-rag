from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pokemon_rag.constraints.query_constraints import (
    extract_explicit_constraints, extract_national_pokedex_number, normalize, reconcile_search_args,
    without_unnamed_learning_method,
)


SERVER_MODULE = "pokemon_rag.mcp.server"

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
MODEL = "qwen/qwen3-vl-8b"

TOOL_SELECTION_PROMPT = """Tu sélectionnes un tool MCP pour répondre à une question sur Pokémon.

Tu reçois la liste des tools disponibles avec leur description et leur schéma JSON.

Réponds uniquement avec un objet JSON de cette forme :
{
  "tool": "nom_du_tool",
  "arguments": {
    "...": "..."
  }
}

Règles :
- utilise uniquement un tool présent dans la liste fournie ;
- respecte exactement son schéma d'entrée ;
- n'invente pas de paramètre ;
- utilise pokemon_search pour les listes, comptages et recherches croisées ;
- utilise pokemon_moves pour les capacités apprenables selon leurs propriétés ;
- pour retrouver un Pokémon par numéro national, utilise pokemon_search avec
  pokedex_number ; ne devine pas un nom pour appeler pokemon_pokedex_identity ;
- pokemon_pokedex_identity obtient le numéro d'un Pokémon déjà nommé ;
- pour les classements par statistiques de base, utilise pokemon_search avec sort_by,
  sort_order et tous les filtres ; superlatif singulier : best_only=true,
  top N : best_only=false et limit=N ; toutes les Méga : form_category="mega" ;
- ne calcule ni total, ni tri, ni min/max toi-même ; signale les ex aequo (tie/tie_count) ;
- combine tous les filtres en SQL via les arguments, sans filtrer toi-même les résultats ;
- utilise pokemon_rag_search lorsque la question demande une information documentaire
  qui n'est pas couverte par un tool structuré ;
- pour pokemon_rag_search, renseigne "pokemon" lorsqu'un Pokémon unique est explicitement
  identifiable dans la question ;
- ne réponds pas toi-même à la question ;
- aucun texte avant ou après le JSON.
"""

ANSWER_PROMPT = """Tu réponds à une question sur Pokémon à partir du résultat d'un tool MCP.

Règles :
- réponds en français ;
- réponds directement à la question ;
- utilise uniquement les informations présentes dans le résultat du tool ;
- n'invente aucune information absente du résultat ;
- si le résultat ne permet pas de répondre, dis-le clairement ;
- reste concis, sauf si la question demande davantage de détails ;
- ne mentionne pas MCP, le tool, le JSON, la base de données ou le fonctionnement interne ;
- ne recopie pas les champs techniques inutiles.
- utilise total_count pour les nombres et questions d'existence ;
- best_only=true : reprends best_value et signale les ex aequo avec tie/tie_count,
  même si la page ne montre qu'un gagnant ; ne recalcule jamais les statistiques ;
- signale les listes partielles (truncated) et leur total ;
- précise le jeu retenu pour un movepool et utilise les noms français ;
- movepool_available=false signifie données indisponibles, pas impossibilité d'apprendre ;
- les propriétés des capacités sont actuelles, même pour un movepool ancien.
- catalogue_complete=false impose de préciser que le total porte sur un catalogue incomplet.

Pour les résultats structurés :
- donne uniquement les informations demandées et attestées par le résultat disponible ;
- pour « Quels Pokémon… ? », reprends exclusivement les name_fr des Pokémon dans
  results, dans leur ordre ; n'ajoute, ne remplace et ne retire aucun Pokémon de mémoire ;
- ne complète jamais une page tronquée par tes connaissances ;
- n'ajoute pas de générations, numéros, classifications légendaires ou fabuleuses,
  noms anglais, exemples de capacités ou explications non demandés ;
- pokemon_search donne les Pokémon correspondants, pas les noms des capacités :
  ne cite aucune capacité à partir de ce seul résultat ;
- pour une liste de capacités, utilise exclusivement les name_fr des capacités retournées ;
- ne termine pas une liste par une phrase illustrative ajoutant de nouveaux faits ;
- avant de répondre, retire tout nom ou fait sans preuve appropriée et tout détail non demandé ;
- garde les précisions nécessaires sur le jeu et les limites, en une courte phrase
  pour la couverture du catalogue, sans nommer les formes manquantes sauf demande explicite.
"""


def create_llm_client() -> OpenAI:
    return OpenAI(
        base_url=LM_STUDIO_BASE_URL,
        api_key="lm-studio",
    )


def build_tools_payload(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("Qwen n'a pas retourné d'objet JSON.")

    parsed = json.loads(cleaned[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("La sélection de tool doit être un objet JSON.")

    return parsed


def choose_tool(
    question: str,
    tools: list[Any],
    client: OpenAI,
) -> tuple[str, dict[str, Any]]:
    tools_payload = build_tools_payload(tools)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": TOOL_SELECTION_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"Question : {question}\n\n"
                    "Tools MCP disponibles :\n"
                    f"{json.dumps(tools_payload, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        temperature=0,
        max_tokens=300,
    )

    content = response.choices[0].message.content or ""
    selection = parse_json_object(content)

    tool_name = selection.get("tool")
    arguments = selection.get("arguments", {})

    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("Qwen n'a pas sélectionné de tool valide.")

    if not isinstance(arguments, dict):
        raise ValueError("Les arguments du tool doivent être un objet JSON.")

    available_tool_names = {tool.name for tool in tools}

    if tool_name not in available_tool_names:
        raise ValueError(f"Tool MCP inconnu sélectionné par Qwen : {tool_name}")

    return tool_name, arguments



class ConstraintResolutionError(ValueError):
    """Empêche l'exécution d'une requête MCP qui perd une contrainte explicite."""


def _tool_by_name(tools: list[Any], name: str) -> Any | None:
    return next((tool for tool in tools if tool.name == name), None)


def _tool_properties(tool: Any) -> set[str]:
    schema = tool.input_schema or {}
    properties = schema.get("properties") or {}
    return set(properties)


def reconcile_tool_call(
    question: str,
    tool_name: str,
    arguments: dict[str, Any],
    tools: list[Any],
) -> tuple[str, dict[str, Any]]:
    """Réconcilie le choix du LLM avec les contraintes certaines de la question."""
    constraints = extract_explicit_constraints(question)
    reconciled = dict(arguments)
    if tool_name in {"pokemon_moves", "pokemon_search"}:
        reconciled = without_unnamed_learning_method(question, reconciled)
    try:
        national_number = extract_national_pokedex_number(question)
        if tool_name == "pokemon_search":
            reconciled = reconcile_search_args(question, reconciled)
    except ValueError as exc:
        raise ConstraintResolutionError(str(exc)) from exc
    if national_number is not None:
        search_tool = _tool_by_name(tools, "pokemon_search")
        if search_tool is None or "pokedex_number" not in _tool_properties(search_tool):
            raise ConstraintResolutionError("Aucun outil disponible ne permet de rechercher ce numéro national.")
        if tool_name not in {"pokemon_search", "pokemon_pokedex_identity"}:
            raise ConstraintResolutionError("Utilisez pokemon_search pour rechercher ce numéro national.")
        if tool_name == "pokemon_pokedex_identity":
            tool_name = "pokemon_search"
            properties = _tool_properties(search_tool)
            reconciled = {key: value for key, value in reconciled.items() if key in properties}
        reconciled["pokedex_number"] = national_number

    # Un Pokémon fourni par le modèle doit réellement apparaître dans la question.
    # S'il est absent, on bloque plutôt que d'exécuter une question simplifiée.
    pokemon = reconciled.get("pokemon")
    if tool_name != "pokemon_search" and (not isinstance(pokemon, str) or not pokemon.strip()):
        raise ConstraintResolutionError(
            "Je ne peux pas exécuter la demande sans identifier avec certitude le Pokémon concerné."
        )
    if pokemon is not None and normalize(pokemon) not in normalize(question):
        raise ConstraintResolutionError(
            "Le Pokémon sélectionné ne correspond pas clairement à celui demandé ; précisez le Pokémon concerné."
        )

    if constraints.level_explicit:
        if constraints.level_bounds is None:
            raise ConstraintResolutionError(
                "La contrainte de niveau est ambiguë ; précisez la borne ou l'intervalle souhaité."
            )
        if tool_name not in {"pokemon_level_up_moves", "pokemon_moves", "pokemon_search"}:
            level_tool = _tool_by_name(tools, "pokemon_level_up_moves")
            if level_tool is None:
                raise ConstraintResolutionError(
                    "La contrainte de niveau est explicite, mais aucun outil disponible ne peut la respecter."
                )
            tool_name = "pokemon_level_up_moves"
            allowed = _tool_properties(level_tool)
            reconciled = {key: value for key, value in reconciled.items() if key in allowed}
            reconciled["pokemon"] = pokemon.strip()

        minimum, maximum = constraints.level_bounds
        reconciled["min_level"] = minimum
        reconciled["max_level"] = maximum
        if tool_name in {"pokemon_moves", "pokemon_search"}:
            if reconciled.get("learning_method") not in (None, "level-up"):
                raise ConstraintResolutionError("Les bornes de niveau exigent la montée de niveau.")
            reconciled["learning_method"] = "level-up"

    tool = _tool_by_name(tools, tool_name)
    if tool is None:
        raise ConstraintResolutionError(f"Le tool sélectionné n'est plus disponible : {tool_name}")
    properties = _tool_properties(tool)

    if constraints.form is not None:
        if "form" not in properties:
            raise ConstraintResolutionError(
                "La forme demandée est explicite, mais l'outil sélectionné ne permet pas de la respecter."
            )
        reconciled["form"] = constraints.form

    if constraints.explicit_game:
        if constraints.version_ambiguous or constraints.version_group is None:
            raise ConstraintResolutionError(
                "Le jeu demandé n'est pas reconnu sans ambiguïté ; précisez la version souhaitée."
            )
        if "version_group" not in properties:
            raise ConstraintResolutionError(
                "Le jeu demandé est explicite, mais cette information n'est pas filtrable par version."
            )
        reconciled["version_group"] = constraints.version_group

    unknown = set(reconciled) - properties
    if unknown:
        raise ConstraintResolutionError(
            "Les arguments sélectionnés ne sont pas compatibles avec l'outil choisi : "
            + ", ".join(sorted(unknown))
        )

    return tool_name, reconciled

def extract_result(result: Any) -> Any:
    if result.structured_content is not None:
        return result.structured_content

    texts = [
        block.text
        for block in result.content
        if hasattr(block, "text")
    ]

    if len(texts) == 1:
        text = texts[0]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    return texts


def formulate_answer(
    question: str,
    tool_result: Any,
    client: OpenAI,
) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": ANSWER_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"Question : {question}\n\n"
                    "Résultat disponible :\n"
                    f"{json.dumps(tool_result, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        temperature=0,
        max_tokens=400,
    )

    answer = (response.choices[0].message.content or "").strip()

    if not answer:
        raise ValueError("Qwen n'a pas généré de réponse.")

    return answer


@dataclass
class MCPConversation:
    """Session séquentielle ; à utiliser uniquement dans le contexte open_client."""

    session: ClientSession
    tools: list[Any]
    llm: OpenAI

    async def ask(self, question: str) -> str:
        # Les questions restent indépendantes : aucun historique de conversation.
        tool_name, arguments = choose_tool(question, self.tools, self.llm)
        try:
            tool_name, arguments = reconcile_tool_call(
                question, tool_name, arguments, self.tools
            )
        except ConstraintResolutionError as exc:
            return str(exc)
        result = await self.session.call_tool(tool_name, arguments=arguments)
        if result.is_error:
            raise RuntimeError(f"Le tool MCP {tool_name!r} a retourné une erreur.")
        return formulate_answer(question, extract_result(result), self.llm)


@asynccontextmanager
async def open_client():
    """Partage serveur, catalogue et client LLM ; les ferme même en cas d'erreur."""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
    )

    client = create_llm_client()

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                yield MCPConversation(session, tools_result.tools, client)
    finally:
        client.close()


async def ask(question: str) -> str:
    """Appel ponctuel compatible ; utiliser open_client pour plusieurs questions."""
    async with open_client() as conversation:
        return await conversation.ask(question)


async def read_question() -> str:
    """Attend la saisie sans bloquer les tâches de réception MCP."""
    try:
        return (await asyncio.to_thread(input, "Question (quit pour sortir) : ")).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


async def main() -> None:
    question = await read_question()

    if not question or question.casefold() in {"quit", "exit", "/quit"}:
        return

    async with open_client() as conversation:
        while question and question.casefold() not in {"quit", "exit", "/quit"}:
            print(await conversation.ask(question))
            question = await read_question()


if __name__ == "__main__":
    asyncio.run(main())
