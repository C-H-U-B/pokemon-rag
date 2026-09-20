from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

# Permet de lancer le test depuis la racine du projet :
# python pokemon/test_pokemon_query_engine.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pokemon.pokemon_query_engine import get_evolutions


PASSED = 0
FAILED = 0


def check(condition: bool, message: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {message}")
    else:
        FAILED += 1
        print(f"  ✗ {message}")


def find_evolution(result: dict, target_identifier: str, version_group: str | None = None):
    for evolution in result["evolutions"]:
        if evolution["to"]["identifier"] != target_identifier:
            continue
        if version_group is not None and evolution["version_group"] != version_group:
            continue
        return evolution
    return None


def test_pikachu() -> None:
    result = get_evolutions("Pikachu")

    check(result["count"] == 2, "Pikachu possède 2 règles d'évolution historiques")

    normal = find_evolution(result, "raichu", "red-blue")
    alola = find_evolution(result, "raichu", "sun-moon")

    check(normal is not None, "Pikachu → Raichu est présent")
    check(alola is not None, "Pikachu → Raichu d'Alola est présent")

    if normal:
        check(
            normal["conditions"].get("trigger_item", {}).get("fr") == "Pierre Foudre",
            "Raichu utilise la Pierre Foudre",
        )

    if alola:
        check(
            alola["to"].get("form", {}).get("form_identifier") == "alola",
            "La cible de la règle Soleil/Lune est bien Raichu d'Alola",
        )
        check(
            alola["conditions"].get("region", {}).get("fr") == "Alola",
            "La règle de Raichu d'Alola est liée à la région Alola",
        )


def test_dinoclier() -> None:
    result = get_evolutions("Dinoclier")

    check(result["count"] == 1, "Dinoclier possède une règle d'évolution")
    evo = find_evolution(result, "bastiodon")

    check(evo is not None, "Dinoclier → Bastiodon")
    if evo:
        check(evo["trigger"] == "level-up", "Déclencheur : montée de niveau")
        check(
            evo["conditions"].get("minimum_level") == 30,
            "Niveau minimum : 30",
        )


def test_debugant() -> None:
    result = get_evolutions("Debugant")

    check(result["count"] == 3, "Debugant possède 3 branches d'évolution")

    kicklee = find_evolution(result, "hitmonlee")
    tygnon = find_evolution(result, "hitmonchan")
    kapoera = find_evolution(result, "hitmontop")

    check(kicklee is not None, "Debugant → Kicklee")
    check(tygnon is not None, "Debugant → Tygnon")
    check(kapoera is not None, "Debugant → Kapoera")

    if kicklee:
        check(
            kicklee["conditions"].get("relative_physical_stats") == 1,
            "Kicklee : statistique physique relative = 1",
        )
    if tygnon:
        check(
            tygnon["conditions"].get("relative_physical_stats") == -1,
            "Tygnon : statistique physique relative = -1",
        )
    if kapoera:
        check(
            kapoera["conditions"].get("relative_physical_stats") == 0,
            "Kapoera : statistique physique relative = 0",
        )


def test_sepiatop() -> None:
    result = get_evolutions("Sepiatop")
    evo = find_evolution(result, "malamar")

    check(result["count"] == 1, "Sepiatop possède une règle d'évolution")
    check(evo is not None, "Sepiatop → Sepiatroce")

    if evo:
        check(
            evo["conditions"].get("minimum_level") == 30,
            "Sepiatop : niveau minimum 30",
        )
        check(
            evo["conditions"].get("turn_upside_down") == 1,
            "Sepiatop : console retournée",
        )


def test_tutafeh_galar() -> None:
    result = get_evolutions("Tutafeh", form="Galar")

    check(
        result["count"] == 1,
        "Tutafeh de Galar ne récupère qu'une seule règle",
    )

    evo = find_evolution(result, "runerigus")
    check(evo is not None, "Tutafeh de Galar → Tutétékri")
    check(
        find_evolution(result, "cofagrigus") is None,
        "La règle Tutafeh → Tutankafer ne déborde pas sur la forme de Galar",
    )

    if evo:
        check(
            evo["from"].get("form", {}).get("form_identifier") == "galar",
            "La forme source est explicitement Galar",
        )
        check(
            evo["conditions"].get("minimum_damage_taken") == 49,
            "Condition : au moins 49 dégâts",
        )
        check(
            evo["conditions"].get("location", {}).get("fr") == "Fosse des Sables",
            "Condition : Fosse des Sables",
        )


def test_dofin() -> None:
    result = get_evolutions("Dofin")
    evo = find_evolution(result, "palafin")

    check(result["count"] == 1, "Dofin possède une règle d'évolution")
    check(evo is not None, "Dofin → Superdofin")

    if evo:
        check(
            evo["conditions"].get("minimum_level") == 38,
            "Dofin : niveau minimum 38",
        )
        check(
            evo["conditions"].get("needs_multiplayer") == 1,
            "Dofin : multijoueur requis",
        )


def test_evoli_history() -> None:
    result = get_evolutions("Évoli")

    check(result["count"] == 19, "Évoli conserve les 19 règles historiques")

    old_leafeon = find_evolution(result, "leafeon", "diamond-pearl")
    new_leafeon = find_evolution(result, "leafeon", "sword-shield")
    sylveon_xy = find_evolution(result, "sylveon", "x-y")
    sylveon_swsh = find_evolution(result, "sylveon", "sword-shield")

    check(old_leafeon is not None, "Phyllali Diamant/Perle est présent")
    check(new_leafeon is not None, "Phyllali Épée/Bouclier est présent")
    check(sylveon_xy is not None, "Nymphali X/Y est présent")
    check(sylveon_swsh is not None, "Nymphali Épée/Bouclier est présent")

    if old_leafeon:
        check(
            old_leafeon["conditions"].get("near_special_rock") == 1,
            "Phyllali Diamant/Perle utilise la condition du rocher spécial",
        )
    if new_leafeon:
        check(
            new_leafeon["conditions"].get("trigger_item", {}).get("fr") == "Pierre Plante",
            "Phyllali Épée/Bouclier utilise la Pierre Plante",
        )
    if sylveon_xy:
        check(
            sylveon_xy["conditions"].get("minimum_affection") == 2,
            "Nymphali X/Y utilise l'affection",
        )
    if sylveon_swsh:
        check(
            sylveon_swsh["conditions"].get("minimum_happiness") == 160,
            "Nymphali Épée/Bouclier utilise le bonheur",
        )


def test_version_filter() -> None:
    result = get_evolutions("Évoli", version_group="sword-shield")

    check(result["count"] == 3, "Filtre version_group=sword-shield : 3 règles")
    check(
        all(e["version_group"] == "sword-shield" for e in result["evolutions"]),
        "Aucune règle d'une autre version ne passe le filtre",
    )


def test_invalid_inputs() -> None:
    try:
        get_evolutions("PokémonQuiNExistePas")
    except ValueError:
        check(True, "Pokémon inconnu : échec contrôlé")
    else:
        check(False, "Pokémon inconnu : aurait dû lever ValueError")

    try:
        get_evolutions("Tutafeh", form="FormeQuiNExistePas")
    except ValueError:
        check(True, "Forme inconnue : échec contrôlé")
    else:
        check(False, "Forme inconnue : aurait dû lever ValueError")


TESTS: list[tuple[str, Callable[[], None]]] = [
    ("Pikachu / forme cible régionale", test_pikachu),
    ("Dinoclier / niveau", test_dinoclier),
    ("Debugant / branches statistiques", test_debugant),
    ("Sepiatop / condition spéciale", test_sepiatop),
    ("Tutafeh de Galar / isolation de forme", test_tutafeh_galar),
    ("Dofin / multijoueur", test_dofin),
    ("Évoli / historique des méthodes", test_evoli_history),
    ("Filtrage par version", test_version_filter),
    ("Entrées invalides", test_invalid_inputs),
]


def main() -> int:
    global PASSED, FAILED

    start = time.perf_counter()

    print("=" * 90)
    print("TESTS pokemon_query_engine — get_evolutions()")
    print("=" * 90)

    for index, (name, test) in enumerate(TESTS, 1):
        print(f"\n[{index}/{len(TESTS)}] {name}")
        test()

    elapsed = time.perf_counter() - start

    print("\n" + "=" * 90)
    print(f"Assertions réussies : {PASSED}")
    print(f"Assertions échouées : {FAILED}")
    print(f"Temps total          : {elapsed:.3f} s")
    print("=" * 90)

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
