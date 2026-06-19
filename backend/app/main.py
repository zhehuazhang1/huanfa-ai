from __future__ import annotations

import os
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from typing import Any

try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Please install backend/requirements.txt before starting FastAPI") from exc

from .auth import Principal, encode_token, ROLE_PLATFORM_ADMIN
from .dependencies import (
    get_current_principal,
    require_customer,
    require_merchant,
    require_platform_admin,
    assert_can_access_store,
)
from .db import build_store_from_env
from .aliyun_hair_tryon import HairTryOnError, build_aliyun_hair_tryon_from_env
from .dify_client import build_dify_client_from_env
from .feishu import build_feishu_sync_provider_from_env
from .models import BillingType, Direction, GenerateRequest
from .payments import build_payment_provider_from_env
from .queue import build_queue_from_env
from .services import BusinessError, HairAiService, parse_hairstyle_display_metadata
from .storage import build_temp_storage_from_env
from .consultant import build_consultant_from_env


class GeneratePayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    direction: Direction
    billing_type: BillingType
    selected_style_id: str | None = None
    selected_color_id: str | None = None
    photo_temp_url: str | None = None
    customer_reference_url: str | None = None
    customer_reference_type: str | None = None
    hair_profile: dict | None = None
    pay_order_no: str | None = None


class WxLoginPayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    code: str | None = None
    openid: str | None = None
    phone: str | None = None
    nickname: str | None = None


class PayPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    amount: float
    mock_paid: bool = True


class TempUploadPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    file_ext: str = "jpg"


class CatalogUploadPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    asset_type: str = "hairstyle"
    file_ext: str = "jpg"


class InternalHairEditPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    photo_temp_url: str
    hairstyle: str | None = None
    hair_color: str | None = None
    hairstyle_reference_url: str | None = None
    reference_type: str | None = None
    hair_profile: dict | None = None


class InternalDifyHairRunPayload(BaseModel):
    job_no: str
    direction: str
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    photo_temp_url: str
    customer_reference_url: str | None = None
    customer_reference_type: str | None = None
    selected_style: dict | None = None
    selected_color: dict | None = None
    recommendations: list[dict] = []
    hair_profile: dict | None = None


class StoreScanPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    qr_scene: str


class PrivacyConsentPayload(BaseModel):
    tenant_id: int = 1
    user_id: int = 1
    consent_scope: str = "photo_ai_generation"
    consent_version: str = "v1"


class CustomerProfilePayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    nickname: str | None = None
    birthday: str | None = None
    gender: str | None = None
    profile_note: str | None = None


class PayNotifyPayload(BaseModel):
    pay_order_no: str


class OrderPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    stylist_id: int | None = None
    direction: str | None = None
    hairstyle_id: str | None = None
    hair_color_id: str | None = None
    ai_job_no: str | None = None
    appointment_time: str | None = None
    notes: str | None = None


class CompleteOrderPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    stylist_id: int
    service_item_id: int
    actual_amount: float
    payment_method: str = "cash"
    customer_package_id: int | None = None


class ManualServiceRecordPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    stylist_id: int
    service_item_id: int
    actual_amount: float
    customer_id: int | None = None
    customer_package_id: int | None = None
    payment_method: str = "cash"
    source: str = "walk_in"
    service_date: str | None = None
    notes: str | None = None


class OrderStatusPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    status: str
    stylist_id: int | None = None


class AssignStylistPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    stylist_id: int


class ServiceItemPayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    name: str
    category: str
    base_price: float = 0
    sort_order: int = 100


class ServiceItemUpdatePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = None
    name: str | None = None
    category: str | None = None
    base_price: float | None = None
    is_enabled: bool | None = None
    sort_order: int | None = None


class MarketingPackageItemPayload(BaseModel):
    service_item_id: int
    included_count: int


class MarketingPackagePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    name: str
    package_type: str = "times_card"
    sale_price: float = 0
    validity_days: int = 180
    items: list[MarketingPackageItemPayload] = []
    sort_order: int = 100


class MarketingPackageUpdatePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = None
    name: str | None = None
    package_type: str | None = None
    sale_price: float | None = None
    validity_days: int | None = None
    is_enabled: bool | None = None
    items: list[MarketingPackageItemPayload] | None = None
    sort_order: int | None = None


class AiKnowledgePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    category: str = "general"
    question: str
    answer: str
    keywords: list[str] = []
    is_enabled: bool = True
    sort_order: int = 100


class AiKnowledgeUpdatePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = None
    category: str | None = None
    question: str | None = None
    answer: str | None = None
    keywords: list[str] | None = None
    is_enabled: bool | None = None
    sort_order: int | None = None


class AssetTagPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    asset_type: str
    image_url: str


class AssetEventPayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    user_id: int | None = 1
    asset_type: str
    asset_id: str
    event_type: str = "view"


class HairstylePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    style_id: str | None = None
    name: str
    direction: str
    hair_length: str = "medium"
    thumbnail_url: str | None = None
    display_tags: Any = []
    need_perm: bool = False
    is_enabled: bool = True
    is_recommended: bool = True
    sort_order: int = 0


class HairColorPayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    color_id: str | None = None
    name: str
    direction: str
    color_swatch: str | None = None
    thumbnail_url: str | None = None
    display_tags: list[str] = []
    need_bleach: bool = False
    is_enabled: bool = True
    is_recommended: bool = True
    sort_order: int = 0


class HairstyleUpdatePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = None
    name: str | None = None
    direction: str | None = None
    hair_length: str | None = None
    thumbnail_url: str | None = None
    display_tags: Any | None = None
    need_perm: bool | None = None
    is_enabled: bool | None = None
    is_recommended: bool | None = None
    sort_order: int | None = None


class HairColorUpdatePayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = None
    name: str | None = None
    direction: str | None = None
    color_swatch: str | None = None
    thumbnail_url: str | None = None
    display_tags: list[str] | None = None
    need_bleach: bool | None = None
    is_enabled: bool | None = None
    is_recommended: bool | None = None
    sort_order: int | None = None


def build_hairstyle_ai_reference(style: dict) -> str | None:
    parts: list[str] = []
    if style.get("style_name"):
        parts.append(str(style["style_name"]))
    length_label = {"short": "short hair", "medium": "medium-length hair", "long": "long hair"}.get(
        style.get("hair_length")
    )
    if length_label:
        parts.append(length_label)
    metadata = {
        "customer_description": style.get("customer_description") or "",
        "ai_reference_tags": style.get("ai_reference_tags"),
        "tags": style.get("tags"),
    }
    if style.get("display_tags") and metadata["ai_reference_tags"] is None and metadata["tags"] is None:
        metadata |= parse_hairstyle_display_metadata(style.get("display_tags"))
    if metadata.get("customer_description"):
        parts.append(str(metadata["customer_description"]))
    tags = metadata.get("ai_reference_tags") or metadata.get("tags") or []
    for tag in tags:
        clean = str(tag).strip()
        if clean and clean not in parts:
            parts.append(clean)
    if style.get("need_perm"):
        parts.append("permed or heat-styled texture")
    return ", ".join(parts) if parts else None


class AiChatPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    user_id: int = 1
    message: str
    session_key: str | None = None   # 不传则按 tenant_id:user_id 自动生成


class GiftPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    customer_id: int
    staff_id: int
    count: int = 1


class CustomerFreeLimitPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    customer_id: int
    free_limit: int


class GiftQuotaPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    extra_count: int


class StaffStatusPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    availability_status: str


class StaffPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    openid: str
    phone: str | None = None
    display_name: str
    title: str | None = None
    directions: list[str] = []
    skill_tags: list[str] = []
    avatar_url: str | None = None
    role: str = "staff"
    sort_order: int = 100


class StaffUpdatePayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    phone: str | None = None
    display_name: str | None = None
    title: str | None = None
    directions: list[str] | None = None
    skill_tags: list[str] | None = None
    avatar_url: str | None = None
    role: str | None = None
    availability_status: str | None = None
    is_enabled: bool | None = None
    is_recommended: bool | None = None
    sort_order: int | None = None


