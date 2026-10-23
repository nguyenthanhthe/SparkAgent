"""Encrypted secret vault + log redaction.

Secrets are read, in priority order, from:

1. Real environment variables (``GLM_API_KEY``, ``TELEGRAM_BOT_TOKEN``, …).
2. The encrypted store ``data/vault.bin``, usable only when a master key is
   provided via the ``SPARKAGENT_VAULT_KEY`` environment variable.

No credential ever lives in source code, config files, or examples.

The store uses a pure-stdlib authenticated-encryption envelope:

- ``enc_key`` / ``mac_key`` derived from the master key and a random salt
  with HMAC-SHA256 (HKDF-style domain separation);
- keystream blocks generated as ``HMAC(enc_key, nonce || counter)`` — a
  standard PRF-based stream cipher;
- ciphertext truncated-mac'd with ``HMAC(mac_key, nonce || ciphertext)`` and
  verified in constant time before decryption.

That is sound for local secrets at rest without pulling in a crypto
dependency; swap in `cryptography` AES-GCM if compliance requires it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
from pathlib import Path

from kernel.logging import get_logger

logger = get_logger("vault")

MASTER_KEY_ENV = "SPARKAGENT_VAULT_KEY"
SECRET_ENV_PREFIX = "SPARKAGENT_SECRET_"
_SALT_LEN = 16
_NONCE_LEN = 16
_TAG_LEN = 16


class VaultLocked(Exception):
    """The encrypted store is unavailable (no master key configured)."""


class SecretVault:
    def __init__(self, store_path: Path | None = None):
        self._store_path = store_path
        self._secrets: dict[str, str] = {}
        self._master_key: bytes | None = None
        raw = os.environ.get(MASTER_KEY_ENV, "").strip()
        if raw:
            self._master_key = hashlib.sha256(raw.encode("utf-8")).digest()
        self._load()

    # ------------------------------------------------------------------ store
    @property
    def unlocked(self) -> bool:
        return self._master_key is not None

    def _load(self) -> None:
        if self._store_path is None or not self._store_path.exists():
            return
        if self._master_key is None:
            logger.warning(
                "vault store exists but %s is not set — encrypted secrets "
                "unavailable", MASTER_KEY_ENV)
            return
        blob = self._store_path.read_bytes()
        salt, nonce, tag, ct = (blob[:_SALT_LEN], blob[_SALT_LEN:_SALT_LEN + _NONCE_LEN],
                                blob[_SALT_LEN + _NONCE_LEN:_SALT_LEN + _NONCE_LEN + _TAG_LEN],
                                blob[_SALT_LEN + _NONCE_LEN + _TAG_LEN:])
        try:
            plaintext = _decrypt(self._master_key, salt, nonce, tag, ct)
            loaded = json.loads(plaintext)
            if isinstance(loaded, dict):
                self._secrets = {str(k): str(v) for k, v in loaded.items()}
        except Exception as exc:  # noqa: BLE001 — corrupted store must not crash boot
            logger.error("vault store failed to decrypt: %s", exc)

    def _persist(self) -> None:
        if self._store_path is None or self._master_key is None:
            raise VaultLocked(
                f"set {MASTER_KEY_ENV} to enable the encrypted vault store")
        blob = _encrypt(self._master_key, json.dumps(self._secrets).encode("utf-8"))
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_bytes(blob)
        try:  # best-effort permissions; a no-op on Windows
            os.chmod(self._store_path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------- api
    def get(self, name: str) -> str | None:
        """Look up a secret by canonical name (env first, then store)."""
        upper = name.strip().upper()
        for env_name in (upper, SECRET_ENV_PREFIX + upper):
            value = os.environ.get(env_name, "").strip()
            if value:
                return value
        return self._secrets.get(upper)

    def require(self, name: str) -> str:
        value = self.get(name)
        if not value:
            raise VaultLocked(
                f"secret {name!r} not found — set the {name} environment "
                f"variable or add it to the vault "
                f"(python -m openshell.vault set {name})")
        return value

    def set(self, name: str, value: str) -> None:
        self._secrets[name.strip().upper()] = value
        self._persist()
        logger.info("vault secret stored: %s", name)

    def delete(self, name: str) -> bool:
        existed = self._secrets.pop(name.strip().upper(), None) is not None
        if existed:
            self._persist()
        return existed

    def list_names(self) -> list[str]:
        stored = sorted(self._secrets)
        envs = sorted(k[len(SECRET_ENV_PREFIX):] for k in os.environ
                      if k.startswith(SECRET_ENV_PREFIX))
        return sorted(set(stored) | set(envs))

    # -------------------------------------------------------------- redaction
    _GENERIC_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
        r"(sk-[A-Za-z0-9]{16,})",
        r"(ghp_[A-Za-z0-9]{20,})",
        r"(github_pat_[A-Za-z0-9_]{20,})",
        r"(glpat-[A-Za-z0-9\-_]{16,})",
        r"(xox[bap]-[A-Za-z0-9\-]{10,})",
        r"(AKIA[0-9A-Z]{16})",
        r"(Bearer\s+)[A-Za-z0-9._\-]{16,}",
        r"((?:api[_\-]?key|token|secret|password)\b[\"']?\s*[:=]\s*[\"']?)"
        r"[A-Za-z0-9._\-+/]{8,}",
    ))

    def redact(self, text: str) -> str:
        """Mask secret values (known + pattern-matched) before logging/output."""
        for value in self._secrets.values():
            if len(value) >= 6:
                text = text.replace(value, "***REDACTED***")
        for pattern in self._GENERIC_PATTERNS:
            def _sub(match: re.Match, _pattern: re.Pattern = pattern) -> str:
                # If the pattern captures a prefix (e.g. "Bearer ", "token="),
                # keep it and redact only the credential itself.
                if (match.lastindex and match.start(1) == match.start()
                        and match.end(1) < match.end()):
                    return match.group(1) + "***REDACTED***"
                return "***REDACTED***"
            text = pattern.sub(_sub, text)
        return text


# --------------------------------------------------------------------- crypto
def _derive_keys(master: bytes, salt: bytes) -> tuple[bytes, bytes]:
    enc_key = hmac.new(master, salt + b"|enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, salt + b"|mac", hashlib.sha256).digest()
    return enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    for counter in range((length + 31) // 32):
        blocks.append(hmac.new(enc_key, nonce + struct.pack(">Q", counter),
                               hashlib.sha256).digest())
    return b"".join(blocks)[:length]


def _encrypt(master: bytes, plaintext: bytes) -> bytes:
    salt = secrets.token_bytes(_SALT_LEN)
    nonce = secrets.token_bytes(_NONCE_LEN)
    enc_key, mac_key = _derive_keys(master, salt)
    ct = bytes(a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()[:_TAG_LEN]
    return salt + nonce + tag + ct


def _decrypt(master: bytes, salt: bytes, nonce: bytes,
             tag: bytes, ct: bytes) -> bytes:
    enc_key, mac_key = _derive_keys(master, salt)
    expected = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()[:_TAG_LEN]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("vault integrity check failed (wrong master key or corrupt file)")
    keystream = _keystream(enc_key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, keystream))


# ----------------------------------------------------------------------- CLI
def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m openshell.vault",
                                     description="manage the SparkAgent secret vault")
    parser.add_argument("command", choices=["set", "get", "delete", "list"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()

    from kernel.config import Config
    vault = SecretVault(Config.load().path("data/vault.bin"))

    if args.command == "list":
        for name in vault.list_names():
            print(name)
        return 0
    if not args.name:
        parser.error("secret name is required")
    if args.command == "set":
        import getpass
        value = getpass.getpass(f"value for {args.name}: ")
        vault.set(args.name, value)
        print("stored")
    elif args.command == "get":
        value = vault.get(args.name)
        if value is None:
            print("(not set)")
            return 1
        print(value)
    elif args.command == "delete":
        print("deleted" if vault.delete(args.name) else "(not found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
