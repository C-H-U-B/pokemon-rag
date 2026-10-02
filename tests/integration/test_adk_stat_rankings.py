"""Vrai runner ADK, MCP et SQL ; modèle simulé, sans aucune inférence."""
import asyncio
import runpy
from pathlib import Path

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset
from google.genai import types
from pydantic import Field

from pokemon_rag.agent.agent import root_agent, pokemon_mcp
from pokemon_rag.agent.context_budget import _size


class WrongRankingModel(BaseLlm):
    model: str = "simulated-ranking"
    calls: int = 0
    request_sizes: list[int] = Field(default_factory=list)
    tool_counts: list[int] = Field(default_factory=list)
    proposed_name: str = "pokemon_search"
    proposed_args: dict = Field(default_factory=lambda: {"types":["Steel"],"form_category":"mega"})

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        self.tool_counts.append(len(llm_request.config.tools or []))
        self.request_sizes.append(_size({"contents":llm_request.contents,
            "system_instruction":llm_request.config.system_instruction,"tools":llm_request.config.tools}))
        assert self.calls <= 2
        if self.calls == 1:
            part = types.Part(function_call=types.FunctionCall(
                name=self.proposed_name, args=self.proposed_args))
        else:
            part = types.Part(text="Réponse simulée après résultat SQL.")
        yield LlmResponse(content=types.Content(role="model",parts=[part]))


@pytest.mark.real_data
@pytest.mark.parametrize("question,statistic,order,count,expected", [
    ("Quel est le Pokémon Méga avec le moins de Défense ?", "defense","asc",1,"Méga-Dardargnan"),
    ("Quels sont les Pokémon Méga les plus lents ?", "speed","asc",2,"Méga-Ténéfix"),
    ("Quels sont les 10 Pokémon les plus rapides ?", "speed","desc",10,"Regieleki"),
])
def test_runner_corrects_invented_filter_and_missing_ranking_without_budget_abstention(
        question, statistic, order, count, expected):
    async def run():
        model = WrongRankingModel()
        toolset = McpToolset(connection_params=pokemon_mcp.connection_params,
                             tool_filter=pokemon_mcp.tool_filter)
        agent = root_agent.model_copy(update={"model":model,"tools":[toolset]})
        runner = InMemoryRunner(agent=agent)
        try:
            session = await runner.session_service.create_session(app_name=runner.app_name,user_id="test")
            events = [event async for event in runner.run_async(user_id="test",session_id=session.id,
                new_message=types.Content(role="user",parts=[types.Part(text=question)]))]
            responses = [part.function_response.response for event in events
                         for part in (event.content.parts if event.content else []) if part.function_response]
            texts = [part.text for event in events for part in (event.content.parts if event.content else []) if part.text]
            assert responses, (texts,model.request_sizes)
            result = responses[-1]
            assert result["sort_by"] == statistic, (result,texts,model.request_sizes)
            assert result["sort_order"] == order and result["best_only"] == (count < 3)
            assert result["results"][0]["name_fr"] == expected
            assert result["returned_count"] == count
            if count == 1:
                assert result["best_value"] == 40
            if count == 2:
                assert result["best_value"] == 20 and result["tie"] and result["tie_count"] == 2
                assert {row["name_fr"] for row in result["results"]} == {"Méga-Ténéfix","Méga-Camérupt"}
                assert all(row["Vitesse"] == 20 for row in result["results"])
            assert "Réponse simulée après résultat SQL." in texts, (texts,model.request_sizes)
            assert model.calls == 2
            assert model.tool_counts[0] > 0 and model.tool_counts[1] == 0
        finally:
            await runner.close()
    asyncio.run(run())


