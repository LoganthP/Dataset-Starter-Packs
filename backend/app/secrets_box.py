"""Encryption at rest for provider credentials (Fernet: AES-128-CBC + HMAC-SHA256).

Key: DSP_SECRET_KEY (a Fernet key: 32 url-safe base64 bytes). Required on Vercel and anywhere with more
than one instance. Locally and in Docker, a key is generated once into DSP_STATE_DIR/secret.key (0600)
on the named volume, so connections survive restarts. Rotating the key disconnects stored accounts.
"""
from __future__ import annotations

import os
from functools import lru_cache

from . import config


class SecretsUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _fernet():
    from cryptography.fernet import Fernet

    key = os.getenv("DSP_SECRET_KEY")
    if not key:
        if config.ON_VERCEL:
            raise SecretsUnavailable("Set DSP_SECRET_KEY to store provider connections on this deployment.")
        path = config.STATE_DIR / "secret.key"
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(Fernet.generate_key())
        key = path.read_text().strip()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretsUnavailable("Stored credentials can't be decrypted (DSP_SECRET_KEY changed). Reconnect the account.") from exc
