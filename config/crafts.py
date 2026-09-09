"""Craft identity: which Moodle category is which trade, and how to look it up.

This lives in ``config`` rather than in ``services.rag_service``, where
``DOMAIN_MAP`` used to sit, because the ingest path needs it too.
``services.course_rag_service`` must not import ``services.rag_service``:
that would pull the whole retrieval stack (sentence_transformers, langsmith,
the reranker) into ingestion, and set up exactly the import cycle
``services.translation_service`` documents avoiding. A neutral module both
sides can import costs nothing and keeps the layering honest.

``services.rag_service`` re-exports ``DOMAIN_MAP`` so existing importers are
unaffected.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Maps a domain-focus button's label (sent by the frontend as `selected_domain`,
# see plugin/templates/chat_interface.mustache) to the two identifiers needed to
# narrow retrieval: the Moodle course category (for course_content) and the
# annotation `craft` tag (for video_annotation). A domain is only added here
# once its category/craft actually exist and hold content — never the other
# way around, so a stale/unmapped label just falls through to unfiltered
# retrieval (see retrieve_initial/retrieve_final_dual) instead of dead-ending.
DOMAIN_MAP: Dict[str, Dict[str, Any]] = {
    "Soufflerie de verre": {"category_id": 25, "craft": "glassblowing"},
    "Ganterie": {"category_id": 34, "craft": "glovemaking"},
}


def resolve_craft_for_course(course_id: Any, silo_service: Any) -> Optional[str]:
    """Return the craft a Moodle course belongs to, or None.

    None is the overwhelmingly common answer and is not an error: most of the
    corpus is the AI/robotics programme, which belongs to no craft. Callers
    use the result to decide whether a glossary applies, so None simply means
    "translate as before".

    Every failure is folded into None on purpose. The database can be
    unreachable, the category can be empty, the caller can have no silo
    service at all (``eval/`` scripts construct services without one). None of
    those should cost more than the glossary — an ingest that fails because a
    vocabulary lookup failed would be a far worse bug than the one the
    glossary fixes.
    """
    if silo_service is None:
        return None

    wanted = str(course_id)
    try:
        for entry in DOMAIN_MAP.values():
            course_ids = silo_service.get_course_ids_by_category(entry["category_id"])
            if wanted in {str(cid) for cid in course_ids or ()}:
                return entry["craft"]
    except Exception as e:
        # Debug, not warning: for the ~97% of courses that belong to no craft
        # this path is ordinary, and a transient DB error here is already
        # visible in SiloService's own logging.
        logger.debug(f"resolve_craft_for_course({wanted}): {e} — no craft")
        return None

    return None
