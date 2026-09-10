"""Shared language-detection + translate-to-French helpers.

Used by:
  - RAGService.detect_and_translate_query (query-side, ephemeral; passes
    self.llm, the shared temperature=0.4 generation client)
  - AnnotationService.annotation_to_documents (ingestion, persisted; passes a
    dedicated temperature=0 client, see build_translation_llm)
  - CourseRAGService.ingest_module (ingestion, persisted; same dedicated client)

No dependency on services.rag_service / services.annotation_service /
services.course_rag_service — importable by all three without a cycle.
"""

import logging
import re
import time
from collections import Counter
from typing import Any, Optional, Tuple

from langchain_openai import ChatOpenAI

from config.settings import ConfigurationManager

logger = logging.getLogger(__name__)


def load_langid():
    """Load py3langid with a normalized-probability identifier, or None on failure.

    The bare module-level `py3langid.classify()` returns unnormalized
    log-probabilities, not a usable [0, 1] confidence — the
    LanguageIdentifier instance with norm_probs=True is required for
    decide_translation's confidence threshold to mean anything.
    """
    try:
        import py3langid as langid
        identifier = langid.langid.LanguageIdentifier.from_pickled_model(
            langid.langid.MODEL_FILE, norm_probs=True
        )
        logger.info("py3langid initialized (normalized probabilities)")
        return identifier
    except Exception as e:
        logger.error(f"py3langid initialization failed: {e} — cross-lingual detection disabled")
        return None


# Languages this corpus is actually written in, and that py3langid identifies
# reliably. Anything else it reports is treated as a misdetection.
#
# This is an allowlist, not a denylist, and the difference is the whole point.
# The guard used to be "translate unless confidence is low", which assumes a
# wrong answer arrives hesitantly. It does not. py3langid reads this paragraph
# of course 101 — human-written French, a table of expansion coefficients —
#
#   "LES 4 FAMILLES DE VERRE ESSENTIELLES > PROPRIÉTÉS PHYSIQUES ..."
#
# as Latin with confidence 1.0000, and French at 0.0000. Every threshold in
# the world lets that through, and the result is French content round-tripped
# through an LLM for no reason: 1 chunk in 179 of the only human-authored
# French course in the corpus. It survived intact because it is mostly digits.
# The next one might not.
#
# So the question changed from "how sure are we it is foreign?" to "is it a
# language we expect at all?". Being wrong now means leaving text alone, which
# is safe by construction — the text is already in the language it is in.
#
# Only English is listed. It is the one non-French language present in bulk
# (~8,000 chunks of AI/robotics coursework) and the one py3langid is dependable
# on. The project is French-only going forward, so nothing else needs to be
# here; add a code only if real content in that language turns up.
TRANSLATABLE_SOURCE_LANGUAGES = frozenset({"en"})


def decide_translation(
    text: str,
    langid_identifier: Any,
    confidence_threshold: float,
    min_chars: int,
) -> Tuple[str, bool]:
    """Decide whether `text` should be translated to French.

    Returns (detected_lang, should_translate). ("fr", False) — do nothing — is
    the answer whenever there is any doubt: no identifier, French detected, low
    confidence, text too short, or a language outside
    TRANSLATABLE_SOURCE_LANGUAGES. Translating French into French is the one
    outcome that can damage content that was already correct, so every
    uncertain case resolves away from the translator.
    """
    if langid_identifier is None:
        return "fr", False

    lang, confidence = langid_identifier.classify(text)

    if lang == "fr" or confidence < confidence_threshold or len(text) < min_chars:
        return "fr", False

    if lang not in TRANSLATABLE_SOURCE_LANGUAGES:
        return "fr", False

    return lang, True


def is_degenerate_text(text: str, threshold: float = 0.3) -> bool:
    """Detect OCR/text-extraction garbage that shouldn't be sent to an LLM.

    Scanned PDF forms routinely extract as walls of repeated characters —
    dot-leaders on blank fill-in lines (". . . . . . . .") being the case
    that actually hung a backfill run: pathological input like this can
    send a translation call into a slow, repetitive generation loop instead
    of a normal quick response. Heuristic: if one character dominates more
    than `threshold` of the non-whitespace content, it's not real prose.
    """
    stripped = "".join(ch for ch in text if not ch.isspace())
    if not stripped:
        return False
    _, count = Counter(stripped).most_common(1)[0]
    return (count / len(stripped)) > threshold


