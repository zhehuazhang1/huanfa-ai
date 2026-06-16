"""JWT 鉴权核心模块（无外部依赖，使用标准库实现 HS256）。

设计目标：
1. 不引入新依赖（不强制 PyJWT），用 hmac + hashlib 实现 HS256，便于直接落地。
2. 身份信息（tenant_id / store_id / role / user_id）一律以服务端签发的 token 为准，
   业务接口不再信任前端传来的 tenant_id / store_id。
3. 生产环境必须配置 JWT_SECRET，否则启动即报错，杜绝默认密钥上线。

如果团队后续希望换成 PyJWT，只需替换 encode_token / decode_token 两个函数即可，
Principal 和上层依赖（dependencies.py）无需改动。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 角色定义
# ---------------------------------------------------------------------------
# 与 users 表的 role 枚举对齐：boss / manager / staff / customer。
# platform_admin 是平台运营方专用角色（不落 users 表，由平台登录单独签发）。
ROLE_CUSTOMER = "customer"
ROLE_STAFF = "staff"
ROLE_MANAGER = "manager"
ROLE_BOSS = "boss"
ROLE_PLATFORM_ADMIN = "platform_admin"

ALL_ROLES = {
    ROLE_CUSTOMER,
    ROLE_STAFF,
    ROLE_MANAGER,
    ROLE_BOSS,
    ROLE_PLATFORM_ADMIN,
}


class AuthError(Exception):
    """鉴权失败（token 缺失、过期、被篡改、权限不足等）。

    上层（dependencies.py）会把它转成 HTTP 401 / 403。
    """


@dataclass(frozen=True)
class Principal:
    """从已验证 token 中解析出的当前身份。所有业务接口都应以它为准。"""

    user_id: int
    tenant_id: int
    role: str
    store_id: int | None = None
    openid: str | None = None

    @property
    def is_platform_admin(self) -> bool:
        return self.role == ROLE_PLATFORM_ADMIN

    @property
    def is_boss(self) -> bool:
        return self.role == ROLE_BOSS

    @property
    def is_merchant(self) -> bool:
        """商家侧角色：老板 / 店长 / 发型师。"""
        return self.role in {ROLE_BOSS, ROLE_MANAGER, ROLE_STAFF}


# ---------------------------------------------------------------------------
# 密钥与配置
# ---------------------------------------------------------------------------
_DEFAULT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", str(7 * 24 * 3600)))


def _get_secret() -> bytes:
    """读取 JWT 签名密钥。

    生产环境（APP_ENV=production）必须显式配置 JWT_SECRET，否则抛错拒绝启动签发，
    避免用弱默认密钥把 token 签出去。
    """
    secret = os.getenv("JWT_SECRET", "").strip()
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if not secret:
        if app_env == "production":
            raise AuthError(
                "JWT_SECRET 未配置：生产环境必须设置 JWT_SECRET 环境变量"
            )
        # 仅本地/演示环境允许弱默认密钥，方便联调。
        secret = "local-dev-jwt-secret-do-not-use-in-prod"
    return secret.encode("utf-8")


# ---------------------------------------------------------------------------
# base64url 工具
# ---------------------------------------------------------------------------
def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ---------------------------------------------------------------------------
# 签发 / 校验
# ---------------------------------------------------------------------------
def encode_token(principal: Principal, ttl_seconds: int | None = None) -> str:
    """根据身份签发一个 HS256 JWT。"""
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL_SECONDS
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(principal.user_id),
        "tid": principal.tenant_id,
        "sid": principal.store_id,
        "role": principal.role,
        "openid": principal.openid,
        "iat": now,
        "exp": now + ttl,
    }
    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(_get_secret(), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return ".".join(segments)


def decode_token(token: str) -> Principal:
    """校验 token 签名与有效期，返回 Principal。失败抛 AuthError。"""
    if not token or token.count(".") != 2:
        raise AuthError("token 格式非法")

    header_seg, payload_seg, signature_seg = token.split(".")
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    expected_sig = hmac.new(_get_secret(), signing_input, hashlib.sha256).digest()

    try:
        actual_sig = _b64url_decode(signature_seg)
    except Exception as exc:  # noqa: BLE001
        raise AuthError("token 签名解析失败") from exc

    # 常量时间比较，防时序攻击。
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise AuthError("token 签名校验失败")

    try:
        payload = json.loads(_b64url_decode(payload_seg).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AuthError("token 载荷解析失败") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise AuthError("token 已过期")

    role = payload.get("role")
    if role not in ALL_ROLES:
        raise AuthError("token 角色非法")

    try:
        user_id = int(payload["sub"])
        tenant_id = int(payload["tid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("token 缺少必要身份字段") from exc

    sid = payload.get("sid")
    store_id = int(sid) if isinstance(sid, int) else None

    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        store_id=store_id,
        openid=payload.get("openid"),
    )


def extract_bearer_token(authorization_header: str | None) -> str:
    """从 `Authorization: Bearer <token>` 头里取出 token。"""
    if not authorization_header:
        raise AuthError("缺少 Authorization 请求头")
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("Authorization 头格式应为 'Bearer <token>'")
    return parts[1].strip()
