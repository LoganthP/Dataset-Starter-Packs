"""Connect Kaggle: per-user Kaggle access for listing and downloading dataset files inside the app.

Two ways to connect, both official:
  OAuth 2.0 (authorization code + PKCE) when this deployment has a registered Kaggle client:
      KAGGLE_OAUTH_CLIENT_ID (+ KAGGLE_OAUTH_CLIENT_SECRET for confidential clients), DSP_PUBLIC_URL.
      Endpoints: /api/v1/oauth2/authorize and /api/v1/oauth2/token; access tokens are KGAT_..., refreshed with KGRT_....
  An API token from kaggle.com/settings: either a KGAT_ access token (Bearer) or the kaggle.json
      username + key pair (HTTP Basic). Verified against the Kaggle API before it is stored.

Credentials are encrypted at rest (secrets_box), scoped to the app user, sent only in Authorization headers,
and never returned to the browser, put in URLs, or written to logs or run reports.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from . import durable, secrets_box

PROVIDER = "kaggle"


def base() -> str:
    return os.getenv("KAGGLE_API_BASE", "https://www.kaggle.com").rstrip("/")


def is_kaggle_url(url: str) -> bool:
    return urllib.parse.urlparse(url).netloc in ("www.kaggle.com", urllib.parse.urlparse(base()).netloc)


def oauth_available() -> bool:
    return bool(os.getenv("KAGGLE_OAUTH_CLIENT_ID"))


class ConnectError(RuntimeError):
    def __init__(self, message: str, kind: str = "auth"):
        super().__init__(message)
        self.kind = kind


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _headers_for_secret(sec: dict) -> dict:
    if sec.get("access_token"):
        return {"Authorization": f"Bearer {sec['access_token']}"}
    if sec.get("token"):
        return {"Authorization": f"Bearer {sec['token']}"}
    raw = f"{sec['username']}:{sec['key']}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _call(path: str, headers: dict, *, data: bytes | None = None, ctype: str | None = None, timeout: float = 15) -> dict:
    h = {"User-Agent": "dataset-starter-packs/0.7", "Accept": "application/json", **headers}
    if ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(base() + path, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ConnectError("Kaggle rejected these credentials. Create a new API token at kaggle.com/settings and try again.") from exc
        raise ConnectError(f"Kaggle returned HTTP {exc.code}.", "network") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectError(f"Couldn't reach Kaggle: {getattr(exc, 'reason', exc)}.", "network") from exc


def verify(sec: dict) -> None:
    """One cheap authenticated call; raises ConnectError when Kaggle doesn't accept the credentials."""
    _call("/api/v1/datasets/list?page=1&pageSize=1&search=iris", _headers_for_secret(sec))


def _store(user_id: str, account: str | None, kind: str, sec: dict) -> None:
    durable.execute("""insert into provider_connections (user_id, provider, account, secret, kind, created_at, verified_at, last_error)
                       values (?,?,?,?,?,?,?,null)
                       on conflict (user_id, provider) do update set account=excluded.account, secret=excluded.secret, kind=excluded.kind,
                       verified_at=excluded.verified_at, last_error=null""",
                    (user_id, PROVIDER, account, secrets_box.encrypt(json.dumps(sec)), kind, _now(), _now()))


def connect_with_token(user_id: str, *, token: str | None = None, username: str | None = None, key: str | None = None,
                       kaggle_json: str | None = None) -> dict:
    if kaggle_json:
        try:
            data = json.loads(kaggle_json)
            username, key = data.get("username"), data.get("key")
        except (json.JSONDecodeError, AttributeError) as exc:
            raise ConnectError("That isn't a kaggle.json file (expected {\"username\": ..., \"key\": ...}).", "invalid") from exc
    if token:
        token = token.strip()
        sec, kind, account = {"token": token}, "bearer", username or None
    elif username and key:
        sec, kind, account = {"username": username.strip(), "key": key.strip()}, "basic", username.strip()
    else:
        raise ConnectError("Paste a Kaggle API token, or your kaggle.json username and key.", "invalid")
    verify(sec)
    _store(user_id, account, kind, sec)
    return status(user_id)


def status(user_id: str | None) -> dict:
    row = durable.one("select account, kind, verified_at, last_error, created_at from provider_connections where user_id=? and provider=?",
                      (user_id, PROVIDER)) if user_id else None
    return {"provider": PROVIDER, "connected": bool(row), "account": row["account"] if row else None,
            "method": {"basic": "API key (kaggle.json)", "bearer": "API token", "oauth": "Kaggle sign-in"}.get(row["kind"]) if row else None,
            "verifiedAt": row["verified_at"] if row else None, "lastError": row["last_error"] if row else None,
            "oauthAvailable": oauth_available(), "signedIn": bool(user_id)}


def disconnect(user_id: str) -> None:
    durable.execute("delete from provider_connections where user_id=? and provider=?", (user_id, PROVIDER))


def _secret(user_id: str) -> tuple[dict, str] | None:
    row = durable.one("select secret, kind from provider_connections where user_id=? and provider=?", (user_id, PROVIDER))
    if not row:
        return None
    return json.loads(secrets_box.decrypt(row["secret"])), row["kind"]


