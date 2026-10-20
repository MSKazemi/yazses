"""Machine-bound encryption for the learning corpus.

A single 256-bit key is generated on first use and stored at
``<data_dir>/corpus.key`` with ``0600`` permissions (the SSH-key model): the
daemon can read it without prompting, but it is not world/group readable and is
not synced to any cloud. This protects the captured audio and transcripts
against casual access and accidental sync — not against a determined local
attacker who already has the user's read access.

Encryption is AES-256-GCM (authenticated): a fresh 12-byte nonce is generated
per message and prepended to the ciphertext, so tampering is detected on decrypt.
"""
from __future__ import annotations

import os
from pathlib import Path

_KEY_FILENAME = "corpus.key"
_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # GCM standard nonce size


def load_or_create_key(data_dir: Path) -> bytes:
    """Return the corpus key, creating it (and ``data_dir``) on first use.

    The directory is created ``0700`` and the key file ``0600``.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    # Tighten perms even if the directory already existed with looser bits.
    os.chmod(data_dir, 0o700)
    key_file = data_dir / _KEY_FILENAME

    if key_file.exists():
        return key_file.read_bytes()

    key = os.urandom(_KEY_BYTES)
    # Write with restrictive perms from the start, never widening the window.
    # O_BINARY (Windows only; 0 elsewhere) avoids text-mode CRLF translation that
    # would expand a 0x0A byte in the random key to 0x0D 0x0A, corrupting it to
    # 33+ bytes ("key must be 32 bytes, got 33").
    fd = os.open(
        key_file,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    os.chmod(key_file, 0o600)
    return key


class Cipher:
    """AES-256-GCM encrypt/decrypt with a per-message random nonce."""

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise ValueError(f"key must be {_KEY_BYTES} bytes, got {len(key)}")
        # Imported here: the daemon imports this module on every start (the corpus
        # writer is built even when learning is off, and returns None), and the
        # cryptography bindings cost ~7 ms that a user who never opted in should not pay.
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext, None)

    def decrypt(self, blob: bytes) -> bytes:
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        return self._aead.decrypt(nonce, ct, None)

    def encrypt_str(self, text: str) -> bytes:
        return self.encrypt(text.encode("utf-8"))

    def decrypt_str(self, blob: bytes) -> str:
        return self.decrypt(blob).decode("utf-8")
