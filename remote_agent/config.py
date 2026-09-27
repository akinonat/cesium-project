"""Yapılandırma dosyası ve parola özeti (PBKDF2-SHA256) yönetimi."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10


def default_config_dir() -> Path:
    """Windows'ta %APPDATA%\\RemoteAgent, diğer sistemlerde ~/.config/remote-agent."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "RemoteAgent"
    return Path.home() / ".config" / "remote-agent"


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass
class Config:
    name: str = field(default_factory=lambda: os.environ.get("COMPUTERNAME", "Bilgisayar"))
    host: str = "0.0.0.0"
    port: int = 8765
    password_hash: str = ""
    tls: bool = False
    session_hours: int = 12
    keep_awake: bool = True
    # Yayın varsayılanları (bağlantı sırasında istemciden değiştirilebilir)
    fps: int = 15
    quality: int = 60
    max_width: int = 1920

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