def auth_headers(user_id: str | None) -> dict | None:
    if not user_id:
        return None
    got = _secret(user_id)
    if not got:
        return None
    sec, kind = got
    if kind == "oauth" and sec.get("expires_at", 0) < dt.datetime.now(dt.UTC).timestamp() + 60 and sec.get("refresh_token"):
        sec = _refresh(user_id, sec)
    return _headers_for_secret(sec)


def mark_error(user_id: str, message: str) -> None:
    durable.execute("update provider_connections set last_error=? where user_id=? and provider=?", (message[:300], user_id, PROVIDER))


# ---------------------------------------------------------------- OAuth (registered client only)
def _redirect_uri() -> str:
    return os.getenv("DSP_PUBLIC_URL", "http://localhost:8000").rstrip("/") + "/api/kaggle/oauth/callback"


def oauth_start(user_id: str, return_to: str) -> str:
    if not oauth_available():
        raise ConnectError("This deployment has no registered Kaggle OAuth client. Connect with an API token instead.", "unavailable")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    durable.execute("insert into oauth_states (state, user_id, verifier, return_to, created_at) values (?,?,?,?,?)",
                    (state, user_id, secrets_box.encrypt(verifier), return_to if return_to.startswith("/") else "/settings", _now()))
    q = {"client_id": os.environ["KAGGLE_OAUTH_CLIENT_ID"], "redirect_uri": _redirect_uri(), "scope": os.getenv("KAGGLE_OAUTH_SCOPE", "datasets.get:*"),
         "state": state, "response_type": "code", "response_mode": "query", "code_challenge": challenge, "code_challenge_method": "S256"}
    return base() + "/api/v1/oauth2/authorize?" + urllib.parse.urlencode(q)


def _token_request(fields: dict) -> dict:
    headers = {}
    if os.getenv("KAGGLE_OAUTH_CLIENT_SECRET"):
        raw = f"{os.environ['KAGGLE_OAUTH_CLIENT_ID']}:{os.environ['KAGGLE_OAUTH_CLIENT_SECRET']}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    return _call("/api/v1/oauth2/token", headers, data=urllib.parse.urlencode(fields).encode(), ctype="application/x-www-form-urlencoded")


def oauth_callback(state: str, code: str) -> tuple[str, str]:
    row = durable.one("select user_id, verifier, return_to, created_at from oauth_states where state=?", (state,))
    durable.execute("delete from oauth_states where state=?", (state,))
    if not row or row["created_at"] < (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=15)).isoformat(timespec="seconds"):
        raise ConnectError("The Kaggle sign-in expired or was already used. Start again from Settings.", "invalid")
    tok = _token_request({"grant_type": "authorization_code", "code": code, "code_verifier": secrets_box.decrypt(row["verifier"]),
                          "client_id": os.environ.get("KAGGLE_OAUTH_CLIENT_ID", ""), "redirect_uri": _redirect_uri()})
    sec = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
           "expires_at": dt.datetime.now(dt.UTC).timestamp() + float(tok.get("expires_in") or 3600)}
    _store(row["user_id"], tok.get("username"), "oauth", sec)
    return row["user_id"], row["return_to"] or "/settings"


def _refresh(user_id: str, sec: dict) -> dict:
    tok = _token_request({"grant_type": "refresh_token", "refresh_token": sec["refresh_token"]})
    new = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token") or sec["refresh_token"],
           "expires_at": dt.datetime.now(dt.UTC).timestamp() + float(tok.get("expires_in") or 3600)}
    row = durable.one("select account from provider_connections where user_id=? and provider=?", (user_id, PROVIDER))
    _store(user_id, row["account"] if row else None, "oauth", new)
    return new


# ---------------------------------------------------------------- dataset files for a connected user
def list_files(user_id: str, ref: str) -> list[dict]:
    """All files of a Kaggle dataset (follows nextPageToken). Raises ConnectError when not connected or refused."""
    headers = auth_headers(user_id)
    if not headers:
        raise ConnectError("Connect your Kaggle account to list and fetch this dataset's files.", "not_connected")
    owner, slug = ref.split("/", 1)
    out, token, pages = [], None, 0
    while pages < 50:
        q = "?pageSize=200" + (f"&pageToken={urllib.parse.quote(token)}" if token else "")
        try:
            data = _call(f"/api/v1/datasets/list/{urllib.parse.quote(owner)}/{urllib.parse.quote(slug)}{q}", headers)
        except ConnectError as exc:
            mark_error(user_id, str(exc))
            raise
        out += data.get("datasetFiles") or data.get("files") or []
        token = data.get("nextPageToken")
        pages += 1
        if not token:
            break
    return out


def download_url(ref: str, name: str | None) -> str:
    """One file, or the whole dataset as a ZIP when name is None."""
    owner, slug = ref.split("/", 1)
    url = f"{base()}/api/v1/datasets/download/{urllib.parse.quote(owner)}/{urllib.parse.quote(slug)}"
    return url + (f"/{urllib.parse.quote(name)}" if name else "")


def consent_url(ref: str) -> str:
    return f"https://www.kaggle.com/datasets/{ref}"
