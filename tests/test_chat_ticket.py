"""Chat tickets: /api/chat must only speak for the Moodle user who asked.

Apache used to add the internal token to every public request, so anyone
could POST to /craftpilot-api/chat with any user_id and read that user's
cohort-siloed content. Now browsers carry a short-lived ticket signed by
local/craftpilot/chat_proxy.php, and the backend holds each request to the
ticket's user. These tests need only FastAPI (and PHP for the cross-check).
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from core.chat_ticket import (
    MAX_TTL_SECONDS,
    authorize,
    internal_token_middleware,
    issue_ticket,
    require_ticket_user,
    token_matches,
    verify_ticket,
)

SECRET = "a" * 64
NOW = 1_800_000_000
PUBLIC = {"/", "/api/health", "/api/status"}
PLUGIN_TICKET_CLASS = Path(__file__).resolve().parents[1] / "plugin" / "classes" / "chat_ticket.php"


# --------------------------------------------------------------- the ticket
def test_round_trip():
    assert verify_ticket(issue_ticket(42, SECRET, now=NOW), SECRET, now=NOW + 5) == 42


@pytest.mark.parametrize("ticket_fn", [
    lambda: issue_ticket(42, "other-secret", now=NOW),                      # wrong key
    lambda: issue_ticket(42, SECRET, ttl=10, now=NOW - 60),                 # expired
    lambda: issue_ticket(42, SECRET, ttl=MAX_TTL_SECONDS + 60, now=NOW),    # claims too long a life
    lambda: issue_ticket(42, SECRET, now=NOW).replace("v1.42.", "v1.43.", 1),  # user swapped, same signature
    lambda: "",
    lambda: "v1.42",
    lambda: "v2.42.1800000120." + "0" * 64,
    lambda: "v1.0.1800000120." + "0" * 64,                                  # user 0
    lambda: "v1.42.1800000120." + "Z" * 64,
    lambda: issue_ticket(42, SECRET, now=NOW) + "0",
])
def test_bad_tickets_are_refused(ticket_fn):
    assert verify_ticket(ticket_fn(), SECRET, now=NOW) is None


def test_no_secret_accepts_nothing():
    assert verify_ticket(issue_ticket(42, "", now=NOW), "", now=NOW) is None


@pytest.mark.parametrize("provided, expected, ok", [
    ("tok", "tok", True), ("tok", "other", False), ("", "tok", False),
    ("tok", "", False), ("", "", False), ("tök-nonascii", "tok", False),
])
def test_token_matches(provided, expected, ok):
    assert token_matches(provided, expected) is ok


# --------------------------------------------------------------- the decision
def test_authorize_rules():
    t = issue_ticket(7, SECRET, now=NOW)
    assert authorize("/api/health", "", "", SECRET, PUBLIC, now=NOW) == (True, None)
    assert authorize("/api/annotations-dashboard", SECRET, "", SECRET, PUBLIC, now=NOW) == (True, None)
    assert authorize("/api/chat", SECRET, "", SECRET, PUBLIC, now=NOW) == (True, None)   # server-side caller
    assert authorize("/api/chat", "", t, SECRET, PUBLIC, now=NOW) == (True, 7)          # browser with ticket
    assert authorize("/api/chat", "", "", SECRET, PUBLIC, now=NOW) == (False, None)
    assert authorize("/api/chat", "wrong", t[:-1] + "0", SECRET, PUBLIC, now=NOW) == (False, None)
    # a ticket opens the chat route only
    assert authorize("/api/annotations-dashboard", "", t, SECRET, PUBLIC, now=NOW) == (False, None)
    assert authorize("/api/delete-course", "", t, SECRET, PUBLIC, now=NOW) == (False, None)
    assert authorize("/api/chat/", "", t, SECRET, PUBLIC, now=NOW) == (False, None)


# --------------------------------------------------------------- wired into an app
class _Body(BaseModel):
    user_id: int


@pytest.fixture
def client():
    app = FastAPI()
    app.middleware("http")(internal_token_middleware(SECRET, PUBLIC))

    @app.post("/api/chat")
    async def chat(body: _Body, http_request: Request):
        require_ticket_user(http_request, body.user_id)
        return {"ok": True}

    @app.get("/api/annotations-dashboard")
    async def dashboard():
        return {"rows": []}

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return TestClient(app)


def test_browser_with_own_ticket_is_served(client):
    t = issue_ticket(7, SECRET)
    assert client.post(f"/api/chat?ticket={t}", json={"user_id": 7}).status_code == 200


def test_ticket_cannot_speak_for_another_user(client):
    t = issue_ticket(7, SECRET)
    r = client.post(f"/api/chat?ticket={t}", json={"user_id": 8})
    assert r.status_code == 403


def test_chat_without_ticket_or_token_is_refused(client):
    assert client.post("/api/chat", json={"user_id": 7}).status_code == 401


def test_forged_ticket_is_refused(client):
    t = issue_ticket(7, "guessed-secret")
    assert client.post(f"/api/chat?ticket={t}", json={"user_id": 7}).status_code == 401


def test_server_side_caller_with_token_is_not_held_to_a_ticket(client):
    r = client.post("/api/chat", json={"user_id": 8}, headers={"X-Internal-Token": SECRET})
    assert r.status_code == 200


def test_ticket_does_not_open_other_routes(client):
    t = issue_ticket(7, SECRET)
    assert client.get(f"/api/annotations-dashboard?ticket={t}").status_code == 401
    assert client.get("/api/health").status_code == 200


# --------------------------------------------------------------- PHP <-> Python
@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_ticket_minted_by_the_moodle_plugin_verifies_here():
    php = (
        "define('MOODLE_INTERNAL', true); require $argv[1];"
        "echo \\local_craftpilot\\chat_ticket::issue((int) $argv[2], $argv[3], 120, (int) $argv[4]);"
    )
    out = subprocess.run(
        ["php", "-r", php, str(PLUGIN_TICKET_CLASS), "293", SECRET, str(NOW)],
        capture_output=True, text=True, check=True,
    ).stdout
    assert out == issue_ticket(293, SECRET, now=NOW)
    assert verify_ticket(out, SECRET, now=NOW + 1) == 293
    assert verify_ticket(out, "b" * 64, now=NOW + 1) is None
