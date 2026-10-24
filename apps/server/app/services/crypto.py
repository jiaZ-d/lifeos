"""Encryption service: Argon2id KDF + KEK/DEK + AES-256-GCM (design P0-4, N1).

Structure:
- DEK: random 256-bit data key, encrypts private payloads (AES-256-GCM).
- KEK: derived from PIN (user) or recovery passphrase (admin) via Argon2id,
  wraps/unwraps the DEK. Changing a PIN re-wraps only; data never re-encrypted.
- Admin recovery: DEK is wrapped twice (pin wrap + recovery wrap).
"""
from __future__ import annotations

import base64
import os

from argon2 import PasswordHasher
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_b64 = base64.urlsafe_b64encode
_unb64 = base64.urlsafe_b64decode

# Argon2id parameters (design: memory=64MB, iterations>=3)
ARGON2_TIME_COST = 3
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_PARALLELISM = 2
SALT_LEN = 16

_pin_hasher = PasswordHasher()  # for pin_verify_hash (stores its own salt)


def _derive_kek(secret: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret=secret.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=32,
        type=Type.ID,
    )


def generate_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


# ---------- wrapping (KEK wraps DEK) ----------

def wrap_dek(dek: bytes, secret: str) -> tuple[str, str]:
    """Return (wrapped_dek_b64, kek_salt_hex)."""
    salt = os.urandom(SALT_LEN)
    kek = _derive_kek(secret, salt)
    nonce = os.urandom(12)
    ct = AESGCM(kek).encrypt(nonce, dek, None)
    return _b64(nonce + ct).decode(), salt.hex()


def unwrap_dek(wrapped_b64: str, secret: str, kek_salt_hex: str) -> bytes:
    kek = _derive_kek(secret, bytes.fromhex(kek_salt_hex))
    raw = _unb64(wrapped_b64.encode())
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(kek).decrypt(nonce, ct, None)


# ---------- payload encryption (DEK) ----------

def encrypt_payload(dek: bytes, plaintext: bytes) -> str:
    nonce = os.urandom(12)
    return _b64(nonce + AESGCM(dek).encrypt(nonce, plaintext, None)).decode()


def decrypt_payload(dek: bytes, token_b64: str) -> bytes:
    raw = _unb64(token_b64.encode())
    return AESGCM(dek).decrypt(raw[:12], raw[12:], None)


# ---------- PIN rules ----------

def validate_pin(pin: str) -> None:
    if len(pin) < 6:
        raise ValueError("PIN must be at least 6 characters")


def make_pin_verify(pin: str) -> tuple[str, str]:
    """Return (pin_verify_salt_hex, pin_verify_hash) using argon2's own encoding."""
    salt = os.urandom(SALT_LEN)
    digest = _pin_hasher.hash(pin + salt.hex())
    return salt.hex(), digest


def verify_pin(pin: str, salt_hex: str, expected_hash: str) -> bool:
    try:
        return _pin_hasher.verify(expected_hash, pin + salt_hex)
    except Exception:
        return False


# ---------- passwords (login) ----------

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except Exception:
        return False
