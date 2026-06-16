"""JWT 鉴权模块测试。

这些测试只依赖标准库（auth.py 本身不引入第三方依赖），
因此即使没装 FastAPI 也能跑：

    PYTHONPATH=backend python -m pytest backend/tests/test_auth.py -q
"""

from __future__ import annotations

import time

import pytest

from app.auth import (
    ROLE_BOSS,
    ROLE_CUSTOMER,
    ROLE_PLATFORM_ADMIN,
    AuthError,
    Principal,
    decode_token,
    encode_token,
    extract_bearer_token,
)


def _customer() -> Principal:
    return Principal(
        user_id=42,
        tenant_id=7,
        role=ROLE_CUSTOMER,
        store_id=3,
        openid="oABC123",
    )


def test_roundtrip_preserves_identity():
    token = encode_token(_customer())
    decoded = decode_token(token)
    assert decoded.user_id == 42
    assert decoded.tenant_id == 7
    assert decoded.store_id == 3
    assert decoded.role == ROLE_CUSTOMER
    assert decoded.openid == "oABC123"


def test_boss_and_platform_admin_flags():
    boss = decode_token(encode_token(Principal(user_id=1, tenant_id=7, role=ROLE_BOSS)))
    assert boss.is_boss is True
    assert boss.is_merchant is True
    assert boss.is_platform_admin is False

    admin = decode_token(
        encode_token(Principal(user_id=0, tenant_id=0, role=ROLE_PLATFORM_ADMIN))
    )
    assert admin.is_platform_admin is True
    assert admin.is_merchant is False


def test_expired_token_rejected():
    token = encode_token(_customer(), ttl_seconds=-1)
    with pytest.raises(AuthError):
        decode_token(token)


def test_tampered_payload_rejected():
    token = encode_token(_customer())
    header, payload, signature = token.split(".")
    # 篡改载荷（哪怕只动一个字符），签名就对不上。
    bad_payload = payload[:-2] + ("AA" if not payload.endswith("AA") else "BB")
    tampered = f"{header}.{bad_payload}.{signature}"
    with pytest.raises(AuthError):
        decode_token(tampered)


def test_garbage_token_rejected():
    for bad in ["", "abc", "a.b", "a.b.c.d", "not-a-token"]:
        with pytest.raises(AuthError):
            decode_token(bad)


def test_extract_bearer_token():
    assert extract_bearer_token("Bearer xyz.123.abc") == "xyz.123.abc"
    assert extract_bearer_token("bearer xyz.123.abc") == "xyz.123.abc"
    for bad in [None, "", "Token abc", "Bearer", "Bearer "]:
        with pytest.raises(AuthError):
            extract_bearer_token(bad)


def test_signature_depends_on_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "secret-A")
    token = encode_token(_customer())
    # 换密钥后，旧 token 应当验签失败。
    monkeypatch.setenv("JWT_SECRET", "secret-B")
    with pytest.raises(AuthError):
        decode_token(token)


def test_production_requires_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(AuthError):
        encode_token(_customer())
