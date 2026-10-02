import asyncio
from types import SimpleNamespace

import pytest
from google.adk.tools.mcp_tool import McpToolset

from pokemon_rag.agent.agent import pokemon_mcp
from pokemon_rag.agent.agent import root_agent
from pokemon_rag.agent.context_budget import before_model_budget, bounded_tool_result
from google.adk.models.llm_request import LlmRequest
from google.genai import types


async def _get_mcp_tools():
    """Charge les tools exposés à ADK par le serveur MCP."""
    # Une session indépendante par boucle asyncio, fermée avant sa destruction.
    toolset = McpToolset(
        connection_params=pokemon_mcp.connection_params,
        tool_filter=pokemon_mcp.tool_filter,
    )
    try:
        return await toolset.get_tools()
    finally:
        await toolset.close()


@pytest.mark.integration
def test_adk_mcp_toolset_exposes_expected_tools():
    """ADK doit exposer exactement les tools MCP autorisés à l'agent."""

    tools = asyncio.run(_get_mcp_tools())

    tool_names = {tool.name for tool in tools}

    expected_tools = {
        "pokemon_evolutions",
        "pokemon_level_up_moves",
        "pokemon_move_learning_methods",
        "pokemon_machine_moves",
        "pokemon_types",
        "pokemon_pokedex_identity",
        "pokemon_signature_moves",
        "pokemon_rag_search",
        "pokemon_search",
        "pokemon_moves",
    }

    assert tool_names == expected_tools, (
        "Les tools MCP exposés à l'agent ne correspondent pas "
        "à l'interface attendue. "
        f"Tools découverts : {sorted(tool_names)}"
    )


def test_real_tool_catalogue_and_instructions_fit_initial_budget():
    tools = asyncio.run(_get_mcp_tools())
    req = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="Quel est le Pokémon le plus rapide ?")])],
        config=types.GenerateContentConfig(system_instruction=root_agent.instruction,
            tools=[types.Tool(function_declarations=[tool._get_declaration() for tool in tools])]))
    assert before_model_budget(SimpleNamespace(state={}), req) is None


@pytest.mark.real_data
def test_actual_top_ten_rankings_fit_tool_and_model_context_without_llm():
    from pokemon_rag.structured.query_engine import search_pokemon

    tools = asyncio.run(_get_mcp_tools())
    for statistic in ("speed", "base-stat-total"):
        arguments = {"sort_by":statistic, "sort_order":"desc", "limit":10}
        result = bounded_tool_result(search_pokemon(**arguments))
        assert len(result["results"]) == result["returned_count"] == 10
        assert not result.get("context_truncated")
        req = LlmRequest(contents=[
            types.Content(role="user", parts=[types.Part(text="Donne-moi les 10 Pokémon avec la meilleure statistique.")]),
            types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="pokemon_search", args=arguments))]),
            types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(name="pokemon_search",response=result))]),
        ], config=types.GenerateContentConfig(system_instruction=root_agent.instruction,
            tools=[types.Tool(function_declarations=[tool._get_declaration() for tool in tools])]))
        assert before_model_budget(SimpleNamespace(state={}), req) is None


def test_abridged_catalogue_keeps_boundaries_closed_values_and_instruction_names():
    """Vérifie ce que le modèle reçoit après abrègement, pas son comportement."""
    import re

    tools = asyncio.run(_get_mcp_tools())
    full = {tool.name: tool._get_declaration().description for tool in tools}
    req = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="Question")])],
        config=types.GenerateContentConfig(system_instruction=root_agent.instruction,
            tools=[types.Tool(function_declarations=[tool._get_declaration() for tool in tools])]))
    assert before_model_budget(SimpleNamespace(state={}), req) is None
    seen = {declaration.name: declaration for declaration in req.config.tools[0].function_declarations}
    properties = {name: declaration.parameters_json_schema["properties"] for name, declaration in seen.items()}

    for name, declaration in seen.items():
        assert declaration.description == full[name].split("\n\n", 1)[0], f"{name} : premier paragraphe coupé"
    assert set(properties["pokemon_search"]["type_match"]["enum"]) == {"all", "any", "exact"}
    assert properties["pokemon_search"]["pokedex_number"].get("description")
    description = properties["pokemon_moves"]["damage_class"].get("description", "")
    assert all(value in description for value in ("physical", "special", "status"))
    # Convention de direction : cible nommée → faits, ou propriétés → Pokémon.
    for name, declaration in seen.items():
        if name != "pokemon_rag_search":
            named = "pokemon" in declaration.parameters_json_schema.get("required", [])
            assert declaration.description.startswith("Pokémon" if named else "Propriétés → Pokémon"), name

    # L'instruction ne cite que des outils existants ; les règles d'arguments vivent dans les schémas.
    assert set(re.findall(r"\bpokemon_\w+", root_agent.instruction)) <= set(seen)
