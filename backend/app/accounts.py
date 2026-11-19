"""App accounts: sign up, log in, log out. Keeps each person's provider connections and reports separate.

Passwords: scrypt (n=2^14, r=8, p=1) with a per-user salt. Sessions: a random token in an HttpOnly,
SameSite=Lax cookie (Secure on HTTPS); only its SHA-256 is stored. Nothing about the session or any
provider credential is readable from JavaScript or stored in the browser.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets
import uuid

from fastapi import HTTPException, Request, Response

from . import durable

COOKIE = "dsp_session"
SESSION_DAYS = 30
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def _check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    test = _hash_password(password, base64.b64decode(salt)).split("$")[2]
    return hmac.compare_digest(test, digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_up(email: str, password: str) -> dict:
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if len(password) < 10:
        raise HTTPException(422, "Use a password of at least 10 characters.")
    if durable.one("select id from users where email=?", (email,)):
        raise HTTPException(409, "An account with this email already exists. Log in instead.")
    uid = uuid.uuid4().hex
    durable.execute("insert into users (id, email, password_hash, created_at) values (?,?,?,?)",
                    (uid, email, _hash_password(password), _now().isoformat()))
    return {"id": uid, "email": email}


def log_in(email: str, password: str) -> dict:
    row = durable.one("select id, email, password_hash from users where email=?", (email.strip().lower(),))
    if not row or not _check_password(password, row["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    return {"id": row["id"], "email": row["email"]}


def start_session(response: Response, request: Request, user: dict) -> None:
    token = secrets.token_urlsafe(32)
    durable.execute("insert into sessions (token_hash, user_id, created_at, expires_at) values (?,?,?,?)",
                    (_token_hash(token), user["id"], _now().isoformat(), (_now() + dt.timedelta(days=SESSION_DAYS)).isoformat()))
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")


def end_session(response: Response, request: Request) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        durable.execute("delete from sessions where token_hash=?", (_token_hash(token),))
    response.delete_cookie(COOKIE, path="/")


def current(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    row = durable.one("select u.id, u.email, s.expires_at from sessions s join users u on u.id=s.user_id where s.token_hash=?", (_token_hash(token),))
    if not row or row["expires_at"] < _now().isoformat():
        return None
    return {"id": row["id"], "email": row["email"]}


def user_id(request: Request) -> str | None:
    u = current(request)
    return u["id"] if u else None


def require(request: Request) -> dict:
    u = current(request)
    if not u:
        raise HTTPException(401, {"message": "Log in to connect a provider account.", "kind": "login_required"})
    return u