class TenantPayload(BaseModel):
    tenant_code: str
    name: str
    package_plan: str | None = None
    initial_ai_count: int = 0


class TenantOnboardingPayload(BaseModel):
    tenant_code: str
    name: str
    package_plan: str | None = "trial"
    initial_ai_count: int = 0
    notes: str | None = None
    store_code: str
    store_name: str
    daily_ai_limit: int = 300
    boss_name: str | None = None
    boss_phone: str | None = None
    boss_openid: str | None = None
    boss_is_manager: bool = True
    manager_name: str | None = None
    manager_phone: str | None = None
    manager_openid: str | None = None


class TenantUpdatePayload(BaseModel):
    name: str | None = None
    logo_url: str | None = None
    package_plan: str | None = None
    status: str | None = None
    notes: str | None = None


class PackagePayload(BaseModel):
    tenant_id: int
    package_name: str
    purchased_count: int
    unit_price: float
    payment_status: str = "paid"


class PackagePlanPayload(BaseModel):
    plan_code: str
    name: str
    monthly_fee: float = 0
    included_ai_count: int = 0
    store_limit: int = 1
    advanced_features: list[str] = []
    status: str = "active"


class MonthlyBillPayload(BaseModel):
    tenant_id: int
    bill_month: str
    tenant_settle_unit_price: float = 1.8
    bill_status: str = "draft"


class MonthlyBillStatusPayload(BaseModel):
    tenant_id: int
    bill_status: str


class PocEvaluationPayload(BaseModel):
    tenant_id: int = 1
    store_id: int | None = 1
    job_no: str | None = None
    direction: str
    test_case_no: str
    input_photo_label: str | None = None
    selected_style_id: str | None = None
    selected_color_id: str | None = None
    is_like_customer: bool = False
    only_changed_hair: bool = False
    face_changed: bool = False
    generated_three_images: bool = False
    hair_color_accurate: bool = False
    hairstyle_acceptable: bool = False
    can_show_customer: bool = False
    generate_duration_seconds: int | None = None
    internal_api_cost: float = 0
    notes: str | None = None


class AiBalanceAdjustPayload(BaseModel):
    tenant_id: int
    store_id: int
    change_count: int
    usage_type: str = "admin_adjust"
    remark: str
    user_id: int | None = None


class PlatformStorePayload(BaseModel):
    tenant_id: int
    store_code: str
    name: str
    daily_ai_limit: int = 300


class PlatformStoreUpdatePayload(BaseModel):
    name: str | None = None
    daily_ai_limit: int | None = None
    status: str | None = None


class DeletePayload(BaseModel):
    reason: str | None = None


class PlatformLeadPayload(BaseModel):
    source: str = "website"
    name: str | None = None
    phone: str | None = None
    wechat: str | None = None
    city: str | None = None
    store_count: int = 1
    interest: str | None = None
    message: str | None = None


class PlatformLeadUpdatePayload(BaseModel):
    status: str | None = None
    follow_note: str | None = None
    assigned_to: str | None = None
    tenant_id: int | None = None


class StoreHomeConfigPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    store_name: str | None = None
    home_title: str | None = None
    home_subtitle: str | None = None
    store_photos: list[dict[str, Any]] = []


class ApiKeyConfigPayload(BaseModel):
    tenant_id: int | None = None
    provider: str
    key_name: str
    secret_value: str
    updated_by_user_id: int | None = None


class AiLimitsPayload(BaseModel):
    tenant_id: int | None = None
    store_id: int | None = None
    user_concurrency_limit: int = 1
    store_concurrency_limit: int = 5
    tenant_concurrency_limit: int = 20
    platform_concurrency_limit: int = 50
    user_daily_limit: int = 20
    tenant_daily_limit: int = 5000


store = build_store_from_env()
store.seed_demo()
queue = build_queue_from_env()
storage_provider = build_temp_storage_from_env()
payment_provider = build_payment_provider_from_env()
feishu_provider = build_feishu_sync_provider_from_env()
# service 先用占位 dify（无密钥），后面 service 建好再替换为支持 DB 热读的懒加载客户端
service = HairAiService(
    store,
    dify_client=build_dify_client_from_env(),  # 占位，先用环境变量版
    queue=queue,
    storage_provider=storage_provider,
    payment_provider=payment_provider,
    feishu_provider=feishu_provider,
)
# 用 DB 热读版替换 dify client，此时 service 已建好可传入
service.dify = build_dify_client_from_env(service=service)
dify_client = service.dify  # 保留全局引用，供 /health 等接口使用
consultant = build_consultant_from_env(store)
app = FastAPI(title="Hair AI Mini Program MVP Backend")
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def handle_business_error(exc: BusinessError, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def customer_scope(principal: Principal, requested_store_id: int | None = None) -> tuple[int, int, int]:
    store_id = principal.store_id or requested_store_id
    if store_id is None:
        raise HTTPException(status_code=403, detail="当前顾客未绑定门店")
    return principal.tenant_id, store_id, principal.user_id


def merchant_scope(principal: Principal, requested_store_id: int | None = None) -> tuple[int, int]:
    store_id = requested_store_id if requested_store_id is not None else principal.store_id
    assert_can_access_store(principal, store_id)
    if store_id is None:
        raise HTTPException(status_code=403, detail="当前商家账号未绑定门店")
    return principal.tenant_id, store_id


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "database": "ok",
        "database_type": store.__class__.__name__,
        "dify": getattr(dify_client, "provider_name", "unknown"),
        "temp_storage": getattr(storage_provider, "provider_name", "unknown"),
        "payment": getattr(payment_provider, "provider_name", "unknown"),
        "feishu": getattr(feishu_provider, "provider_name", "unknown"),
    }


@app.get("/platform/deployment-readiness")
def deployment_readiness() -> dict:
    return service.deployment_readiness(os.getenv("APP_ENV", "local"))