def build_translation_llm(config_manager: ConfigurationManager) -> ChatOpenAI:
    """A second ChatOpenAI client dedicated to translation calls.

    Ingestion-time translations are persisted permanently, unlike ephemeral
    per-query translations, so determinism matters more here than for the
    shared generation/PRF client (temperature=0.4) — temperature=0, and no
    streaming since this is only ever called via .invoke().
    """
    config = config_manager.get_config().rag
    api_key = config_manager.get_env_var("INFOMANIAK_API_KEY")
    product_id = config_manager.get_env_var("INFOMANIAK_PRODUCT_ID")
    base_url = f"https://api.infomaniak.com/2/ai/{product_id}/openai/v1"
    return ChatOpenAI(
        model=config.llm_model,
        openai_api_key=api_key,
        openai_api_base=base_url,
        streaming=False,
        temperature=0,
        # A stalled request with no timeout blocks forever and never raises
        # — translate_to_french's own retry-with-backoff never even gets a
        # chance to run. request_timeout=60 makes a stuck call fail fast
        # instead; max_retries=0 disables the SDK's own hidden retry layer
        # so translate_to_french's max_retries is the only one in effect —
        # two independent retry layers would make total wait time
        # unpredictable and compound with each other.
        request_timeout=60,
        max_retries=0,
        max_tokens=1200,
        model_kwargs={"tool_choice": "none"},
    )


def extract_text(response: Any) -> str:
    """Normalize a ChatOpenAI response's .content into a plain string."""
    if isinstance(response.content, str):
        return response.content.strip()
    elif isinstance(response.content, list):
        return " ".join(str(item) for item in response.content).strip()
    return str(response.content).strip()


# Statuses worth sending the same request again for: the server said it could
# not serve this *now*, not that the request was wrong.
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_retryable(error: Exception) -> bool:
    """Should this failure be retried?

    Decided from the HTTP status, not the error text. On 2026-09-09 the
    provider returned 503 Service Unavailable whose *body* was a load-balancer
    page reading "404 page not found", and the OpenAI SDK surfaces the body as
    the exception message. So the text said 404, the status said 503, and only
    the status was true. Matching the text would have meant depending on the
    wording of someone else's error page — it happens to work today and breaks
    silently the day they reword it.

    Falls back to the message only when no status is available at all, which
    is the case for connection and timeout errors raised before any response.
    """
    for attribute in ("status_code", "http_status", "code"):
        status = getattr(error, attribute, None)
        if isinstance(status, int):
            return status in RETRYABLE_STATUS_CODES

    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS_CODES

    text = str(error).lower()
    if any(word in text for word in ("timeout", "timed out", "connection", "temporarily")):
        return True
    # Last resort: the status as the SDK stringified it. Anchored to the
    # documented "Error code: NNN" prefix so a 503 in the body text cannot
    # masquerade as the status.
    match = re.search(r"error code:\s*(\d{3})", text)
    return bool(match) and int(match.group(1)) in RETRYABLE_STATUS_CODES


