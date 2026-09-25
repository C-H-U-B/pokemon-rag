from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pokemon_rag.graph.graph import graph
from pokemon_rag.graph import nodes


def _llm_response(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def _router_result():
    return {
        "route": "RAG",
        "single_question": True,
        "reason": "Question documentaire.",
        "information_need": "information précise",
        "intent": "DOCUMENT_SEARCH",
        "pokemon": "Pikachu",
        "pokemon_validated": True,
    }


def _chunk(text: str, section: str):
    return {
        "id": section,
        "document": text,
        "metadata": {
            "pokemon": "Pikachu",
            "national_number": 25,
            "source_file": "pikachu.txt",
            "chunk_number": 1,
            "section_path": section,
        },
    }


def _grounding(decision: str, reason: str = "test"):
    return {
        "decision": decision,
        "reason": reason,
        "time": 0.001,
        "grounded": decision == "PASS",
    }


def _invoke():
    # On conserve l'exécution réelle du nœud de finalisation tout en
    # neutralisant l'écriture disque, qui n'appartient pas à ces tests.
    with patch("pokemon_rag.graph.graph.save_trace"):
        return graph.invoke(
            {
                "question": "Question de test sur Pikachu",
                "verbose": False,
                "retrieval_retry_count": 0,
                "generation_retry_count": 0,
            }
        )


def test_retrieval_retry_does_not_consume_generation_retry_budget():
    """
    Un contexte insuffisant doit pouvoir provoquer un retry retrieval,
    puis une mauvaise génération sur le nouveau contexte doit encore
    pouvoir provoquer son propre retry de génération.

    Politique attendue :
    INSUFFICIENT -> retry retrieval
    UNSUPPORTED -> retry answer
    PASS -> fin
    """
    first = _chunk("Contexte initial incomplet.", "Section A")
    second = _chunk("Nouveau contexte suffisant.", "Section B")

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _llm_response("Réponse initiale."),
        _llm_response("Réponse non supportée malgré le nouveau contexte."),
        _llm_response("Réponse finalement correcte."),
    ]

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]),
        patch.object(
            nodes, "retrieve_retry_context", return_value=[second]
        ) as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            side_effect=[
                _grounding("INSUFFICIENT", "Le premier contexte est insuffisant."),
                _grounding("UNSUPPORTED", "La deuxième réponse dépasse le contexte."),
                _grounding("PASS"),
            ],
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "PASS"
    assert result["answer"] == "Réponse finalement correcte."
    assert retry_retrieval.call_count == 1
    assert client.chat.completions.create.call_count == 3
    assert grounding.call_count == 3


def test_generation_retry_does_not_consume_retrieval_retry_budget():
    """
    Une mauvaise génération doit pouvoir être retentée, puis si le
    grounding conclut ensuite que le contexte est insuffisant, le budget
    de retry retrieval doit encore être disponible.

    Politique attendue :
    UNSUPPORTED -> retry answer
    INSUFFICIENT -> retry retrieval
    PASS -> fin
    """
    first = _chunk("Contexte initial.", "Section A")
    second = _chunk("Nouveau contexte suffisant.", "Section B")

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _llm_response("Réponse initiale non supportée."),
        _llm_response("Réponse retentée mais contexte finalement insuffisant."),
        _llm_response("Réponse après nouveau retrieval."),
    ]

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]),
        patch.object(
            nodes, "retrieve_retry_context", return_value=[second]
        ) as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            side_effect=[
                _grounding("UNSUPPORTED", "La première réponse dépasse le contexte."),
                _grounding("INSUFFICIENT", "Le contexte ne permet pas de répondre."),
                _grounding("PASS"),
            ],
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "PASS"
    assert result["answer"] == "Réponse après nouveau retrieval."
    assert retry_retrieval.call_count == 1
    assert client.chat.completions.create.call_count == 3
    assert grounding.call_count == 3


def test_incomplete_retries_answer_without_retrieval():
    """
    Une réponse incomplète avec un contexte suffisant doit consommer le budget
    de génération, pas le budget de retrieval.
    """
    first = _chunk("Contexte suffisant.", "Section A")

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _llm_response("Réponse incomplète."),
        _llm_response("Réponse complète."),
    ]

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]) as retrieve,
        patch.object(nodes, "retrieve_retry_context") as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            side_effect=[
                _grounding("INCOMPLETE", "La réponse omet une partie nécessaire."),
                _grounding("PASS"),
            ],
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "PASS"
    assert result["retrieval_retry_count"] == 0
    assert result["generation_retry_count"] == 1
    assert retrieve.call_count == 1
    retry_retrieval.assert_not_called()
    assert client.chat.completions.create.call_count == 2
    assert grounding.call_count == 2


def test_unknown_grounding_decision_fails_closed_without_retry():
    """
    Une décision inconnue du Grounding Checker ne doit jamais être
    interprétée implicitement comme une demande de régénération.
    """
    first = _chunk("Contexte.", "Section A")

    client = MagicMock()
    client.chat.completions.create.return_value = _llm_response("Réponse.")

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]) as retrieve,
        patch.object(nodes, "retrieve_retry_context") as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            return_value=_grounding("UNKNOWN_DECISION", "Décision invalide."),
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "UNKNOWN_DECISION"
    assert retrieve.call_count == 1
    retry_retrieval.assert_not_called()
    assert client.chat.completions.create.call_count == 1
    assert grounding.call_count == 1
