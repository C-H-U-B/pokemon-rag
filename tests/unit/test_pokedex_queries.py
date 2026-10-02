import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pokemon_rag.structured import query_engine as engine, query_parser as parser
from pokemon_rag.graph.nodes import format_structured_answer, _structured_result_to_context


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    def connect():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE custom_pokedex(
              species_id INTEGER, is_default INTEGER, name_fr TEXT, name_en TEXT,
              pokemon_identifier TEXT, form_identifier TEXT, form_fr TEXT, form_en TEXT,
              type_1_fr TEXT, type_2_fr TEXT, national_number INTEGER,
              introduction_generation_fr TEXT, signature_move_fr TEXT, pseudo_signature_move_fr TEXT);
            INSERT INTO custom_pokedex VALUES
              (25,1,'Pikachu','Pikachu','pikachu','pikachu',NULL,NULL,'Électrik',NULL,25,'G1','Électacle','Tonnerre (G1)'),
              (103,1,'Noadkoko','Exeggutor','exeggutor','exeggutor',NULL,NULL,'Plante','Psy',103,'G1',NULL,NULL),
              (103,0,'Noadkoko d’Alola','Alolan Exeggutor','exeggutor-alola','exeggutor-alola','Forme d’Alola','Alolan Form','Plante','Dragon',103,'G7','Draco-Marteau (G7)',NULL);
        ''')
        return conn
    monkeypatch.setattr(engine, "_connect", connect)


@pytest.mark.parametrize("question, operation", [
    ("Quels sont les types de Pikachu ?", "get_pokemon_types"),
    ("Quel est le numéro national de Pikachu ?", "get_pokedex_identity"),
    ("Quelle est la génération d'introduction de Pikachu ?", "get_pokedex_identity"),
    ("Quelle est la capacité signature de Pikachu ?", "get_signature_moves"),
    ("Quels sont les types de Noadkoko d'Alola ?", "get_pokemon_types"),
])
def test_simple_questions_execute_without_llm(question, operation):
    with patch.object(parser.llm_client.chat.completions, "create") as llm:
        result = parser.query_structured_data(question)
    assert result["error"] is None
    assert result["operation"] == operation
    llm.assert_not_called()
    assert result["rows"]
    assert "ENTRÉE STRUCTURÉE" in _structured_result_to_context(result)


def test_forms_are_isolated_and_english_names_supported():
    base = engine.get_pokemon_types("Exeggutor")
    regional = engine.get_pokemon_types("Alolan Exeggutor")
    assert base["rows"][0]["type_2_fr"] == "Psy"
    assert regional["rows"][0]["type_2_fr"] == "Dragon"
    assert engine.get_pokemon_types("Noadkoko", "alola")["rows"] == regional["rows"]


@pytest.mark.parametrize("pokemon, form", [
    ("Inconnu", None), ("Pikachu", "alola"), ("Noadkoko d'Alola", "galar"),
    ("", None), ("---", None), (None, None), ("Pikachu", ""), ("Pikachu", 123),
])
def test_unknown_entry_or_form_is_not_replaced_by_base(pokemon, form):
    with pytest.raises(ValueError):
        engine.get_pokemon_types(pokemon, form)


def test_signature_annotations_and_missing_values_are_preserved():
    result = engine.get_signature_moves("Pikachu")
    assert "Tonnerre (G1)" in format_structured_answer({"structured_result": result})["answer"]
    missing = engine.get_signature_moves("Noadkoko")
    assert "non renseigné" in format_structured_answer({"structured_result": missing})["answer"]


def test_identity_uses_generation_of_selected_form():
    row = engine.get_pokedex_identity("Alolan Exeggutor")["rows"][0]
    assert row["national_number"] == 103
    assert row["introduction_generation_fr"] == "G7"


@pytest.mark.parametrize("operation", sorted(engine.POKEDEX_OPERATIONS))
def test_version_filters_are_rejected(operation):
    with pytest.raises(ValueError, match="version"):
        engine.validate_plan({"operation": operation, "pokemon": "Pikachu", "form": None, "version_group": "red-blue"})


@pytest.mark.parametrize("game", ["dans Rouge et Bleu", "en Rouge et Bleu", "dans JeuInconnu"])
def test_llm_cannot_silently_drop_explicit_game(game):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=
        '{"operation":"get_pokemon_types","pokemon":"Pikachu","form":null,"version_group":null}'))])
    with patch.object(parser, "_fast_parse_query", return_value=None), patch.object(
        parser.llm_client.chat.completions, "create", return_value=response
    ), patch.object(engine, "execute_plan") as execute:
        result = parser.query_structured_data(f"Quels sont les types de Pikachu {game} ?")
    assert result["error"]
    execute.assert_not_called()


def test_sql_engine_mcp_server_and_guard_load_no_llm_client():
    """Interpréteur neuf : le parcours SQL/MCP ne doit importer ni client LLM ni analyse de question."""
    import subprocess
    import sys

    code = ("import sys\n"
            "import pokemon_rag.structured.query_engine, pokemon_rag.mcp.server, pokemon_rag.agent.tool_guard\n"
            "loaded = [name for name in ('openai', 'pokemon_rag.structured.query_parser') if name in sys.modules]\n"
            "sys.exit(', '.join(loaded) or 0)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
