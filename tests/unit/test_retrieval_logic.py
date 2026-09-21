from __future__ import annotations

import sys
from unittest.mock import patch

import numpy as np
import pytest

# retrieval.py charge Chroma et les modèles à l'import.
# Les tests unitaires remplacent ces dépendances lourdes avant l'import du module.
with patch("chromadb.PersistentClient") as client_cls, \
     patch("sentence_transformers.SentenceTransformer"), \
     patch("sentence_transformers.CrossEncoder"), \
     patch("rank_bm25.BM25Okapi"):
    collection = client_cls.return_value.get_collection.return_value
    collection.count.return_value = 0
    collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}

    import pokemon_rag.rag.retrieval as retrieval

# Important : ce module a été importé avec Chroma et les modèles mockés.
# On conserve cette référence locale pour les tests unitaires, mais on retire
# immédiatement le faux module du cache d'import Python. Ainsi, les tests
# d'intégration exécutés plus tard dans le même processus pytest réimporteront
# retrieval.py normalement et chargeront le vrai corpus.
sys.modules.pop("pokemon_rag.rag.retrieval", None)

import pokemon_rag.rag as rag_package

if getattr(rag_package, "retrieval", None) is retrieval:
    delattr(rag_package, "retrieval")


def test_tokenize_normalizes_case_and_preserves_accents() -> None:
    assert retrieval.tokenize("ÉLECTACLE, Pikachu !") == ["électacle", "pikachu"]


def test_normalize_section_tokens_removes_stopwords() -> None:
    tokens = retrieval.normalize_section_tokens(
        "Quelles sont les capacités de Pikachu dans cette section ?"
    )

    assert "capacités" in tokens
    assert "pikachu" in tokens
    assert "les" not in tokens
    assert "de" not in tokens


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"section_path": "Capacités > Par niveau"}, "Capacités > Par niveau"),
        ({"section": "Statistiques"}, "Statistiques"),
        ({"section_path": "", "section": "Évolution"}, "Évolution"),
        ({}, ""),
        (None, ""),
    ],
    ids=[
        "section-path",
        "legacy-section",
        "empty-path-fallback",
        "empty-metadata",
        "none-metadata",
    ],
)
def test_metadata_section_path(metadata, expected: str) -> None:
    assert retrieval.metadata_section_path(metadata) == expected


def test_reciprocal_rank_fusion_merges_and_deduplicates() -> None:
    vector_results = [
        {
            "id": "a",
            "document": "A",
            "metadata": {"pokemon": "Pikachu"},
            "vector_rank": 1,
            "vector_distance": 0.1,
        },
        {
            "id": "b",
            "document": "B",
            "metadata": {"pokemon": "Pikachu"},
            "vector_rank": 2,
            "vector_distance": 0.2,
        },
    ]
    bm25_results = [
        {
            "id": "b",
            "document": "B",
            "metadata": {"pokemon": "Pikachu"},
            "bm25_rank": 1,
            "bm25_score": 8.0,
        },
        {
            "id": "c",
            "document": "C",
            "metadata": {"pokemon": "Pikachu"},
            "bm25_rank": 2,
            "bm25_score": 7.0,
        },
    ]

    results = retrieval.reciprocal_rank_fusion(
        vector_results,
        bm25_results,
        n_results=3,
    )

    assert [item["id"] for item in results] == ["b", "a", "c"]
    assert len({item["id"] for item in results}) == 3
    assert results[0]["vector_rank"] == 2
    assert results[0]["bm25_rank"] == 1
    assert results[0]["rrf_rank"] == 1


def test_merge_candidates_keeps_rrf_order_and_adds_unique_sections() -> None:
    rrf = [
        {"id": "a", "document": "A", "metadata": {}, "rrf_rank": 1},
        {"id": "b", "document": "B", "metadata": {}, "rrf_rank": 2},
    ]
    sections = [
        {
            "id": "b",
            "document": "B",
            "metadata": {},
            "section_path": "Évolution",
            "section_structural_score": 4.2,
        },
        {
            "id": "c",
            "document": "C",
            "metadata": {},
            "section_path": "Capacités",
            "section_structural_score": 3.0,
        },
    ]

    results = retrieval.merge_candidates(rrf, sections)

    assert [item["id"] for item in results] == ["a", "b", "c"]
    assert results[1]["section_path"] == "Évolution"
    assert results[1]["section_structural_score"] == 4.2


