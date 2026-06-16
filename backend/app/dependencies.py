"""FastAPI 鉴权依赖（Depends 守卫）。

用法：在任意接口参数里加上对应的 Depends，即可拿到经过校验的当前身份 Principal，
并自动完成角色校验。业务逻辑里请用 principal.tenant_id / principal.store_id，
不要再用前端传来的同名字段。

示例：

    from .dependencies import require_merchant

    @app.get("/merchant/orders")
    def list_merchant_orders(
        status: str | None = None,
        principal: Principal = Depends(require_merchant),
    ):
        return service.list_merchant_orders(
            tenant_id=principal.tenant_id,   # 以 token 为准
            store_id=principal.store_id,     # 以 token 为准
            status=status,
        )

权限模型（与现有 services.assert_scope_access 对齐）：
- platform_admin : 平台运营方，可访问 /platform/* 全部数据。
- boss           : 租户老板，可看本租户全部门店。
- manager        : 店长，仅本门店。
- staff          : 发型师，仅本门店、且通常仅本人数据。
- customer       : 顾客，仅本人数据。
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from .auth import (
    ROLE_BOSS,
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_PLATFORM_ADMIN,
    ROLE_STAFF,
    AuthError,
    Principal,
    decode_token,
    extract_bearer_token,
)


def get_current_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    """从 Authorization 头解析并校验当前身份。所有需要登录的接口都依赖它。"""
    try:
        token = extract_bearer_token(authorization)
        return decode_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _require_roles(principal: Principal, allowed: set[str]) -> Principal:
    if principal.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"当前角色 '{principal.role}' 无权访问该接口",
        )
    return principal


# --- 角色守卫 -----------------------------------------------------------------
def require_customer(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    return _require_roles(principal, {ROLE_CUSTOMER})


def require_staff(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """发型师及以上（staff / manager / boss 均可）。"""
    return _require_roles(principal, {ROLE_STAFF, ROLE_MANAGER, ROLE_BOSS})


def require_manager(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """店长及以上（manager / boss）。"""
    return _require_roles(principal, {ROLE_MANAGER, ROLE_BOSS})


def require_boss(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    return _require_roles(principal, {ROLE_BOSS})


def require_merchant(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """任意商家侧角色（boss / manager / staff），用于 /merchant/* 入口。"""
    return _require_roles(principal, {ROLE_BOSS, ROLE_MANAGER, ROLE_STAFF})


def require_platform_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """平台运营方，用于 /platform/* 入口。"""
    return _require_roles(principal, {ROLE_PLATFORM_ADMIN})


# --- 跨门店访问辅助 -----------------------------------------------------------
def assert_can_access_store(principal: Principal, target_store_id: int | None) -> None:
    """在已通过角色守卫后，进一步校验是否能访问指定门店。

    boss / platform_admin 不受门店限制；manager / staff 只能访问自己所属门店。
    用于接口确实需要接收一个 store_id 参数的场景（如老板切换查看某店）。
    """
    if principal.role in {ROLE_BOSS, ROLE_PLATFORM_ADMIN}:
        return
    if target_store_id is not None and principal.store_id != target_store_id:
        raise HTTPException(status_code=403, detail="无权访问其它门店数据")
