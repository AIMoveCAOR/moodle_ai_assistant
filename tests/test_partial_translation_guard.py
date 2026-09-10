"""A half-translated module must never replace a fully translated one.

The 2026-09-09 outage: Infomaniak's /chat/completions endpoint began returning
"404 page not found" mid-run while /embeddings kept working. Every module
therefore indexed successfully and the CLI reported errors=0 — with 37 of
course 109's 53 chunks written back as untranslated Greek, over the French
that was there before. Nothing noticed, because ingest checks that indexing
worked, and indexing did work.

Same principle as the atomic-replace fix, one level up: do not replace content
with worse content.

The guard is deliberately narrow. Falling back to the original text is right
when a module has nothing indexed yet — an untranslated chunk beats an absent
one, and the embedding model is multilingual. It is only the *overwrite* that
destroys value, so only ingest_module, which knows whether a previous revision
exists, is in a position to refuse.

No network: translation and the Chroma collection are both stubs.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.documents.base import Document

from services import translation_service
from services.course_rag_service import CourseRAGService


class FakeCollection:
    """Chroma stand-in that reports whichever previous revision we want."""

    def __init__(self, existing_ids):
        self.existing_ids = list(existing_ids)
        self.added = []
        self.deleted = []

    def get(self, where=None):
        return {"ids": list(self.existing_ids)}

    def add_documents(self, docs):
        ids = [f"new-{len(self.added) + i}" for i in range(len(docs))]
        self.added.extend(docs)
        return ids

    def delete(self, ids=None):
        self.deleted.extend(ids or [])


def _service(collection, translation_enabled=True):
    svc = CourseRAGService.__new__(CourseRAGService)
    svc._translation_llm = MagicMock()
    svc._langid = None
    svc._craft_cache = {}
    svc.silo_service = None
    svc._write_lock = __import__("threading").Lock()
    svc._get_collection = lambda course_id: collection

    rag = MagicMock()
    rag.enable_ingestion_translation = translation_enabled
    rag.langid_confidence_threshold = 0.5
    rag.min_langid_chars = 10
    config = MagicMock()
    config.get_config.return_value.rag = rag
    svc.config_manager = config

    svc.chunker = MagicMock()
    svc.chunker.chunk_html.return_value = [
        Document(
            page_content=f"Εισαγωγή > Ενότητα\n\nΤο γυαλί είναι υλικό {i}. " * 6,
            metadata={"heading_path": "Εισαγωγή > Ενότητα", "module_id": "10"},
        )
        for i in range(3)
    ]
    return svc


def _ingest(svc):
    return svc.ingest_module(
        course_id="109", module_id="10", module_type="page",
        module_name="Ανόπτηση", section_name="Intro",
        content_html="<p>Το γυαλί</p>",
    )


@pytest.fixture
def greek_that_fails_to_translate(monkeypatch):
    monkeypatch.setattr(
        translation_service, "decide_translation", lambda *a, **kw: ("el", True)
    )
    monkeypatch.setattr(translation_service, "is_degenerate_text", lambda text: False)
    monkeypatch.setattr(
        translation_service, "translate_to_french", lambda *a, **kw: None
    )


@pytest.fixture
def greek_that_translates(monkeypatch):
    monkeypatch.setattr(
        translation_service, "decide_translation", lambda *a, **kw: ("el", True)
    )
    monkeypatch.setattr(translation_service, "is_degenerate_text", lambda text: False)
    monkeypatch.setattr(
        translation_service,
        "translate_to_french",
        lambda *a, **kw: "Le verre est un matériau.",
    )


def test_failed_translation_does_not_overwrite_an_existing_revision(
    greek_that_fails_to_translate,
):
    """The exact 2026-09-09 damage: good French replaced by Greek."""
    collection = FakeCollection(existing_ids=["old-1", "old-2", "old-3"])

    with pytest.raises(RuntimeError, match="failed to translate"):
        _ingest(_service(collection))

    assert collection.deleted == [], "the previous French revision was destroyed"


def test_the_refusal_says_what_it_kept_and_why():
    """The CLI surfaces this message, so it has to be actionable."""
    collection = FakeCollection(existing_ids=["old-1", "old-2"])
    svc = _service(collection)
    svc._translate_chunks_if_needed = lambda chunks, cfg, glossary="", stats=None: (
        stats.update({"failed": 2, "total": 3, "source_language": "el"}) or chunks
    )

    with pytest.raises(RuntimeError) as excinfo:
        _ingest(svc)

    message = str(excinfo.value)
    assert "2/3" in message
    assert "el" in message
    assert "previous 2 chunks" in message


def test_a_first_ingest_still_stores_what_it_could_translate(
    greek_that_fails_to_translate,
):
    """With nothing to lose, an untranslated chunk beats an absent one.

    The embedding model is multilingual, so the text is not unreachable — and
    refusing here would leave the module invisible instead of imperfect.
    """
    collection = FakeCollection(existing_ids=[])

    count = _ingest(_service(collection))

    assert count == 3
    assert len(collection.added) == 3


def test_a_successful_translation_replaces_as_usual(greek_that_translates):
    """The guard must not fire on the path that works."""
    collection = FakeCollection(existing_ids=["old-1", "old-2", "old-3"])

    count = _ingest(_service(collection))

    assert count == 3
    assert collection.deleted == ["old-1", "old-2", "old-3"]
