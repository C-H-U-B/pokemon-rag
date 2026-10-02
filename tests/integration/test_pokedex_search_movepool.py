"""Vrai SQLite + moteur : adversaires synthétiques sans LLM ni données externes."""
import sqlite3

import pytest

from pokemon_rag.structured import query_engine as engine


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    path = tmp_path / "catalogue.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE language_ids(fr INTEGER, en INTEGER);
        INSERT INTO language_ids VALUES(5,9);
        CREATE TABLE pokemon_species(id INTEGER,identifier TEXT,generation_id INTEGER,is_legendary TEXT,is_mythical TEXT);
        INSERT INTO pokemon_species VALUES (38,'ninetales',1,'0','0'),(369,'relicanth',3,'0','0'),
            (245,'suicune',2,'1','0'),(385,'jirachi',3,'0','1'),(352,'kecleon',3,'0','0');
        CREATE TABLE pokemon_species_names(pokemon_species_id INTEGER,local_language_id INTEGER,name TEXT);
        INSERT INTO pokemon_species_names VALUES (38,5,'Feunard'),(369,5,'Relicanth'),
            (245,5,'Suicune'),(385,5,'Jirachi'),(352,5,'Kecleon');
        CREATE TABLE pokemon(id INTEGER,species_id INTEGER,identifier TEXT,is_default INTEGER);
        INSERT INTO pokemon VALUES (38,38,'ninetales',1),(1038,38,'ninetales-alola',0),
            (369,369,'relicanth',1),(245,245,'suicune',1),(385,385,'jirachi',1),(352,352,'kecleon',1);
        CREATE TABLE pokemon_forms(id INTEGER,pokemon_id INTEGER,identifier TEXT,form_identifier TEXT,is_default INTEGER);
        INSERT INTO pokemon_forms VALUES (38,38,'ninetales',NULL,1),(1038,1038,'ninetales-alola','alola',1),
            (369,369,'relicanth',NULL,1),(245,245,'suicune',NULL,1),(385,385,'jirachi',NULL,1),(352,352,'kecleon',NULL,1);
        CREATE TABLE custom_pokedex(pokemon_id INTEGER,pokemon_form_id INTEGER,national_number INTEGER,
            name_fr TEXT,name_en TEXT,type_1_fr TEXT,type_2_fr TEXT);
        INSERT INTO custom_pokedex VALUES (38,38,38,'Feunard','Ninetales','Feu',NULL),
            (1038,1038,38,'Feunard d’Alola','Alolan Ninetales','Glace','Fée'),
            (369,369,369,'Relicanth','Relicanth','Eau','Roche'),
            (245,245,245,'Suicune','Suicune','Eau',NULL),
            (385,385,385,'Jirachi','Jirachi','Acier','Psy'),(352,352,352,'Kecleon','Kecleon','Normal',NULL);
        CREATE TABLE type_display(type_id INTEGER,identifier TEXT,name_fr TEXT,name_en TEXT);
        INSERT INTO type_display VALUES (1,'normal','Normal','Normal'),(2,'fighting','Combat','Fighting'),
            (10,'fire','Feu','Fire'),(11,'water','Eau','Water'),(15,'ice','Glace','Ice'),
            (6,'rock','Roche','Rock'),(18,'fairy','Fée','Fairy');
        CREATE TABLE version_groups(id INTEGER,identifier TEXT,generation_id INTEGER,"order" INTEGER);
        -- IDs volontairement contraires à l'ordre chronologique.
        INSERT INTO version_groups VALUES (99,'old',3,1),(4,'latest',9,3),(10,'middle',7,2);
        CREATE TABLE pokemon_move_methods(id INTEGER,identifier TEXT);
        INSERT INTO pokemon_move_methods VALUES (1,'level-up'),(2,'egg'),(3,'tutor'),(4,'machine');
        CREATE TABLE moves(id INTEGER,identifier TEXT,type_id INTEGER,damage_class_id INTEGER,
            power INTEGER,accuracy INTEGER,pp INTEGER);
        INSERT INTO moves VALUES (1,'flamethrower',10,3,90,100,15),(2,'ice-beam',15,3,90,100,10),
            (3,'seismic-toss',2,2,NULL,100,20),(4,'will-o-wisp',10,1,NULL,85,15),
            (5,'waterfall',11,2,80,100,15),(6,'hydro-pump',11,3,110,80,5);
        CREATE TABLE move_display(move_id INTEGER,identifier TEXT,name_fr TEXT,name_en TEXT);
        INSERT INTO move_display VALUES (1,'flamethrower','Lance-Flammes','Flamethrower'),
            (2,'ice-beam','Laser Glace','Ice Beam'),(3,'seismic-toss','Frappe Atlas','Seismic Toss'),
            (4,'will-o-wisp','Feu Follet','Will-O-Wisp'),(5,'waterfall','Cascade','Waterfall'),
            (6,'hydro-pump','Hydrocanon','Hydro Pump');
        CREATE TABLE pokemon_moves(pokemon_id INTEGER,move_id INTEGER,version_group_id INTEGER,
            pokemon_move_method_id INTEGER,level INTEGER);
        INSERT INTO pokemon_moves VALUES
            (38,2,99,4,0),(38,1,4,1,40),(38,1,4,4,0),(38,1,4,1,40),(38,4,4,1,10),
            (1038,2,10,4,0),(369,5,10,1,30),(369,6,10,4,0),(369,3,10,3,0),
            (245,2,4,1,20),(245,5,99,1,20);
        """)
    monkeypatch.setattr(engine, "DB_PATH", path)


def names(result):
    return [row["name_fr"] for row in result["results"]]


@pytest.fixture
def stat_catalogue(catalogue):
    """Même vrai moteur/SQLite ; lignes adverses pour forme, total, égalité et NULL."""
    defaults = [
        (3, "Florizarre", 1, 0, "Plante", "Poison", (80,82,83,100,100,80)),
        (6, "Dracaufeu", 1, 0, "Feu", "Vol", (78,84,78,109,85,100)),
        (92, "Fantominus", 1, 0, "Spectre", "Poison", (30,35,30,100,35,80)),
        (93, "Spectrum", 1, 0, "Spectre", "Poison", (45,50,45,115,55,95)),
        (94, "Ectoplasma", 1, 0, "Spectre", "Poison", (60,65,60,130,75,110)),
        (150, "Mewtwo", 1, 1, "Psy", None, (106,110,90,154,90,130)),
        (324, "Chartor", 3, 0, "Feu", None, (70,85,140,85,70,20)),
        (355, "Skelénox", 3, 0, "Spectre", None, (20,40,90,30,90,25)),
        (356, "Téraclope", 3, 0, "Spectre", None, (40,70,130,60,130,25)),
        (411, "Bastiodon", 4, 0, "Roche", "Acier", (60,52,168,47,138,30)),
        (555, "Darumacho", 5, 0, "Feu", None, (105,140,55,30,55,95)),
        (894, "Regieleki", 8, 1, "Électrik", None, (80,100,50,100,50,200)),
    ]
    megas = [
        (10003, 3, "Méga-Florizarre", "mega", "Plante", "Poison", (80,100,123,122,120,80)),
        (10006, 6, "Méga-Dracaufeu X", "mega-x", "Feu", "Dragon", (78,130,111,130,85,100)),
        (11006, 6, "Méga-Dracaufeu Y", "mega-y", "Feu", "Vol", (78,104,78,159,115,100)),
        (10150, 150, "Méga-Mewtwo X", "mega-x", "Combat", "Psy", (106,190,100,154,100,130)),
        (11150, 150, "Méga-Mewtwo Y", "mega-y", "Psy", None, (106,150,70,194,120,140)),
    ]
    with sqlite3.connect(engine.DB_PATH) as conn:
        conn.executescript("""
            ALTER TABLE custom_pokedex ADD COLUMN source_row INTEGER;
            UPDATE custom_pokedex SET source_row=pokemon_id;
            ALTER TABLE pokemon_forms ADD COLUMN is_mega INTEGER DEFAULT 0;
            CREATE TABLE custom_pokedex_fr(source_row INTEGER, pv INTEGER, attaque INTEGER,
                defense INTEGER, attaque_speciale INTEGER, defense_speciale INTEGER,
                vitesse INTEGER, total_de_base INTEGER);
            INSERT INTO custom_pokedex_fr VALUES
                (38,73,76,75,81,100,100,505),(1038,73,67,75,81,100,109,505),
                (369,100,90,130,45,65,55,485),(245,100,75,115,90,115,85,580),
                (385,100,100,100,100,100,100,600),(352,60,90,70,60,120,NULL,500);
            INSERT INTO type_display VALUES (8,'ghost','Spectre','Ghost'),
                (3,'flying','Vol','Flying'),(12,'grass','Plante','Grass'),(14,'psychic','Psy','Psychic');
        """)
        for identifier, name, generation, legendary, type1, type2, stats in defaults:
            conn.execute("INSERT INTO pokemon_species VALUES (?,?,?,?, '0')",
                         (identifier, name, generation, str(legendary)))
            conn.execute("INSERT INTO pokemon_species_names VALUES (?,5,?)", (identifier, name))
            conn.execute("INSERT INTO pokemon VALUES (?,?,?,1)", (identifier,identifier,name))
            conn.execute("INSERT INTO pokemon_forms VALUES (?,?,?,NULL,1,0)", (identifier,identifier,name))
            conn.execute("INSERT INTO custom_pokedex VALUES (?,?,?,?,?,?,?,?)",
                         (identifier,identifier,identifier,name,name,type1,type2,identifier))
            conn.execute("INSERT INTO custom_pokedex_fr VALUES (?,?,?,?,?,?,?,?)",
                         (identifier,*stats,sum(stats)))
        for identifier, species, name, form, type1, type2, stats in megas:
            conn.execute("INSERT INTO pokemon VALUES (?,?,?,0)", (identifier,species,name))
            conn.execute("INSERT INTO pokemon_forms VALUES (?,?,?,?,1,1)", (identifier,identifier,name,form))
            conn.execute("INSERT INTO custom_pokedex VALUES (?,?,?,?,?,?,?,?)",
                         (identifier,identifier,species,name,name,type1,type2,identifier))
            conn.execute("INSERT INTO custom_pokedex_fr VALUES (?,?,?,?,?,?,?,?)",
                         (identifier,*stats,sum(stats)))


@pytest.mark.parametrize("filters,expected,value", [
    ({"sort_by":"speed"}, ["Regieleki"], 200),
    ({"sort_by":"speed","sort_order":"asc"}, ["Chartor"], 20),
    ({"sort_by":"speed","legendary":True}, ["Regieleki"], 200),
    ({"sort_by":"attack","types":["fire"]}, ["Darumacho"], 140),
    ({"sort_by":"defense","generation":4}, ["Bastiodon"], 168),
    ({"sort_by":"special-attack","legendary":False,"mythical":False}, ["Ectoplasma"], 130),
    ({"sort_by":"special-defense","types":["water"]}, ["Suicune"], 115),
    ({"sort_by":"hp"}, ["Mewtwo"], 106),
    ({"sort_by":"base-stat-total"}, ["Mewtwo"], 680),
    ({"sort_by":"base-stat-total","types":["water"]}, ["Suicune"], 580),
    ({"sort_by":"base-stat-total","types":["fire","flying"],"type_match":"exact"}, ["Dracaufeu"], 534),
    ({"sort_by":"speed","sort_order":"asc","form_category":"mega"}, ["Méga-Florizarre"], 80),
    ({"sort_by":"attack","form_category":"mega"}, ["Méga-Mewtwo X"], 190),
    ({"sort_by":"attack","form_category":"mega","pokedex_number":6}, ["Méga-Dracaufeu X"], 130),
    ({"sort_by":"attack","pokedex_number":6}, ["Dracaufeu"], 84),
    ({"sort_by":"base-stat-total","form_category":"mega"}, ["Méga-Mewtwo X","Méga-Mewtwo Y"], 780),
    ({"sort_by":"attack","types":["fire"],"generation":1,"legendary":False,
      "mythical":False,"move_type":"fire","damage_class":"special"}, ["Feunard"], 76),
])
def test_filtered_base_stat_superlatives_sql(stat_catalogue, filters, expected, value):
    result = engine.search_pokemon(**{"sort_order":"desc", "best_only":True, **filters})
    assert names(result) == expected
    assert result["best_value"] == value
    assert all(row["base_stat_value"] == value for row in result["results"])
    assert result["tie"] == (len(expected) > 1)
    assert result["tie_count"] == result["total_count"] == len(expected)


def test_top_n_with_ties_has_stable_sql_order_and_pagination(stat_catalogue):
    result = engine.search_pokemon(sort_by="speed", sort_order="desc", limit=10)
    assert names(result) == ["Regieleki","Mewtwo","Ectoplasma","Dracaufeu","Feunard",
                            "Jirachi","Spectrum","Darumacho","Suicune","Florizarre"]
    assert result["returned_count"] == 10 and result["has_more"]
    assert "tie" not in result  # top N, pas un ensemble de gagnants
    assert names(engine.search_pokemon(sort_by="speed", sort_order="desc", limit=3, offset=3)) == [
        "Dracaufeu","Feunard","Jirachi"]
    ghosts = engine.search_pokemon(types=["ghost"], sort_by="special-attack", sort_order="desc", limit=5)
    assert names(ghosts) == ["Ectoplasma","Spectrum","Fantominus","Téraclope","Skelénox"]
    assert ghosts["returned_count"] == 5

    totals = engine.search_pokemon(sort_by="base-stat-total", sort_order="desc", limit=10)
    assert names(totals) == ["Mewtwo","Jirachi","Suicune","Regieleki","Dracaufeu",
                            "Florizarre","Feunard","Ectoplasma","Bastiodon","Relicanth"]
    assert [row["base_stat_total"] for row in totals["results"]] == [680,600,580,580,534,525,505,500,495,485]


def test_mega_category_and_exact_form_are_intersected_without_default_fallback(stat_catalogue):
    result = engine.search_pokemon(form_category="mega", form="mega-x", types=["fire"], sort_by="attack")
    assert names(result) == ["Méga-Dracaufeu X"]
    assert result["results"][0]["base_stat_value"] == 130
    assert engine.search_pokemon(form_category="mega", form="alola")["results"] == []
    # Une Méga n'est pas déduite du nom ni de son identifiant.
    with sqlite3.connect(engine.DB_PATH) as conn:
        conn.execute("UPDATE pokemon_forms SET is_mega=0 WHERE id=10150")
    winners = engine.search_pokemon(form_category="mega", sort_by="attack", sort_order="desc", best_only=True)
    assert names(winners) == ["Méga-Mewtwo Y"]


def test_best_only_detects_ties_even_when_page_shows_one_winner(stat_catalogue):
    args = {"types":["fire"],"generation":1,"sort_by":"speed","sort_order":"desc","best_only":True}
    complete = engine.search_pokemon(**args)
    assert names(complete) == ["Dracaufeu","Feunard"]
    first = engine.search_pokemon(**args, limit=1)
    assert names(first) == ["Dracaufeu"]
    assert first["tie"] and first["tie_count"] == 2 and first["best_value"] == 100
    assert first["matching_count"] == 2 and first["truncated"] and first["has_more"]
    assert names(engine.search_pokemon(**args, limit=1, offset=1)) == ["Feunard"]
    assert engine.search_pokemon(**args, limit=0)["total_count"] == 2


def test_total_uses_six_fields_not_stored_total_and_excludes_incomplete_rows(stat_catalogue):
    with sqlite3.connect(engine.DB_PATH) as conn:
        conn.execute("UPDATE custom_pokedex_fr SET total_de_base=9999 WHERE source_row=369")
        conn.execute("UPDATE custom_pokedex_fr SET attaque=9999 WHERE source_row=352")
    result = engine.search_pokemon(sort_by="base-stat-total", sort_order="desc", best_only=True)
    assert names(result) == ["Mewtwo"] and result["best_value"] == 680
    assert result["results"][0]["base_stat_total"] == 680
    assert engine.search_pokemon(pokedex_number=352, sort_by="base-stat-total")["total_count"] == 0


@pytest.mark.parametrize("sort_by", ["hp","PV","Attaque","Défense","Attaque Spéciale",
                                    "Défense Spéciale","Vitesse","base_stat_total","total de base"])
def test_stat_identifiers_and_french_labels_share_one_mapping(stat_catalogue, sort_by):
    result = engine.search_pokemon(pokedex_number=385, sort_by=sort_by)
    assert result["results"][0]["base_stat_value"] == (600 if "total" in sort_by else 100)


@pytest.mark.parametrize("filters,match", [
    ({"sort_by":"attack DESC; DROP TABLE pokemon"},"sort_by"),
    ({"sort_by":None},"sort_by"),({"sort_by":[]},"sort_by"),
    ({"sort_order":"DESC"},"sort_order"),({"sort_order":[]},"sort_order"),
    ({"best_only":1},"best_only"),({"best_only":True},"best_only"),
    ({"form_category":"regional"},"form_category"),({"form_category":False},"form_category"),
])
def test_invalid_ranking_arguments_rejected_before_sql(stat_catalogue, filters, match):
    with pytest.raises(ValueError, match=match):
        engine.search_pokemon(**filters)


def test_empty_superlative_does_not_invent_a_winner(stat_catalogue):
    result = engine.search_pokemon(generation=4, legendary=True, sort_by="defense", best_only=True)
    assert result["results"] == [] and result["total_count"] == result["matching_count"] == 0
    assert result["best_value"] is None and result["tie_count"] == 0 and not result["tie"]


@pytest.mark.real_data
@pytest.mark.parametrize("filters,expected,value", [
    ({"sort_by":"speed","sort_order":"desc","legendary":True}, ["Regieleki"], 200),
    ({"sort_by":"speed","sort_order":"asc"}, ["Caratroc","Goinfrex","Concombaffe"], 5),
    ({"sort_by":"attack","sort_order":"desc","types":["Feu"]}, ["Darumacho"], 140),
    ({"sort_by":"defense","sort_order":"desc","generation":4}, ["Bastiodon"], 168),
    ({"sort_by":"speed","sort_order":"asc","form_category":"mega"}, ["Méga-Ténéfix","Méga-Camérupt"], 20),
    ({"sort_by":"attack","sort_order":"desc","form_category":"mega"}, ["Méga-Mewtwo X"], 190),
    ({"sort_by":"base-stat-total","sort_order":"desc"}, ["Arceus Normal"], 720),
    ({"sort_by":"base-stat-total","sort_order":"desc","types":["Eau","Vol"],"type_match":"exact"}, ["Léviator"], 540),
])
def test_rankings_against_actual_catalogue_without_llm(filters, expected, value):
    result = engine.search_pokemon(**filters, best_only=True)
    assert names(result) == expected and result["best_value"] == value


@pytest.mark.parametrize("filters,expected", [
    ({"types": ["Eau"]}, ["Suicune", "Relicanth"]),
    ({"types": ["water", "Roche"]}, ["Relicanth"]),
    ({"types": ["Roche", "Eau"], "type_match": "exact"}, ["Relicanth"]),
    ({"types": ["Eau"], "type_match": "exact"}, ["Suicune"]),
    ({"types": ["Feu", "water"], "type_match": "any"}, ["Feunard", "Suicune", "Relicanth"]),
    ({"pokedex_number": 369}, ["Relicanth"]),
    ({"generation": 3, "mythical": True}, ["Jirachi"]),
    ({"generation": 2, "legendary": True, "mythical": False}, ["Suicune"]),
    ({"types": ["Glace"]}, []),
    ({"types": ["Glace"], "form": "alola", "generation": 1}, ["Feunard d’Alola"]),
    ({"types": ["Eau"], "move_type": "Glace", "damage_class": "special"}, ["Suicune"]),
    ({"move_type": "Glace", "generation": 1}, []),  # ancien apprentissage exclu
    ({"move_type": "Glace", "generation": 1, "version_group": "old"}, ["Feunard"]),
    ({"move_type": "Glace", "form": "alola"}, ["Feunard d’Alola"]),
    ({"damage_class": "physical", "max_power": 80, "min_level": 30}, ["Relicanth"]),
])
def test_combined_search_sql(catalogue, filters, expected):
    assert names(engine.search_pokemon(**filters)) == expected


def test_species_generation_and_default_form_not_form_generation(catalogue):
    result = engine.search_pokemon(pokedex_number=38)
    assert names(result) == ["Feunard"]
    assert result["total_count"] == 1
    regional = engine.search_pokemon(form="alola", generation=1)
    assert names(regional) == ["Feunard d’Alola"]


@pytest.mark.parametrize("pokemon,form,version,expected", [
    ("Feunard", None, None, "latest"),
    ("Relicanth", None, None, "middle"),
    ("Feunard", "alola", None, "middle"),
    ("Feunard", None, "old", "old"),
    ("Kecleon", None, None, None),
])
def test_latest_available_before_filtering(catalogue, pokemon, form, version, expected):
    result = engine.get_pokemon_moves(pokemon, form=form, version_group=version)
    assert result["version_group"] == expected
    assert result["version_group_explicit"] == (version is not None)
    assert result["movepool_available"] == (expected is not None)


def test_no_historical_union_and_no_fallback_after_filter(catalogue):
    result = engine.get_pokemon_moves("Feunard", move_type="Glace")
    assert result["total_count"] == 0
    assert result["version_group"] == "latest"
    assert result["movepool_available"] is True
    explicit = engine.get_pokemon_moves("Feunard", move_type="Glace", version_group="old")
    assert names(explicit) == ["Laser Glace"]
    absent = engine.get_pokemon_moves("Relicanth", version_group="latest")
    assert absent["version_group"] == "latest"
    assert absent["movepool_available"] is False


@pytest.fixture
def menu_only_latest_game(catalogue):
    """Jeu le plus récent où tout s'apprend par une seule méthode propre, sans niveau ni CT."""
    with sqlite3.connect(engine.DB_PATH) as conn:
        conn.executescript("""
        INSERT INTO pokemon_move_methods VALUES (12,'train');
        INSERT INTO version_groups VALUES (50,'menu',9,4);
        INSERT INTO pokemon_moves VALUES (369,5,50,12,0),(369,6,50,12,0);
        """)


