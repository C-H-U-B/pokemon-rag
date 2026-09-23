from unittest.mock import MagicMock, patch
from types import SimpleNamespace
import pytest
from pokemon_rag.graph import nodes

def response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

def test_unknown_router_route_fails_closed_to_rag():
    with patch.object(nodes, "route_question", return_value={"route":"INVALID","information_need":"","pokemon":"Pikachu","pokemon_validated":True}):
        r = nodes.route_query({"question":"Q","verbose":False})
    assert r["route"] == "RAG"
    assert r["information_need"] == "Q"

@pytest.mark.parametrize("validated,expected", [(True,"Pikachu"),(False,None)])
def test_retrieval_scope_depends_on_validation(validated, expected):
    s={"question":"Q","pokemon":"Pikachu","pokemon_validated":validated,"verbose":False}
    with patch.object(nodes,"retrieve",return_value=[]) as f:
        nodes.retrieve_documents(s)
    assert f.call_args.kwargs["pokemon"] == expected

def test_retrieval_uses_expanded_section_as_context():
    expanded=[{"document":"section","metadata":{}}]
    top={"document":"top","metadata":{},"context_results":expanded}
    with patch.object(nodes,"retrieve",return_value=[top]):
        r=nodes.retrieve_documents({"question":"Q","pokemon_validated":False,"verbose":False})
    assert r["context_documents"] == expanded

def test_retry_keeps_scope_and_excludes_previous_section():
    s={"question":"Q","pokemon":"Pikachu","pokemon_validated":True,
       "context_documents":[{"metadata":{"section_path":"Capacités > Niveau"}}],
       "grounding_reason":"insuffisant","retrieval_retry_count":0,"verbose":False}
    with patch.object(nodes,"retrieve_retry_context",return_value=[]) as f:
        r=nodes.retry_retrieval(s)
    k=f.call_args.kwargs
    assert k["pokemon"]=="Pikachu"
    assert k["excluded_section_path"]=="Capacités > Niveau"
    assert k["grounding_reason"]=="insuffisant"
    assert r["retrieval_retry_count"]==1

def test_build_context_prefers_context_documents():
    r=nodes.build_context({"retrieved_documents":[{"document":"MAUVAIS","metadata":{}}],
                           "context_documents":[{"document":"BON","metadata":{}}],"verbose":False})
    assert "BON" in r["rag_context"]
    assert "MAUVAIS" not in r["rag_context"]

def test_hybrid_context_does_not_drop_either_source():
    r=nodes.build_hybrid_context({"structured_context":"SQL",
        "context_documents":[{"document":"DOC","metadata":{}}]})
    assert "SQL" in r["rag_context"] and "DOC" in r["rag_context"]

def test_empty_context_never_calls_main_llm():
    client = MagicMock()

    with patch.object(nodes, "llm_client", client):
        result = nodes.call_main_llm(
            {
                "question": "Q",
                "rag_context": "   ",
                "verbose": False,
            }
        )

    client.chat.completions.create.assert_not_called()

    assert isinstance(result["answer"], str)
    assert result["answer"].strip()
    assert result["llm_time"] >= 0

def test_main_llm_does_not_receive_unrelated_state():
    client=MagicMock()
    client.chat.completions.create.return_value=response("OK")
    with patch.object(nodes,"llm_client",client):
        nodes.call_main_llm({"question":"QUESTION","rag_context":"CONTEXTE",
                             "secret":"NE_PAS_ENVOYER","verbose":False})
    messages=client.chat.completions.create.call_args.kwargs["messages"]
    payload=repr(messages)
    assert "QUESTION" in payload and "CONTEXTE" in payload
    assert "NE_PAS_ENVOYER" not in payload

@pytest.mark.parametrize("decision",["CONTRADICTION","UNSUPPORTED","INSUFFICIENT"])
def test_grounding_preserves_failure_decision(decision):
    with patch.object(nodes,"check_grounding",return_value={"decision":decision,"reason":"x","time":0.1}):
        r=nodes.grounding_check({"question":"Q","rag_context":"C","answer":"A","verbose":False})
    assert r["grounding_decision"]==decision
    assert r["grounding_decision"]!="PASS"


def test_structured_error_fast_path_does_not_invoke_llms():
    with patch.object(nodes,"llm_client") as client, patch.object(nodes,"check_grounding") as grounding:
        r=nodes.format_structured_answer({"structured_result":{"error":"SQL indisponible"},"verbose":False})
    client.chat.completions.create.assert_not_called()
    grounding.assert_not_called()
    assert "SQL indisponible" in r["answer"]
    assert r["grounding_decision"]=="DETERMINISTIC"

def test_retry_answer_contains_failure_diagnostics():
    client=MagicMock()
    client.chat.completions.create.return_value=response("corrigée")
    s={"question":"Q","rag_context":"CTX","answer":"ancienne",
       "grounding_reason":"non supportée","verbose":False}
    with patch.object(nodes,"llm_client",client):
        r=nodes.retry_answer(s)
    prompt=client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "CTX" in prompt and "ancienne" in prompt and "non supportée" in prompt
    assert r["answer"]=="corrigée"
