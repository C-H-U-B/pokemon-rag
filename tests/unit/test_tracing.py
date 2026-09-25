from __future__ import annotations

import json

import pytest

from pokemon_rag.observability.tracing import (
    create_trace,
    finalize_trace,
    save_trace,
)


def test_create_trace_generates_unique_ids():
    first = create_trace("Question 1")
    second = create_trace("Question 2")

    assert first["trace_id"] != second["trace_id"]


def test_finalize_trace_calculates_elapsed_time_and_removes_runtime_state(
    monkeypatch,
):
    trace = create_trace("Question")
    trace["started_at"] = 100.0

    monkeypatch.setattr(
        "pokemon_rag.observability.tracing.time.perf_counter",
        lambda: 112.75,
    )

    result = finalize_trace(trace)

    assert result is trace
    assert result["total_time"] == 12.75
    assert "started_at" not in result


def test_finalize_trace_accepts_explicit_total_time():
    trace = create_trace("Question")

    finalize_trace(trace, total_time=4.25)

    assert trace["total_time"] == 4.25
    assert "started_at" not in trace


def test_finalize_trace_fails_when_start_time_is_missing():
    trace = create_trace("Question")
    trace.pop("started_at")

    with pytest.raises(ValueError, match="started_at absent"):
        finalize_trace(trace)


def test_save_trace_appends_one_valid_json_object_per_run(tmp_path):
    path = tmp_path / "traces.jsonl"

    first = create_trace("Question 1")
    finalize_trace(first, total_time=1.0)

    second = create_trace("Question 2")
    finalize_trace(second, total_time=2.0)

    save_trace(first, path)
    save_trace(second, path)

    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2

    saved = [json.loads(line) for line in lines]

    assert [item["trace_id"] for item in saved] == [
        first["trace_id"],
        second["trace_id"],
    ]
    assert [item["question"] for item in saved] == [
        "Question 1",
        "Question 2",
    ]
    assert [item["total_time"] for item in saved] == [1.0, 2.0]
    assert all("started_at" not in item for item in saved)


def test_save_trace_preserves_unicode_content(tmp_path):
    path = tmp_path / "traces.jsonl"
    question = "Pourquoi Évoli n'évolue-t-il pas ? — génération 2"

    trace = create_trace(question)
    trace["pokemon"] = "Évoli"
    finalize_trace(trace, total_time=1.0)

    save_trace(trace, path)

    raw = path.read_text(encoding="utf-8")
    saved = json.loads(raw)

    assert "Évoli" in raw
    assert saved["question"] == question
    assert saved["pokemon"] == "Évoli"


def test_save_trace_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "observability" / "traces.jsonl"

    trace = create_trace("Question")
    finalize_trace(trace, total_time=1.0)

    save_trace(trace, path)

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["question"] == "Question"
