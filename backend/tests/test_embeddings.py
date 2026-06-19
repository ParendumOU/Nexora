"""Unit tests for the embedding/semantic-search pure functions.

`_cosine`, `_keyword_score`, and `semantic_search` are synchronous and need no
provider/DB. They cover the keyword-overlap fallback used when no embedding
provider is configured.
"""
from dataclasses import dataclass, field

import pytest

from src.services.embeddings import _cosine, _keyword_score, semantic_search


@dataclass
class FakeMem:
    content: str
    embedding: list | None = field(default=None)


# ── _cosine ─────────────────────────────────────────────────────────────────


def test_cosine_identical_vectors_is_one():
    v = [1.0, 2.0, 3.0]
    assert _cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite_is_negative_one():
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_zero_vector_is_zero():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── _keyword_score ──────────────────────────────────────────────────────────


def test_keyword_score_full_overlap():
    assert _keyword_score("deploy the app", "we deploy the app now") == pytest.approx(1.0)


def test_keyword_score_partial_overlap():
    # 1 of 2 query words present
    assert _keyword_score("deploy rollback", "deploy something") == pytest.approx(0.5)


def test_keyword_score_no_overlap():
    assert _keyword_score("alpha beta", "gamma delta") == 0.0


def test_keyword_score_empty_query():
    assert _keyword_score("", "anything") == 0.0


def test_keyword_score_is_case_insensitive():
    assert _keyword_score("Deploy", "deploy now") == pytest.approx(1.0)


# ── semantic_search ─────────────────────────────────────────────────────────


def test_semantic_search_uses_keyword_fallback_without_query_vec():
    mems = [
        FakeMem("deploy the production service"),
        FakeMem("unrelated note about lunch"),
    ]
    result = semantic_search(None, "deploy production", mems, top_k=10, threshold=0.3)
    assert result
    assert result[0].content == "deploy the production service"


def test_semantic_search_filters_below_threshold():
    mems = [FakeMem("totally different words")]
    result = semantic_search(None, "deploy production app", mems, threshold=0.5)
    assert result == []


def test_semantic_search_respects_top_k():
    mems = [FakeMem(f"deploy task {i}") for i in range(5)]
    result = semantic_search(None, "deploy", mems, top_k=2, threshold=0.0)
    assert len(result) == 2


def test_semantic_search_uses_cosine_when_dims_match():
    mems = [
        FakeMem("vector match", embedding=[1.0, 0.0, 0.0]),
        FakeMem("vector miss", embedding=[0.0, 1.0, 0.0]),
    ]
    result = semantic_search([1.0, 0.0, 0.0], "ignored", mems, top_k=10, threshold=0.5)
    assert len(result) == 1
    assert result[0].content == "vector match"


def test_semantic_search_falls_back_when_embedding_dim_mismatch():
    # query_vec present but stored embedding has wrong length → keyword scoring.
    mems = [FakeMem("deploy production", embedding=[1.0, 2.0])]
    result = semantic_search([1.0, 0.0, 0.0], "deploy production", mems, threshold=0.3)
    assert len(result) == 1


def test_semantic_search_sorted_descending():
    mems = [
        FakeMem("one shared word: deploy"),
        FakeMem("deploy production rollback restart"),
    ]
    result = semantic_search(None, "deploy production rollback restart", mems, threshold=0.0)
    # Best keyword overlap first.
    assert result[0].content == "deploy production rollback restart"


def test_semantic_search_empty_memories():
    assert semantic_search(None, "anything", [], threshold=0.0) == []
