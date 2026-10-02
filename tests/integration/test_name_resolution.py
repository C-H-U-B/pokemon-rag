import pytest

from pokemon_rag.graph.router import _canonical_pokemon_name
from pokemon_rag.structured.query_parser import _fast_species, _fast_move

pytestmark = pytest.mark.real_data


@pytest.mark.parametrize("name", ["Dracaufeu", "Charizard", "dracaufeu"])
def test_real_species_names(name):
    assert _canonical_pokemon_name(name) == "Dracaufeu"
    assert _fast_species(f"Comment {name} évolue-t-il ?") == "Dracaufeu"


def test_real_move_name():
    assert _fast_move("Comment Pikachu apprend-il Électacle ?") == "Électacle"


def test_static_evolution_reference_matches_real_database():
    import json
    import runpy
    from pathlib import Path
    from pokemon_rag.structured.query_engine import get_evolutions
    root = Path(__file__).resolve().parents[2]
    expected = json.loads((root / "benchmarks/data/answer_references.json").read_text(encoding="utf-8"))["S01"]["structured"]
    match = runpy.run_path(str(root / "benchmarks/review_answers.py"))["matches_reference"]
    assert match(get_evolutions("Pikachu"), expected)