@pytest.mark.parametrize("filters,version,expected", [
    ({}, "menu", ["Cascade", "Hydrocanon"]),
    # Une méthode demandée sans jeu : dernier jeu où ce Pokémon a cette méthode.
    ({"learning_method":"machine"}, "middle", ["Hydrocanon"]),
    ({"min_level":10,"max_level":40}, "middle", ["Cascade"]),
    ({"learning_method":"train"}, "menu", ["Cascade", "Hydrocanon"]),
    # Méthode absente de tous les jeux : pas de jeu inventé, dernier movepool et liste vide.
    ({"learning_method":"egg"}, "menu", []),
    # Un filtre sur les propriétés d'une capacité ne change jamais de jeu.
    ({"move_type":"Combat"}, "menu", []),
    ({"move_type":"Combat","learning_method":"tutor"}, "middle", ["Frappe Atlas"]),
])
def test_requested_method_selects_latest_game_having_it(menu_only_latest_game, filters, version, expected):
    result = engine.get_pokemon_moves("Relicanth", **filters)
    assert (result["version_group"], names(result)) == (version, expected)
    assert result["movepool_available"] is True and result["version_group_explicit"] is False


def test_explicit_game_stays_strict_and_search_uses_the_same_selection(menu_only_latest_game):
    strict = engine.get_pokemon_moves("Relicanth", version_group="menu", learning_method="machine")
    assert (strict["version_group"], strict["total_count"]) == ("menu", 0)
    by_machine = engine.search_pokemon(move_type="Eau", learning_method="machine")
    assert [(row["name_fr"], row["version_group"]) for row in by_machine["results"]] == [("Relicanth", "middle")]
    any_method = engine.search_pokemon(types=["Roche"], move_type="Eau")
    assert [(row["name_fr"], row["version_group"]) for row in any_method["results"]] == [("Relicanth", "menu")]
    by_level = engine.search_pokemon(types=["Roche"], min_level=10, max_level=40)
    assert [(row["name_fr"], row["version_group"]) for row in by_level["results"]] == [("Relicanth", "middle")]


