"""Signed, short-lived tickets that bind a browser's chat request to a Moodle user.

Browsers reach /api/chat through Apache, not from Moodle's server, so they
cannot present the internal token. Instead local/craftpilot/chat_proxy.php,
after checking the Moodle session and sesskey, puts a ticket in the 307
redirect it issues (/craftpilot-api/chat?ticket=...):

    v1.<user_id>.<expires_unix>.<hex HMAC-SHA256(secret, "v1|<user_id>|<expires_unix>")>

The secret is the internal token both sides already share. /api/chat accepts
either the internal token (server-side callers) or a valid ticket, and the
route then holds the request to the ticket's user. Before this, Apache added
the internal token to every public request, so anyone could POST to
/craftpilot-api/chat with any user_id and read that user's cohort-siloed
content.

Keep the format in sync with plugin/classes/chat_ticket.php.
"""

import hashlib
import hmac
import re
import time
from typing import Iterable, Optional, Tuple

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

TICKET_TTL_SECONDS = 120  # what chat_proxy.php grants; the redirect is followed at once
MAX_TTL_SECONDS = 300     # refuse tickets claiming a longer life than any issuer grants
CHAT_PATH = "/api/chat"

_TICKET_RE = re.compile(r"^v1\.([1-9][0-9]{0,9})\.([0-9]{1,12})\.([0-9a-f]{64})$")


def _signature(secret: str, user_id: int, expires: int) -> str:
    return hmac.new(secret.encode(), f"v1|{user_id}|{expires}".encode(), hashlib.sha256).hexdigest()


def issue_ticket(user_id: int, secret: str, ttl: int = TICKET_TTL_SECONDS,
                 now: Optional[int] = None) -> str:
    """Mint a ticket. Production tickets come from PHP; this mirrors it for tests."""
    expires = int(now if now is not None else time.time()) + ttl
    return f"v1.{user_id}.{expires}.{_signature(secret, user_id, expires)}"


def verify_ticket(ticket: str, secret: str, now: Optional[int] = None) -> Optional[int]:
    """Return the ticket's user id, or None if it is malformed, forged or expired."""
    if not secret or not ticket:
        return None
    match = _TICKET_RE.match(ticket)
    if not match:
        return None
    user_id, expires, signature = int(match.group(1)), int(match.group(2)), match.group(3)
    current = int(now if now is not None else time.time())
    if expires < current or expires > current + MAX_TTL_SECONDS:
        return None
    if not hmac.compare_digest(signature, _signature(secret, user_id, expires)):
        return None
    return user_id


def token_matches(provided: str, expected: str) -> bool:
    """Constant-time X-Internal-Token check. An unset secret matches nothing."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def authorize(path: str, internal_token: str, ticket: str, secret: str,
              public_paths: Iterable[str], now: Optional[int] = None) -> Tuple[bool, Optional[int]]:
    """Decide a request: (allowed, ticket_user_id).

    Public paths are open. Everything else needs the internal token, except
    the chat route, which also accepts a valid ticket. When a ticket is what
    let the request in, ticket_user_id is the user the route must hold it to.
    """
    if path in public_paths:
        return True, None
    if token_matches(internal_token, secret):
        return True, None
    if path == CHAT_PATH:
        user_id = verify_ticket(ticket, secret, now=now)
        if user_id is not None:
            return True, user_id
    return False, None


def internal_token_middleware(secret: str, public_paths: Iterable[str]):
    """The HTTP middleware server.py installs, built around authorize()."""
    public = frozenset(public_paths)

    async def middleware(request: Request, call_next):
        allowed, ticket_user_id = authorize(
            request.url.path,
            request.headers.get("X-Internal-Token", ""),
            request.query_params.get("ticket", ""),
            secret,
            public,
        )
        if not allowed:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        request.state.chat_ticket_user_id = ticket_user_id
        return await call_next(request)

    return middleware


def require_ticket_user(request: Request, user_id: Optional[int]) -> None:
    """In the chat route: a ticket-authenticated request may only speak for its own user."""
    ticket_user_id = getattr(request.state, "chat_ticket_user_id", None)
    if ticket_user_id is not None and user_id != ticket_user_id:
        raise HTTPException(status_code=403, detail="user_id does not match the chat ticket")
