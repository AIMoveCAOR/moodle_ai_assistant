"""Tests for the route_query router node.

Two test layers:
  1. Unit tests — mock the LLM and vector store so the router logic is tested
     deterministically without any network calls.
  2. Corpus tests — run the real LLM against a labelled set of messages and
     measure accuracy.  These tests require FIREWORKS_API_KEY to be set and a
     live RAG backend; they are skipped automatically when the key is absent.
"""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from core.types import ConversationState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(message: str) -> ConversationState:
    return ConversationState(
        messages=[HumanMessage(content=message)],
        context=[],
        video_metadata=None,
        enhanced_query=None,
        query_variants=[],
        route=None,
    )


def _make_service(llm_response: str, vector_ids: list):
    """Build a minimal RAGService-like object with mocked dependencies."""
    from services.rag_service import RAGService
    from config.settings import ConfigurationManager

    config_manager = ConfigurationManager()
    with patch.object(RAGService, "_initialize_embeddings", return_value=MagicMock()), \
         patch.object(RAGService, "_initialize_vector_store", return_value=MagicMock()), \
         patch.object(RAGService, "_initialize_llm", return_value=MagicMock()), \
         patch.object(RAGService, "_initialize_cross_encoder", return_value=None):
        # The cross-encoder must be mocked too: unmocked it loaded the real
        # bge-reranker model (~45 s), and failed outright whenever an earlier
        # test (test_cohort_filter) had stubbed sentence_transformers.

        service = RAGService(config_manager=config_manager)

    # Mock vector store
    service.vector_store = MagicMock()
    service.vector_store.get.return_value = {"ids": vector_ids}

    # Mock LLM
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content=llm_response)
    service.llm = mock_llm

    return service


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestRouteQueryUnit:

    def test_empty_vector_store_always_routes_llm_only(self):
        """When vector store is empty the router must bypass RAG regardless of query."""
        service = _make_service(llm_response="rag", vector_ids=[])
        result = service.route_query(_state("Comment souffler le verre ?"))
        assert result["route"] == "llm_only"
        # LLM should NOT have been called — no point classifying when store is empty
        service.llm.invoke.assert_not_called()

    def test_rag_response_routes_to_rag(self):
        service = _make_service(llm_response="rag", vector_ids=["doc1"])
        result = service.route_query(_state("Quelle technique pour la glaçure ?"))
        assert result["route"] == "rag"

    def test_llm_only_response_routes_to_llm_only(self):
        service = _make_service(llm_response="llm_only", vector_ids=["doc1"])
        result = service.route_query(_state("Bonjour !"))
        assert result["route"] == "llm_only"

    def test_ambiguous_llm_response_defaults_to_rag(self):
        """Garbled LLM output should fall back to RAG (safer than skipping retrieval)."""
        service = _make_service(llm_response="I think it's rag but I'm not sure", vector_ids=["doc1"])
        result = service.route_query(_state("Comment affûter un ciseau ?"))
        assert result["route"] == "rag"

    def test_no_llm_defaults_to_rag(self):
        service = _make_service(llm_response="rag", vector_ids=["doc1"])
        service.llm = None
        result = service.route_query(_state("Technique de pliage du cuir ?"))
        assert result["route"] == "rag"

    def test_llm_exception_defaults_to_rag(self):
        service = _make_service(llm_response="rag", vector_ids=["doc1"])
        service.llm.invoke.side_effect = RuntimeError("API timeout")
        result = service.route_query(_state("Comment préparer la barbotine ?"))
        assert result["route"] == "rag"


# ---------------------------------------------------------------------------
# Corpus tests (require live LLM — skipped without API key)
# ---------------------------------------------------------------------------

import os

FIREWORKS_KEY_PRESENT = bool(os.getenv("FIREWORKS_API_KEY"))

