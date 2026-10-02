"""Verdict et diagnostic E2E : helpers réels, aucune exécution d'agent/LLM."""
import runpy
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def reporting():
    return runpy.run_path(str(Path(__file__).parents[1] / "long/test_adk_structured_database_e2e.py"))


def ranking_case(reporting):
    case = reporting["Case"]("test", "Quels sont les Pokémon les plus lents ?", "pokemon_search",
                             {"sort_by":"speed", "sort_order":"asc", "best_only":True})
    calls = [{"name":"pokemon_search", "args":{}}]
    executions = [{"name":"pokemon_search", "args":case.expected_args, "blocked":False}]
    responses = [{"name":"pokemon_search", "response":{
        "stat_name_fr":"Vitesse", "results":[{"name_fr":"Nom français", "base_stat_value":20}]}}]
    return case, calls, executions, responses


def test_repaired_proposal_remains_diagnostic_and_not_functional_failure(reporting):
    case, calls, executions, responses = ranking_case(reporting)
    assert not all(ok for ok, _, _ in reporting["_proposal_checks"](case, calls))
    checks = reporting["_semantic_checks"](case, calls, responses, "Nom français : 20 en Vitesse", executions)
    assert all(ok for ok, _, _ in checks)


@pytest.mark.parametrize("failure", ["blocked", "wrong_args", "missing_value", "wrong_value", "budget", "mcp_error"])
def test_functional_errors_still_fail_even_when_proposal_is_ignored(reporting, failure):
    case, calls, executions, responses = ranking_case(reporting)
    answer = "Nom français : 20 en Vitesse"
    if failure == "blocked":
        executions[0]["blocked"] = True
    elif failure == "wrong_args":
        executions[0]["args"] = {"best_only":False}
    elif failure == "missing_value":
        answer = "Nom français"
    elif failure == "wrong_value":
        answer = "Nom français : 200 en Vitesse"
    elif failure == "budget":
        answer = "Je n'ai pas pu obtenir une réponse fiable dans les limites de traitement."
    else:
        responses[0]["response"]["error"] = "failure"
    assert not all(ok for ok, _, _ in reporting["_semantic_checks"](case, calls, responses, answer, executions))


@pytest.mark.parametrize("level", [18,30,42])
def test_added_evolution_level_absent_from_tool_is_rejected_generically(reporting,level):
    result = {"operation":"get_evolutions","evolutions":[{"conditions":{"known_move":{"fr":"Capacité française","en":"English Move"}}}]}
    checks = reporting["_factual_checks"](result,f"Évolue au niveau {level} en connaissant Capacité française.")
    assert not all(ok for ok,_,_ in checks)
    result["evolutions"][0]["conditions"]["minimum_level"] = level
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,f"Évolue au niveau {level}."))


def test_english_added_even_after_adk_projection_is_detected_from_raw_mcp(reporting):
    case,calls,executions,responses = ranking_case(reporting)
    raw = [{"name":"pokemon_search","origin":"mcp","response":{"structuredContent":{
        "results":[{"name_fr":"Nom français","name_en":"English Name"}]}}}]
    checks = reporting["_semantic_checks"](case,calls,responses,"Nom français (English Name) : 20",executions,raw)
    assert not all(ok for ok,_,_ in checks)


def test_large_simple_list_requires_some_sourced_names_and_added_statistic_is_rejected(reporting):
    result = {"operation":"search_pokemon", "results":[{"name_fr":f"Nom {i}"} for i in range(30)]}
    assert not all(ok for ok,_,_ in reporting["_factual_checks"](result,"Une réponse quelconque"))
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,"Exemples : Nom 1, Nom 2"))
    result = {"operation":"search_pokemon","stat_name_fr":"Vitesse",
              "results":[{"name_fr":"Espèce","base_stat_value":100}]}
    assert not all(ok for ok,_,_ in reporting["_factual_checks"](result,"Espèce : 100, Vitesse : 200"))


def test_game_labels_are_french_when_available(reporting):
    result = {"operation":"get_move_learning_methods","version_group":"sword-shield"}
    assert not all(ok for ok,_,_ in reporting["_factual_checks"](result,"Dans Sword & Shield"))
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,"Dans Pokémon Épée et Bouclier"))


