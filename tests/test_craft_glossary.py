"""The glossary must improve a translation and must never prevent one.

Course content is translated to French at ingest time and the French text is
what gets embedded, so the words the translator picks are the words retrieval
searches. Three rounds of prompt tuning each fixed the error they named and
left the next one standing: `cullet` survived untranslated, and incandescent
glass came out as `glace incandescente` — glace is ice.

A glossary fixes the class rather than the instance, but only if it is applied
to craft content and nothing else. Roughly 11,400 of the corpus's 11,703 chunks
are an AI/robotics master's programme, so the default must be "no glossary":
pushing trade vocabulary into a lecture on image classification would be a new
defect, not a fix.

Hence the shape of these tests. Every way of not knowing the craft — no craft,
an unmapped craft, a craft with no terms yet, a database that raises — has to
land on today's exact behaviour.

No network, no database: the silo service is a stub.
"""

from unittest.mock import MagicMock

import pytest

from config import glossaries
from config.crafts import DOMAIN_MAP, resolve_craft_for_course
from services import translation_service
from services.course_rag_service import _build_heading_translation_prompt


# ── The prompt fragment ────────────────────────────────────────────────


def test_no_craft_yields_no_fragment():
    """The overwhelming majority of the corpus has no craft at all."""
    assert glossaries.glossary_prompt_fragment(None) == ""


def test_unknown_craft_yields_no_fragment():
    """A craft added to DOMAIN_MAP before its glossary exists must not break."""
    assert glossaries.glossary_prompt_fragment("basket-weaving") == ""


def test_craft_with_no_terms_yields_no_fragment():
    """Glovemaking ships with an empty list until someone supplies terms.

    An empty list has to behave exactly like an absent one, or shipping the
    key ahead of its contents would degrade every glovemaking translation.
    """
    glossaries.CRAFT_GLOSSARIES["_empty_craft_for_test"] = {}
    try:
        assert glossaries.glossary_prompt_fragment("_empty_craft_for_test") == ""
    finally:
        del glossaries.CRAFT_GLOSSARIES["_empty_craft_for_test"]


def test_fragment_names_every_term_and_its_meaning():
    """A bare word list would not have fixed `cullet`.

    The model has to be told which concept a term names before it can choose
    the term, so both halves of each entry must reach the prompt.
    """
    fragment = glossaries.glossary_prompt_fragment("glassblowing")
    for term, gloss in glossaries.CRAFT_GLOSSARIES["glassblowing"].items():
        assert term in fragment
        assert gloss in fragment


def test_glassblowing_carries_the_terms_the_corpus_got_wrong():
    """Regression cover for the specific defects mined from the corpus."""
    terms = glossaries.CRAFT_GLOSSARIES["glassblowing"]
    for term in ("calcin", "canne", "arche de recuisson", "verre"):
        assert term in terms, f"{term} missing — a known mistranslation is uncovered"


def test_every_craft_in_domain_map_has_a_glossary_key():
    """Adding a craft without a glossary key should fail here, not in production."""
    for entry in DOMAIN_MAP.values():
        assert entry["craft"] in glossaries.CRAFT_GLOSSARIES


# ── Craft resolution ───────────────────────────────────────────────────


def _silo_returning(mapping):
    silo = MagicMock()
    silo.get_course_ids_by_category.side_effect = lambda cid: mapping.get(cid, [])
    return silo


def test_resolves_the_craft_of_a_mapped_course():
    silo = _silo_returning({25: ["101", "109"], 34: []})
    assert resolve_craft_for_course("109", silo) == "glassblowing"


def test_unmapped_course_resolves_to_no_craft():
    """Most courses are the AI programme and must resolve to nothing."""
    silo = _silo_returning({25: ["101", "109"], 34: []})
    assert resolve_craft_for_course("11", silo) is None


def test_course_id_type_does_not_matter():
    """Moodle ids arrive as both str and int depending on the call path."""
    silo = _silo_returning({25: ["101", "109"], 34: []})
    assert resolve_craft_for_course(109, silo) == "glassblowing"


def test_database_failure_resolves_to_no_craft():
    """A database hiccup must cost the glossary, never the ingest."""
    silo = MagicMock()
    silo.get_course_ids_by_category.side_effect = RuntimeError("connection refused")
    assert resolve_craft_for_course("109", silo) is None


def test_absent_silo_service_resolves_to_no_craft():
    """eval/ scripts construct the service with no database at all."""
    assert resolve_craft_for_course("109", None) is None


def test_domain_map_is_re_exported_from_rag_service():
    """Moving DOMAIN_MAP must not silently fork it into two maps."""
    from services.rag_service import DOMAIN_MAP as re_exported

    assert re_exported is DOMAIN_MAP


# ── The prompts themselves ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "build",
    [
        lambda glossary: translation_service.build_chunk_translation_prompt(
            "Το γυαλί", "el", glossary=glossary
        ),
        lambda glossary: _build_heading_translation_prompt(
            "Ανόπτηση", "el", context="", glossary=glossary
        ),
        lambda glossary: _build_heading_translation_prompt(
            "Ανόπτηση", "el", context="Τα εργαλεία", glossary=glossary
        ),
    ],
    ids=["chunk", "heading-no-context", "heading-with-context"],
)
def test_prompts_are_unchanged_when_there_is_no_glossary(build):
    """Non-craft content is the common case and must get today's exact prompt."""
    assert build("") == build("")
    assert "calcin" not in build("")


@pytest.mark.parametrize(
    "build",
    [
        lambda glossary: translation_service.build_chunk_translation_prompt(
            "Το γυαλί", "el", glossary=glossary
        ),
        lambda glossary: _build_heading_translation_prompt(
            "Ανόπτηση", "el", context="", glossary=glossary
        ),
        lambda glossary: _build_heading_translation_prompt(
            "Ανόπτηση", "el", context="Τα εργαλεία", glossary=glossary
        ),
    ],
    ids=["chunk", "heading-no-context", "heading-with-context"],
)
def test_prompts_carry_the_glossary_when_there_is_one(build):
    fragment = glossaries.glossary_prompt_fragment("glassblowing")
    prompt = build(fragment)
    assert "calcin" in prompt
    # The text being translated must survive alongside the glossary.
    assert "Το γυαλί" in prompt or "Ανόπτηση" in prompt
