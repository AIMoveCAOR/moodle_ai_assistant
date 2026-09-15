"""retrieve_ranked: score the whole pool before cutting it, and select relative to the top.

The chain it replaced truncated the merged candidate list to 8 by position
before the reranker saw it, so for "Quelles sont les températures de fusion des
verres classiques ?" the four glass-family chunks (vector ranks 8-14 behind
syllabus fragments) never reached the reranker and the learner was refused.
"""

from unittest.mock import MagicMock

from langchain_core.documents import Document

from services.rag_service import RAGService, select_ranked


def _doc(source, text="x"):
    return Document(page_content=text, metadata={"source": source, "type": "course_content"})


# Measured BGE scores for the glass-temperatures question (see module docstring).
GLASS_SCORES = [
    (0.3335, _doc("chunk_25")),
    (0.1837, _doc("plomb")),
    (0.1179, _doc("boro")),
    (0.1154, _doc("silice")),
    (0.0790, _doc("sodo")),
    (0.0216, _doc("chunk_14")),
    (0.0084, _doc("chunk_17")),
]


def test_relative_cut_keeps_all_four_glass_families():
    kept = [d.metadata["source"] for d in select_ranked(GLASS_SCORES, limit=8)]
    assert kept == ["chunk_25", "plomb", "boro", "silice", "sodo"]


def test_selection_respects_limit():
    assert len(select_ranked(GLASS_SCORES, limit=3)) == 3


def test_uniformly_irrelevant_pool_selects_nothing():
    assert select_ranked([(0.0008, _doc("a")), (0.0005, _doc("b"))], limit=8) == []


def test_empty_pool():
    assert select_ranked([], limit=8) == []


def _service(pool, scores=None, scoring_error=None):
    service = object.__new__(RAGService)
    service.course_rag_service = MagicMock()
    service.course_rag_service.similarity_search_all_courses.return_value = pool
    service.get_vector_store_data = lambda: {"ids": []}
    service._extract_video_metadata = lambda docs, **kw: []
    if scoring_error:
        service._score_documents = MagicMock(side_effect=scoring_error)
    else:
        service._score_documents = MagicMock(return_value=scores)
    return service


def _state():
    return {"messages": [MagicMock(content="q")], "course_id": "101", "enrolled_course_ids": None}


def test_whole_pool_is_scored_not_a_positional_prefix():
    pool = [_doc(f"c{i}") for i in range(40)]
    service = _service(pool, scores=[(0.5, pool[35])])

    result = service.retrieve_ranked(_state())

    scored_docs = service._score_documents.call_args[0][1]
    assert len(scored_docs) == 40, "every candidate must reach the reranker"
    assert [d.metadata["source"] for d in result["context"]] == ["c35"]


def test_priority_course_is_searched_wide():
    service = _service([_doc("a")], scores=[(0.5, _doc("a"))])
    service.retrieve_ranked(_state())
    kwargs = service.course_rag_service.similarity_search_all_courses.call_args.kwargs
    assert kwargs["priority_k"] >= 30


def test_scoring_failure_falls_back_to_vector_order():
    pool = [_doc(f"c{i}") for i in range(20)]
    service = _service(pool, scoring_error=RuntimeError("reranker down"))
    result = service.retrieve_ranked(_state())
    assert len(result["context"]) == RAGService.MAX_CONTEXT_DOCS
    assert result["context"][0].metadata["source"] == "c0"


# ── PRF second pass ────────────────────────────────────────────────────────


def _prf_service(first_pool, second_pool, first_scores, extra_scores, refined="requête PRF"):
    service = _service(first_pool)
    service._candidate_pool = MagicMock(side_effect=[first_pool, second_pool])
    service._score_documents = MagicMock(side_effect=[first_scores, extra_scores])
    service.refine_query_prf = MagicMock(return_value={"refined_query": refined})
    return service


def test_prf_adds_candidates_scored_against_the_original_query():
    a, b, c = _doc("a"), _doc("b"), _doc("c")
    service = _prf_service(
        first_pool=[a, b], second_pool=[b, c],
        first_scores=[(0.5, a), (0.01, b)], extra_scores=[(0.4, c)],
    )
    result = service.retrieve_ranked(_state())

    assert [d.metadata["source"] for d in result["context"]] == ["a", "c"]
    assert result["refined_query"] == "requête PRF"
    second_call = service._score_documents.call_args_list[1]
    assert second_call.args[0] == "q", "PRF candidates must be scored against the learner's query"
    assert second_call.args[1] == [c], "only candidates new to the pool are re-scored"


def test_prf_is_grounded_on_reranked_documents():
    docs = [_doc(s) for s in "wxyz"]
    service = _prf_service(
        first_pool=docs, second_pool=[],
        first_scores=[(0.9, docs[3]), (0.8, docs[2]), (0.7, docs[1]), (0.6, docs[0])],
        extra_scores=[],
    )
    service.retrieve_ranked(_state())
    grounding = service.refine_query_prf.call_args.args[0]["context"]
    assert [d.metadata["source"] for d in grounding] == ["z", "y", "x"]


def test_prf_failure_keeps_first_pass():
    a = _doc("a")
    service = _prf_service([a], [], [(0.5, a)], [])
    service.refine_query_prf = MagicMock(side_effect=RuntimeError("llm down"))
    result = service.retrieve_ranked(_state())
    assert [d.metadata["source"] for d in result["context"]] == ["a"]
    assert result["refined_query"] is None


def test_pagination_skips_prf():
    a = _doc("a")
    service = _prf_service([a], [], [(0.5, a)], [])
    state = {**_state(), "is_pagination_request": True, "last_topical_query": "topic"}
    service.retrieve_ranked(state)
    service.refine_query_prf.assert_not_called()
