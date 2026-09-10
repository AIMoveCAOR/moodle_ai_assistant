"""Transient provider failures must be retried; client errors must not.

Two outages in three days, both in bursts that cleared on their own:

  * 2026-09-07 — /embeddings returned 500s for about an hour.
  * 2026-09-09 — /chat returned 503 Service Unavailable. Only 429 was retried
    at the time, so 37 of course 109's 53 chunks were lost in one run.

The 2026-09-09 case is why this is decided from the HTTP status and not the
error text. The 503's *body* was a load-balancer page reading "404 page not
found", and the OpenAI SDK surfaces the body as the exception message — so
the message said 404 while the status said 503, and only the status was true.
Matching the text would mean depending on the wording of someone else's error
page: it works until the day they reword it, and then it fails silently.

The line is drawn at whether repeating the request could plausibly work. A 401
or a 400 means the request itself is wrong.

No sleeping: conftest neutralises the backoff.
"""

from unittest.mock import MagicMock

import pytest

from services import translation_service


class FakeAPIError(Exception):
    """Shaped like an openai SDK error: a status alongside the body text."""

    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def _llm_failing_times(n, error):
    llm = MagicMock()
    calls = {"n": 0}

    def invoke(prompt):
        calls["n"] += 1
        if calls["n"] <= n:
            raise error
        response = MagicMock()          # extract_text reads .content
        response.content = "Le verre est un matériau."
        return response

    llm.invoke.side_effect = invoke
    llm.call_count = calls
    return llm


def test_the_503_whose_body_says_404_is_retried():
    """The exact 2026-09-09 failure. The message lies; the status does not."""
    error = FakeAPIError(503, "404 page not found")
    llm = _llm_failing_times(2, error)

    result = translation_service.translate_to_french("prompt", llm, max_retries=3)

    assert result == "Le verre est un matériau."
    assert llm.call_count["n"] == 3


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_transient_statuses_are_retried(status):
    llm = _llm_failing_times(1, FakeAPIError(status, "upstream unhappy"))

    assert translation_service.translate_to_french("p", llm, max_retries=2)
    assert llm.call_count["n"] == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_fail_immediately(status):
    """Repeating a rejected request cannot fix it — fail fast instead."""
    llm = _llm_failing_times(2, FakeAPIError(status, "rejected"))

    assert translation_service.translate_to_french("p", llm, max_retries=3) is None
    assert llm.call_count["n"] == 1


def test_a_genuine_404_is_not_retried_just_because_a_503_once_said_404():
    """Status 404 means the route is gone; retrying it is pure delay."""
    llm = _llm_failing_times(2, FakeAPIError(404, "404 page not found"))

    assert translation_service.translate_to_french("p", llm, max_retries=3) is None
    assert llm.call_count["n"] == 1


def test_errors_with_no_status_fall_back_to_the_message():
    """Connection and timeout failures raise before any response exists."""
    for message in ("Request timed out", "Connection reset by peer",
                    "Error code: 502 - bad gateway"):
        llm = _llm_failing_times(1, RuntimeError(message))
        assert translation_service.translate_to_french("p", llm, max_retries=2), message
        assert llm.call_count["n"] == 2, message


def test_a_body_that_merely_mentions_a_status_is_not_treated_as_one():
    """The text fallback is anchored, so body text cannot fake a status."""
    llm = _llm_failing_times(2, RuntimeError("the page said 503 somewhere"))

    assert translation_service.translate_to_french("p", llm, max_retries=3) is None
    assert llm.call_count["n"] == 1


def test_retries_give_up_and_return_none():
    """Exhausting the retries still degrades to None, never raises."""
    llm = _llm_failing_times(99, FakeAPIError(503, "still down"))

    assert translation_service.translate_to_french("p", llm, max_retries=2) is None
    assert llm.call_count["n"] == 3   # first attempt plus two retries


def test_the_query_path_does_not_retry_by_default():
    """A live query must not wait out a provider incident."""
    llm = _llm_failing_times(99, FakeAPIError(503, "still down"))

    assert translation_service.translate_to_french("p", llm) is None
    assert llm.call_count["n"] == 1