def test_section_key_requires_source_and_section() -> None:
    assert retrieval.section_key(
        {
            "metadata": {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
            }
        }
    ) == ("Pikachu.md", "Évolution")

    assert retrieval.section_key({"metadata": {"source_file": "Pikachu.md"}}) is None
    assert retrieval.section_key({"metadata": {"section_path": "Évolution"}}) is None


def test_section_structural_candidates_requires_pokemon() -> None:
    assert retrieval.section_structural_candidates("Évolution", None) == []


def test_section_structural_candidates_stays_inside_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        retrieval,
        "CORPUS_IDS",
        ["pika-1", "pika-2", "rai-1"],
    )
    monkeypatch.setattr(
        retrieval,
        "CORPUS_DOCUMENTS",
        ["P1", "P2", "R1"],
    )
    monkeypatch.setattr(
        retrieval,
        "CORPUS_METADATAS",
        [
            {
                "pokemon": "Pikachu",
                "source_file": "Pikachu.md",
                "section_path": "Capacités > Capacités apprises",
                "chunk_number": 1,
            },
            {
                "pokemon": "Pikachu",
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "chunk_number": 2,
            },
            {
                "pokemon": "Raichu",
                "source_file": "Raichu.md",
                "section_path": "Capacités > Capacités apprises",
                "chunk_number": 1,
            },
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "POKEMON_TO_INDICES",
        {"Pikachu": [0, 1], "Raichu": [2]},
    )

    results = retrieval.section_structural_candidates(
        "Quelles capacités Pikachu peut-il apprendre ?",
        pokemon="Pikachu",
    )

    assert results
    assert all(item["metadata"]["pokemon"] == "Pikachu" for item in results)
    assert all(item["id"] != "rai-1" for item in results)


def test_expand_exact_section_uses_section_chunk_order_and_limit(monkeypatch) -> None:
    monkeypatch.setattr(retrieval, "CORPUS_IDS", ["a", "b", "c", "d"])
    monkeypatch.setattr(retrieval, "CORPUS_DOCUMENTS", ["A", "B", "C", "D"])
    monkeypatch.setattr(
        retrieval,
        "CORPUS_METADATAS",
        [
            {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "section_chunk_number": 1,
            },
            {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "section_chunk_number": 2,
            },
            {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "section_chunk_number": 3,
            },
            {
                "source_file": "Pikachu.md",
                "section_path": "Autre",
                "section_chunk_number": 1,
            },
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "SECTION_TO_INDICES",
        {("Pikachu.md", "Évolution"): [0, 1, 2]},
    )

    seed = {
        "id": "b",
        "document": "B",
        "metadata": retrieval.CORPUS_METADATAS[1],
        "reranker_rank": 1,
    }

    results = retrieval.expand_exact_section(seed, max_chunks=2)

    assert [item["id"] for item in results] == ["a", "b"]
    assert all(item["section"] == "Évolution" for item in results)
    assert results[0]["is_section_expansion"] is True
    assert results[1]["is_section_expansion"] is False


def test_rerank_candidates_orders_crossencoder_scores(monkeypatch) -> None:
    class FakeReranker:
        def predict(self, pairs, **kwargs):
            assert len(pairs) == 3
            return np.asarray([0.2, 0.9, -0.1])

    monkeypatch.setattr(retrieval, "reranker_model", FakeReranker())

    candidates = [
        {"id": "a", "document": "A", "metadata": {"section_path": "A"}},
        {"id": "b", "document": "B", "metadata": {"section_path": "B"}},
        {"id": "c", "document": "C", "metadata": {"section_path": "C"}},
    ]

    results, _ = retrieval.rerank_candidates(
        "question",
        candidates,
        n_results=2,
    )

    assert [item["id"] for item in results] == ["b", "a"]
    assert [item["reranker_rank"] for item in results] == [1, 2]
    assert results[0]["reranker_score"] == pytest.approx(0.9)
