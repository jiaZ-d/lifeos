"""Crypto round-trip tests (design P1-7, M0 PoC)."""
import pytest

from app.services import crypto


def test_dek_roundtrip():
    dek = crypto.generate_dek()
    token = crypto.encrypt_payload(dek, "秘密内容 secret 123".encode())
    assert crypto.decrypt_payload(dek, token).decode() == "秘密内容 secret 123"


def test_wrong_dek_fails():
    dek = crypto.generate_dek()
    token = crypto.encrypt_payload(dek, b"data")
    with pytest.raises(Exception):
        crypto.decrypt_payload(crypto.generate_dek(), token)


def test_pin_wrap_unwrap():
    dek = crypto.generate_dek()
    wrapped, salt = crypto.wrap_dek(dek, "654321")
    assert crypto.unwrap_dek(wrapped, "654321", salt) == dek
    with pytest.raises(Exception):
        crypto.unwrap_dek(wrapped, "999999", salt)


def test_change_pin_rewrap_keeps_dek():
    """Changing PIN re-wraps the same DEK; old data stays readable (P0-4)."""
    dek = crypto.generate_dek()
    token = crypto.encrypt_payload(dek, b"diary")
    wrapped_old, salt_old = crypto.wrap_dek(dek, "111111")
    dek2 = crypto.unwrap_dek(wrapped_old, "111111", salt_old)
    wrapped_new, salt_new = crypto.wrap_dek(dek2, "222222")
    assert crypto.unwrap_dek(wrapped_new, "222222", salt_new) == dek
    assert crypto.decrypt_payload(dek, token) == b"diary"


def test_admin_recovery_dual_wrap():
    """DEK wrapped by both PIN and recovery passphrase; admin path recovers (N1)."""
    dek = crypto.generate_dek()
    pin_wrap, pin_salt = crypto.wrap_dek(dek, "abcdef")
    rec_wrap, rec_salt = crypto.wrap_dek(dek, "recovery-passphrase-2026")
    # user forgot PIN -> admin path recovers DEK, user sets new PIN
    dek_recovered = crypto.unwrap_dek(rec_wrap, "recovery-passphrase-2026", rec_salt)
    new_wrap, new_salt = crypto.wrap_dek(dek_recovered, "newpin99")
    assert crypto.unwrap_dek(new_wrap, "newpin99", new_salt) == dek
    assert crypto.unwrap_dek(pin_wrap, "abcdef", pin_salt) == dek


def test_pin_rules():
    with pytest.raises(ValueError):
        crypto.validate_pin("12345")
    crypto.validate_pin("123456")


def test_pin_verify():
    salt, digest = crypto.make_pin_verify("secret-pin")
    assert crypto.verify_pin("secret-pin", salt, digest)
    assert not crypto.verify_pin("wrong-pin", salt, digest)


def test_password_hash():
    h = crypto.hash_password("p@ssw0rd")
    assert crypto.verify_password("p@ssw0rd", h)
    assert not crypto.verify_password("nope", h)
