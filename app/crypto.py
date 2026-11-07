import base64
import hashlib
import hmac
import json
import os
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def generate_salt() -> str:
    return base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")


def hash_password(password: str, salt: str) -> str:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode("ascii"),
        iterations=120_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8"))).decode("ascii")


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected_hash)


def _derive_fernet_key(secret: str, salt: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode("ascii"),
        iterations=120_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def _preclaim_secret(server_salt: str, user_id: int) -> str:
    return hmac.new(
        server_salt.encode("utf-8"),
        f"preclaim-slot-{user_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def encrypt_payload(payload: Dict[str, Any], secret: str, salt: str) -> str:
    key = _derive_fernet_key(secret, salt)
    f = Fernet(key)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return f.encrypt(raw).decode("ascii")


def decrypt_payload(token: str, secret: str, salt: str) -> Dict[str, Any]:
    key = _derive_fernet_key(secret, salt)
    f = Fernet(key)
    try:
        raw = f.decrypt(token.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Kunde inte låsa upp lottningen med angivet lösenord.") from exc


def encrypt_preclaim_assignment(payload: Dict[str, Any], server_salt: str, user_id: int, user_salt: str) -> str:
    secret = _preclaim_secret(server_salt, user_id)
    return encrypt_payload(payload, secret, user_salt)


def decrypt_preclaim_assignment(token: str, server_salt: str, user_id: int, user_salt: str) -> Dict[str, Any]:
    secret = _preclaim_secret(server_salt, user_id)
    return decrypt_payload(token, secret, user_salt)
