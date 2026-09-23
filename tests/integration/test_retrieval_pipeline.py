from __future__ import annotations

import pytest

import pokemon_rag.rag.retrieval as retrieval


def test_real_corpus_is_loaded() -> None:
    retrieval.ensure_retrieval_initialized()

    assert retrieval.CORPUS_IDS
    assert len(retrieval.CORPUS_IDS) == len(retrieval.CORPUS_DOCUMENTS)
    assert len(retrieval.CORPUS_IDS) == len(retrieval.CORPUS_METADATAS)


def test_real_corpus_indexes_are_available() -> None:
    retrieval.ensure_retrieval_initialized()

    assert retrieval.POKEMON_TO_INDICES
    assert retrieval.SECTION_TO_INDICES


def test_bm25_scope_is_strict_for_real_pokemon() -> None:
    pokemon = "Pikachu"
    if pokemon not in retrieval.POKEMON_TO_INDICES:
        pytest.skip(f"{pokemon} absent de l'index réel")

    results = retrieval.bm25_retrieve(
        "capacités évolution statistiques",
        n_candidates=20,
        pokemon=pokemon,
    )

    assert results
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in results
    )


def test_vector_scope_is_strict_for_real_pokemon() -> None:
    pokemon = "Pikachu"
    if pokemon not in retrieval.POKEMON_TO_INDICES:
        pytest.skip(f"{pokemon} absent de l'index réel")

    results = retrieval.vector_retrieve(
        "Comment Pikachu évolue-t-il ?",
        n_candidates=20,
        pokemon=pokemon,
    )

    assert results
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in results
    )


def test_unknown_pokemon_scope_returns_no_results() -> None:
    missing = "__pokemon_absent_du_corpus__"

    assert retrieval.bm25_retrieve(
        "question",
        n_candidates=10,
        pokemon=missing,
    ) == []

    assert retrieval.vector_retrieve(
        "question",
        n_candidates=10,
        pokemon=missing,
    ) == []


def test_structural_candidates_are_strictly_scoped_on_real_corpus() -> None:
    pokemon = "Pikachu"
    if pokemon not in retrieval.POKEMON_TO_INDICES:
        pytest.skip(f"{pokemon} absent de l'index réel")

    results = retrieval.section_structural_candidates(
        "Quelles capacités Pikachu peut-il apprendre ?",
        pokemon=pokemon,
    )

    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in results
    )


def test_retrieve_without_reranker_preserves_scope() -> None:
    pokemon = "Pikachu"
    if pokemon not in retrieval.POKEMON_TO_INDICES:
        pytest.skip(f"{pokemon} absent de l'index réel")

    results = retrieval.retrieve(
        "Comment Pikachu évolue-t-il ?",
        n_results=5,
        rerank=False,
        pokemon=pokemon,
    )

    assert results
    assert len(results) <= 5
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in results
    )
    assert all(item["retrieval_scope"] == pokemon for item in results)
    assert all(item["rerank_enabled"] is False for item in results)

    context = results[0].get("context_results") or []
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in context
    )


def test_retrieve_with_reranker_preserves_scope() -> None:
    pokemon = "Pikachu"
    if pokemon not in retrieval.POKEMON_TO_INDICES:
        pytest.skip(f"{pokemon} absent de l'index réel")

    results = retrieval.retrieve(
        "Comment Pikachu évolue-t-il ?",
        n_results=5,
        rerank=True,
        pokemon=pokemon,
    )

    assert results
    assert len(results) <= 5
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in results
    )
    assert all(item["retrieval_scope"] == pokemon for item in results)
    assert all(item["rerank_enabled"] is True for item in results)

    context = results[0].get("context_results") or []
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in context
    )


def test_real_section_expansion_stays_in_exact_section() -> None:
    candidate = None

    for key, indices in retrieval.SECTION_TO_INDICES.items():
        if len(indices) >= 2:
            idx = indices[len(indices) // 2]
            candidate = {
                "id": retrieval.CORPUS_IDS[idx],
                "document": retrieval.CORPUS_DOCUMENTS[idx],
                "metadata": retrieval.CORPUS_METADATAS[idx],
            }
            expected_key = key
            break

    if candidate is None:
        pytest.skip("Aucune section multi-chunks dans l'index réel")

    expanded = retrieval.expand_exact_section(candidate)

    assert expanded
    assert len(expanded) <= retrieval.MAX_SECTION_EXPANSION_CHUNKS
    assert all(retrieval.section_key(item) == expected_key for item in expanded)

    numbers = [
        int((item["metadata"] or {}).get("section_chunk_number", 0))
        for item in expanded
    ]
    assert numbers == sorted(numbers)
