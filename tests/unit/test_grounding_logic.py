from __future__ import annotations

from types import SimpleNamespace

import pytest

import pokemon_rag.rag.grounding as grounding


def _response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content)
            )
        ]
    )


@pytest.mark.parametrize(
    ("decision", "grounded"),
    [
        ("PASS", True),
        ("CONTRADICTION", False),
        ("UNSUPPORTED", False),
        ("INSUFFICIENT", False),
        ("INCOMPLETE", False),
    ],
)
def test_check_grounding_accepts_valid_decisions(
    monkeypatch,
    decision: str,
    grounded: bool,
) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(
            f'{{"context_sufficient":true,"unsupported_claims":[],"decision":"{decision}","reason":"raison de test"}}'
        ),
    )

    result = grounding.check_grounding(
        "Question ?",
        "Contexte.",
        "Réponse.",
    )

    assert result["decision"] == decision
    assert result["grounded"] is grounded
    assert result["reason"] == "raison de test"
    assert result["time"] >= 0


def test_check_grounding_normalizes_decision(monkeypatch) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(
            '{"context_sufficient":true,"unsupported_claims":[],"decision":"  pass  ","reason":"ok"}'
        ),
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["decision"] == "PASS"
    assert result["grounded"] is True


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"context_sufficient":true,"unsupported_claims":[],"decision":"PASS","reason":"ok"}\n```',
        '```\n{"context_sufficient":true,"unsupported_claims":[],"decision":"PASS","reason":"ok"}\n```',
    ],
    ids=["json-fence", "plain-fence"],
)
def test_check_grounding_accepts_markdown_json_fences(
    monkeypatch,
    content: str,
) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(content),
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["decision"] == "PASS"
    assert result["grounded"] is True
    assert result["reason"] == "ok"


def test_check_grounding_uses_default_reason_when_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(
            '{"context_sufficient":true,"unsupported_claims":[],"decision":"PASS","reason":""}'
        ),
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["decision"] == "PASS"
    assert result["grounded"] is True
    assert result["reason"] == "Aucune justification fournie."


@pytest.mark.parametrize(
    "content",
    [
        "pas du json",
        '{"context_sufficient":true,"unsupported_claims":[],"decision":"UNKNOWN","reason":"x"}',
        '{"reason":"x"}',
        "[]",
    ],
    ids=[
        "invalid-json",
        "invalid-decision",
        "missing-decision",
        "wrong-json-shape",
    ],
)
def test_check_grounding_fails_closed_on_invalid_output(
    monkeypatch,
    content: str,
) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(content),
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["decision"] == "INSUFFICIENT"
    assert result["grounded"] is False
    assert result["reason"].startswith("Échec du grounding checker :")


def test_check_grounding_fails_closed_on_client_error(monkeypatch) -> None:
    def fail(**kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        fail,
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["decision"] == "INSUFFICIENT"
    assert result["grounded"] is False
    assert "LLM unavailable" in result["reason"]


def test_check_grounding_sends_expected_model_and_prompts(monkeypatch) -> None:
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _response(
            '{"context_sufficient":true,"unsupported_claims":[],"decision":"PASS","reason":"ok"}'
        )

    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        fake_create,
    )

    question = "Comment évolue ce Pokémon ?"
    context = "Il évolue avec une Pierre."
    answer = "Il évolue avec une Pierre."

    grounding.check_grounding(question, context, answer)

    assert captured["model"] == grounding.GROUNDING_MODEL
    assert captured["temperature"] == 0
    assert captured["messages"][0] == {
        "role": "system",
        "content": grounding.GROUNDING_SYSTEM_PROMPT,
    }

    user_message = captured["messages"][1]
    assert user_message["role"] == "user"
    assert question in user_message["content"]
    assert context in user_message["content"]
    assert answer in user_message["content"]


def test_check_grounding_does_not_treat_non_pass_as_grounded(monkeypatch) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(
            '{"context_sufficient":true,"unsupported_claims":["information absente"],"decision":"UNSUPPORTED","reason":"information absente"}'
        ),
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["grounded"] is False



def test_check_grounding_rejects_pass_when_context_is_insufficient(monkeypatch) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(
            '{"context_sufficient":false,"unsupported_claims":[],'
            '"decision":"PASS","reason":"contexte insuffisant"}'
        ),
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["decision"] == "INSUFFICIENT"
    assert result["grounded"] is False


def test_check_grounding_rejects_pass_with_unsupported_claims(monkeypatch) -> None:
    monkeypatch.setattr(
        grounding.client.chat.completions,
        "create",
        lambda **kwargs: _response(
            '{"context_sufficient":true,"unsupported_claims":["fait absent"],'
            '"decision":"PASS","reason":"affirmation absente"}'
        ),
    )

    result = grounding.check_grounding("Q", "C", "R")

    assert result["decision"] == "INSUFFICIENT"
    assert result["grounded"] is False
