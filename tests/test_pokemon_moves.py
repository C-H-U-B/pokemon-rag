from __future__ import annotations

import sqlite3
import sys
import time
from pokemon_rag.config import DB_PATH

from pokemon_rag.structured.query_engine import (
    get_level_up_moves,
    get_machine_moves,
    get_move_learning_methods,
)



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


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def find_example(method: str) -> sqlite3.Row:
    """Trouve un exemple réel dans pokemon.db pour tester une méthode sans hardcoding."""
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT
                ps.identifier AS pokemon,
                m.identifier AS move,
                vg.identifier AS version_group
            FROM pokemon_moves pm
            JOIN pokemon p ON p.id = pm.pokemon_id
            JOIN pokemon_species ps ON ps.id = p.species_id
            JOIN moves m ON m.id = pm.move_id
            JOIN pokemon_move_methods pmm ON pmm.id = pm.pokemon_move_method_id
            JOIN version_groups vg ON vg.id = pm.version_group_id
            WHERE p.is_default = 1
              AND pmm.identifier = ?
            ORDER BY pm.pokemon_id, pm.version_group_id, pm.move_id
            LIMIT 1
            """,
            (method,),
        ).fetchone()
        if row is None:
            raise AssertionError(f"Aucun exemple {method!r} présent dans pokemon.db")
        return row
    finally:
        conn.close()


def test_roïtiflam_level_up() -> None:
    result = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=41,
    )
    by_name = {m["name_fr"]: m["level"] for m in result["moves"]}

    check(result["operation"] == "get_level_up_moves", "Opération correcte")
    check(result["count"] == 4, "Roitiflam a 4 capacités après le niveau 40 dans EV")
    check(by_name.get("Lance-Flammes") == 43, "Lance-Flammes niveau 43")
    check(by_name.get("Fracass’Tête") == 50, "Fracass’Tête niveau 50")
    check(by_name.get("Hurlement") == 55, "Hurlement niveau 55")
    check(by_name.get("Boutefeu") == 62, "Boutefeu niveau 62")
    check(all(m["level"] >= 41 for m in result["moves"]), "min_level=41 respecté")
    check(
        all(m["version_group"] == "scarlet-violet" for m in result["moves"]),
        "version_group strictement respecté",
    )


def test_level_boundaries() -> None:
    exact = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=50,
        max_level=50,
    )
    check(exact["count"] == 1, "Niveau exact 50 : une seule capacité")
    check(exact["moves"][0]["identifier"] == "head-smash", "Niveau 50 = head-smash")

    interval = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=43,
        max_level=50,
    )
    check(interval["count"] == 2, "Intervalle 43–50 : 2 capacités")
    check(
        {m["level"] for m in interval["moves"]} == {43, 50},
        "Bornes min/max inclusives",
    )

    empty = get_level_up_moves(
        "Roitiflam",
        version_group="scarlet-violet",
        min_level=100,
    )
    check(empty["count"] == 0, "Niveau >= 100 : résultat vide")
    check(empty["moves"] == [], "Résultat vide représenté par []")


def test_version_isolation() -> None:
    old = get_level_up_moves("Pikachu", version_group="red-blue")
    new = get_level_up_moves("Pikachu", version_group="scarlet-violet")

    check(old["count"] > 0, "Pikachu possède un learnset red-blue")
    check(new["count"] > 0, "Pikachu possède un learnset scarlet-violet")
    check(
        all(m["version_group"] == "red-blue" for m in old["moves"]),
        "Aucune fuite de version dans red-blue",
    )
    check(
        all(m["version_group"] == "scarlet-violet" for m in new["moves"]),
        "Aucune fuite de version dans scarlet-violet",
    )
    old_signature = {(m["identifier"], m["level"]) for m in old["moves"]}
    new_signature = {(m["identifier"], m["level"]) for m in new["moves"]}
    check(old_signature != new_signature, "Les learnsets red-blue et scarlet-violet diffèrent")


def test_no_version_filter() -> None:
    result = get_level_up_moves("Pikachu")
    groups = {m["version_group"] for m in result["moves"]}
    check(result["count"] > 0, "Learnset sans filtre non vide")
    check(len(groups) > 1, "Sans filtre, plusieurs version_groups sont conservés")
    check(
        result["count"] == len({
            (m["move_id"], m["level"], m["order"], m["version_group"])
            for m in result["moves"]
        }),
        "Pas de doublons artificiels dans le learnset",
    )


def test_machine_pikachu() -> None:
    result = get_machine_moves("Pikachu", version_group="scarlet-violet")
    check(result["operation"] == "get_machine_moves", "Opération machine correcte")
    check(result["count"] > 0, "Pikachu possède des machines dans EV")
    check(
        all(m["version_group"] == "scarlet-violet" for m in result["moves"]),
        "Toutes les machines appartiennent à scarlet-violet",
    )
    check(all(m["move_id"] is not None for m in result["moves"]), "Chaque machine a un move_id")
    check(all(m["identifier"] for m in result["moves"]), "Chaque machine a un identifier")
    check(
        result["count"] == len({
            (m["move_id"], m["version_group"], m["machine_number"])
            for m in result["moves"]
        }),
        "Pas de doublons artificiels dans les machines",
    )


def test_machine_version_isolation() -> None:
    old = get_machine_moves("Pikachu", version_group="red-blue")
    new = get_machine_moves("Pikachu", version_group="scarlet-violet")
    check(old["count"] > 0, "Machines Pikachu red-blue non vides")
    check(new["count"] > 0, "Machines Pikachu scarlet-violet non vides")
    check(
        all(m["version_group"] == "red-blue" for m in old["moves"]),
        "Machines red-blue isolées",
    )
    check(
        all(m["version_group"] == "scarlet-violet" for m in new["moves"]),
        "Machines scarlet-violet isolées",
    )


def test_methods_from_real_db_examples() -> None:
    # On choisit automatiquement un cas réel pour chaque méthode dans la DB,
    # puis on vérifie que le moteur retrouve cette méthode.
    for method in ("level-up", "machine", "egg", "tutor"):
        example = find_example(method)
        result = get_move_learning_methods(
            example["pokemon"],
            example["move"],
            version_group=example["version_group"],
        )
        methods = {row["method"] for row in result["methods"]}
        check(result["count"] > 0, f"{method}: exemple réel retrouvé")
        check(method in methods, f"{method}: méthode correctement restituée")


def test_electacle_contract() -> None:
    result = get_move_learning_methods("Pikachu", "Électacle")
    check(result["operation"] == "get_move_learning_methods", "Opération méthodes correcte")
    check(result["move"]["identifier"] == "volt-tackle", "Électacle résolu vers volt-tackle")
    check(result["count"] > 0, "PokéAPI contient une méthode Pikachu + Électacle")
    check(all(m["method"] for m in result["methods"]), "Chaque entrée possède une méthode")
    # On n'attend volontairement PAS la condition Balle Lumière :
    # elle n'est pas encodée dans les tables PokéAPI intégrées.


def test_french_english_resolution() -> None:
    fr = get_move_learning_methods("Dracaufeu", "Lance-Flammes")
    en = get_move_learning_methods("Charizard", "Flamethrower")

    check(fr["move"]["move_id"] == en["move"]["move_id"], "Nom FR/EN de capacité -> même move_id")
    check(fr["move"]["identifier"] == "flamethrower", "Lance-Flammes -> flamethrower")

    fr_rows = {
        (r["pokemon_id"], r["level"], r["method"], r["version_group"])
        for r in fr["methods"]
    }
    en_rows = {
        (r["pokemon_id"], r["level"], r["method"], r["version_group"])
        for r in en["methods"]
    }
    check(fr_rows == en_rows, "Nom FR/EN du Pokémon -> mêmes méthodes")


def test_form_isolation_meowth_galar() -> None:
    normal = get_level_up_moves(
        "Miaouss",
        version_group="sword-shield",
    )
    galar = get_level_up_moves(
        "Miaouss",
        form="Galar",
        version_group="sword-shield",
    )

    check(normal["count"] > 0, "Miaouss normal : learnset disponible")
    check(galar["count"] > 0, "Miaouss de Galar : learnset disponible")

    normal_signature = {(m["identifier"], m["level"]) for m in normal["moves"]}
    galar_signature = {(m["identifier"], m["level"]) for m in galar["moves"]}
    check(
        normal_signature != galar_signature,
        "Miaouss normal et Galar ne partagent pas artificiellement le même learnset",
    )


def test_valid_move_not_learned() -> None:
    # Une capacité valide mais impossible pour ce Pokémon doit produire 0,
    # et non une erreur de résolution de capacité.
    result = get_move_learning_methods(
        "Magicarpe",
        "Tonnerre",
        version_group="scarlet-violet",
    )
    check(result["move"]["identifier"] == "thunderbolt", "Tonnerre est une capacité valide")
    check(result["count"] == 0, "Magicarpe + Tonnerre : aucune méthode")


def test_invalid_inputs() -> None:
    try:
        get_move_learning_methods("Pikachouuu", "Tonnerre")
    except ValueError:
        check(True, "Pokémon inexistant : ValueError")
    else:
        check(False, "Pokémon inexistant aurait dû lever ValueError")

    try:
        get_move_learning_methods("Pikachu", "CapacitéQuiNExistePas")
    except ValueError:
        check(True, "Capacité inexistante : ValueError")
    else:
        check(False, "Capacité inexistante aurait dû lever ValueError")

    try:
        get_level_up_moves("Pikachu", form="Galar")
    except ValueError:
        check(True, "Forme inexistante : ValueError")
    else:
        check(False, "Forme inexistante aurait dû lever ValueError")

    try:
        get_level_up_moves("Pikachu", min_level=50, max_level=40)
    except ValueError:
        check(True, "Intervalle min > max : ValueError")
    else:
        check(False, "Intervalle min > max aurait dû lever ValueError")

    try:
        get_level_up_moves("Pikachu", min_level=-1)
    except ValueError:
        check(True, "Niveau négatif : ValueError")
    else:
        check(False, "Niveau négatif aurait dû lever ValueError")


def test_unknown_version_contract() -> None:
    level = get_level_up_moves("Pikachu", version_group="version-inexistante")
    machine = get_machine_moves("Pikachu", version_group="version-inexistante")
    methods = get_move_learning_methods(
        "Pikachu",
        "Tonnerre",
        version_group="version-inexistante",
    )
    check(level["count"] == 0, "Version inconnue / level-up -> 0 résultat")
    check(machine["count"] == 0, "Version inconnue / machine -> 0 résultat")
    check(methods["count"] == 0, "Version inconnue / methods -> 0 résultat")


TESTS = [
    ("Roitiflam / montée de niveau", test_roïtiflam_level_up),
    ("Bornes de niveaux", test_level_boundaries),
    ("Isolation des générations", test_version_isolation),
    ("Learnset sans version", test_no_version_filter),
    ("Pikachu / machines", test_machine_pikachu),
    ("Isolation des machines", test_machine_version_isolation),
    ("Méthodes level-up / machine / egg / tutor", test_methods_from_real_db_examples),
    ("Pikachu + Électacle", test_electacle_contract),
    ("Résolution français / anglais", test_french_english_resolution),
    ("Isolation Miaouss / Miaouss de Galar", test_form_isolation_meowth_galar),
    ("Capacité valide mais non apprenable", test_valid_move_not_learned),
    ("Entrées invalides", test_invalid_inputs),
    ("Version inconnue", test_unknown_version_contract),
]


def main() -> int:
    start = time.perf_counter()
    print("=" * 94)
    print("TESTS ÉTENDUS pokemon_query_engine — CAPACITÉS")
    print("=" * 94)

    for index, (name, fn) in enumerate(TESTS, 1):
        print(f"\n[{index}/{len(TESTS)}] {name}")
        try:
            fn()
        except Exception as exc:
            global FAILED
            FAILED += 1
            print(f"  ✗ ERREUR NON GÉRÉE : {type(exc).__name__}: {exc}")

    elapsed = time.perf_counter() - start
    print("\n" + "=" * 94)
    print(f"Assertions réussies : {PASSED}")
    print(f"Assertions échouées : {FAILED}")
    print(f"Temps total          : {elapsed:.3f} s")
    print("=" * 94)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