def translate_to_french(prompt: str, llm: ChatOpenAI, max_retries: int = 0) -> Optional[str]:
    """Invoke `llm` with `prompt`, returning the translated text or None.

    Never raises — every failure (API error, empty response) degrades to
    None so callers can fall back to the original, untranslated text.

    `max_retries` defaults to 0 — a single ephemeral query-side translation
    shouldn't add retry latency to a live request. Bulk/sequential callers
    (course chunk translation, the backfill script) pass a higher value,
    since firing many calls back-to-back is exactly what triggers Infomaniak's
    rate limit. A retryable failure backs off exponentially (5s, 10s, 20s...);
    anything else fails immediately.

    What counts as retryable is deliberately broader than 429, and is decided
    from the HTTP status rather than the error text — see `_is_retryable`.

    Client errors stay non-retryable. A 401 or a 400 means the request itself
    is wrong, and repeating it just turns a fast failure into a slow one.
    """
    delay = 5.0
    attempt = 0
    while True:
        try:
            response = llm.invoke(prompt)
            text = extract_text(response)
            return text or None
        except Exception as e:
            if _is_retryable(e) and attempt < max_retries:
                attempt += 1
                logger.warning(
                    f"translate_to_french: retryable failure ({str(e)[:80]}), "
                    f"retrying in {delay:.0f}s (attempt {attempt}/{max_retries})"
                )
                time.sleep(delay)
                delay *= 2
                continue
            logger.error(f"translate_to_french: translation failed: {e}")
            return None


def build_query_translation_prompt(
    original_query: str, source_lang: str, glossary: str = ""
) -> str:
    """Translation prompt for a learner's question.

    Byte-identical to the original detect_and_translate_query prompt when no
    glossary applies, which is the common case.

    Retrieval compares French to French: the query is translated, then
    embedded against a French corpus. So the two sides have to agree on their
    words. If the chunks say `arche de recuisson` and the question becomes
    `anneau de recuisson`, the match degrades for no reason other than
    vocabulary drift between two prompts. Passing the same glossary to both
    keeps them speaking the same language.
    """
    return (
        "Traduis la question suivante en français, en conservant tout son sens "
        "technique et son intention.\n\n"
        f"{glossary}"
        f'Question originale ({source_lang}) :\n"{original_query}"\n\n'
        "Réponds avec UNIQUEMENT la traduction française, sans explication."
    )


def build_transcript_translation_prompt(
    transcription: str, source_lang: str, glossary: str = ""
) -> str:
    """Translation prompt for a spoken, first-person craft-elicitation transcript."""
    return (
        "Traduis la transcription suivante en français, en conservant tout son sens "
        "technique, son registre oral et son intention. Il s'agit de la transcription "
        "d'un artisan expliquant son geste métier à voix haute — conserve le ton "
        "parlé, à la première personne.\n\n"
        f"{glossary}"
        f'Transcription originale ({source_lang}) :\n"{transcription}"\n\n'
        "Réponds avec UNIQUEMENT la traduction française, sans explication."
    )


def build_chunk_translation_prompt(
    chunk_text: str, source_lang: str, glossary: str = ""
) -> str:
    """Translation prompt for a course-content chunk.

    `chunk_text` may already include a heading breadcrumb baked in by
    SemanticChunker (see course_rag_service.py) — translate the whole thing
    as plain text, there's no markup to preserve.

    The French-vocabulary instruction is not decoration: translating a Greek
    glassblowing page, the model rendered "ανοπτητήριο" (annealing oven) as
    the English "annealer" rather than "four de recuit". English leaking into
    the French corpus hurts retrieval twice over — the chunk no longer matches
    the French term a learner would search for, and the breadcrumb translator
    takes this text as its glossary, so one English word in a body propagates
    into every heading under it.

    `glossary` is the craft's term list (see config/glossaries.py), empty for
    the ~97% of the corpus that belongs to no craft. Forbidding English was
    not enough on its own: the model went on to pick French words the trade
    does not use — `l'anneau de recuisson` for an annealing oven, `glace` for
    the glass itself. Naming the right term is what a prohibition cannot do.
    """
    return (
        "Traduis le contenu pédagogique suivant en français, en conservant tout son "
        "sens technique et sa structure (y compris un éventuel titre de section en "
        "début de texte).\n\n"
        "Emploie systématiquement le terme français du métier : n'introduis aucun mot "
        "anglais et ne translittère pas un terme technique. Ne conserve un mot d'origine "
        "étrangère que s'il est lui-même le terme consacré en français dans ce métier.\n\n"
        f"{glossary}"
        f'Contenu original ({source_lang}) :\n"{chunk_text}"\n\n'
        "Réponds avec UNIQUEMENT la traduction française, sans explication."
    )
