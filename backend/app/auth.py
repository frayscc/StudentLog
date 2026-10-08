import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, HTTPException, Response, status

from .config import settings

SESSION_TTL = timedelta(hours=12)


def _signature(value: str) -> str:
    return hmac.new(settings.app_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def create_session(response: Response, username: str) -> None:
    expiry = int((datetime.now() + SESSION_TTL).timestamp())
    nonce = secrets.token_hex(8)
    body = f"{username}:{expiry}:{nonce}"
    response.set_cookie(
        "studentlog_session",
        f"{body}:{_signature(body)}",
        httponly=True,
        samesite="strict",
        max_age=int(SESSION_TTL.total_seconds()),
    )


def require_login(studentlog_session: str | None = Cookie(default=None)) -> str:
    if not studentlog_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        body, signature = studentlog_session.rsplit(":", 1)
        username, expiry, _ = body.split(":", 2)
        expiry_timestamp = int(expiry)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="登录状态无效") from exc
    if not hmac.compare_digest(signature, _signature(body)) or expiry_timestamp < datetime.now().timestamp():
        raise HTTPException(status_code=401, detail="登录已过期")
    return username


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False