def test_unique_moves_preserve_learning_methods(catalogue):
    result = engine.get_pokemon_moves("Feunard", move_type="Feu", damage_class="special")
    assert names(result) == ["Lance-Flammes"]
    assert result["total_count"] == 1
    assert result["results"][0]["learning"] == [
        {"method": "level-up", "level": 40}, {"method": "machine", "level": 0}]
    levels = engine.get_pokemon_moves("Feunard", min_level=40, max_level=40)
    assert names(levels) == ["Lance-Flammes"]
    assert levels["results"][0]["learning"] == [{"method": "level-up", "level": 40}]
    assert names(engine.get_pokemon_moves("Feunard", max_level=39)) == ["Feu Follet"]


def test_null_power_physical_is_never_status(catalogue):
    result = engine.get_pokemon_moves("Relicanth", damage_class="physical")
    assert names(result) == ["Cascade", "Frappe Atlas"]
    atlas = result["results"][1]
    assert atlas["power"] is None
    assert atlas["damage_class_id"] == 2
    assert atlas["damage_class_fr"] == "physique"
    assert engine.get_pokemon_moves("Relicanth", damage_class="status")["total_count"] == 0
    assert names(engine.get_pokemon_moves("Relicanth", min_power=0, max_power=80)) == ["Cascade"]
    assert names(engine.get_pokemon_moves("Relicanth", min_power=100)) == ["Hydrocanon"]
    assert names(engine.get_pokemon_moves("Feunard", damage_class="status")) == ["Feu Follet"]
    assert names(engine.search_pokemon(damage_class="physical", learning_method="tutor")) == ["Relicanth"]


