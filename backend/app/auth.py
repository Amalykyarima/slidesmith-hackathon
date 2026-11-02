"""Access-code sign-in for a hosted SlideSmith.

No user database: codes come from the ACCESS_CODES setting ("Name:code, ..."),
and a signed cookie remembers who signed in. That suits free hosts whose disk is
wiped on restart. Everything a teacher uploads or makes is tagged with her name,
and she only ever sees her own.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextvars import ContextVar

from . import config

COOKIE = "slidesmith_session"
MAX_AGE = 14 * 24 * 3600  # two weeks
PUBLIC_PATHS = {"/api/health", "/api/session", "/api/login", "/api/logout"}

# The signed-in teacher for the current request ("" when sign-in is switched off).
current_owner: ContextVar[str] = ContextVar("current_owner", default="")


def owner() -> str:
    return current_owner.get()


def _sig(payload: bytes) -> str:
    return hmac.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()


def make_token(name: str, now: float | None = None) -> str:
    # No "=" padding: cookies can't hold "=", and a quoted cookie value would not verify.
    payload = base64.urlsafe_b64encode(
        json.dumps({"n": name, "exp": int((now or time.time()) + MAX_AGE)}).encode()
    ).rstrip(b"=")
    return f"{payload.decode()}.{_sig(payload)}"


def read_token(token: str | None) -> str | None:
    """The teacher's name if the token is genuine and not expired."""
    token = (token or "").strip('"')
    if "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(_sig(payload.encode()), sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode() + b"=" * (-len(payload) % 4)))
    except ValueError:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data.get("n") or None


def name_for_code(code: str) -> str | None:
    code = (code or "").strip()
    for known, name in config.ACCESS_CODES.items():
        if hmac.compare_digest(known.encode(), code.encode()):
            return name
    return None


def _cookie_value(scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key == b"cookie":
            for part in value.decode("latin-1").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    return v
    return None


class AuthMiddleware:
    """Pure ASGI middleware: sets `current_owner` and blocks /api and /files without a sign-in."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        name = read_token(_cookie_value(scope)) if config.AUTH_ENABLED else ""
        path = scope.get("path", "")
        protected = path.startswith("/api/") or path.startswith("/files/")
        if config.AUTH_ENABLED and protected and path not in PUBLIC_PATHS and not name:
            body = json.dumps({"detail": "Please sign in with your access code."}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        token = current_owner.set(name or "")
        try:
            await self.app(scope, receive, send)
        finally:
            current_owner.reset(token)
