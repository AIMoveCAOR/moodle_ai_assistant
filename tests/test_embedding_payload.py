"""The embeddings client must send raw text, never tiktoken token IDs.

`langchain_openai.OpenAIEmbeddings` defaults to `check_embedding_ctx_length=True`,
which encodes each input with **tiktoken** (an OpenAI tokenizer) and posts arrays
of integer token IDs instead of strings. OpenAI's own endpoint understands that
convention; Infomaniak's `bge_multilingual_gemma2` endpoint does not — it accepts
the array, embeds it as if the digits were the document, and returns HTTP 200 with
a correctly-shaped, plausibly-normed, semantically meaningless vector.

Nothing downstream can detect this. It cost the assistant every course answer:
a chunk re-embedded through that path scored cosine 0.094 against its own stored
vector, so retrieval returned syllabus boilerplate for every question and
assess_relevance refused, correctly, on the garbage it was handed.

The corpus itself was ingested through a client that sent text (its stored vectors
match the raw API at cosine 0.9999), so the index is sound and only the query path
had to change — but both paths share this constructor, so pinning the behaviour
here keeps queries and any future re-ingest in the same vector space.
"""

from unittest.mock import MagicMock, patch

import pytest


EMBED_DIM = 3584


def _build_embeddings():
    """Build RAGService's embeddings object without running the full constructor.

    __init__ also opens Chroma, the LLM and the cross-encoder; none of that is
    needed to inspect what the embeddings client puts on the wire.
    """
    from services.rag_service import RAGService

    service = object.__new__(RAGService)
    service.config_manager = MagicMock()
    service.config_manager.get_env_var.side_effect = lambda name: {
        "INFOMANIAK_API_KEY": "test-key",
        "INFOMANIAK_PRODUCT_ID": "000000",
    }[name]
    service.config = MagicMock()
    service.config.embedding_model = "bge_multilingual_gemma2"
    return service._initialize_embeddings()


def _capture_payload(embeddings, text):
    """Return the `input` payload the client would POST for `text`."""
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {"data": [{"embedding": [0.01] * EMBED_DIM}]}

    embeddings.client = MagicMock()
    embeddings.client.create.side_effect = fake_create
    embeddings.embed_query(text)
    return captured["input"]


def test_embed_query_sends_text_not_token_ids():
    """The wire payload must be the string itself.

    A list of ints here means tiktoken re-encoded the text for an endpoint that
    does not speak token IDs — the silent corruption described in the docstring.
    """
    embeddings = _build_embeddings()
    payload = _capture_payload(embeddings, "Quelle est la température de travail du verre borosilicaté ?")

    assert isinstance(payload, list) and payload, f"expected a non-empty list, got {payload!r}"
    for item in payload:
        assert isinstance(item, str), (
            f"embeddings client posted {type(item).__name__} instead of str — "
            "tiktoken token IDs are being sent to an endpoint that expects text"
        )
    assert payload == ["Quelle est la température de travail du verre borosilicaté ?"]


def test_context_length_check_is_disabled():
    """Guards the flag itself, so a future refactor can't silently re-enable it."""
    embeddings = _build_embeddings()
    assert embeddings.check_embedding_ctx_length is False