def test_pagination_counts_and_stable_order(catalogue):
    first = engine.search_pokemon(limit=2)
    second = engine.search_pokemon(limit=2, offset=2)
    complete = engine.search_pokemon(limit=100)
    assert names(first) + names(second) == names(complete)[:4]
    assert first["total_count"] == second["total_count"] == 5
    assert first["returned_count"] == 2 and first["truncated"] and first["has_more"]
    assert not complete["truncated"]
    count = engine.get_pokemon_moves("Relicanth", limit=0)
    assert count["results"] == [] and count["total_count"] == 3 and count["truncated"]
    last = engine.get_pokemon_moves("Relicanth", limit=1, offset=2)
    assert last["truncated"] and not last["has_more"]
    assert engine.get_pokemon_moves("Relicanth", offset=100)["total_count"] == 3


@pytest.mark.parametrize("filters", [
    {"move_type": "inexistant"}, {"damage_class": "inconnue"}, {"learning_method": "unknown"},
    {"min_power": -1}, {"min_power": True}, {"min_power": 100, "max_power": 90},
    {"min_level": 30, "max_level": 20}, {"learning_method": "machine", "min_level": 1},
    {"version_group": "unknown"}, {"limit": 101}, {"limit": None}, {"offset": -1},
])
def test_invalid_shared_filters(catalogue, filters):
    with pytest.raises(ValueError):
        engine.search_pokemon(**filters)
    with pytest.raises(ValueError):
        engine.get_pokemon_moves("Relicanth", **filters)


