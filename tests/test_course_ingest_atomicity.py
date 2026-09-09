"""Ingesting a module must never leave it with zero chunks.

The 2026-09-07 Infomaniak /embeddings outage exposed this: the re-ingest
path deleted a module's chunks and then failed to add the replacements, so
courses 1293-1295 sat in the index with nothing in them. The pages were
still in Moodle, but the assistant could not see them.

Ordering is the whole fix — index the new chunks first, drop the old ones
only once that succeeded. A provider blip then leaves the previous, slightly
stale chunks in place, which is strictly better than an empty module. If the
add fails halfway through its batches, whatever it managed to write is rolled
back, so the module is never left holding half a revision.

No live backend, no network: the collection is a stub that fails on demand.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.documents.base import Document

from services.course_rag_service import CourseRAGService


OLD_IDS = ["old-1", "old-2", "old-3"]


class FakeCollection:
    """Minimal stand-in for a langchain-chroma Chroma collection."""

    def __init__(self, fail_on_add_call=None):
        self.ids = list(OLD_IDS)
        self.deleted = []
        self.added = []
        self._add_calls = 0
        self._fail_on_add_call = fail_on_add_call

    def get(self, where=None):
        return {"ids": list(self.ids)}

    def add_documents(self, docs):
        self._add_calls += 1
        if self._fail_on_add_call == self._add_calls:
            raise RuntimeError("Error code: 500 - upstream embeddings unavailable")
        new_ids = [f"new-{self._add_calls}-{i}" for i in range(len(docs))]
        self.ids.extend(new_ids)
        self.added.extend(new_ids)
        return new_ids

    def delete(self, ids=None):
        self.deleted.extend(ids or [])
        self.ids = [i for i in self.ids if i not in set(ids or [])]


def _service(collection):
    svc = CourseRAGService(
        embeddings=MagicMock(),
        persist_directory="/tmp/does-not-exist",
        config_manager=None,
    )
    svc._get_collection = MagicMock(return_value=collection)
    svc._translate_chunks_if_needed = lambda chunks, cfg, glossary="", stats=None: chunks
    return svc


def _ingest(svc, html):
    return svc.ingest_module(
        course_id="109",
        module_id="1293",
        module_type="page",
        module_name="Ανόπτηση",
        section_name="Section 8",
        content_html=html,
    )


def _html(n_paragraphs=2):
    para = "<p>" + (" ".join(["recuit"] * 40)) + "</p>"
    return "".join(f"<h2>Titre {i}</h2>{para}" for i in range(n_paragraphs))


def test_failed_add_leaves_the_previous_chunks_in_place():
    """The outage case: embeddings 500, module must not end up empty."""
    collection = FakeCollection(fail_on_add_call=1)
    svc = _service(collection)

    with pytest.raises(RuntimeError):
        _ingest(svc, _html())

    assert collection.deleted == [], "old chunks were deleted despite the add failing"
    assert collection.ids == OLD_IDS, "module should still hold its previous revision"


def test_successful_add_replaces_the_previous_chunks():
    collection = FakeCollection()
    svc = _service(collection)

    count = _ingest(svc, _html())

    assert count > 0
    assert sorted(collection.deleted) == sorted(OLD_IDS), "stale chunks were not removed"
    assert collection.ids == collection.added, "only the new revision should remain"
    assert not set(collection.ids) & set(OLD_IDS)


def test_partial_add_failure_rolls_back_what_it_wrote(monkeypatch):
    """A failure on the second batch must not leave batch one behind."""
    import services.course_rag_service as mod

    collection = FakeCollection(fail_on_add_call=2)
    svc = _service(collection)
    monkeypatch.setattr(mod, "INGEST_BATCH_SIZE", 1)

    with pytest.raises(RuntimeError):
        _ingest(svc, _html(n_paragraphs=3))

    assert collection.deleted == collection.added, "partial writes were not rolled back"
    assert collection.ids == OLD_IDS, "module should be back to its previous revision"
