from __future__ import annotations

import pytest

from pokemon_rag.rag.grounding import check_grounding


pytestmark = pytest.mark.long


CASES = [
    # PASS — le contexte suffit et la réponse reste fidèle.
    pytest.param(
        "Comment Pikachu évolue-t-il ?",
        "Pikachu évolue en Raichu lorsqu'une Pierre Foudre est utilisée sur lui.",
        "Pikachu évolue en Raichu avec une Pierre Foudre.",
        "PASS",
        id="pass-evolution-paraphrase",
    ),
    pytest.param(
        "Quel est le type de Bulbizarre ?",
        "Bulbizarre est de type Plante et Poison.",
        "Bulbizarre est de type Plante et Poison.",
        "PASS",
        id="pass-types",
    ),
    pytest.param(
        "À quel niveau X apprend-il A ?",
        "X apprend A au niveau 20.",
        "X apprend A au niveau 20.",
        "PASS",
        id="pass-level",
    ),
    pytest.param(
        "Où trouve-t-on X ?",
        "X peut être rencontré dans la Forêt Verte.",
        "On trouve X dans la Forêt Verte.",
        "PASS",
        id="pass-location",
    ),

    # INSUFFICIENT — le contexte lui-même ne permet pas de répondre à la question.
    pytest.param(
        "Comment Pikachu évolue-t-il ?",
        "Pikachu est un Pokémon de type Électrik.",
        "Pikachu évolue en Raichu avec une Pierre Foudre.",
        "INSUFFICIENT",
        id="insufficient-unrelated-property",
    ),
    pytest.param(
        "Quels sont les types de X ?",
        "X est un Pokémon très rare.",
        "X est de type Feu.",
        "INSUFFICIENT",
        id="insufficient-type-missing",
    ),
    pytest.param(
        "Quelles sont les deux capacités de X ?",
        "X peut apprendre A.",
        "X peut apprendre A et B.",
        "INSUFFICIENT",
        id="insufficient-partial-list",
    ),
    pytest.param(
        "À quel niveau X apprend-il A ?",
        "X peut apprendre A.",
        "X apprend A au niveau 20.",
        "INSUFFICIENT",
        id="insufficient-level-missing",
    ),
    pytest.param(
        "Où trouve-t-on X ?",
        "X est actif principalement la nuit.",
        "On trouve X dans la Grotte Bleue.",
        "INSUFFICIENT",
        id="insufficient-location-missing",
    ),

    # CONTRADICTION — le contexte répond au point demandé et la réponse donne
    # une valeur, condition ou relation incompatible pour ce même point.
    pytest.param(
        "Quel est le type de X ?",
        "X est de type Eau.",
        "X est de type Feu.",
        "CONTRADICTION",
        id="contradiction-type",
    ),
    pytest.param(
        "À quel niveau X apprend-il A ?",
        "X apprend A au niveau 20.",
        "X apprend A au niveau 30.",
        "CONTRADICTION",
        id="contradiction-level",
    ),
    pytest.param(
        "Où trouve-t-on X ?",
        "X se trouve uniquement dans la Grotte Rouge.",
        "X se trouve uniquement dans la Grotte Bleue.",
        "CONTRADICTION",
        id="contradiction-location",
    ),
    pytest.param(
        "Comment X devient-il Y ?",
        "X devient Y grâce à l'objet A.",
        "X devient Y automatiquement au niveau 30.",
        "CONTRADICTION",
        id="contradiction-method",
    ),

    # UNSUPPORTED — le contexte est suffisant pour répondre à la question,
    # mais la réponse ajoute un fait important que le contexte n'établit pas.
    pytest.param(
        "Comment Pikachu évolue-t-il ?",
        "Pikachu évolue en Raichu lorsqu'une Pierre Foudre est utilisée sur lui.",
        "Pikachu évolue en Raichu avec une Pierre Foudre et apprend ensuite une attaque exclusive.",
        "UNSUPPORTED",
        id="unsupported-extra-claim",
    ),
    pytest.param(
        "Quel est le type de X ?",
        "X est de type Eau.",
        "X est de type Eau et vit uniquement la nuit.",
        "UNSUPPORTED",
        id="unsupported-extra-property",
    ),
    pytest.param(
        "Où trouve-t-on X ?",
        "X se trouve dans la Grotte Rouge.",
        "X se trouve dans la Grotte Rouge, où il apparaît uniquement à 1 %.",
        "UNSUPPORTED",
        id="unsupported-extra-rate",
    ),
    pytest.param(
        "À quel niveau X apprend-il A ?",
        "X apprend A au niveau 20.",
        "X apprend A au niveau 20 et B au niveau 25.",
        "UNSUPPORTED",
        id="unsupported-extra-move",
    ),

    # Contraintes de question — le contexte permet de contrôler la réponse.
    pytest.param(
        "Quelles capacités X apprend-il après le niveau 20 ?",
        "X apprend A au niveau 10, B au niveau 25 et C au niveau 40.",
        "X apprend B et C après le niveau 20.",
        "PASS",
        id="pass-explicit-constraint",
    ),
    pytest.param(
        "Quelles capacités X apprend-il après le niveau 20 ?",
        "X apprend A au niveau 10, B au niveau 25 et C au niveau 40.",
        "X apprend A, B et C après le niveau 20.",
        "CONTRADICTION",
        id="contradiction-explicit-constraint",
    ),
    pytest.param(
        "Quelles sont les deux capacités de X ?",
        "X peut apprendre A et B.",
        "X peut apprendre A.",
        "INCOMPLETE",
        id="incomplete-answer",
    ),
]


@pytest.mark.parametrize(
    ("question", "context", "answer", "expected_decision"),
    CASES,
)
def test_grounding_llm_decisions(
    question: str,
    context: str,
    answer: str,
    expected_decision: str,
) -> None:
    result = check_grounding(question, context, answer)

    assert result["decision"] == expected_decision, (
        f"decision={result['decision']} | "
        f"expected={expected_decision} | "
        f"reason={result['reason']}"
    )
    assert result["grounded"] is (expected_decision == "PASS")
    assert result["reason"]
    assert result["time"] >= 0
