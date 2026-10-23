"""HMAC signing for agent-authored artifacts (skills, prompts, configs).

Skills written at runtime are signed with a key derived from the vault
master key; the loader verifies the signature before activation so a
tampered ``skills/*.py`` file on disk cannot silently execute. Tags are
constant-time compared.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

_SIGNATURE_PREFIX = "# signature: "


def derive_signing_key(master_key: str | bytes, domain: str = "skill") -> bytes:
    """Domain-separated subkey from the vault master key."""
    if isinstance(master_key, str):
        master_key = master_key.encode("utf-8")
    return hmac.new(master_key, f"sparkagent|{domain}".encode("utf-8"),
                    hashlib.sha256).digest()


def sign_bytes(data: bytes, key: bytes) -> str:
    digest = hmac.new(key, data, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign_text(text: str, key: bytes) -> str:
    return sign_bytes(text.encode("utf-8"), key)


def verify_bytes(data: bytes, key: bytes, tag: str) -> bool:
    expected = sign_bytes(data, key)
    return hmac.compare_digest(expected, tag or "")


def verify_text(text: str, key: bytes, tag: str) -> bool:
    return verify_bytes(text.encode("utf-8"), key, tag)


def sign_file(path: Path, key: bytes) -> str:
    """Sign file contents as-is (no mutation)."""
    return sign_bytes(path.read_bytes(), key)


def write_signed_file(path: Path, content: str, key: bytes) -> str:
    """Write content with a signature header line; return the tag."""
    tag = sign_text(content, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{_SIGNATURE_PREFIX}{tag}\n{content}", encoding="utf-8")
    return tag


def read_verified_file(path: Path, key: bytes) -> tuple[bool, str, str]:
    """Read a signed file: (valid, content, tag)."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n", 1)
    if len(lines) != 2 or not lines[0].startswith(_SIGNATURE_PREFIX):
        return False, raw, ""
    tag = lines[0][len(_SIGNATURE_PREFIX):].strip()
    content = lines[1]
    return verify_text(content, key, tag), content, tag
