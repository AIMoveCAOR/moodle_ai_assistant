"""assess_relevance must judge on the best document, not on every document.

Retrieval merges two collections and always returns its top-k, so a handful of
off-topic documents ride along with the good ones — the annotation collection
holds only 15 clips, so its nearest two are returned whatever the question is.

Asked whether "ces documents" answer the question, the classifier read that as
*all* of them and refused whenever the off-topic ones were present. Measured on
the live model with the real retrieved context for "Quelles sont les températures
de fusion des verres classiques ?", where four course chunks carried the answer
outright (900/1000/1200/2000 °C):

    context                       temp 0.0        temp 0.2        temp 0.4
    six course chunks             SUFFISANT 6/6   SUFFISANT 6/6   SUFFISANT 6/6
    + two off-topic bevel clips   INSUFFISANT 6/6 INSUFFISANT 5/6 INSUFFISANT 4/6

Same answer present in both rows — two irrelevant clips flipped the verdict, and
at 0.4 flipped it intermittently, which is why the failure looked random.

Telling the classifier that off-topic documents are expected and that one
sufficient document is enough scored 36/36 on the live model: SUFFISANT for the
mixed context at both temperatures, INSUFFISANT for the off-topic clips alone and
for an unrelated question against the glass chunks. The gate stays strict; it just
stops being confused by its own recall.
"""

from unittest.mock import MagicMock

import pytest


class _Doc:
    def __init__(self, text):
        self.page_content = text
        self.metadata = {}


def _service_with_captured_prompt(response="SUFFISANT"):
    """Build a bare RAGService whose llm records the prompt it was handed."""
    from services.rag_service import RAGService

    service = object.__new__(RAGService)
    captured = {}

    def fake_invoke(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return MagicMock(content=response)

    service.llm = MagicMock()
    service.llm.invoke.side_effect = fake_invoke
    return service, captured


def _state(docs, query="Quelles sont les températures de fusion des verres classiques ?"):
    return {"context": docs, "messages": [MagicMock(content=query)]}


def test_prompt_tells_classifier_to_ignore_off_topic_documents():
    """The prompt must say that off-topic documents are expected and ignorable."""
    service, captured = _service_with_captured_prompt()
    service.assess_relevance(_state([_Doc("Température de travail : 1200°C"), _Doc("Le biseau oblique...")]))

    prompt = captured["prompt"].lower()
    assert "hors sujet" in prompt, (
        "prompt never warns that some retrieved documents are off-topic, so the "
        "classifier judges the whole set and refuses on good context"
    )
    assert "au moins un" in prompt, (
        "prompt must ask whether AT LEAST ONE document answers the question"
    )


def test_sufficient_verdict_still_parsed():
    """Guard the INSUFFISANT-before-SUFFISANT substring ordering while editing."""
    service, _ = _service_with_captured_prompt("SUFFISANT")
    assert service.assess_relevance(_state([_Doc("x")]))["relevance_assessment"] == "SUFFICIENT"


def test_insufficient_verdict_still_parsed():
    service, _ = _service_with_captured_prompt("INSUFFISANT")
    assert service.assess_relevance(_state([_Doc("x")]))["relevance_assessment"] == "INSUFFICIENT"


def test_empty_context_still_refuses_without_calling_the_llm():
    """No documents at all must stay a refusal — this fix must not weaken that."""
    service, captured = _service_with_captured_prompt()
    assert service.assess_relevance(_state([]))["relevance_assessment"] == "INSUFFICIENT"
    assert "prompt" not in captured, "empty context must short-circuit before the LLM call"


def test_generation_prompt_carries_no_refusal_of_its_own():
    """Refusal is assess_relevance's decision alone.

    A refusal clause in the generation prompt acted as a second, literal-minded
    gate: with all four glass-family chunks in context ("Température de
    travail : …") the model still answered with the refusal for "températures de
    fusion", because the exact word was missing.
    """
    from services.rag_service import RAGService

    service = object.__new__(RAGService)
    service.INSUFFICIENT_CONTEXT_MESSAGE = RAGService.INSUFFICIENT_CONTEXT_MESSAGE
    with pytest.MonkeyPatch.context() as mp:
        for name in ("_initialize_embeddings", "_initialize_vector_store",
                     "_initialize_llm", "_initialize_cross_encoder", "_initialize_langid"):
            mp.setattr(RAGService, name, lambda self: None)
        RAGService.__init__(service, MagicMock())

    prompt = service.system_prompt
    assert RAGService.INSUFFICIENT_CONTEXT_MESSAGE not in prompt
    assert "hors sujet" in prompt.lower()
    assert "terme voisin" in prompt.lower(), "prompt must allow mapping close terminology"
