"""Invariants avant outil : extracteurs réels, catalogue et contexte injectés.

Risque : une contrainte utilisateur oubliée/contredite atteint l'outil, ou un
nombre/adjectif hors contexte devient un filtre. Aucun serveur, base ou LLM.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pokemon_rag.agent.tool_guard import before_tool_guard
from pokemon_rag.constraints.query_constraints import (
    extract_explicit_constraints, extract_generation, extract_move_constraints,
    extract_national_pokedex_number, extract_pokemon_types, extract_power_bounds,
)


CATALOGUE = [("porygon-z", "Porygon-Z", None), ("munja", "Munja", None),
             ("flabebe", "Flabébé", None), ("krakos", "Krakos", None),
             ("motisma", "Motisma", None), ("motisma-lavage", "Motisma", "rotom-wash"),
             ("nigirigon", "Nigirigon", None), ("gouroutan", "Gouroutan", None)]


@pytest.fixture(autouse=True)
def catalogue(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue", lambda: CATALOGUE)


def guard(question, name, args):
    ctx = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(text=question)]))
    return before_tool_guard(SimpleNamespace(name=name), args, ctx)


@pytest.mark.parametrize("proposal", [{}, {"damage_class":"special","move_type":"water","min_power":80},
                                    {"damage_class":"physical","move_type":"fire","min_power":120,"max_power":130}])
def test_explicit_move_filters_are_authoritative_and_idempotent(proposal):
    question = "Quelles capacités SPÉCIALES de type Eau d'au moins 80 de puissance Nigirigon peut-il apprendre ?"
    args = {"pokemon":"Gourgeist", **proposal}
    assert guard(question,"pokemon_moves",args) is None
    assert args == {"pokemon":"Nigirigon","damage_class":"special","move_type":"water",
                    "min_power":80,"max_power":None}
    repaired = deepcopy(args)
    assert guard(question,"pokemon_moves",args) is None
    assert args == repaired


@pytest.mark.parametrize("name", ["pokemon_machine_moves","pokemon_level_up_moves","pokemon_types","pokemon_rag_search"])
def test_incompatible_tools_cannot_silently_drop_move_constraints_or_mutate_proposal(name):
    args = {"pokemon":"Wrong species"}
    original = deepcopy(args)
    result = guard("Quelles capacités physiques Krakos peut-il apprendre ?",name,args)
    assert result["error"] == "unsupported_move_constraints"
    assert result["required_arguments"]["damage_class"] == "physical"
    assert args == original


@pytest.mark.parametrize("question,expected", [
    ("Quelles attaques physiques Munja apprend-il ?", {"damage_class":"physical"}),
    ("Quelles capacités de statut Flabébé peut-il apprendre ?", {"damage_class":"status"}),
    ("Quelles capacités de catégorie spéciale Motisma apprend-il ?", {"damage_class":"special"}),
    ("Quel Pokémon peut apprendre une attaque Eau spéciale ?", {"move_type":"water","damage_class":"special"}),
    ("Quel Pokémon a la meilleure Attaque Spéciale ?", {}),
    ("Quels Pokémon ont les meilleures Attaques Spéciales ?", {}),
    ("Quelle est la Défense Spéciale de Munja ?", {}),
    ("Décris l'apparence physique de Munja", {}),
    ("Des capacités de puissance inconnue", {}),
])
def test_damage_class_is_attached_to_moves_and_never_inferred_from_power_or_statistics(question,expected):
    assert extract_move_constraints(question) == expected


@pytest.mark.parametrize("question", ["Des capacités physiques ou spéciales", "Des attaques Eau et Feu",
                                     "Des capacités spéciales et physiques", "Sans les capacités physiques",
                                     "Des capacités spéciales de type Eau ou Glace"])
def test_move_disjunctions_and_negations_are_blocked(question):
    args = {"pokemon":"Munja"}
    result = guard(question,"pokemon_moves",args)
    assert result["error"] == "invalid_explicit_constraints"
    assert args == {"pokemon":"Munja"}


@pytest.mark.parametrize("question,expected", [
    ("Des capacités d'au moins 100 de puissance", (100,None)),
    ("Des capacités d'au plus 95 de puissance", (None,95)),
    ("Des capacités de plus de 80 de puissance", (81,None)),
    ("Des capacités de moins de 80 de puissance", (None,79)),
    ("Des capacités de puissance entre 70 et 100", (70,100)),
    ("Des capacités entre 70 et 100 de puissance", (70,100)),
    ("Des capacités de puissance 90", (90,90)),
    ("Des capacités de puissance 90 minimum", (90,None)),
    ("Des capacités de puissance 90 maximum", (None,90)),
    ("Top 5 Pokémon de génération 7 au niveau 40", None),
])
def test_power_uses_only_explicit_numeric_power_relationship(question,expected):
    assert extract_power_bounds(question) == expected


@pytest.mark.parametrize("question", ["Des capacités de puissance entre 100 et 80",
                                     "Des capacités de puissance 80 ou 100",
                                     "Des capacités d'environ 100 de puissance",
                                     "Des capacités de puissance >= 80",
                                     "Des capacités d'au moins -100 de puissance",
                                     "Des capacités de puissance 80,5"])
def test_ambiguous_or_impossible_power_never_becomes_an_exact_filter(question):
    args = {"pokemon":"Munja","min_power":80}
    assert guard(question,"pokemon_moves",args)["error"] == "invalid_explicit_constraints"
    assert args == {"pokemon":"Munja","min_power":80}


def test_all_numeric_domains_and_move_filters_survive_together():
    question = ("Quels Pokémon numéro 369 du Pokédex national de génération 3 apprennent "
                "des capacités physiques de type Eau d'au moins 80 de puissance "
                "entre les niveaux 20 et 40 dans Pokémon Soleil ?")
    args = {"pokedex_number":25,"generation":7,"damage_class":"special","min_power":150,
            "min_level":2,"max_level":90,"version_group":"sword-shield"}
    assert guard(question,"pokemon_search",args) is None
    assert args == {"pokedex_number":369,"generation":3,"damage_class":"physical","move_type":"water",
                    "min_power":80,"max_power":None,"min_level":20,"max_level":40,
                    "learning_method":"level-up","version_group":"sun-moon"}


@pytest.mark.parametrize("number", [25, 213, 352, 618, 1000])
def test_national_number_blocks_guessed_identity_then_allows_explicit_retry(number):
    question = f"Quel Pokémon porte le numéro {number} du Pokédex national ?"
    args = {"pokemon":"Gigalith"}
    rejected = guard(question,"pokemon_pokedex_identity",args)
    assert rejected["error"] == "unsupported_pokedex_number_constraint"
    assert rejected["required_tool"] == "pokemon_search"
    retry = rejected["required_arguments"]
    assert retry == {"pokedex_number":number}
    assert guard(question,"pokemon_search",retry) is None
    assert args == {"pokemon":"Gigalith"}


@pytest.mark.parametrize("question,number", [
    ("Pokédex national 213", 213),
    ("Pokémon numéro 213 de génération 2 au niveau 30", 213),
    ("Pokémon n° 352 avec les 5 capacités les plus puissantes", 352),
    ("Pokémon de génération 7 au niveau 30", None),
])
def test_multiple_numbers_are_scoped_by_their_labels(question,number):
    assert extract_national_pokedex_number(question) == number


@pytest.mark.parametrize("question", ["Pokémon numéros 213 et 352", "Pokémon numéro 25 du Pokédex de Kanto",
                                     "Pokémon numéro 25,5"])
def test_multiple_or_regional_pokedex_numbers_are_not_national(question):
    assert guard(question,"pokemon_search",{})["error"] == "invalid_explicit_constraints"


@pytest.mark.parametrize("question,generation", [
    ("Pokémon introduits en QUATRIÈME génération", 4), ("Pokémon de 7G", 7),
    ("Pokémon de 3e génération", 3), ("Pokémon de génération 9", 9),
    ("Pokémon de première génération", 1), ("Pokémon dans Épée", None),
])
def test_generation_is_explicit_origin_not_inferred_from_game(question,generation):
    assert extract_generation(question) == generation


@pytest.mark.parametrize("question", ["Pokémon de génération 4 ou 5", "Pokémon de générations 4 et 5",
                                     "Pokémon après la quatrième génération", "Pokémon de génération 3,5"])
def test_generation_alternatives_and_ranges_are_not_single_filters(question):
    assert guard(question,"pokemon_search",{})["error"] == "invalid_explicit_constraints"


@pytest.mark.parametrize("question,expected", [
    ("Des Pokémon de type Eau et Vol", {"types":("water","flying"),"type_match":"all"}),
    ("Des Pokémon de type Feu ou Glace", {"types":("fire","ice"),"type_match":"any"}),
    ("Des Pokémon uniquement de type Électrik", {"types":("electric",),"type_match":"exact"}),
    ("Des Pokémon Eau/Vol", {"types":("water","flying"),"type_match":"all"}),
    ("Quel Pokémon Feu apprend une attaque Eau spéciale ?", {"types":("fire",),"type_match":"all"}),
    ("Quelles capacités de type Eau Krakos apprend-il ?", {}),
    ("Quels sont les types de Flabébé ?", {}), ("Pokémon résistants au Feu", {}),
    ("Les Pokémon combattent au sol", {}),
])
def test_species_type_and_move_type_have_separate_literal_contexts(question,expected):
    assert extract_pokemon_types(question) == expected


def test_unrelated_or_does_not_turn_double_type_into_union():
    args = {"types":["fire"],"type_match":"any"}
    assert guard("Les Pokémon Eau/Vol les plus rapides, sans objets ou talents", "pokemon_search", args) is None
    assert args["types"] == ["water","flying"] and args["type_match"] == "all"


def test_generation_classifications_and_types_override_wrong_values_together():
    args = {"generation":1,"legendary":True,"mythical":False,"types":["fire"],"type_match":"any"}
    assert guard("Quels Pokémon mythiques de troisième génération sont de type Acier et Psy ?", "pokemon_search", args) is None
    assert args == {"generation":3,"mythical":True,"types":["steel","psychic"],"type_match":"all"}
    assert guard("Les Pokémon légendaires de génération 4", "pokemon_types", {})["error"] == "unsupported_search_constraints"


def test_full_form_alias_survives_wrong_species_and_form():
    args = {"pokemon":"Wrong species","form":"heat"}
    assert guard("Quels sont les types de MOTISMA LAVAGE ?", "pokemon_types", args) is None
    assert args == {"pokemon":"Motisma","form":"rotom-wash"}


def test_ambiguous_names_forms_and_regions_are_blocked_atomically():
    for question in ("Types de Munja et Flabébé", "Types des formes d'Alola et de Galar de Motisma"):
        args = {"pokemon":"Wrong species","form":"wrong"}
        assert guard(question,"pokemon_types",args) is not None
        assert args == {"pokemon":"Wrong species","form":"wrong"}


def test_no_named_species_means_no_name_invention_and_no_unrequested_numeric_filters():
    args = {"pokemon":"Chosen by model"}
    assert guard("Quelles capacités sont apprises par niveau en génération 4 ?", "pokemon_search", {}) is None
    assert guard("Des capacités spéciales", "pokemon_moves", args) is None
    assert args == {"pokemon":"Chosen by model","damage_class":"special"}


def test_number_and_named_target_contradiction_is_blocked(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.get_pokedex_identity",lambda **kwargs:{"rows":[{"national_number":292}]})
    args = {"pokedex_number":352}
    result = guard("Pokémon numéro 352 du Pokédex national : Munja", "pokemon_search", args)
    assert result["error"] == "invalid_explicit_constraints" and args == {"pokedex_number":352}


def test_level_range_intersects_later_bound_and_does_not_ignore_alternatives():
    args = {"pokemon":"Munja","min_level":1,"max_level":99}
    assert guard("Capacités Munja entre les niveaux 10 et 30 et avant le niveau 20", "pokemon_level_up_moves", args) is None
    assert (args["min_level"],args["max_level"]) == (10,19)
    assert guard("Capacités entre les niveaux 10 et 30 ou au niveau 50", "pokemon_level_up_moves", {})["error"] == "ambiguous_level_constraints"
    args = {"pokemon":"Munja","min_level":90,"max_level":99}
    assert guard("Capacités Munja jusqu'au niveau 30", "pokemon_level_up_moves", args) is None
    assert args["min_level"] is None and args["max_level"] == 30
    assert guard("Capacités après le niveau 20 mais avant 40", "pokemon_level_up_moves", {})["error"] == "ambiguous_level_constraints"


@pytest.mark.parametrize("wording,bounds", [("au niveau 20 minimum",(20,None)),
                                           ("au niveau 30 maximum",(None,30)),
                                           ("au moins le niveau 20",(20,None))])
def test_explicit_inequality_cannot_be_truncated_into_exact_level(wording,bounds):
    args = {"pokemon":"Munja"}
    assert guard(f"Capacités Munja {wording}","pokemon_level_up_moves",args) is None
    assert (args["min_level"],args["max_level"]) == bounds


@pytest.mark.parametrize("title,identifier", [
    ("Ultra-Soleil", "ultra-sun-ultra-moon"), ("Rouge Feu", "firered-leafgreen"),
    ("Diamant Étincelant", "brilliant-diamond-shining-pearl"),
    ("Rubis Oméga", "omega-ruby-alpha-sapphire"), ("sword-shield", "sword-shield"),
])
def test_complete_game_title_wins_over_contained_short_alias(title,identifier):
    args = {"pokemon":"Porygon-Z","version_group":"red-blue"}
    assert guard(f"Quelles CT Porygon-Z apprend-il dans Pokémon {title} ?", "pokemon_machine_moves", args) is None
    assert args["version_group"] == identifier


@pytest.mark.parametrize("stat", ["PV", "Attaque", "Défense", "Attaque Spéciale", "Défense Spéciale", "Vitesse", "total des statistiques"])
def test_incompatible_tool_cannot_execute_recognized_ranking(stat):
    result = guard(f"Quels sont les 5 Pokémon avec le plus de {stat} ?", "pokemon_types", {})
    assert result["error"] == "unsupported_search_constraints"
    assert result["required_arguments"]["best_only"] is False
    assert result["required_arguments"]["limit"] == 5


def test_ambiguous_ranking_keeps_proposal_unchanged():
    args = {"types":["steel"],"best_only":True}
    assert guard("Quel Pokémon a le plus d'Attaque et le moins de Défense ?", "pokemon_search", args)["error"] == "invalid_explicit_constraints"
    assert args == {"types":["steel"],"best_only":True}


def test_numeric_minimum_is_not_misread_as_an_optimum_and_top_survives_level_range():
    args = {"best_only":True}
    assert guard("Quels Pokémon Feu apprennent une attaque Eau spéciale d'au moins 80 de puissance ?",
                 "pokemon_search", args) is None
    assert not args["best_only"] and args["min_power"] == 80
    assert args["damage_class"] == "special" and args["types"] == ["fire"]
    args = {"best_only":True,"limit":1}
    assert guard("Quels sont les 5 Pokémon les plus rapides qui apprennent des capacités entre les niveaux 10 et 20 ?",
                 "pokemon_search", args) is None
    assert args["limit"] == 5 and not args["best_only"]
    assert (args["min_level"],args["max_level"]) == (10,20)


def test_more_than_two_pokemon_types_cannot_be_silently_shortened():
    args = {"types":["water","flying"]}
    assert guard("Pokémon de type Eau et Vol et Feu", "pokemon_search", args)["error"] == "invalid_explicit_constraints"
    assert args == {"types":["water","flying"]}


@pytest.mark.parametrize("question,name,args,expected", [
    ("Quelles capacités spéciales de type Eau d'au moins 80 de puissance Nigirigon peut-il apprendre ?", "pokemon_moves",
     {"pokemon":"Nigirigon","move_type":"water","min_power":80,"learning_method":"level-up"},
     {"pokemon":"Nigirigon","move_type":"water","damage_class":"special","min_power":80,"max_power":None}),
    ("Quels Pokémon peuvent apprendre une capacité de type Eau d'au moins 80 de puissance ?", "pokemon_search",
     {"move_type":"water","min_power":80,"learning_method":"machine"}, None),
])
def test_learning_method_absent_from_the_question_is_removed(question, name, args, expected):
    assert guard(question, name, args) is None
    assert "learning_method" not in args
    if expected is not None:
        assert args == expected


@pytest.mark.parametrize("question,method", [
    ("Quelles capacités Krakos apprend-il par CT ?", "machine"),
    ("Quelles capacités Krakos peut-il apprendre grâce à la CT12 ?", "machine"),
    ("Quelles capacités Krakos apprend-il par reproduction ?", "egg"),
    ("Quelles capacités œuf Krakos peut-il apprendre ?", "egg"),
    ("Quelles capacités Krakos apprend-il auprès d'un donneur de capacités ?", "tutor"),
    ("Quelles capacités Krakos apprend-il en montant de niveau ?", "level-up"),
    ("Par quelle méthode Krakos apprend-il ses capacités de type Eau ?", "tutor"),
    ("Comment Krakos apprend-il ses capacités de type Eau ?", "egg"),
])
def test_learning_method_is_kept_as_soon_as_the_question_mentions_a_method(question, method):
    args = {"pokemon":"Krakos","learning_method":method}
    assert guard(question, "pokemon_moves", args) is None
    assert args["learning_method"] == method


def test_level_bounds_still_force_level_up_after_the_method_check():
    args = {"pokemon":"Krakos"}
    assert guard("Quelles capacités Krakos apprend-il entre les niveaux 10 et 20 ?", "pokemon_moves", args) is None
    assert (args["learning_method"], args["min_level"], args["max_level"]) == ("level-up", 10, 20)