@pytest.mark.parametrize("filters", [
    {"types": []}, {"types": "Eau"}, {"types": ["unknown"]}, {"type_match": "guess"},
    {"legendary": 1}, {"mythical": "true"}, {"generation": 0}, {"pokedex_number": True},
])
def test_invalid_search_filters(catalogue, filters):
    with pytest.raises(ValueError):
        engine.search_pokemon(**filters)


def test_unknown_forms_and_species_not_empty_success(catalogue):
    with pytest.raises(ValueError):
        engine.get_pokemon_moves("Relicanth", form="alola")
    with pytest.raises(ValueError):
        engine.get_pokemon_moves("inconnu")


@pytest.mark.real_data
def test_real_db_lookup_classification_and_null_power():
    assert names(engine.search_pokemon(pokedex_number=369)) == ["Relicanth"]
    assert names(engine.search_pokemon(generation=3, mythical=True)) == ["Jirachi", "Deoxys Normal"]
    result = engine.get_pokemon_moves("Scarhino", version_group="scarlet-violet", damage_class="physical")
    atlas = next(row for row in result["results"] if row["identifier"] == "seismic-toss")
    assert atlas["power"] is None and atlas["damage_class_id"] == 2


@pytest.mark.real_data
def test_real_db_shared_pokemon_id_does_not_merge_arceus_types():
    result = engine.search_pokemon(pokedex_number=493)
    assert names(result) == ["Arceus Normal"]
    assert result["total_count"] == 1
    assert engine.search_pokemon(pokedex_number=493, types=["Eau"])["total_count"] == 0
    assert names(engine.search_pokemon(pokedex_number=493, form="water", types=["Eau"])) == ["Arceus Eau"]
    assert engine.get_pokemon_moves("Arceus")["form_identifier"] == "arceus-normal"