@pytest.mark.real_data
@pytest.mark.parametrize("question,tool,args,count", [
    ("Quels sont les Pokémon légendaires de quatrième génération ?", "pokemon_search",
     {"generation":4,"legendary":True,"best_only":True},9),
    ("Quels Pokémon sont de type Eau et Vol ?", "pokemon_search",{"types":["Eau","Vol"]},8),
    ("Quelles CT Gouroutan peut-il apprendre dans Pokémon Soleil et Lune ?", "pokemon_machine_moves",
     {"pokemon":"Gourgeist","version_group":"sun-moon"},None),
])
def test_simple_lists_and_named_machine_query_reach_final_formulation_without_budget_abstention(question,tool,args,count):
    async def run():
        model = WrongRankingModel(proposed_name=tool,proposed_args=args)
        toolset = McpToolset(connection_params=pokemon_mcp.connection_params,tool_filter=pokemon_mcp.tool_filter)
        agent = root_agent.model_copy(update={"model":model,"tools":[toolset]})
        runner = InMemoryRunner(agent=agent)
        try:
            session = await runner.session_service.create_session(app_name=runner.app_name,user_id="test")
            events = [event async for event in runner.run_async(user_id="test",session_id=session.id,
                new_message=types.Content(role="user",parts=[types.Part(text=question)]))]
            result = next(part.function_response.response for event in reversed(events)
                for part in (event.content.parts if event.content else []) if part.function_response)
            assert not result.get("error") and not result.get("context_truncated")
            if count is not None:
                assert result["returned_count"] == count and not result["best_only"]
            else:
                assert result["pokemon"] == "Gouroutan" and result["moves"]
            assert model.calls == 2 and model.tool_counts[-1] == 0
            assert max(model.request_sizes) <= 12000
        finally:
            await runner.close()
    asyncio.run(run())


@pytest.mark.real_data
def test_e2e_recorder_separates_proposal_execution_raw_mcp_and_adk_projection(monkeypatch):
    helpers = runpy.run_path(str(Path(__file__).parents[1] / "long/test_adk_structured_database_e2e.py"))
    async def run():
        model = WrongRankingModel()
        toolset = McpToolset(connection_params=pokemon_mcp.connection_params,
                             tool_filter=pokemon_mcp.tool_filter)
        agent = root_agent.model_copy(update={"model":model,"tools":[toolset]})
        monkeypatch.setitem(helpers["_run_agent"].__globals__, "root_agent", agent)
        events, _, executions, raw = await helpers["_run_agent"]("Quels sont les Pokémon Méga les plus lents ?")
        assert executions[0]["proposed_args"] == {"types":["Steel"],"form_category":"mega"}
        assert helpers["_calls"](events, executions)[0]["args"] == executions[0]["proposed_args"]
        assert executions[0]["args"]["best_only"] is True
        assert executions[0]["args"]["sort_by"] == "speed" and not executions[0]["blocked"]
        assert raw[0]["origin"] == "mcp"
        raw_data = raw[0]["response"]["structuredContent"]
        adapted = helpers["_responses"](events)[0]["response"]
        assert raw_data["best_value"] == adapted["best_value"] == 20
        assert "name_en" in raw_data["results"][0]
        assert "name_en" not in adapted["results"][0]
    asyncio.run(run())


def test_long_question_reaches_the_model_within_the_real_request_budget():
    """Le vrai flux ajoute au catalogue le balisage ADK, absent d'une mesure hors runner."""
    class AnsweringModel(BaseLlm):
        model: str = "simulated-answer"
        request_sizes: list[int] = Field(default_factory=list)

        async def generate_content_async(self, llm_request, stream=False):
            self.request_sizes.append(_size({"contents":llm_request.contents,
                "system_instruction":llm_request.config.system_instruction,"tools":llm_request.config.tools}))
            yield LlmResponse(content=types.Content(role="model",parts=[types.Part(text="Réponse simulée.")]))

    async def run():
        model = AnsweringModel()
        toolset = McpToolset(connection_params=pokemon_mcp.connection_params,
                             tool_filter=pokemon_mcp.tool_filter)
        runner = InMemoryRunner(agent=root_agent.model_copy(update={"model":model,"tools":[toolset]}))
        question = "Parmi tous les Pokémon du catalogue, " + "en tenant compte de chaque précision donnée, " * 6 + "lequel est concerné ?"
        assert 300 <= len(question.encode("utf-8")) <= 350
        try:
            session = await runner.session_service.create_session(app_name=runner.app_name,user_id="test")
            texts = [part.text async for event in runner.run_async(user_id="test",session_id=session.id,
                        new_message=types.Content(role="user",parts=[types.Part(text=question)]))
                     for part in (event.content.parts if event.content else []) if part.text]
            assert texts == ["Réponse simulée."], (texts, model.request_sizes)
        finally:
            await runner.close()
    asyncio.run(run())