def test_type_aliases_are_compared_semantically_and_defaults_are_not_missing_constraints(reporting):
    assert reporting["_arg_matches"](["Eau","Flying"],["water","flying"],"types")
    assert not reporting["_arg_matches"](["Eau"],["water","flying"],"types")
    assert reporting["_arg_matches"]("Eau","water","move_type")
    assert reporting["_arg_matches"]("Physique","physical","damage_class")
    case = reporting["Case"]("list","Des Pokémon Spectre", "pokemon_search",{"best_only":False})
    executions = [{"name":"pokemon_search","args":{},"effective_args":{"best_only":False},"blocked":False}]
    assert all(ok for ok,_,_ in reporting["_semantic_checks"](case,[],
        [{"name":"pokemon_search","response":{"operation":"search_pokemon","results":[{"name_fr":"Nom"}]}}],
        "Nom",executions))


def test_valid_move_alias_is_checked_against_resolved_tool_identity(reporting):
    case = reporting["Case"]("move", "Comment apprendre Toxik ?", "get_move_learning_methods", {"move":"Toxik"})
    executions = [{"name":case.expected_tool,"args":{"move":"toxic"},"blocked":False}]
    responses = [{"name":case.expected_tool,"response":{"move":{"name_fr":"Toxik","name_en":"Toxic"},"methods":[]}}]
    assert all(ok for ok,_,_ in reporting["_semantic_checks"](case,[],responses,"Toxik",executions))


def test_french_label_containing_an_english_word_is_not_an_added_english_name(reporting):
    result = {"operation":"get_machine_moves","moves":[
        {"name_fr":"Abri","name_en":"Protect"},{"name_fr":"Rune Protect","name_en":"Safeguard"}]}
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,"CT : Abri, Rune Protect"))
    assert not all(ok for ok,_,_ in reporting["_factual_checks"](result,"CT : Abri (Protect), Rune Protect"))


def test_rank_number_on_next_line_is_not_read_as_a_statistic_value(reporting):
    result = {"operation":"search_pokemon","stat_name_fr":"PV","results":[
        {"name_fr":"Premier","base_stat_value":255},{"name_fr":"Second","base_stat_value":250}]}
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,"1. Premier - 255 PV  \n2. Second - 250 PV"))
    assert not all(ok for ok,_,_ in reporting["_factual_checks"](result,"Premier 255, Second 250, PV : 300"))


def test_omitted_argument_equal_to_schema_default_is_not_a_proposal_gap(reporting):
    case = reporting["Case"]("list","Des Pokémon Spectre","pokemon_search",{"best_only":False,"limit":5})
    calls = [{"name":"pokemon_search","args":{},"effective_args":{"best_only":False,"limit":30}}]
    assert [ok for ok,_,_ in reporting["_proposal_checks"](case,calls)] == [True,False]


def test_ranking_value_is_checked_under_its_projected_statistic_name(reporting):
    result = {"operation":"search_pokemon","stat_name_fr":"Vitesse","results":[{"name_fr":"Espèce","Vitesse":200}]}
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,"Espèce : 200 de Vitesse"))
    assert not all(ok for ok,_,_ in reporting["_factual_checks"](result,"Espèce"))


def test_level_from_a_filtered_movepool_row_is_a_proven_level(reporting):
    result = {"operation":"get_pokemon_moves","results":[
        {"name_fr":"Capacité","learning":[{"method":"montée de niveau","level":39},{"method":"CT/CS"}]}]}
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,"Capacité, apprise au niveau 39."))
    assert not all(ok for ok,_,_ in reporting["_factual_checks"](result,"Capacité, apprise au niveau 12."))


def test_french_game_title_containing_its_identifier_is_not_an_english_name(reporting):
    result = {"operation":"get_pokemon_moves","version_group":"champions","results":[]}
    assert all(ok for ok,_,_ in reporting["_factual_checks"](result,"Dans Pokémon Champions, aucune capacité."))