@app.get("/platform/overview")
def platform_overview(
    month: str | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    # BUG-02: 支持按月过滤，month 格式 YYYY-MM，不传则全时段
    return service.platform_overview(month=month)


@app.get("/platform/tenant-dashboard")
def platform_tenant_dashboard(
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.platform_tenant_dashboard()


@app.post("/auth/wx-login")
def wx_login(payload: WxLoginPayload) -> dict:
    """顾客微信登录。

    注意：payload.openid 目前由前端直接传入（演示模式）。正式上线时应改为：
    前端传 wx.login 拿到的 code -> 后端用 WECHAT_APP_ID/SECRET 调 code2Session
    换取真实 openid，再继续下面的流程。绝不能信任前端直接传来的 openid。

    登录成功后返回 access_token，后续所有需要登录的接口都用
    `Authorization: Bearer <access_token>` 携带。
    """
    try:
        openid = payload.openid
        if payload.code:
            openid = exchange_wx_code_for_openid(payload.code)
        if not openid:
            raise BusinessError("微信登录失败，请重新打开小程序")
        result = service.wx_login(
            tenant_id=payload.tenant_id,
            store_id=payload.store_id,
            openid=openid,
            phone=payload.phone,
            nickname=payload.nickname,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc

    user = result["user"]
    principal = Principal(
        user_id=int(user["id"]),
        tenant_id=int(user["tenant_id"]),
        role=user.get("role", "customer"),
        store_id=user.get("store_id"),
        openid=user.get("openid"),
    )
    result["access_token"] = encode_token(principal)
    result["token_type"] = "Bearer"
    return result


def exchange_wx_code_for_openid(code: str) -> str:
    appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
    secret = os.getenv("WECHAT_MINIAPP_SECRET", "").strip()
    if not appid or not secret:
        raise BusinessError("微信登录密钥未配置")
    query = urllib.parse.urlencode(
        {
            "appid": appid,
            "secret": secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    try:
        with urllib.request.urlopen(f"https://api.weixin.qq.com/sns/jscode2session?{query}", timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise BusinessError("微信登录服务暂时不可用") from exc
    if data.get("errcode"):
        raise BusinessError(f"微信登录失败：{data.get('errmsg') or data.get('errcode')}")
    openid = str(data.get("openid") or "").strip()
    if not openid:
        raise BusinessError("微信登录未返回 openid")
    return openid


@app.post("/auth/merchant-login")
def merchant_login(payload: WxLoginPayload) -> dict:
    """商家端（老板/店长/发型师）登录，签发带角色的 token。

    复用 wx_login 找/建用户记录，但身份与门店、角色一律以数据库记录为准，
    不接受前端伪造角色。正式上线建议改为账号密码或扫码绑定登录。
    """
    try:
        result = service.wx_login(
            tenant_id=payload.tenant_id,
            store_id=payload.store_id,
            openid=payload.openid,
            phone=payload.phone,
            nickname=payload.nickname,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc

    user = result["user"]
    # 演示模式：openid 以 demo_merchant 开头时自动升级为 boss 角色，方便测试
    if user.get("role") not in {"boss", "manager", "staff"}:
        openid = user.get("openid", "")
        if openid.startswith("demo_merchant"):
            with service.store.transaction() as conn:
                conn.execute("UPDATE users SET role='boss' WHERE id=?", (user["id"],))
            user["role"] = "boss"
        else:
            raise HTTPException(status_code=403, detail="该账号不是商家角色，无法登录商家端")
    principal = Principal(
        user_id=int(user["id"]),
        tenant_id=int(user["tenant_id"]),
        role=user["role"],
        store_id=user.get("store_id"),
        openid=user.get("openid"),
    )
    result["access_token"] = encode_token(principal)
    result["token_type"] = "Bearer"
    return result


class PlatformLoginPayload(BaseModel):
    username: str
    password: str


@app.post("/auth/platform-login")
def platform_login(payload: PlatformLoginPayload) -> dict:
    """平台运营方登录，签发 platform_admin token。

    演示实现：账号密码来自环境变量 PLATFORM_ADMIN_USER / PLATFORM_ADMIN_PASSWORD。
    正式上线应改为平台后台账号体系 + 强密码/二次验证，并记录登录审计。
    """
    expected_user = os.getenv("PLATFORM_ADMIN_USER", "admin")
    expected_pass = os.getenv("PLATFORM_ADMIN_PASSWORD", "")
    if not expected_pass:
        raise HTTPException(
            status_code=500,
            detail="平台管理员密码未配置（PLATFORM_ADMIN_PASSWORD）",
        )
    if payload.username != expected_user or payload.password != expected_pass:
        raise HTTPException(status_code=401, detail="账号或密码错误")

    principal = Principal(
        user_id=0,
        tenant_id=0,
        role=ROLE_PLATFORM_ADMIN,
        store_id=None,
        openid=None,
    )
    return {"access_token": encode_token(principal), "token_type": "Bearer"}


@app.get("/auth/me")
def auth_me(principal: Principal = Depends(get_current_principal)) -> dict:
    """返回当前 token 解析出的身份，便于前端确认登录态。"""
    return {
        "user_id": principal.user_id,
        "tenant_id": principal.tenant_id,
        "store_id": principal.store_id,
        "role": principal.role,
    }


@app.get("/ai/quota/today")
def quota_today(tenant_id: int = 1, store_id: int = 1, user_id: int = 1,
    principal: Principal = Depends(require_customer),
) -> dict:
    return service.quota_today(tenant_id, store_id, user_id)


# ============================================================================
# 以下为「鉴权接入示例」：演示如何把现有接口改成以 token 身份为准。
# 这些是与原接口并存的 *_secure 版本，方便团队对照、逐步迁移；
# 迁移完成后可把原始不鉴权版本删除，或直接在原接口上加 Depends。
# ============================================================================


@app.get("/ai/quota/today/secure")
def quota_today_secure(
    principal: Principal = Depends(require_customer),
) -> dict:
    """示例：顾客查自己的当日 AI 额度。

    对比原 /ai/quota/today —— 这里完全不接收前端的 tenant_id/store_id/user_id，
    一律用 token 里的身份，从根本上杜绝越权查别人额度。
    """
    return service.quota_today(
        principal.tenant_id,
        principal.store_id or 0,
        principal.user_id,
    )


@app.get("/merchant/orders/secure")
def list_merchant_orders_secure(
    status: str | None = None,
    stylist_id: int | None = None,
    store_id: int | None = None,
    limit: int = 50,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    """示例：商家查门店订单。

    - tenant_id 永远来自 token。
    - store_id：老板可传任意本租户门店（或不传看默认）；店长/发型师只能看自己门店，
      传了别的门店会被 assert_can_access_store 拒绝。
    """
    effective_store_id = store_id if store_id is not None else principal.store_id
    assert_can_access_store(principal, effective_store_id)
    try:
        return service.list_merchant_orders(
            tenant_id=principal.tenant_id,
            store_id=effective_store_id,
            status=status,
            stylist_id=stylist_id,
            limit=limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/overview/secure")
def platform_overview_secure(
    month: str | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    """示例：平台总览，仅平台管理员可访问。"""
    return service.platform_overview(month=month)


@app.post("/stores/scan-qr")
def scan_store_qr(payload: StoreScanPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
        session = service.confirm_store_visit(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            qr_scene=payload.qr_scene,
        )
        return {
            "visit_session": session,
            "quota": service.quota_today(tenant_id, store_id, user_id),
        }
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/stores/public-profile")
def store_public_profile(tenant_id: int = 1, store_id: int = 1) -> dict:
    try:
        return service.store_public_profile(tenant_id, store_id)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/service-items")
def public_service_items(tenant_id: int = 1, store_id: int | None = 1) -> list[dict]:
    return service.list_service_items(
        tenant_id=tenant_id,
        store_id=store_id,
        include_disabled=False,
    )


@app.get("/merchant/store-home-config")
def merchant_store_home_config(tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.store_public_profile(effective_tenant_id, effective_store_id)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/store-home-config")
def update_merchant_store_home_config(payload: StoreHomeConfigPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_store_home_config(
            tenant_id=tenant_id,
            store_id=store_id,
            store_name=payload.store_name,
            home_title=payload.home_title,
            home_subtitle=payload.home_subtitle,
            store_photos=payload.store_photos,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/privacy/consent")
def privacy_consent_status(
    tenant_id: int = 1,
    user_id: int = 1,
    consent_scope: str = "photo_ai_generation",
    consent_version: str = "v1",
    principal: Principal = Depends(require_customer),
) -> dict:
    effective_tenant_id, _, effective_user_id = customer_scope(principal)
    return service.privacy_consent_status(
        tenant_id=effective_tenant_id,
        user_id=effective_user_id,
        consent_scope=consent_scope,
        consent_version=consent_version,
    )


@app.post("/privacy/consent")
def record_privacy_consent(payload: PrivacyConsentPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, _, user_id = customer_scope(principal)
        return service.record_privacy_consent(
            tenant_id=tenant_id,
            user_id=user_id,
            consent_scope=payload.consent_scope,
            consent_version=payload.consent_version,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/privacy/consent/revoke")
def revoke_privacy_consent(payload: PrivacyConsentPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, _, user_id = customer_scope(principal)
        return service.revoke_privacy_consent(
            tenant_id=tenant_id,
            user_id=user_id,
            consent_scope=payload.consent_scope,
            consent_version=payload.consent_version,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/hairstyles")
def hairstyles(
    tenant_id: int = 1,
    store_id: int | None = None,
    direction: str | None = None,
    hair_length: str | None = None,
    recommended_only: bool = False,
    limit: int | None = None,
) -> list[dict]:
    try:
        return service.list_styles(
            tenant_id=tenant_id,
            store_id=store_id,
            direction=direction,
            hair_length=hair_length,
            recommended_only=recommended_only,
            limit=limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/hair-colors")
def hair_colors(tenant_id: int = 1, store_id: int | None = None, direction: str | None = None, recommended_only: bool = False, limit: int | None = None) -> list[dict]:
    return service.list_colors(tenant_id=tenant_id, store_id=store_id, direction=direction, recommended_only=recommended_only, limit=limit)


@app.get("/inspiration")
def inspiration(tenant_id: int = 1, direction: str = "female") -> dict:
    try:
        return service.hairstyle_inspiration(tenant_id, direction)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/uploads/temp-url")
def create_temp_upload(payload: TempUploadPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
        return service.create_temp_upload_url(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            file_ext=payload.file_ext,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/assets/upload-url")
def create_catalog_upload(payload: CatalogUploadPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_catalog_upload_url(
            tenant_id=tenant_id,
            store_id=store_id,
            asset_type=payload.asset_type,
            file_ext=payload.file_ext,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/internal/ai/hair-edit")
def internal_hair_edit(
    payload: InternalHairEditPayload,
    x_internal_token: str | None = Header(default=None),
) -> dict:
    expected_token = os.getenv("AI_ADAPTER_TOKEN", "")
    if not expected_token or x_internal_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid internal AI adapter token")
    try:
        provider = build_aliyun_hair_tryon_from_env(storage_provider, service=service)
        result = provider.generate(
            tenant_id=payload.tenant_id,
            store_id=payload.store_id,
            user_id=payload.user_id,
            photo_temp_url=payload.photo_temp_url,
            hairstyle=payload.hairstyle,
            hair_color=payload.hair_color,
            hair_profile=payload.hair_profile,
            reference_type=payload.reference_type,
            hairstyle_reference_url=payload.hairstyle_reference_url,
        )
        return {
            "status": "success",
            "temp_image_url": result.image_url,
            "wanx_task_id": result.wanx_task_id,
        }
    except HairTryOnError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/internal/ai/dify-run")
def internal_dify_hair_run(
    payload: InternalDifyHairRunPayload,
    x_internal_token: str | None = Header(default=None),
) -> dict:
    expected_token = os.getenv("AI_ADAPTER_TOKEN", "")
    if not expected_token or x_internal_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid internal AI adapter token")
    variants = [
        {
            "slot": "main",
            "title": "Selected style",
            "style": payload.selected_style or {},
            "color": payload.selected_color or {},
        },
        *[
            {
                "slot": item.get("slot"),
                "title": item.get("title"),
                "style": item,
                "color": item,
            }
            for item in payload.recommendations[:2]
        ],
    ]
    if len(variants) != 3:
        raise HTTPException(status_code=400, detail="Dify run requires exactly 2 recommendations")
    try:
        def generate_variant(variant: dict) -> dict:
            provider = build_aliyun_hair_tryon_from_env(storage_provider, service=service)
            style = variant["style"]
            color = variant["color"]
            result = provider.generate(
                tenant_id=payload.tenant_id,
                store_id=payload.store_id,
                user_id=payload.user_id,
                photo_temp_url=payload.photo_temp_url,
                hairstyle=(
                    "参考顾客上传图片中的发型轮廓、发长、刘海、分缝、卷度、层次和发量感；只参考发型结构，不参考发色、脸、五官、表情、胡子、皮肤、身体、衣服和背景"
                    if variant["slot"] == "main" and payload.customer_reference_url and payload.customer_reference_type == "hairstyle"
                    else (
                        "保持顾客当前发型轮廓，只参考顾客上传图片中的头发颜色、明暗层次和发色质感；不要参考参考图的发型结构、脸、五官、身体、衣服和背景"
                        if variant["slot"] == "main" and payload.customer_reference_url and payload.customer_reference_type == "hair_color"
                        else build_hairstyle_ai_reference(style)
                    )
                ),
                hair_color=("参考上传图中的发色" if variant["slot"] == "main" and payload.customer_reference_url and payload.customer_reference_type == "hair_color" else color.get("color_name")),
                hair_profile=payload.hair_profile,
                reference_type=payload.customer_reference_type,
                hairstyle_reference_url=payload.customer_reference_url if variant["slot"] == "main" and payload.customer_reference_url else style.get("thumbnail_url"),
            )
            return {
                "slot": variant["slot"],
                "title": variant["title"],
                "direction": payload.direction,
                "style_id": style.get("style_id"),
                "style_name": style.get("style_name"),
                "color_id": color.get("color_id"),
                "color_name": color.get("color_name"),
                "temp_image_url": result.image_url,
            }

        images = [generate_variant(variants[0])]
        service.save_partial_generation_images(payload.job_no, images)
        parallelism = max(1, min(2, int(os.getenv("AI_VARIANT_PARALLELISM", "3"))))
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = [executor.submit(generate_variant, variant) for variant in variants[1:]]
            for future in as_completed(futures):
                try:
                    images.append(future.result())
                except Exception:
                    continue
                service.save_partial_generation_images(payload.job_no, images)
        images.sort(key=lambda image: {"main": 0, "natural": 1, "advanced": 2}.get(image["slot"], 99))
        return {
            "status": "success",
            "internal_api_cost": 0.444,
            "images": images,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "internal_api_cost": 0,
            "error_code": "ALIYUN_HAIR_TRYON_FAILED",
            "error_message": str(exc),
        }


@app.post("/ai/style/prepare")
def prepare(payload: GeneratePayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, _, _ = customer_scope(principal, payload.store_id)
        return service.prepare_recommendations(
            tenant_id,
            payload.direction.value,
            payload.selected_style_id,
            payload.selected_color_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/ai/pay/create")
def create_pay(payload: PayPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
        return service.create_ai_payment(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            amount=payload.amount,
            mock_paid=payload.mock_paid,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/ai/pay/notify")
def pay_notify(payload: PayNotifyPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        return service.mark_payment_paid(payload.pay_order_no)
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.get("/ai/pay/orders/{pay_order_no}")
def get_pay_order(pay_order_no: str, tenant_id: int = 1, store_id: int = 1, user_id: int = 1,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        effective_tenant_id, effective_store_id, effective_user_id = customer_scope(principal, store_id)
        return service.payment_order_for_customer(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            user_id=effective_user_id,
            pay_order_no=pay_order_no,
        )
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.post("/ai/style/generate")
def generate(payload: GeneratePayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
        req = GenerateRequest(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction=payload.direction,
            billing_type=payload.billing_type,
            selected_style_id=payload.selected_style_id,
            selected_color_id=payload.selected_color_id,
            photo_temp_url=payload.photo_temp_url,
            customer_reference_url=payload.customer_reference_url,
            customer_reference_type=payload.customer_reference_type,
            hair_profile=payload.hair_profile,
            pay_order_no=payload.pay_order_no,
        )
        return service.generate(req)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/ai/style/enqueue")
def enqueue_generate(payload: GeneratePayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
        req = GenerateRequest(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            direction=payload.direction,
            billing_type=payload.billing_type,
            selected_style_id=payload.selected_style_id,
            selected_color_id=payload.selected_color_id,
            photo_temp_url=payload.photo_temp_url,
            customer_reference_url=payload.customer_reference_url,
            customer_reference_type=payload.customer_reference_type,
            hair_profile=payload.hair_profile,
            pay_order_no=payload.pay_order_no,
        )
        return service.enqueue_generation(req)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/worker/ai/process-next")
def worker_process_next() -> dict:
    processed = service.process_next_generation_job()
    if processed is None:
        return {"status": "empty"}
    return processed


@app.post("/ai/chat")
def ai_chat(payload: AiChatPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
        return service.ai_chat(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            message=payload.message,
            session_key=payload.session_key or f"{tenant_id}:{user_id}",
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


# ── AI 发型咨询师 ────────────────────────────────────────────────────────────

class ConsultStartPayload(BaseModel):
    tenant_id: int
    store_id: int
    user_id: int


class ConsultReplyPayload(BaseModel):
    session_id: str
    choice: str     # 对应当前步骤 choices 中的 value


@app.post("/ai/consultant/start")
def consultant_start(
    payload: ConsultStartPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    """开始一次发型咨询，返回第一步问题和选项。"""
    tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
    return consultant.start(
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=user_id,
    )


@app.post("/ai/consultant/reply")
def consultant_reply(
    payload: ConsultReplyPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    """
    提交当前步骤的选择。
    - status='in_progress'：返回下一步问题 + choices
    - status='completed'：返回 recommendations 推荐卡片列表
    """
    try:
        return consultant.reply(
            session_id=payload.session_id,
            choice=payload.choice,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/ai/consultant/session/{session_id}")
def consultant_session(
    session_id: str,
    principal: Principal = Depends(require_customer),
) -> dict:
    """查询咨询会话当前状态（用于页面刷新恢复）。"""
    data = consultant.get_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return data


# ── AI 发型试穿（原有接口）────────────────────────────────────────────────────

@app.get("/ai/style/jobs/{job_no}")
def get_job(job_no: str, tenant_id: int = 1, store_id: int = 1, user_id: int = 1,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        effective_tenant_id, effective_store_id, effective_user_id = customer_scope(principal, store_id)
        return service.get_customer_job(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            user_id=effective_user_id,
            job_no=job_no,
        )
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.get("/ai/style/results/{job_no}")
def get_result_detail(job_no: str, tenant_id: int = 1, store_id: int = 1, user_id: int = 1,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        effective_tenant_id, effective_store_id, effective_user_id = customer_scope(principal, store_id)
        return service.result_detail(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            user_id=effective_user_id,
            job_no=job_no,
        )
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.post("/orders")
def create_order(payload: OrderPayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, user_id = customer_scope(principal, payload.store_id)
        return service.create_order(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            stylist_id=payload.stylist_id,
            direction=payload.direction,
            hairstyle_id=payload.hairstyle_id,
            hair_color_id=payload.hair_color_id,
            ai_job_no=payload.ai_job_no,
            appointment_time=payload.appointment_time,
            notes=payload.notes,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/orders")
def list_customer_orders(
    tenant_id: int = 1,
    user_id: int = 1,
    store_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    principal: Principal = Depends(require_customer),
) -> list[dict]:
    try:
        effective_tenant_id, effective_store_id, effective_user_id = customer_scope(principal, store_id)
        return service.list_customer_orders(
            tenant_id=effective_tenant_id,
            user_id=effective_user_id,
            store_id=effective_store_id,
            status=status,
            limit=limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/orders/{order_id}")
def get_order(order_id: int, tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        eff_tenant_id, eff_store_id, eff_user_id = customer_scope(principal, store_id)
        order = service.get_order(tenant_id=eff_tenant_id, store_id=eff_store_id, order_id=order_id)
        # 顾客只能查自己的订单：防止改 tenant_id 看别家、或猜 order_id 读到别人订单与手机号
        if order.get("user_id") != eff_user_id:
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.get("/me/membership")
def get_my_membership(
    tenant_id: int = 1,
    store_id: int = 1,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        effective_tenant_id, effective_store_id, customer_id = customer_scope(principal, store_id)
        return {
            "membership": service.customer_membership(effective_tenant_id, effective_store_id, customer_id),
            "packages": service.list_customer_packages(effective_tenant_id, effective_store_id, customer_id),
        }
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.get("/me/profile")
def get_my_profile(
    tenant_id: int = 1,
    store_id: int = 1,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        effective_tenant_id, effective_store_id, customer_id = customer_scope(principal, store_id)
        return service.customer_self_profile(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            customer_id=customer_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.put("/me/profile")
def update_my_profile(
    payload: CustomerProfilePayload,
    principal: Principal = Depends(require_customer),
) -> dict:
    try:
        tenant_id, store_id, customer_id = customer_scope(principal, payload.store_id)
        return service.update_customer_self_profile(
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id,
            nickname=payload.nickname,
            birthday=payload.birthday,
            gender=payload.gender,
            profile_note=payload.profile_note,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/orders/{order_id}")
def get_merchant_order(order_id: int, tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.get_order(tenant_id=effective_tenant_id, store_id=effective_store_id, order_id=order_id)
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.get("/merchant/ai/quota/today")
def merchant_quota_today(tenant_id: int = 1, store_id: int = 1, user_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
    return service.quota_today(effective_tenant_id, effective_store_id, user_id)


@app.get("/merchant/orders")
def list_merchant_orders(
    tenant_id: int = 1,
    store_id: int = 1,
    status: str | None = None,
    stylist_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.list_merchant_orders(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            status=status,
            stylist_id=stylist_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/orders/{order_id}/complete")
def complete_order(order_id: int, payload: CompleteOrderPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.complete_order(
            tenant_id=tenant_id,
            store_id=store_id,
            order_id=order_id,
            stylist_id=payload.stylist_id,
            service_item_id=payload.service_item_id,
            actual_amount=payload.actual_amount,
            payment_method=payload.payment_method,
            customer_package_id=payload.customer_package_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/service-records/manual")
def create_manual_service_record(payload: ManualServiceRecordPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_manual_service_record(
            tenant_id=tenant_id,
            store_id=store_id,
            stylist_id=payload.stylist_id,
            service_item_id=payload.service_item_id,
            actual_amount=payload.actual_amount,
            customer_id=payload.customer_id,
            customer_package_id=payload.customer_package_id,
            payment_method=payload.payment_method,
            source=payload.source,
            service_date=payload.service_date,
            notes=payload.notes,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/orders/{order_id}/status")
def update_order_status(order_id: int, payload: OrderStatusPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_order_status(
            tenant_id=tenant_id,
            store_id=store_id,
            order_id=order_id,
            status=payload.status,
            stylist_id=payload.stylist_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/orders/{order_id}/assign-stylist")
def assign_order_stylist(order_id: int, payload: AssignStylistPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.assign_order_stylist(
            tenant_id=tenant_id,
            store_id=store_id,
            order_id=order_id,
            stylist_id=payload.stylist_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/service-items")
def list_service_items(
    tenant_id: int = 1,
    store_id: int | None = 1,
    include_disabled: bool = False,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    tenant_id, effective_store_id = merchant_scope(principal, store_id)
    return service.list_service_items(
        tenant_id=tenant_id,
        store_id=effective_store_id,
        include_disabled=include_disabled,
    )


@app.post("/merchant/service-items")
def create_service_item(payload: ServiceItemPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_service_item(
            tenant_id=tenant_id,
            store_id=store_id,
            name=payload.name,
            category=payload.category,
            base_price=payload.base_price,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/service-items/{service_item_id}")
def update_service_item(service_item_id: int, payload: ServiceItemUpdatePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_service_item(
            tenant_id=tenant_id,
            service_item_id=service_item_id,
            store_id=store_id,
            name=payload.name,
            category=payload.category,
            base_price=payload.base_price,
            is_enabled=payload.is_enabled,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/marketing-packages")
def list_marketing_packages(
    tenant_id: int = 1,
    store_id: int | None = 1,
    include_disabled: bool = False,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    tenant_id, effective_store_id = merchant_scope(principal, store_id)
    return service.list_marketing_packages(
        tenant_id=tenant_id,
        store_id=effective_store_id,
        include_disabled=include_disabled,
    )


@app.post("/merchant/marketing-packages")
def create_marketing_package(payload: MarketingPackagePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_marketing_package(
            tenant_id=tenant_id,
            store_id=store_id,
            name=payload.name,
            package_type=payload.package_type,
            sale_price=payload.sale_price,
            validity_days=payload.validity_days,
            items=[item.dict() for item in payload.items],
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/marketing-packages/{package_id}")
def update_marketing_package(package_id: int, payload: MarketingPackageUpdatePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_marketing_package(
            tenant_id=tenant_id,
            package_id=package_id,
            store_id=store_id,
            name=payload.name,
            package_type=payload.package_type,
            sale_price=payload.sale_price,
            validity_days=payload.validity_days,
            is_enabled=payload.is_enabled,
            items=None if payload.items is None else [item.dict() for item in payload.items],
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/ai-knowledge")
def list_ai_knowledge(
    tenant_id: int = 1,
    store_id: int | None = 1,
    include_disabled: bool = False,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    tenant_id, effective_store_id = merchant_scope(principal, store_id)
    return service.list_ai_knowledge_items(tenant_id, effective_store_id, include_disabled=include_disabled)


@app.get("/merchant/ai-customer-context")
def merchant_ai_customer_context(tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.ai_customer_context(effective_tenant_id, effective_store_id)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/ai-knowledge")
def create_ai_knowledge(payload: AiKnowledgePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_ai_knowledge_item(
            tenant_id=tenant_id,
            store_id=store_id,
            category=payload.category,
            question=payload.question,
            answer=payload.answer,
            keywords=payload.keywords,
            is_enabled=payload.is_enabled,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/ai-knowledge/{item_id}")
def update_ai_knowledge(item_id: int, payload: AiKnowledgeUpdatePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_ai_knowledge_item(
            tenant_id=tenant_id,
            item_id=item_id,
            store_id=store_id,
            category=payload.category,
            question=payload.question,
            answer=payload.answer,
            keywords=payload.keywords,
            is_enabled=payload.is_enabled,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/assets/ai-tags")
def suggest_asset_tags(payload: AssetTagPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.suggest_asset_tags(
            tenant_id=tenant_id,
            store_id=store_id,
            asset_type=payload.asset_type,
            image_url=payload.image_url,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/analytics/asset-events")
def track_asset_event(payload: AssetEventPayload,
    principal: Principal = Depends(get_current_principal),
) -> dict:
    try:
        user_id = payload.user_id
        tenant_id = principal.tenant_id
        store_id = payload.store_id
        if principal.role == "customer":
            user_id = principal.user_id
            _, store_id, _ = customer_scope(principal, payload.store_id)
        elif principal.is_merchant:
            tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.track_asset_event(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            asset_type=payload.asset_type,
            asset_id=payload.asset_id,
            event_type=payload.event_type,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/assets/popularity")
def asset_popularity(
    tenant_id: int = 1,
    store_id: int | None = None,
    event_type: str | None = None,
    limit: int = 20,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.asset_popularity(
            tenant_id=tenant_id,
            store_id=effective_store_id,
            event_type=event_type,
            limit=limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/hairstyles")
def create_hairstyle(payload: HairstylePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_hairstyle(
            tenant_id=tenant_id,
            store_id=store_id,
            style_id=payload.style_id,
            name=payload.name,
            direction=payload.direction,
            hair_length=payload.hair_length,
            thumbnail_url=payload.thumbnail_url,
            display_tags=payload.display_tags,
            need_perm=payload.need_perm,
            is_enabled=payload.is_enabled,
            is_recommended=payload.is_recommended,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/hairstyles/{style_id}")
def update_hairstyle(style_id: str, payload: HairstyleUpdatePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_hairstyle(
            tenant_id=tenant_id,
            style_id=style_id,
            store_id=store_id,
            name=payload.name,
            direction=payload.direction,
            hair_length=payload.hair_length,
            thumbnail_url=payload.thumbnail_url,
            display_tags=payload.display_tags,
            need_perm=payload.need_perm,
            is_enabled=payload.is_enabled,
            is_recommended=payload.is_recommended,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/hair-colors")
def create_hair_color(payload: HairColorPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_hair_color(
            tenant_id=tenant_id,
            store_id=store_id,
            color_id=payload.color_id,
            name=payload.name,
            direction=payload.direction,
            color_swatch=payload.color_swatch,
            thumbnail_url=payload.thumbnail_url,
            display_tags=payload.display_tags,
            need_bleach=payload.need_bleach,
            is_enabled=payload.is_enabled,
            is_recommended=payload.is_recommended,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/hair-colors/{color_id}")
def update_hair_color(color_id: str, payload: HairColorUpdatePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_hair_color(
            tenant_id=tenant_id,
            color_id=color_id,
            store_id=store_id,
            name=payload.name,
            direction=payload.direction,
            color_swatch=payload.color_swatch,
            thumbnail_url=payload.thumbnail_url,
            display_tags=payload.display_tags,
            need_bleach=payload.need_bleach,
            is_enabled=payload.is_enabled,
            is_recommended=payload.is_recommended,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/ai/gift")
def merchant_ai_gift(payload: GiftPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.grant_ai_gift(
            tenant_id,
            store_id,
            payload.customer_id,
            principal.user_id if principal.role == "staff" else payload.staff_id,
            payload.count,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/ai/free-limit")
def merchant_set_customer_free_limit(payload: CustomerFreeLimitPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.set_customer_daily_free_limit(
            tenant_id,
            store_id,
            payload.customer_id,
            payload.free_limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/ai/gift-conversions")
def merchant_gift_conversions(
    tenant_id: int = 1,
    store_id: int | None = None,
    staff_id: int | None = None,
    principal: Principal = Depends(require_merchant),
) -> dict:
    effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
    effective_staff_id = principal.user_id if principal.role == "staff" else staff_id
    return service.merchant_gift_conversion(
        tenant_id=effective_tenant_id,
        store_id=effective_store_id,
        staff_id=effective_staff_id,
    )


@app.get("/merchant/customers")
def list_merchant_customers(
    tenant_id: int = 1,
    store_id: int = 1,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.list_store_customers(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            status=status,
            keyword=keyword,
            limit=limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/customers/{customer_id}")
def get_merchant_customer(customer_id: int, tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.merchant_customer_detail(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            customer_id=customer_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


class CustomerStatusPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    status: str  # "active" | "disabled"


class CustomerMembershipPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    level_name: str = "普通会员"
    discount_rate: float = 1.0
    notes: str | None = None


class CustomerMembershipTransactionPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    transaction_type: str
    amount: float
    note: str | None = None
    created_by_user_id: int | None = None


class CustomerPackageGrantPayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1
    package_id: int
    paid_amount: float | None = None
    notes: str | None = None


@app.get("/merchant/customers/{customer_id}/membership")
def get_customer_membership(
    customer_id: int,
    tenant_id: int = 1,
    store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.customer_membership(effective_tenant_id, effective_store_id, customer_id)
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.put("/merchant/customers/{customer_id}/membership")
def update_customer_membership(
    customer_id: int,
    payload: CustomerMembershipPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_customer_membership(
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id,
            level_name=payload.level_name,
            discount_rate=payload.discount_rate,
            notes=payload.notes,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/customers/{customer_id}/membership/transactions")
def add_customer_membership_transaction(
    customer_id: int,
    payload: CustomerMembershipTransactionPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.add_customer_membership_transaction(
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id,
            transaction_type=payload.transaction_type,
            amount=payload.amount,
            note=payload.note,
            created_by_user_id=payload.created_by_user_id or principal.user_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/customers/{customer_id}/packages")
def list_customer_packages(
    customer_id: int,
    tenant_id: int = 1,
    store_id: int = 1,
    active_only: bool = False,
    service_item_id: int | None = None,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.list_customer_packages(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            customer_id=customer_id,
            active_only=active_only,
            service_item_id=service_item_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.post("/merchant/customers/{customer_id}/packages")
def grant_customer_package(
    customer_id: int,
    payload: CustomerPackageGrantPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.grant_customer_package(
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id,
            package_id=payload.package_id,
            paid_amount=payload.paid_amount,
            notes=payload.notes,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/customers/{customer_id}/status")
def update_customer_status(
    customer_id: int,
    payload: CustomerStatusPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    """停用或恢复顾客账号。"""
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_customer_status(
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id,
            status=payload.status,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


class CustomerDeletePayload(BaseModel):
    tenant_id: int = 1
    store_id: int = 1


@app.delete("/merchant/customers/{customer_id}")
def delete_merchant_customer(
    customer_id: int,
    tenant_id: int = 1,
    store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    """软删除顾客（保留历史数据，顾客无法再登录）。"""
    try:
        effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
        return service.delete_customer(
            tenant_id=effective_tenant_id,
            store_id=effective_store_id,
            customer_id=customer_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/staff")
def list_staff(tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
    return service.list_staff(effective_tenant_id, effective_store_id)


@app.post("/merchant/staff")
def create_staff(payload: StaffPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.create_staff(
            tenant_id=tenant_id,
            store_id=store_id,
            openid=payload.openid,
            phone=payload.phone,
            display_name=payload.display_name,
            title=payload.title,
            directions=payload.directions,
            skill_tags=payload.skill_tags,
            avatar_url=payload.avatar_url,
            role=payload.role,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/staff/{staff_id}")
def update_staff(staff_id: int, payload: StaffUpdatePayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_staff_profile(
            tenant_id=tenant_id,
            store_id=store_id,
            staff_id=staff_id,
            phone=payload.phone,
            display_name=payload.display_name,
            title=payload.title,
            directions=payload.directions,
            skill_tags=payload.skill_tags,
            avatar_url=payload.avatar_url,
            role=payload.role,
            availability_status=payload.availability_status,
            is_enabled=payload.is_enabled,
            is_recommended=payload.is_recommended,
            sort_order=payload.sort_order,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/merchant/staff/{staff_id}/gift-quota/add")
def add_staff_gift_quota(staff_id: int, payload: GiftQuotaPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.add_staff_gift_quota(
            tenant_id,
            store_id,
            staff_id,
            payload.extra_count,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/merchant/staff/{staff_id}/status")
def update_staff_status(staff_id: int, payload: StaffStatusPayload,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        tenant_id, store_id = merchant_scope(principal, payload.store_id)
        return service.update_staff_status(
            tenant_id=tenant_id,
            store_id=store_id,
            staff_id=staff_id,
            availability_status=payload.availability_status,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/stylists/recommendations")
def recommend_stylists(
    tenant_id: int = 1,
    store_id: int = 1,
    direction: str = "female",
    selected_style_id: str | None = None,
    selected_color_id: str | None = None,
) -> list[dict]:
    return service.recommend_stylists(
        tenant_id=tenant_id,
        store_id=store_id,
        direction=direction,
        selected_style_id=selected_style_id,
        selected_color_id=selected_color_id,
    )


@app.get("/merchant/workbench")
def merchant_workbench(tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
    return service.merchant_workbench(effective_tenant_id, effective_store_id)


@app.get("/merchant/performance")
def merchant_performance(
    tenant_id: int = 1,
    store_id: int | None = None,
    stylist_id: int | None = None,
    period: str = "month",
    offset: int = 0,
    principal: Principal = Depends(require_merchant),
) -> dict:
    effective_tenant_id, effective_store_id = merchant_scope(principal, store_id)
    return service.merchant_performance(
        tenant_id=effective_tenant_id,
        store_id=effective_store_id,
        stylist_id=stylist_id,
        period=period,
        offset=offset,
    )


@app.get("/platform/tenants")
def list_tenants(
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_tenants()


@app.post("/platform/tenants")
def create_tenant(payload: TenantPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.create_tenant(
            tenant_code=payload.tenant_code,
            name=payload.name,
            package_plan=payload.package_plan,
            initial_ai_count=payload.initial_ai_count,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/platform/tenant-onboarding")
def create_tenant_onboarding(payload: TenantOnboardingPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.create_tenant_onboarding(
            tenant_code=payload.tenant_code,
            name=payload.name,
            package_plan=payload.package_plan,
            initial_ai_count=payload.initial_ai_count,
            notes=payload.notes,
            store_code=payload.store_code,
            store_name=payload.store_name,
            daily_ai_limit=payload.daily_ai_limit,
            boss_name=payload.boss_name,
            boss_phone=payload.boss_phone,
            boss_openid=payload.boss_openid,
            boss_is_manager=payload.boss_is_manager,
            manager_name=payload.manager_name,
            manager_phone=payload.manager_phone,
            manager_openid=payload.manager_openid,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/platform/tenants/{tenant_id}")
def update_tenant(tenant_id: int, payload: TenantUpdatePayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.update_tenant(
            tenant_id=tenant_id,
            name=payload.name,
            logo_url=payload.logo_url,
            package_plan=payload.package_plan,
            status=payload.status,
            notes=payload.notes,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.delete("/platform/tenants/{tenant_id}")
def delete_tenant(tenant_id: int, payload: DeletePayload | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.delete_tenant(tenant_id, reason=payload.reason if payload else None)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


## ── 订阅计划管理 ──────────────────────────────────────────────

class SubscriptionPayload(BaseModel):
    plan: str          # trial / basic / pro / enterprise
    months: int = 1   # 续费月数

@app.get("/platform/tenants/{tenant_id}/subscription")
def get_tenant_subscription(tenant_id: int,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.get_tenant_subscription(tenant_id)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc

@app.post("/platform/tenants/{tenant_id}/subscription")
def set_tenant_subscription(tenant_id: int, payload: SubscriptionPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.set_tenant_subscription(
            tenant_id=tenant_id, plan=payload.plan, months=payload.months
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/subscription-alerts")
def platform_subscription_alerts(days: int = 30, balance_threshold: int = 50,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    return service.subscription_alerts(days=days, balance_threshold=balance_threshold)


@app.post("/platform/subscription-alerts/push")
def platform_push_subscription_alerts(days: int = 14, balance_threshold: int = 50,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    """把续费 / 余额预警分类推送到飞书（手动触发，后续可接定时任务）。"""
    return service.push_subscription_alerts(days=days, balance_threshold=balance_threshold)


@app.get("/merchant/subscription")
def merchant_subscription(
    tenant_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    try:
        return service.get_tenant_subscription(principal.tenant_id)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/merchant/plans")
def merchant_plans(
    principal: Principal = Depends(require_merchant),
) -> dict:
    from .plans import PLANS, plan_summary
    return {k: plan_summary(k) for k in PLANS}


@app.get("/platform/plans")
def list_plans(
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    from .plans import PLANS, plan_summary
    return {k: plan_summary(k) for k in PLANS}


@app.get("/platform/stores")
def list_stores(tenant_id: int = 1,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_stores(tenant_id)


@app.post("/platform/stores")
def create_store(payload: PlatformStorePayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.create_store(
            tenant_id=payload.tenant_id,
            store_code=payload.store_code,
            name=payload.name,
            daily_ai_limit=payload.daily_ai_limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/platform/stores/{store_id}")
def update_store(store_id: int, payload: PlatformStoreUpdatePayload, tenant_id: int = 1,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.update_store(
            tenant_id=tenant_id,
            store_id=store_id,
            name=payload.name,
            daily_ai_limit=payload.daily_ai_limit,
            status=payload.status,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.delete("/platform/stores/{store_id}")
def delete_store(store_id: int, tenant_id: int = 1, payload: DeletePayload | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.delete_store(tenant_id=tenant_id, store_id=store_id, reason=payload.reason if payload else None)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/leads")
def create_public_lead(payload: PlatformLeadPayload) -> dict:
    try:
        return service.create_platform_lead(
            source=payload.source,
            name=payload.name,
            phone=payload.phone,
            wechat=payload.wechat,
            city=payload.city,
            store_count=payload.store_count,
            interest=payload.interest,
            message=payload.message,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/leads")
def list_platform_leads(status: str | None = None, limit: int = 100,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_platform_leads(status=status, limit=limit)


@app.put("/platform/leads/{lead_id}")
def update_platform_lead(lead_id: int, payload: PlatformLeadUpdatePayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.update_platform_lead(
            lead_id=lead_id,
            status=payload.status,
            follow_note=payload.follow_note,
            assigned_to=payload.assigned_to,
            tenant_id=payload.tenant_id,
            actor_user_id=principal.user_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/audit-logs")
def list_platform_audit_logs(tenant_id: int | None = None, action: str | None = None, limit: int = 100,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_audit_logs(tenant_id=tenant_id, action=action, limit=limit)


@app.get("/platform/finance-transactions")
def list_platform_finance_transactions(tenant_id: int | None = None, limit: int = 100,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_finance_transactions(tenant_id=tenant_id, limit=limit)


@app.get("/platform/api-keys")
def list_api_keys(tenant_id: int | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_api_key_configs(tenant_id=tenant_id)


@app.get("/platform/api-keys/resolve")
def resolve_api_key(tenant_id: int, provider: str, key_name: str,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.resolve_api_key_config(
            tenant_id=tenant_id,
            provider=provider,
            key_name=key_name,
        )
    except BusinessError as exc:
        raise handle_business_error(exc, 404) from exc


@app.post("/platform/api-keys")
def upsert_api_key(payload: ApiKeyConfigPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.upsert_api_key_config(
            tenant_id=payload.tenant_id,
            provider=payload.provider,
            key_name=payload.key_name,
            secret_value=payload.secret_value,
            updated_by_user_id=payload.updated_by_user_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.put("/platform/api-keys/{config_id}/disable")
def disable_api_key(config_id: int,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.disable_api_key_config(config_id)
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/platform/packages")
def purchase_package(payload: PackagePayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.purchase_ai_package(
            tenant_id=payload.tenant_id,
            package_name=payload.package_name,
            purchased_count=payload.purchased_count,
            unit_price=payload.unit_price,
            payment_status=payload.payment_status,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/packages")
def list_packages(tenant_id: int | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_ai_package_orders(tenant_id=tenant_id)


@app.get("/platform/package-plans")
def list_package_plans(include_disabled: bool = False,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_package_plans(include_disabled=include_disabled)


@app.post("/platform/package-plans")
def upsert_package_plan(payload: PackagePlanPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.upsert_package_plan(
            plan_code=payload.plan_code,
            name=payload.name,
            monthly_fee=payload.monthly_fee,
            included_ai_count=payload.included_ai_count,
            store_limit=payload.store_limit,
            advanced_features=payload.advanced_features,
            status=payload.status,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/platform/monthly-bills/generate")
def generate_monthly_bill(payload: MonthlyBillPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.generate_monthly_bill(
            tenant_id=payload.tenant_id,
            bill_month=payload.bill_month,
            tenant_settle_unit_price=payload.tenant_settle_unit_price,
            bill_status=payload.bill_status,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/monthly-bills")
def list_monthly_bills(tenant_id: int | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> list[dict]:
    return service.list_monthly_bills(tenant_id=tenant_id)


@app.put("/platform/monthly-bills/{bill_id}/status")
def update_monthly_bill_status(bill_id: int, payload: MonthlyBillStatusPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.update_monthly_bill_status(
            bill_id=bill_id,
            tenant_id=payload.tenant_id,
            bill_status=payload.bill_status,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.post("/platform/poc-evaluations")
def create_poc_evaluation(payload: PocEvaluationPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.create_poc_evaluation(
            tenant_id=payload.tenant_id,
            store_id=payload.store_id,
            job_no=payload.job_no,
            direction=payload.direction,
            test_case_no=payload.test_case_no,
            input_photo_label=payload.input_photo_label,
            selected_style_id=payload.selected_style_id,
            selected_color_id=payload.selected_color_id,
            is_like_customer=payload.is_like_customer,
            only_changed_hair=payload.only_changed_hair,
            face_changed=payload.face_changed,
            generated_three_images=payload.generated_three_images,
            hair_color_accurate=payload.hair_color_accurate,
            hairstyle_acceptable=payload.hairstyle_acceptable,
            can_show_customer=payload.can_show_customer,
            generate_duration_seconds=payload.generate_duration_seconds,
            internal_api_cost=payload.internal_api_cost,
            notes=payload.notes,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/poc-evaluations/summary")
def poc_evaluation_summary(tenant_id: int,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    return service.poc_evaluation_summary(tenant_id)


@app.get("/merchant/monthly-bills")
def merchant_monthly_bills(tenant_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    return service.list_monthly_bills(tenant_id=principal.tenant_id, include_platform_fields=False)


@app.post("/platform/ai-balance/adjust")
def adjust_ai_balance(payload: AiBalanceAdjustPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.adjust_tenant_ai_balance(
            tenant_id=payload.tenant_id,
            store_id=payload.store_id,
            change_count=payload.change_count,
            usage_type=payload.usage_type,
            remark=payload.remark,
            user_id=payload.user_id,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/usage")
def platform_usage(
    tenant_id: int,
    month: str | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    # BUG-02: 支持 month=YYYY-MM 过滤
    return service.platform_usage(tenant_id, month=month)


@app.get("/platform/ai-limits")
def get_ai_limits(tenant_id: int = 1, store_id: int = 1,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    return service.ai_limits(tenant_id, store_id)


@app.put("/platform/ai-limits")
def update_ai_limits(payload: AiLimitsPayload,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    try:
        return service.update_ai_limits(
            tenant_id=payload.tenant_id,
            store_id=payload.store_id,
            user_concurrency_limit=payload.user_concurrency_limit,
            store_concurrency_limit=payload.store_concurrency_limit,
            tenant_concurrency_limit=payload.tenant_concurrency_limit,
            platform_concurrency_limit=payload.platform_concurrency_limit,
            user_daily_limit=payload.user_daily_limit,
            tenant_daily_limit=payload.tenant_daily_limit,
        )
    except BusinessError as exc:
        raise handle_business_error(exc) from exc


@app.get("/platform/costs")
def platform_costs(
    tenant_id: int,
    month: str | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    # BUG-02: 支持 month=YYYY-MM 过滤
    return service.platform_costs(tenant_id, month=month)


@app.get("/platform/billing")
def platform_billing(
    tenant_id: int,
    tenant_settle_unit_price: float = 2.0,
    month: str | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    # BUG-01: 默认单价改为 ¥2.0；BUG-02: 支持 month 过滤
    return service.platform_billing(tenant_id, tenant_settle_unit_price, month=month)


@app.get("/platform/billing-summary")
def platform_billing_summary(
    month: str | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    """FEAT-09: 平台月度计费概览，按租户汇总"""
    return service.billing_summary(month=month)


@app.get("/platform/customer-stats")
def platform_customer_stats(
    tenant_id: int,
    month: str | None = None,
    store_id: int | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> list:
    """FEAT-01: 按顾客聚合的生成统计"""
    return service.platform_customer_stats(tenant_id, month=month, store_id=store_id)


@app.get("/platform/stats/daily")
def platform_stats_daily(
    start: str,
    end: str,
    period: str = "day",
    tenant_id: int | None = None,
    principal: Principal = Depends(require_platform_admin),
) -> list:
    """FEAT-02: 按时间维度的成本统计，period=day/week/month"""
    return service.platform_stats_daily(start=start, end=end, period=period, tenant_id=tenant_id)


@app.get("/platform/jobs")
def platform_jobs(
    tenant_id: int | None = None,
    store_id: int | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
    principal: Principal = Depends(require_platform_admin),
) -> dict:
    """FEAT-07: 平台生成记录详情，含三张图各自状态，支持按客户/门店过滤"""
    return service.platform_jobs(
        tenant_id=tenant_id,
        store_id=store_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=min(page_size, 100),
    )


@app.post("/sync/feishu/retry")
def retry_feishu_sync(tenant_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    return service.retry_sync_events(principal.tenant_id)


@app.get("/sync/feishu/status")
def feishu_sync_status(tenant_id: int = 1,
    principal: Principal = Depends(require_merchant),
) -> dict:
    return service.sync_status(principal.tenant_id)


@app.get("/sync/feishu/events")
def list_feishu_sync_events(tenant_id: int = 1, limit: int = 30,
    principal: Principal = Depends(require_merchant),
) -> list[dict]:
    return service.list_sync_events(principal.tenant_id, limit=limit)
