"""Transient provider failures must be retried; client errors must not.

Two outages in three days, both in bursts that cleared on their own:

  * 2026-09-07 — /embeddings returned 500s for about an hour.
  * 2026-09-09 — /chat returned "404 page not found". The first module of
    each run translated fine and every later one failed instantly, then the
    next run succeeded again from a cold start.

Only 429 was retried, so the 404s cost 37 of course 109's 53 chunks in a
single run. A 404 that comes and goes is the provider shedding load, not a
URL that stopped existing.

The line is drawn at whether repeating the request could plausibly work. A
401 or a 400 means the request itself is wrong, and retrying only turns a
fast failure into a slow one.

No sleeping: time.sleep is patched out.
"""

from unittest.mock import MagicMock

import pytest

from services import translation_service


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    monkeypatch.setattr(translation_service.time, "sleep", lambda seconds: None)


def _llm_failing_times(n, error):
    """An LLM that raises `error` n times, then succeeds."""
    llm = MagicMock()
    calls = {"n": 0}

    def invoke(prompt):
        calls["n"] += 1
        if calls["n"] <= n:
            raise RuntimeError(error)
        # extract_text reads .content, so a bare string will not do.
        response = MagicMock()
        response.content = "Le verre est un matériau."
        return response

    llm.invoke.side_effect = invoke
    llm.call_count = calls
    return llm


@pytest.mark.parametrize(
    "error",
    [
        "Error code: 429 - rate limit exceeded",
        "404 page not found",
        "Error code: 500 - internal server error",
        "Error code: 503 - service unavailable",
        "Request timed out",
    ],
    ids=["429", "404", "500", "503", "timeout"],
)
def test_transient_failures_are_retried(error):
    llm = _llm_failing_times(2, error)

    result = translation_service.translate_to_french("prompt", llm, max_retries=3)

    assert result == "Le verre est un matériau."
    assert llm.call_count["n"] == 3


@pytest.mark.parametrize(
    "error",
    [
        "Error code: 401 - invalid api key",
        "Error code: 400 - bad request",
        "Error code: 403 - forbidden",
    ],
    ids=["401", "400", "403"],
)
def test_client_errors_fail_immediately(error):
    """Repeating a malformed or unauthorised request cannot fix it."""
    llm = _llm_failing_times(2, error)

    result = translation_service.translate_to_french("prompt", llm, max_retries=3)

    assert result is None
    assert llm.call_count["n"] == 1


def test_retries_give_up_and_return_none():
    """Exhausting the retries still degrades to None, never raises."""
    llm = _llm_failing_times(99, "404 page not found")

    result = translation_service.translate_to_french("prompt", llm, max_retries=2)

    assert result is None
    assert llm.call_count["n"] == 3   # the first attempt plus two retries


def test_the_query_path_does_not_retry_by_default():
    """A live query must not wait out a provider incident."""
    llm = _llm_failing_times(99, "404 page not found")

    assert translation_service.translate_to_french("prompt", llm) is None
    assert llm.call_count["n"] == 1