@pytest.mark.real_data
def test_fastest_default_pokemon_is_selected_in_sql():
    result = engine.search_pokemon(sort_by="speed", sort_order="desc", limit=1)
    assert names(result) == ["Regieleki"]
    assert result["results"][0]["base_speed"] == 200
    assert result["returned_count"] == 1 and result["has_more"]


def test_speed_order_pagination_missing_values_and_forms(catalogue):
    with sqlite3.connect(engine.DB_PATH) as conn:
        conn.executescript("""
            ALTER TABLE custom_pokedex ADD COLUMN source_row INTEGER;
            UPDATE custom_pokedex SET source_row=pokemon_id;
            CREATE TABLE custom_pokedex_fr(source_row INTEGER, vitesse INTEGER);
            INSERT INTO custom_pokedex_fr VALUES (38,100),(1038,109),(369,55),(245,85),(385,100),(352,NULL);
        """)
    result = engine.search_pokemon(sort_by="speed", sort_order="desc", limit=2)
    assert names(result) == ["Feunard", "Jirachi"]  # égalité départagée par numéro
    assert result["total_count"] == 4  # forme régionale et vitesse inconnue exclues
    assert names(engine.search_pokemon(sort_by="speed", sort_order="desc", offset=2)) == ["Suicune", "Relicanth"]
    assert names(engine.search_pokemon(sort_by="speed", sort_order="asc", limit=1)) == ["Relicanth"]
    assert names(engine.search_pokemon(sort_by="speed", form="alola")) == ["Feunard d’Alola"]