# Each entry: (message, expected_route, description)
CORPUS = [
    # ── llm_only: greetings & small talk ────────────────────────────────────
    ("Bonjour !",                             "llm_only", "greeting_fr"),
    ("Hello!",                                "llm_only", "greeting_en"),
    ("Comment ça va ?",                       "llm_only", "how_are_you"),
    ("Merci pour ton aide.",                  "llm_only", "thanks"),
    ("Au revoir, bonne journée !",            "llm_only", "goodbye"),
    ("Peux-tu te présenter ?",                "llm_only", "self_introduction"),
    ("Quel temps fait-il aujourd'hui ?",      "llm_only", "weather"),
    ("Quelle est la capitale de la France ?", "llm_only", "general_knowledge"),
    ("Combien font 15 fois 7 ?",              "llm_only", "math"),
    ("Raconte-moi une blague.",               "llm_only", "joke"),

    # ── rag: craft / technique questions ────────────────────────────────────
    ("Comment souffler le verre à la canne ?",                              "rag", "glassblowing_technique"),
    ("Quelle est la température de fusion du verre borosilicaté ?",        "rag", "glass_temperature"),
    ("Comment appliquer la glaçure sur une pièce en céramique ?",          "rag", "glazing_technique"),
    ("Montre-moi la vidéo sur le pliage du cuir.",                         "rag", "video_request_leather"),
    ("Quelles sont les étapes pour monter une charnière piano ?",           "rag", "assembly_hinge"),
    ("Comment affûter correctement un ciseau à bois ?",                    "rag", "woodworking_chisel"),
    ("Quelle technique utiliser pour souder à l'étain ?",                  "rag", "soldering"),
    ("Comment réaliser un assemblage à queue d'aronde ?",                  "rag", "dovetail_joint"),
    ("Quelle est la procédure pour recuire le verre après le soufflage ?", "rag", "annealing_glass"),
    ("Explique-moi le mouvement du poignet dans cette démonstration.",     "rag", "gesture_from_demo"),
    ("Comment préparer la barbotine pour le moulage ?",                    "rag", "slip_casting"),
    ("Quels outils sont nécessaires pour le repoussé sur cuivre ?",        "rag", "copper_repoussé"),
    ("Comment régler la tension du fil sur une machine à coudre industrielle ?", "rag", "sewing_machine"),
    ("Montre-moi les étapes de l'assemblage du sous-module B.",            "rag", "assembly_line_submodule"),
    ("Quel geste adopter pour éviter les bulles dans le soufflage ?",      "rag", "glassblowing_bubbles"),
]


@pytest.mark.skipif(
    not FIREWORKS_KEY_PRESENT,
    reason="FIREWORKS_API_KEY not set — skipping live corpus test",
)
class TestRouteQueryCorpus:
    """Run the router against the labelled corpus with the real LLM."""

    @pytest.fixture(scope="class")
    def service(self):
        """One real RAGService instance shared across all corpus tests."""
        from services.rag_service import RAGService
        from config.settings import ConfigurationManager

        config_manager = ConfigurationManager()
        with patch.object(RAGService, "_initialize_embeddings", return_value=MagicMock()), \
             patch.object(RAGService, "_initialize_vector_store", return_value=MagicMock()):
            svc = RAGService(config_manager=config_manager)

        # Simulate a non-empty vector store so the LLM classifier is reached
        svc.vector_store = MagicMock()
        svc.vector_store.get.return_value = {"ids": ["dummy-doc"]}
        return svc

    @pytest.mark.parametrize("message,expected,label", CORPUS, ids=[c[2] for c in CORPUS])
    def test_corpus_entry(self, service, message, expected, label):
        result = service.route_query(_state(message))
        actual = result.get("route")
        assert actual == expected, (
            f"[{label}] Message: '{message}'\n"
            f"  Expected: {expected}\n"
            f"  Got:      {actual}"
        )

    def test_corpus_accuracy_summary(self, service):
        """Print a summary table and assert overall accuracy ≥ 90 %."""
        results = []
        for message, expected, label in CORPUS:
            actual = service.route_query(_state(message)).get("route")
            correct = actual == expected
            results.append((label, message[:55], expected, actual, correct))

        correct_count = sum(1 for *_, ok in results if ok)
        total = len(results)
        accuracy = correct_count / total

        print(f"\n{'Label':<35} {'Expected':<10} {'Got':<10} OK")
        print("-" * 70)
        for label, msg, exp, got, ok in results:
            tick = "✓" if ok else "✗"
            print(f"{label:<35} {exp:<10} {got:<10} {tick}  {msg}")
        print(f"\nAccuracy: {correct_count}/{total} = {accuracy:.0%}")

        assert accuracy >= 0.90, f"Router accuracy {accuracy:.0%} below 90% threshold"
