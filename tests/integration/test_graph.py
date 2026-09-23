from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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
    return graph.invoke(
        {
            "question": "Question de test sur Pikachu",
            "verbose": False,
            "retry_count": 0,
        }
    )


def test_pass_stops_without_any_retry():
    first = _chunk("Contexte correct.", "Section A")
    client = MagicMock()
    client.chat.completions.create.return_value = _llm_response("Réponse correcte.")

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]) as retrieve,
        patch.object(nodes, "retrieve_retry_context") as retry_retrieval,
        patch.object(nodes, "check_grounding", return_value=_grounding("PASS")) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "PASS"
    assert result["retry_count"] == 0
    assert retrieve.call_count == 1
    retry_retrieval.assert_not_called()
    assert client.chat.completions.create.call_count == 1
    assert grounding.call_count == 1


def test_insufficient_retries_retrieval_then_regenerates():
    first = _chunk("Contexte incomplet.", "Section A")
    second = _chunk("Nouveau contexte pertinent.", "Section B")

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _llm_response("Première réponse."),
        _llm_response("Réponse après nouveau retrieval."),
    ]

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]),
        patch.object(nodes, "retrieve_retry_context", return_value=[second]) as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            side_effect=[
                _grounding("INSUFFICIENT", "Le contexte ne répond pas à la question."),
                _grounding("PASS"),
            ],
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "PASS"
    assert result["answer"] == "Réponse après nouveau retrieval."
    assert result["retry_count"] == 1
    assert client.chat.completions.create.call_count == 2
    assert grounding.call_count == 2
    assert retry_retrieval.call_count == 1

    kwargs = retry_retrieval.call_args.kwargs
    assert kwargs["pokemon"] == "Pikachu"
    assert kwargs["excluded_section_path"] == "Section A"
    assert kwargs["grounding_reason"] == "Le contexte ne répond pas à la question."


@pytest.mark.parametrize("first_decision", ["UNSUPPORTED", "CONTRADICTION"])
def test_generation_failure_retries_answer_without_retrieval(first_decision):
    first = _chunk("Contexte suffisant.", "Section A")

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _llm_response("Première réponse incorrecte."),
        _llm_response("Réponse corrigée."),
    ]

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]) as retrieve,
        patch.object(nodes, "retrieve_retry_context") as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            side_effect=[
                _grounding(first_decision, "La réponse dépasse le contexte."),
                _grounding("PASS"),
            ],
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "PASS"
    assert result["answer"] == "Réponse corrigée."
    assert result["retry_count"] == 1
    assert retrieve.call_count == 1
    retry_retrieval.assert_not_called()
    assert client.chat.completions.create.call_count == 2
    assert grounding.call_count == 2


def test_second_grounding_failure_stops_instead_of_looping():
    first = _chunk("Contexte suffisant.", "Section A")

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _llm_response("Première réponse."),
        _llm_response("Deuxième réponse toujours incorrecte."),
    ]

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]),
        patch.object(nodes, "retrieve_retry_context") as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            side_effect=[
                _grounding("UNSUPPORTED", "Premier échec."),
                _grounding("CONTRADICTION", "Deuxième échec."),
            ],
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "CONTRADICTION"
    assert result["retry_count"] == 1
    assert client.chat.completions.create.call_count == 2
    assert grounding.call_count == 2
    retry_retrieval.assert_not_called()


def test_insufficient_retry_that_is_still_insufficient_stops_after_one_retry():
    first = _chunk("Contexte incomplet.", "Section A")
    second = _chunk("Autre contexte encore incomplet.", "Section B")

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _llm_response("Première réponse."),
        _llm_response("Deuxième réponse."),
    ]

    with (
        patch.object(nodes, "route_question", return_value=_router_result()),
        patch.object(nodes, "retrieve", return_value=[first]),
        patch.object(nodes, "retrieve_retry_context", return_value=[second]) as retry_retrieval,
        patch.object(
            nodes,
            "check_grounding",
            side_effect=[
                _grounding("INSUFFICIENT", "Contexte initial insuffisant."),
                _grounding("INSUFFICIENT", "Contexte de retry encore insuffisant."),
            ],
        ) as grounding,
        patch.object(nodes, "llm_client", client),
    ):
        result = _invoke()

    assert result["grounding_decision"] == "INSUFFICIENT"
    assert result["retry_count"] == 1
    assert retry_retrieval.call_count == 1
    assert client.chat.completions.create.call_count == 2
    assert grounding.call_count == 2