def test_large_catalogue_is_bounded_and_counts_unique_forms(catalogue):
    with sqlite3.connect(engine.DB_PATH) as conn:
        for value in range(2000, 2120):
            conn.execute("INSERT INTO pokemon_species VALUES (?,?,1,'0','0')", (value, str(value)))
            conn.execute("INSERT INTO pokemon VALUES (?,?,?,1)", (value, value, str(value)))
            conn.execute("INSERT INTO pokemon_forms VALUES (?,?,?,NULL,1)", (value, value, str(value)))
            conn.execute("INSERT INTO custom_pokedex VALUES (?,?,?,? ,?,'Normal',NULL)",
                         (value, value, value, str(value), str(value)))
    result = engine.search_pokemon(types=["Normal"])
    assert result["total_count"] == 121 and result["returned_count"] == 30
    assert result["truncated"] and result["has_more"]
    assert engine.search_pokemon(limit=100)["returned_count"] == 100


def test_missing_default_mapping_is_reported_without_substituting_other_form(catalogue):
    with sqlite3.connect(engine.DB_PATH) as conn:
        conn.execute("DELETE FROM custom_pokedex WHERE pokemon_id=38")
    result = engine.search_pokemon(pokedex_number=38)
    assert result["results"] == []
    assert not result["catalogue_complete"]
    assert result["catalogue_missing_default_forms"] == [{"species_id": 38, "name_fr": "Feunard"}]
    assert names(engine.search_pokemon(pokedex_number=38, form="alola")) == ["Feunard d’Alola"]