async def _run_simulated(question, tool, args):
    """Vrai runner, guard, MCP et projection ; le modèle simulé propose puis formule."""
    model = WrongRankingModel(proposed_name=tool, proposed_args=args)
    toolset = McpToolset(connection_params=pokemon_mcp.connection_params, tool_filter=pokemon_mcp.tool_filter)
    runner = InMemoryRunner(agent=root_agent.model_copy(update={"model":model,"tools":[toolset]}))
    try:
        session = await runner.session_service.create_session(app_name=runner.app_name,user_id="test")
        events = [event async for event in runner.run_async(user_id="test",session_id=session.id,
            new_message=types.Content(role="user",parts=[types.Part(text=question)]))]
    finally:
        await runner.close()
    parts = [part for event in events for part in (event.content.parts if event.content else [])]
    return model, [part.function_response.response for part in parts if part.function_response], [
        part.text for part in parts if part.text]


@pytest.mark.real_data
@pytest.mark.parametrize("question,args,count", [
    ("Quelles capacités physiques Sovkipou peut-il apprendre ?", {"pokemon":"Sovkipou","damage_class":"physical"}, 8),
    # Catégorie oubliée et nom remplacé : le guard répare, la petite page doit ensuite être formulée.
    ("Quelles capacités spéciales de type Eau d'au moins 80 de puissance Nigirigon peut-il apprendre ?",
     {"pokemon":"Nigirigor","move_type":"Water","min_power":80,"max_power":1000,"learning_method":"level-up"}, 3),
    ("Quelles capacités d'au moins 100 de puissance Gouroutan peut-il apprendre ?", {"pokemon":"Gourgeist","min_power":100}, 8),
])
def test_small_filtered_movepool_reaches_formulation_with_every_fact(question, args, count):
    model, responses, texts = asyncio.run(_run_simulated(question, "pokemon_moves", args))
    result = responses[-1]
    assert not result.get("error") and not result.get("context_truncated"), (result, model.request_sizes)
    assert result["total_count"] == result["returned_count"] == len(result["results"]) == count
    assert all({"name_fr","type_fr","power","damage_class_fr","learning"} <= set(row) for row in result["results"])
    assert not any({"move_id","identifier","damage_class_id","name_en"} & set(row) for row in result["results"])
    assert texts == ["Réponse simulée après résultat SQL."], (texts, model.request_sizes)
    assert model.calls == 2 and model.tool_counts[-1] == 0


@pytest.mark.real_data
def test_unfiltered_movepool_lists_every_name_without_silent_truncation():
    model, responses, texts = asyncio.run(_run_simulated(
        "Quelles capacités Sovkipou peut-il apprendre ?", "pokemon_moves", {"pokemon":"Sovkipou","limit":100}))
    result = responses[-1]
    assert result["total_count"] == result["returned_count"] == len(result["results"]) > 30
    assert not result.get("context_truncated") and not result["truncated"] and not result["has_more"]
    assert all(row.get("name_fr") for row in result["results"])
    assert texts == ["Réponse simulée après résultat SQL."] and model.tool_counts[-1] == 0


def test_guard_refusal_leaves_room_to_retry_with_the_catalogue():
    model, responses, texts = asyncio.run(_run_simulated(
        "Quel Pokémon porte le numéro 618 du Pokédex national ?", "pokemon_pokedex_identity", {"pokemon":"618"}))
    assert responses[-1]["error"] == "unsupported_pokedex_number_constraint"
    assert texts == ["Réponse simulée après résultat SQL."], (texts, model.request_sizes)
    assert model.calls == 2 and model.tool_counts[-1] > 0  # le catalogue reste disponible pour la reprise
