from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import Any
from uuid import uuid4

from .deepseek_client import build_deepseek_from_env, build_system_prompt
from .dify_client import MockDifyClient
from .feishu import FeishuSyncProvider, MockFeishuSyncProvider
from .models import BillingType, Direction, GenerateRequest, JobStatus
from .payments import MockPaymentProvider, PaymentError, PaymentProvider
from .plans import check_feature, get_plan, plan_summary, PLANS
from .queue import InMemoryAiJobQueue, QueuedGenerationJob
from .store import AppStore
from .storage import MockTempStorageProvider, StorageError, TempStorageProvider


class BusinessError(RuntimeError):
    pass


def parse_hairstyle_display_metadata(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        data = []
    if isinstance(data, list):
        tags = [str(item).strip() for item in data if str(item).strip()]
        return {
            "tags": tags,
            "customer_description": "",
            "parameter_groups": [],
            "ai_reference_tags": tags,
        }
    if not isinstance(data, dict):
        return {"tags": [], "customer_description": "", "parameter_groups": [], "ai_reference_tags": []}
    groups = []
    tags = []
    for group in data.get("parameter_groups") or []:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or "").strip()
        values = [str(value).strip() for value in group.get("values") or [] if str(value).strip()]
        if not name or not values:
            continue
        groups.append({"name": name, "values": values})
        tags.extend(values)
    ai_tags = [str(item).strip() for item in data.get("ai_reference_tags") or [] if str(item).strip()]
    for tag in tags:
        if tag not in ai_tags:
            ai_tags.append(tag)
    return {
        "tags": list(dict.fromkeys(tags)),
        "customer_description": str(data.get("customer_description") or "").strip(),
        "parameter_groups": groups,
        "ai_reference_tags": list(dict.fromkeys(ai_tags)),
    }


def should_answer_in_english(message: str) -> bool:
    letters = sum(1 for char in message if char.isascii() and char.isalpha())
    cjk = sum(1 for char in message if "\u4e00" <= char <= "\u9fff")
    if cjk:
        return False
    words = [part for part in message.replace("?", " ").replace(",", " ").split() if any(ch.isalpha() for ch in part)]
    return letters >= 6 and len(words) >= 2


def dev_allow_free_without_visit() -> bool:
    return os.getenv("DEV_ALLOW_FREE_WITHOUT_VISIT", "").strip().lower() in {"1", "true", "yes", "on"}


class HairAiService:
    def __init__(
        self,
        store: AppStore,
        dify_client: MockDifyClient | None = None,
        queue: InMemoryAiJobQueue | None = None,
        storage_provider: TempStorageProvider | None = None,
        payment_provider: PaymentProvider | None = None,
        feishu_provider: FeishuSyncProvider | None = None,
    ) -> None:
        self.store = store
        self.dify = dify_client or MockDifyClient()
        self.queue = queue or InMemoryAiJobQueue()
        self.storage = storage_provider or MockTempStorageProvider()
        self.payment = payment_provider or MockPaymentProvider()
        self.feishu = feishu_provider or MockFeishuSyncProvider()
        self._deduct_lock = threading.Lock()
        self._job_images: dict[str, list[dict]] = {}
        self._queued_requests: dict[str, GenerateRequest] = {}
        try:
            self._ai_image_unit_cost = float(os.getenv("AI_IMAGE_UNIT_COST", "0.15"))
        except (TypeError, ValueError):
            self._ai_image_unit_cost = 0.15
        # DeepSeek 客户端（连锁版专属，None 表示未配置）
        self._deepseek = build_deepseek_from_env()
        # Redis 用于对话历史（复用 queue 的 redis_url）
        self._chat_redis: Any | None = None
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                import redis as _redis
                self._chat_redis = _redis.Redis.from_url(redis_url, decode_responses=True)
                self._chat_redis.ping()
            except Exception:
                self._chat_redis = None

    def resolve_generation_cost(
        self,
        *,
        reported_cost: float,
        image_count: int,
    ) -> float:
        """计算一次 AI 生成的真实内部成本（元）。

        优先信任 AI 服务商（Dify/通义万相工作流）回填的真实成本；
        若服务商没回填（reported_cost <= 0），则退回到
        "图片张数 × 单价" 的后端自算口径，保证成本永远不为 0。
        """
        if reported_cost and reported_cost > 0:
            return float(reported_cost)
        count = max(int(image_count), 0)
        return round(count * self._ai_image_unit_cost, 4)

    def account_balance(self, tenant_id: int) -> int:
        row = self.store.row(
            """
            SELECT total_purchased, total_used, total_gifted_adjustment
            FROM tenant_ai_accounts
            WHERE tenant_id = ?
            """,
            (tenant_id,),
        )
        if row is None:
            return 0
        return int(row["total_purchased"]) + int(row["total_gifted_adjustment"]) - int(row["total_used"])

    def ai_limits(self, tenant_id: int, store_id: int) -> dict:
        row = self.store.row(
            """
            SELECT *
            FROM ai_limit_configs
            WHERE (tenant_id = ? OR tenant_id IS NULL)
              AND (store_id = ? OR store_id IS NULL)
            ORDER BY
              CASE WHEN tenant_id IS NULL THEN 0 ELSE 1 END DESC,
              CASE WHEN store_id IS NULL THEN 0 ELSE 1 END DESC
            LIMIT 1
            """,
            (tenant_id, store_id),
        )
        if row is None:
            return {
                "user_concurrency_limit": 1,
                "store_concurrency_limit": 5,
                "tenant_concurrency_limit": 20,
                "platform_concurrency_limit": 50,
                "user_daily_limit": 20,
                "tenant_daily_limit": 5000,
            }
        return dict(row)

    def deployment_readiness(self, app_env: str) -> dict:
        providers = {
            "dify": getattr(self.dify, "provider_name", "unknown"),
            "temp_storage": getattr(self.storage, "provider_name", "unknown"),
            "payment": getattr(self.payment, "provider_name", "unknown"),
            "feishu": getattr(self.feishu, "provider_name", "unknown"),
        }
        blockers: list[str] = []
        warnings: list[str] = []
        is_production = app_env.lower() in {"prod", "production"}

        if providers["dify"] == "mock":
            message = "Dify provider is mock; real hair image generation is not connected"
            blockers.append(message) if is_production else warnings.append(message)
        if providers["temp_storage"] == "mock":
            message = "Temp storage provider is mock; production must use short-lived object storage"
            blockers.append(message) if is_production else warnings.append(message)
        if providers["payment"] == "mock":
            message = "Payment provider is mock; production paid AI trials require WeChat Pay"
            blockers.append(message) if is_production else warnings.append(message)
        if providers["feishu"] == "mock":
            warnings.append("Feishu sync provider is mock; statistics will not reach Feishu")

        return {
            "app_env": app_env,
            "ready_for_production": len(blockers) == 0,
            "providers": providers,
            "blockers": blockers,
            "warnings": warnings,
        }

    def update_ai_limits(
        self,
        *,
        tenant_id: int | None,
        store_id: int | None,
        user_concurrency_limit: int,
        store_concurrency_limit: int,
        tenant_concurrency_limit: int,
        platform_concurrency_limit: int,
        user_daily_limit: int,
        tenant_daily_limit: int,
    ) -> dict:
        values = [
            user_concurrency_limit,
            store_concurrency_limit,
            tenant_concurrency_limit,
            platform_concurrency_limit,
            user_daily_limit,
            tenant_daily_limit,
        ]
        if any(value < 0 for value in values):
            raise BusinessError("AI limits cannot be negative")
        with self.store.transaction() as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_limit_configs
                WHERE COALESCE(tenant_id, -1) = COALESCE(?, -1)
                  AND COALESCE(store_id, -1) = COALESCE(?, -1)
                """,
                (tenant_id, store_id),
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO ai_limit_configs
                    (tenant_id, store_id, user_concurrency_limit, store_concurrency_limit,
                     tenant_concurrency_limit, platform_concurrency_limit, user_daily_limit, tenant_daily_limit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        store_id,
                        user_concurrency_limit,
                        store_concurrency_limit,
                        tenant_concurrency_limit,
                        platform_concurrency_limit,
                        user_daily_limit,
                        tenant_daily_limit,
                    ),
                )
                config_id = cur.lastrowid
            else:
                config_id = existing["id"]
                conn.execute(
                    """
                    UPDATE ai_limit_configs
                    SET user_concurrency_limit = ?,
                        store_concurrency_limit = ?,
                        tenant_concurrency_limit = ?,
                        platform_concurrency_limit = ?,
                        user_daily_limit = ?,
                        tenant_daily_limit = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        user_concurrency_limit,
                        store_concurrency_limit,
                        tenant_concurrency_limit,
                        platform_concurrency_limit,
                        user_daily_limit,
                        tenant_daily_limit,
                        config_id,
                    ),
                )
        return dict(self.store.row("SELECT * FROM ai_limit_configs WHERE id = ?", (config_id,)))

    def get_user(self, tenant_id: int, user_id: int) -> dict:
        row = self.store.row(
            "SELECT * FROM users WHERE id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        if row is None:
            raise BusinessError("User not found")
        return dict(row)

    def record_privacy_consent(
        self,
        *,
        tenant_id: int,
        user_id: int,
        consent_scope: str = "photo_ai_generation",
        consent_version: str = "v1",
    ) -> dict:
        self.get_user(tenant_id, user_id)
        if not consent_scope.strip() or not consent_version.strip():
            raise BusinessError("consent_scope and consent_version are required")
        with self.store.transaction() as conn:
            existing = conn.execute(
                """
                SELECT id FROM user_privacy_consents
                WHERE tenant_id = ? AND user_id = ? AND consent_scope = ? AND consent_version = ?
                """,
                (tenant_id, user_id, consent_scope, consent_version),
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO user_privacy_consents
                    (tenant_id, user_id, consent_scope, consent_version, status)
                    VALUES (?, ?, ?, ?, 'accepted')
                    """,
                    (tenant_id, user_id, consent_scope, consent_version),
                )
                consent_id = cur.lastrowid
            else:
                consent_id = existing["id"]
                conn.execute(
                    """
                    UPDATE user_privacy_consents
                    SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP, revoked_at = NULL
                    WHERE id = ?
                    """,
                    (consent_id,),
                )
        return dict(self.store.row("SELECT * FROM user_privacy_consents WHERE id = ?", (consent_id,)))

    def revoke_privacy_consent(
        self,
        *,
        tenant_id: int,
        user_id: int,
        consent_scope: str = "photo_ai_generation",
        consent_version: str = "v1",
    ) -> dict:
        with self.store.transaction() as conn:
            row = conn.execute(
                """
                SELECT id FROM user_privacy_consents
                WHERE tenant_id = ? AND user_id = ? AND consent_scope = ? AND consent_version = ?
                """,
                (tenant_id, user_id, consent_scope, consent_version),
            ).fetchone()
            if row is None:
                raise BusinessError("Privacy consent not found")
            conn.execute(
                """
                UPDATE user_privacy_consents
                SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
        return dict(self.store.row("SELECT * FROM user_privacy_consents WHERE id = ?", (row["id"],)))

    def privacy_consent_status(
        self,
        *,
        tenant_id: int,
        user_id: int,
        consent_scope: str = "photo_ai_generation",
        consent_version: str = "v1",
    ) -> dict:
        row = self.store.row(
            """
            SELECT * FROM user_privacy_consents
            WHERE tenant_id = ? AND user_id = ? AND consent_scope = ? AND consent_version = ?
            ORDER BY id DESC LIMIT 1
            """,
            (tenant_id, user_id, consent_scope, consent_version),
        )
        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "consent_scope": consent_scope,
            "consent_version": consent_version,
            "accepted": bool(row and row["status"] == "accepted"),
            "status": row["status"] if row else "missing",
        }

    def wx_login(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        openid: str,
        phone: str | None = None,
        nickname: str | None = None,
    ) -> dict:
        if not openid.strip():
            raise BusinessError("openid is required")
        if store_id is not None:
            self._assert_active_tenant_store(tenant_id, store_id)
        row = self.store.row(
            "SELECT * FROM users WHERE tenant_id = ? AND openid = ?",
            (tenant_id, openid),
        )
        if row is not None:
            user = dict(row)
            if user.get("status") in ("disabled", "deleted"):
                raise BusinessError("账号已被停用，请联系门店")
            return {"is_new": False, "user": user}
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (tenant_id, store_id, openid, phone, nickname, role)
                VALUES (?, ?, ?, ?, ?, 'customer')
                """,
                (tenant_id, store_id, openid, phone, nickname),
            )
            user_id = cur.lastrowid
        return {"is_new": True, "user": self.get_user(tenant_id, user_id)}

    def assert_scope_access(
        self,
        *,
        actor_tenant_id: int,
        actor_user_id: int,
        target_tenant_id: int,
        target_store_id: int | None = None,
        target_user_id: int | None = None,
    ) -> None:
        actor = self.get_user(actor_tenant_id, actor_user_id)
        if actor["tenant_id"] != target_tenant_id:
            raise BusinessError("Cross-tenant access denied")

        role = actor["role"]
        if role == "boss":
            return
        if role == "manager":
            if target_store_id is not None and actor["store_id"] != target_store_id:
                raise BusinessError("Cross-store access denied")
            return
        if role == "staff":
            if target_store_id is not None and actor["store_id"] != target_store_id:
                raise BusinessError("Cross-store access denied")
            if target_user_id is not None and actor["id"] != target_user_id:
                raise BusinessError("Staff can only access own scoped data")
            return
        if role == "customer":
            if target_user_id is None or actor["id"] != target_user_id:
                raise BusinessError("Customer can only access own data")
            return
        raise BusinessError("Unknown role")

    def list_styles(
        self,
        tenant_id: int,
        store_id: int | None = None,
        direction: str | None = None,
        hair_length: str | None = None,
        recommended_only: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        params: tuple = (tenant_id,)
        where = "tenant_id = ? AND is_enabled = 1"
        order_prefix = ""
        if store_id is not None:
            where += " AND (store_id IS NULL OR store_id = ?)"
            params = (*params, store_id)
            order_prefix = "CASE WHEN store_id = ? THEN 0 ELSE 1 END, "
        if direction:
            where += " AND direction = ?"
            params = (*params, direction)
        if hair_length:
            if hair_length not in {"short", "medium", "long"}:
                raise BusinessError("hair_length must be short, medium or long")
            where += " AND hair_length = ?"
            params = (*params, hair_length)
        if recommended_only:
            where += " AND is_recommended = 1"
        limit_clause = ""
        if limit is not None:
            clean_limit = max(1, min(int(limit or 24), 100))
            limit_clause = " LIMIT ?"
        query_params = ((*params, store_id) if store_id is not None else params)
        if limit is not None:
            query_params = (*query_params, clean_limit)
        rows = self.store.rows(
            f"""
            SELECT style_id, name AS style_name, direction, hair_length, thumbnail_url, display_tags,
                   need_perm, is_recommended, sort_order
            FROM hairstyles
            WHERE {where}
            ORDER BY {order_prefix}is_recommended DESC, sort_order ASC
            {limit_clause}
            """,
            query_params,
        )
        return [dict(row) | parse_hairstyle_display_metadata(row["display_tags"]) for row in rows]

    def create_hairstyle(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        style_id: str | None,
        name: str,
        direction: str,
        hair_length: str,
        thumbnail_url: str | None = None,
        display_tags: Any,
        need_perm: bool,
        is_enabled: bool,
        is_recommended: bool,
        sort_order: int = 0,
    ) -> dict:
        if direction not in {"male", "female", "neutral"}:
            raise BusinessError("direction must be male, female or neutral")
        if hair_length not in {"short", "medium", "long"}:
            raise BusinessError("hair_length must be short, medium or long")
        clean_style_id = style_id or "style_" + uuid4().hex[:10]
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO hairstyles
                (tenant_id, store_id, style_id, name, direction, hair_length, thumbnail_url, display_tags,
                 need_perm, is_enabled, is_recommended, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    clean_style_id,
                    name,
                    direction,
                    hair_length,
                    thumbnail_url,
                    json.dumps(display_tags, ensure_ascii=False),
                    int(need_perm),
                    int(is_enabled),
                    int(is_recommended),
                    sort_order,
                ),
            )
            item_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM hairstyles WHERE id = ?", (item_id,)))

    def update_hairstyle(
        self,
        *,
        tenant_id: int,
        style_id: str,
        store_id: int | None = None,
        name: str | None = None,
        direction: str | None = None,
        hair_length: str | None = None,
        thumbnail_url: str | None = None,
        display_tags: Any | None = None,
        need_perm: bool | None = None,
        is_enabled: bool | None = None,
        is_recommended: bool | None = None,
        sort_order: int | None = None,
    ) -> dict:
        existing = self.store.row(
            "SELECT * FROM hairstyles WHERE tenant_id = ? AND style_id = ?",
            (tenant_id, style_id),
        )
        if existing is None:
            raise BusinessError("Hairstyle not found")
        if direction is not None and direction not in {"male", "female", "neutral"}:
            raise BusinessError("direction must be male, female or neutral")
        if hair_length is not None and hair_length not in {"short", "medium", "long"}:
            raise BusinessError("hair_length must be short, medium or long")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE hairstyles
                SET store_id = COALESCE(?, store_id),
                    name = COALESCE(?, name),
                    direction = COALESCE(?, direction),
                    hair_length = COALESCE(?, hair_length),
                    thumbnail_url = COALESCE(?, thumbnail_url),
                    display_tags = COALESCE(?, display_tags),
                    need_perm = COALESCE(?, need_perm),
                    is_enabled = COALESCE(?, is_enabled),
                    is_recommended = COALESCE(?, is_recommended),
                    sort_order = COALESCE(?, sort_order)
                WHERE tenant_id = ? AND style_id = ?
                """,
                (
                    store_id,
                    name,
                    direction,
                    hair_length,
                    thumbnail_url,
                    None if display_tags is None else json.dumps(display_tags, ensure_ascii=False),
                    None if need_perm is None else int(need_perm),
                    None if is_enabled is None else int(is_enabled),
                    None if is_recommended is None else int(is_recommended),
                    sort_order,
                    tenant_id,
                    style_id,
                ),
            )
        return dict(self.store.row("SELECT * FROM hairstyles WHERE tenant_id = ? AND style_id = ?", (tenant_id, style_id)))

    def list_colors(
        self,
        tenant_id: int,
        store_id: int | None = None,
        direction: str | None = None,
        recommended_only: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        params: tuple = (tenant_id,)
        where = "tenant_id = ? AND is_enabled = 1"
        order_prefix = ""
        if store_id is not None:
            where += " AND (store_id IS NULL OR store_id = ?)"
            params = (*params, store_id)
            order_prefix = "CASE WHEN store_id = ? THEN 0 ELSE 1 END, "
        if direction:
            where += " AND direction = ?"
            params = (*params, direction)
        if recommended_only:
            where += " AND is_recommended = 1"
        limit_clause = ""
        if limit is not None:
            clean_limit = max(1, min(int(limit or 30), 100))
            limit_clause = " LIMIT ?"
        query_params = ((*params, store_id) if store_id is not None else params)
        if limit is not None:
            query_params = (*query_params, clean_limit)
        rows = self.store.rows(
            f"""
            SELECT color_id, name AS color_name, direction, color_swatch, thumbnail_url, display_tags,
                   need_bleach, is_recommended, sort_order
            FROM hair_colors
            WHERE {where}
            ORDER BY {order_prefix}is_recommended DESC, sort_order ASC
            {limit_clause}
            """,
            query_params,
        )
        return [dict(row) | {"tags": json.loads(row["display_tags"])} for row in rows]

    def hairstyle_inspiration(self, tenant_id: int, direction: str) -> dict:
        if direction not in {"male", "female", "neutral"}:
            raise BusinessError("direction must be male, female or neutral")
        return {
            "tenant_id": tenant_id,
            "direction": direction,
            "tabs": [
                {"key": "hot", "title": "热门", "items": self.list_styles(tenant_id, direction=direction, recommended_only=True)},
                {"key": "long", "title": "长发", "items": self.list_styles(tenant_id, direction=direction, hair_length="long")},
                {"key": "medium", "title": "中发", "items": self.list_styles(tenant_id, direction=direction, hair_length="medium")},
                {"key": "short", "title": "短发", "items": self.list_styles(tenant_id, direction=direction, hair_length="short")},
                {"key": "colors", "title": "发色", "items": self.list_colors(tenant_id, direction=direction)},
            ],
        }

    def create_hair_color(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        color_id: str | None,
        name: str,
        direction: str,
        color_swatch: str | None,
        display_tags: list[str],
        need_bleach: bool,
        is_enabled: bool,
        is_recommended: bool,
        sort_order: int = 0,
        thumbnail_url: str | None = None,
    ) -> dict:
        if direction not in {"male", "female", "neutral"}:
            raise BusinessError("direction must be male, female or neutral")
        clean_color_id = color_id or "color_" + uuid4().hex[:10]
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO hair_colors
                (tenant_id, store_id, color_id, name, direction, color_swatch, thumbnail_url, display_tags,
                 need_bleach, is_enabled, is_recommended, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    clean_color_id,
                    name,
                    direction,
                    color_swatch,
                    thumbnail_url,
                    json.dumps(display_tags, ensure_ascii=False),
                    int(need_bleach),
                    int(is_enabled),
                    int(is_recommended),
                    sort_order,
                ),
            )
            item_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM hair_colors WHERE id = ?", (item_id,)))

    def update_hair_color(
        self,
        *,
        tenant_id: int,
        color_id: str,
        store_id: int | None = None,
        name: str | None = None,
        direction: str | None = None,
        color_swatch: str | None = None,
        thumbnail_url: str | None = None,
        display_tags: list[str] | None = None,
        need_bleach: bool | None = None,
        is_enabled: bool | None = None,
        is_recommended: bool | None = None,
        sort_order: int | None = None,
    ) -> dict:
        existing = self.store.row(
            "SELECT * FROM hair_colors WHERE tenant_id = ? AND color_id = ?",
            (tenant_id, color_id),
        )
        if existing is None:
            raise BusinessError("Hair color not found")
        if direction is not None and direction not in {"male", "female", "neutral"}:
            raise BusinessError("direction must be male, female or neutral")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE hair_colors
                SET store_id = COALESCE(?, store_id),
                    name = COALESCE(?, name),
                    direction = COALESCE(?, direction),
                    color_swatch = COALESCE(?, color_swatch),
                    thumbnail_url = COALESCE(?, thumbnail_url),
                    display_tags = COALESCE(?, display_tags),
                    need_bleach = COALESCE(?, need_bleach),
                    is_enabled = COALESCE(?, is_enabled),
                    is_recommended = COALESCE(?, is_recommended),
                    sort_order = COALESCE(?, sort_order)
                WHERE tenant_id = ? AND color_id = ?
                """,
                (
                    store_id,
                    name,
                    direction,
                    color_swatch,
                    thumbnail_url,
                    None if display_tags is None else json.dumps(display_tags, ensure_ascii=False),
                    None if need_bleach is None else int(need_bleach),
                    None if is_enabled is None else int(is_enabled),
                    None if is_recommended is None else int(is_recommended),
                    sort_order,
                    tenant_id,
                    color_id,
                ),
            )
        return dict(self.store.row("SELECT * FROM hair_colors WHERE tenant_id = ? AND color_id = ?", (tenant_id, color_id)))

    def prepare_recommendations(
        self,
        tenant_id: int,
        direction: str,
        selected_style_id: str | None,
        selected_color_id: str | None,
    ) -> dict:
        styles = self.list_styles(tenant_id, direction=direction)
        colors = self.list_colors(tenant_id, direction=direction)
        if selected_style_id and not any(item["style_id"] == selected_style_id for item in styles):
            raise BusinessError("Selected hairstyle is not enabled for this tenant/direction")
        if selected_color_id and not any(item["color_id"] == selected_color_id for item in colors):
            raise BusinessError("Selected hair color is not enabled for this tenant/direction")

        selected_style = next((item for item in styles if item["style_id"] == selected_style_id), None)
        selected_color = next((item for item in colors if item["color_id"] == selected_color_id), None)
        hot_style = self._first_different(styles, selected_style_id, None) or selected_style
        hot_color = self._first_different(colors, selected_color_id, "color_id") or selected_color
        if selected_style:
            natural_style = selected_style
            natural_color = hot_color or selected_color
        elif selected_color:
            natural_style = hot_style
            natural_color = selected_color
        else:
            natural_style = hot_style
            natural_color = hot_color

        advanced_style = (
            self._first_different(
                styles,
                selected_style_id,
                "style_id",
                extra_excluded_ids=[natural_style["style_id"]] if natural_style else None,
            )
            or hot_style
            or selected_style
        )
        advanced_color = selected_color or hot_color
        recommendations = [
            self._build_recommendation(
                "natural",
                "Cross recommendation",
                natural_style,
                natural_color,
            ),
            self._build_recommendation(
                "advanced",
                "Merchant popular hairstyle",
                advanced_style,
                advanced_color,
            ),
        ]
        return {
            "candidate_styles": styles,
            "candidate_colors": colors,
            "selected_style": selected_style,
            "selected_color": selected_color,
            "recommendations": recommendations,
        }

    def _first_different(
        self,
        items: list[dict],
        excluded_id: str | None,
        id_key: str | None,
        *,
        extra_excluded_ids: list[str] | None = None,
    ) -> dict | None:
        excluded_ids = {item for item in [excluded_id, *(extra_excluded_ids or [])] if item}
        for item in items:
            key = id_key or ("style_id" if "style_id" in item else "color_id")
            if not excluded_ids or item.get(key) not in excluded_ids:
                return item
        return None

    def _build_recommendation(self, slot: str, title: str, style: dict | None, color: dict | None) -> dict:
        return {
            "slot": slot,
            "title": title,
            "style_id": style["style_id"] if style else None,
            "style_name": style["style_name"] if style else None,
            "thumbnail_url": style["thumbnail_url"] if style else None,
            "customer_description": style.get("customer_description") if style else None,
            "tags": style.get("tags") if style else [],
            "ai_reference_tags": style.get("ai_reference_tags") if style else [],
            "color_id": color["color_id"] if color else None,
            "color_name": color["color_name"] if color else None,
        }

    def recommend_stylists(
        self,
        *,
        tenant_id: int,
        store_id: int,
        direction: str,
        selected_style_id: str | None = None,
        selected_color_id: str | None = None,
        limit: int = 3,
    ) -> list[dict]:
        rows = self.store.rows(
            """
            SELECT sp.staff_id, sp.display_name, sp.title, sp.avatar_url, sp.directions,
                   sp.skill_tags, sp.availability_status, sp.sort_order, u.nickname
            FROM staff_profiles sp
            JOIN users u
              ON u.id = sp.staff_id
             AND u.tenant_id = sp.tenant_id
             AND u.store_id = sp.store_id
            WHERE sp.tenant_id = ?
              AND sp.store_id = ?
              AND sp.is_enabled = 1
              AND sp.is_recommended = 1
              AND sp.availability_status = 'available'
            ORDER BY sp.sort_order ASC, sp.staff_id ASC
            """,
            (tenant_id, store_id),
        )
        candidates: list[dict] = []
        for row in rows:
            directions = json.loads(row["directions"])
            if direction not in directions and "neutral" not in directions:
                continue
            skill_tags = json.loads(row["skill_tags"])
            candidates.append(
                {
                    "staff_id": row["staff_id"],
                    "display_name": row["display_name"],
                    "title": row["title"],
                    "avatar_url": row["avatar_url"],
                    "directions": directions,
                    "skill_tags": skill_tags,
                    "availability_status": row["availability_status"],
                    "recommend_reason": self._stylist_reason(skill_tags, selected_style_id, selected_color_id),
                    "is_default": len(candidates) == 0,
                }
            )
            if len(candidates) >= limit:
                break
        return candidates

    def list_staff(self, tenant_id: int, store_id: int) -> list[dict]:
        rows = self.store.rows(
            """
            SELECT sp.staff_id, sp.display_name, sp.title, sp.avatar_url, sp.directions,
                   sp.skill_tags, sp.availability_status, sp.is_enabled, sp.is_recommended,
                   sp.sort_order, u.phone, u.nickname, u.role
            FROM staff_profiles sp
            JOIN users u ON u.id = sp.staff_id AND u.tenant_id = sp.tenant_id
            WHERE sp.tenant_id = ? AND sp.store_id = ?
            ORDER BY sp.sort_order ASC, sp.staff_id ASC
            """,
            (tenant_id, store_id),
        )
        return [
            dict(row)
            | {
                "directions": json.loads(row["directions"]),
                "skill_tags": json.loads(row["skill_tags"]),
            }
            for row in rows
        ]

    def create_staff(
        self,
        *,
        tenant_id: int,
        store_id: int,
        openid: str,
        phone: str | None,
        display_name: str,
        title: str | None,
        directions: list[str],
        skill_tags: list[str],
        avatar_url: str | None = None,
        role: str = "staff",
        sort_order: int = 100,
    ) -> dict:
        if role not in {"staff", "manager"}:
            raise BusinessError("role must be staff or manager")
        if not openid.strip() or not display_name.strip():
            raise BusinessError("openid and display_name are required")
        if any(direction not in {"male", "female", "neutral"} for direction in directions):
            raise BusinessError("directions must only contain male, female or neutral")
        store = self.store.row(
            "SELECT id FROM stores WHERE tenant_id = ? AND id = ? AND status = 'active'",
            (tenant_id, store_id),
        )
        if store is None:
            raise BusinessError("Store not found or inactive")
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (tenant_id, store_id, openid, phone, nickname, role)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, store_id, openid, phone, display_name, role),
            )
            staff_id = cur.lastrowid
            conn.execute(
                """
                INSERT INTO staff_profiles
                (tenant_id, store_id, staff_id, display_name, title, avatar_url, directions,
                 skill_tags, availability_status, is_enabled, is_recommended, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', 1, 1, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    staff_id,
                    display_name,
                    title,
                    avatar_url,
                    json.dumps(directions, ensure_ascii=False),
                    json.dumps(skill_tags, ensure_ascii=False),
                    sort_order,
                ),
            )
        staff = next(item for item in self.list_staff(tenant_id, store_id) if item["staff_id"] == staff_id)
        return staff

    def update_staff_profile(
        self,
        *,
        tenant_id: int,
        store_id: int,
        staff_id: int,
        phone: str | None = None,
        display_name: str | None = None,
        title: str | None = None,
        directions: list[str] | None = None,
        skill_tags: list[str] | None = None,
        avatar_url: str | None = None,
        role: str | None = None,
        availability_status: str | None = None,
        is_enabled: bool | None = None,
        is_recommended: bool | None = None,
        sort_order: int | None = None,
    ) -> dict:
        existing = self.store.row(
            """
            SELECT sp.staff_id
            FROM staff_profiles sp
            JOIN users u ON u.id = sp.staff_id AND u.tenant_id = sp.tenant_id
            WHERE sp.tenant_id = ? AND sp.store_id = ? AND sp.staff_id = ?
            """,
            (tenant_id, store_id, staff_id),
        )
        if existing is None:
            raise BusinessError("Staff profile not found")
        if display_name is not None and not display_name.strip():
            raise BusinessError("display_name cannot be empty")
        if role is not None and role not in {"staff", "manager"}:
            raise BusinessError("role must be staff or manager")
        if directions is not None and any(direction not in {"male", "female", "neutral"} for direction in directions):
            raise BusinessError("directions must only contain male, female or neutral")
        if availability_status is not None and availability_status not in {"available", "busy", "off_duty", "paused"}:
            raise BusinessError("Invalid staff availability_status")

        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE users
                SET phone = COALESCE(?, phone),
                    nickname = COALESCE(?, nickname),
                    role = COALESCE(?, role)
                WHERE tenant_id = ? AND id = ?
                """,
                (phone, display_name, role, tenant_id, staff_id),
            )
            conn.execute(
                """
                UPDATE staff_profiles
                SET display_name = COALESCE(?, display_name),
                    title = COALESCE(?, title),
                    avatar_url = COALESCE(?, avatar_url),
                    directions = COALESCE(?, directions),
                    skill_tags = COALESCE(?, skill_tags),
                    availability_status = COALESCE(?, availability_status),
                    is_enabled = COALESCE(?, is_enabled),
                    is_recommended = COALESCE(?, is_recommended),
                    sort_order = COALESCE(?, sort_order),
                    updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ? AND store_id = ? AND staff_id = ?
                """,
                (
                    display_name,
                    title,
                    avatar_url,
                    None if directions is None else json.dumps(directions, ensure_ascii=False),
                    None if skill_tags is None else json.dumps(skill_tags, ensure_ascii=False),
                    availability_status,
                    None if is_enabled is None else int(is_enabled),
                    None if is_recommended is None else int(is_recommended),
                    sort_order,
                    tenant_id,
                    store_id,
                    staff_id,
                ),
            )
        return next(item for item in self.list_staff(tenant_id, store_id) if item["staff_id"] == staff_id)

    def update_staff_status(
        self,
        *,
        tenant_id: int,
        store_id: int,
        staff_id: int,
        availability_status: str,
    ) -> dict:
        allowed = {"available", "busy", "off_duty", "paused"}
        if availability_status not in allowed:
            raise BusinessError("Invalid staff availability_status")
        with self.store.transaction() as conn:
            row = conn.execute(
                """
                SELECT * FROM staff_profiles
                WHERE tenant_id = ? AND store_id = ? AND staff_id = ?
                """,
                (tenant_id, store_id, staff_id),
            ).fetchone()
            if row is None:
                raise BusinessError("Staff profile not found")
            conn.execute(
                """
                UPDATE staff_profiles
                SET availability_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ? AND store_id = ? AND staff_id = ?
                """,
                (availability_status, tenant_id, store_id, staff_id),
            )
        return dict(
            self.store.row(
                """
                SELECT * FROM staff_profiles
                WHERE tenant_id = ? AND store_id = ? AND staff_id = ?
                """,
                (tenant_id, store_id, staff_id),
            )
        )

    def _stylist_reason(
        self,
        skill_tags: list[str],
        selected_style_id: str | None,
        selected_color_id: str | None,
    ) -> str:
        if selected_color_id and any("color" in tag for tag in skill_tags):
            return "Recommended for color service experience"
        if selected_style_id and any("short" in tag or "texture" in tag for tag in skill_tags):
            return "Recommended for hairstyle matching experience"
        return "Recommended by store priority and availability"

    def list_service_items(
        self,
        tenant_id: int,
        store_id: int | None = None,
        include_disabled: bool = False,
    ) -> list[dict]:
        enabled_filter = "" if include_disabled else " AND is_enabled = 1"
        params: tuple
        if store_id is None:
            params = (tenant_id,)
            where = f"tenant_id = ?{enabled_filter}"
        else:
            params = (tenant_id, store_id)
            where = f"tenant_id = ?{enabled_filter} AND (store_id = ? OR store_id IS NULL)"
        rows = self.store.rows(
            f"""
            SELECT id, tenant_id, store_id, name, category, base_price, is_enabled, sort_order
            FROM service_items
            WHERE {where}
            ORDER BY sort_order ASC, id ASC
            """,
            params,
        )
        return [dict(row) | {"display_name": self._service_display_name(dict(row))} for row in rows]

    def create_service_item(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        name: str,
        category: str,
        base_price: float = 0,
        sort_order: int = 100,
    ) -> dict:
        if not name.strip():
            raise BusinessError("Service item name is required")
        if not category.strip():
            raise BusinessError("Service item category is required")
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO service_items
                (tenant_id, store_id, name, category, base_price, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, store_id, name, category, base_price, sort_order),
            )
            service_item_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM service_items WHERE id = ?", (service_item_id,)))

    def update_service_item(
        self,
        *,
        tenant_id: int,
        service_item_id: int,
        store_id: int | None = None,
        name: str | None = None,
        category: str | None = None,
        base_price: float | None = None,
        is_enabled: bool | None = None,
        sort_order: int | None = None,
    ) -> dict:
        existing = self.store.row(
            "SELECT * FROM service_items WHERE id = ? AND tenant_id = ?",
            (service_item_id, tenant_id),
        )
        if existing is None:
            raise BusinessError("Service item not found")
        if base_price is not None and base_price < 0:
            raise BusinessError("base_price cannot be negative")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE service_items
                SET store_id = COALESCE(?, store_id),
                    name = COALESCE(?, name),
                    category = COALESCE(?, category),
                    base_price = COALESCE(?, base_price),
                    is_enabled = COALESCE(?, is_enabled),
                    sort_order = COALESCE(?, sort_order)
                WHERE id = ? AND tenant_id = ?
                """,
                (
                    store_id,
                    name,
                    category,
                    base_price,
                    None if is_enabled is None else int(is_enabled),
                    sort_order,
                    service_item_id,
                    tenant_id,
                ),
            )
        return dict(self.store.row("SELECT * FROM service_items WHERE id = ?", (service_item_id,)))

    def list_ai_knowledge_items(
        self,
        tenant_id: int,
        store_id: int | None = None,
        include_disabled: bool = False,
    ) -> list[dict]:
        enabled_filter = "" if include_disabled else " AND is_enabled = 1"
        if store_id is None:
            where = f"tenant_id = ?{enabled_filter}"
            params: tuple = (tenant_id,)
        else:
            where = f"tenant_id = ?{enabled_filter} AND (store_id = ? OR store_id IS NULL)"
            params = (tenant_id, store_id)
        rows = self.store.rows(
            f"""
            SELECT id, tenant_id, store_id, category, question, answer, keywords,
                   is_enabled, sort_order, created_at, updated_at
            FROM ai_knowledge_items
            WHERE {where}
            ORDER BY sort_order ASC, id ASC
            """,
            params,
        )
        return [dict(row) | {"keywords": json.loads(row["keywords"])} for row in rows]

    def create_ai_knowledge_item(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        category: str,
        question: str,
        answer: str,
        keywords: list[str],
        is_enabled: bool = True,
        sort_order: int = 100,
    ) -> dict:
        if not question.strip() or not answer.strip():
            raise BusinessError("question and answer are required")
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO ai_knowledge_items
                (tenant_id, store_id, category, question, answer, keywords, is_enabled, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    category,
                    question,
                    answer,
                    json.dumps(keywords, ensure_ascii=False),
                    int(is_enabled),
                    sort_order,
                ),
            )
            item_id = cur.lastrowid
        row = self.store.row("SELECT * FROM ai_knowledge_items WHERE id = ?", (item_id,))
        assert row is not None
        return dict(row) | {"keywords": json.loads(row["keywords"])}

    def update_ai_knowledge_item(
        self,
        *,
        tenant_id: int,
        item_id: int,
        store_id: int | None = None,
        category: str | None = None,
        question: str | None = None,
        answer: str | None = None,
        keywords: list[str] | None = None,
        is_enabled: bool | None = None,
        sort_order: int | None = None,
    ) -> dict:
        existing = self.store.row(
            "SELECT * FROM ai_knowledge_items WHERE id = ? AND tenant_id = ?",
            (item_id, tenant_id),
        )
        if existing is None:
            raise BusinessError("AI knowledge item not found")
        if question is not None and not question.strip():
            raise BusinessError("question cannot be empty")
        if answer is not None and not answer.strip():
            raise BusinessError("answer cannot be empty")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE ai_knowledge_items
                SET store_id = COALESCE(?, store_id),
                    category = COALESCE(?, category),
                    question = COALESCE(?, question),
                    answer = COALESCE(?, answer),
                    keywords = COALESCE(?, keywords),
                    is_enabled = COALESCE(?, is_enabled),
                    sort_order = COALESCE(?, sort_order),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND tenant_id = ?
                """,
                (
                    store_id,
                    category,
                    question,
                    answer,
                    None if keywords is None else json.dumps(keywords, ensure_ascii=False),
                    None if is_enabled is None else int(is_enabled),
                    sort_order,
                    item_id,
                    tenant_id,
                ),
            )
        row = self.store.row("SELECT * FROM ai_knowledge_items WHERE id = ? AND tenant_id = ?", (item_id, tenant_id))
        assert row is not None
        return dict(row) | {"keywords": json.loads(row["keywords"])}

    def suggest_asset_tags(self, *, tenant_id: int, store_id: int, asset_type: str, image_url: str) -> dict:
        if asset_type not in {"hairstyle", "hair_color"}:
            raise BusinessError("asset_type must be hairstyle or hair_color")
        if not image_url.startswith(("http://", "https://")):
            raise BusinessError("image_url must be an http URL")
        if asset_type == "hairstyle":
            suggestion = {
                "direction": "female",
                "hair_length": "medium",
                "display_tags": ["natural", "face shaping", "salon style"],
                "internal_tags": ["medium hair", "low maintenance"],
                "need_perm": True,
                "need_bleach": None,
            }
        else:
            suggestion = {
                "direction": "female",
                "display_tags": ["natural", "brightening", "low key"],
                "internal_tags": ["brown tone", "commute"],
                "need_perm": None,
                "need_bleach": False,
            }
        return {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "asset_type": asset_type,
            "image_url": image_url,
            "suggestion": suggestion,
            "confidence": 0.86,
            "auto_saved": False,
        }

    def ai_chat(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        message: str,
        session_key: str | None = None,
    ) -> dict:
        if not message.strip():
            raise BusinessError("message is required")

        text = message.strip().lower()
        # 预约是强业务动作：优先引导到预约页，提交后才进入商家端订单管理。
        if any(keyword in text for keyword in ["book", "appointment", "预约", "下单", "到店"]):
            return self._ai_chat_rules(
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                message=message,
            )

        # 连锁版且 DeepSeek 已配置 → 走 LLM
        _t_row = self.store.row("SELECT subscription_plan FROM tenants WHERE id = ?", (tenant_id,))
        plan_key = (dict(_t_row).get("subscription_plan") or "trial") if _t_row else "trial"
        if plan_key == "enterprise" and self._deepseek is not None:
            return self._ai_chat_deepseek(
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                message=message,
                session_key=session_key or f"{tenant_id}:{user_id}",
            )

        # 其他套餐 → 原规则匹配
        return self._ai_chat_rules(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            message=message,
        )

    # ── DeepSeek 多轮对话（连锁版）──────────────────────────────────────────

    _CHAT_HISTORY_TTL = 7200   # Redis 会话 2 小时
    _MAX_HISTORY_TURNS = 10    # 最多保留 10 轮（20 条）

    def _ai_chat_deepseek(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        message: str,
        session_key: str,
    ) -> dict:
        # 1. 拉取对话历史
        history = self._load_chat_history(session_key)

        # 2. 构建系统提示词（含门店上下文）
        ctx = self.ai_customer_context(tenant_id, store_id)
        store_info = ctx.get("store", {})
        system_prompt = build_system_prompt(
            store_name=store_info.get("name", ""),
            store_address=store_info.get("address", ""),
            services=ctx.get("services", []),
            hairstyles=[
                {
                    "id": s.get("style_id") or s.get("id"),
                    "style_name": s.get("style_name") or s.get("name"),
                    "hair_length": s.get("hair_length"),
                    "display_tags": s.get("display_tags") or [],
                }
                for s in ctx.get("recommended_hairstyles", [])[:15]
            ],
            knowledge_items=ctx.get("knowledge", []),
        )

        # 3. 调用 DeepSeek
        history.append({"role": "user", "content": message})
        try:
            result = self._deepseek.chat(
                messages=history,
                system_prompt=system_prompt,
            )
        except Exception as exc:
            # DeepSeek 失败时优雅降级到规则引擎
            history.pop()
            return self._ai_chat_rules(
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                message=message,
            )

        # 4. 追加 assistant 回复到历史
        history.append({"role": "assistant", "content": result["content"]})
        # 只保留最近 N 轮
        if len(history) > self._MAX_HISTORY_TURNS * 2:
            history = history[-(self._MAX_HISTORY_TURNS * 2):]
        self._save_chat_history(session_key, history)

        # 5. 记录成本到 DB
        self._record_llm_cost(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            session_key=session_key,
            prompt_tokens=result["prompt_tokens"],
            cached_tokens=result["cached_tokens"],
            completion_tokens=result["completion_tokens"],
            cost_fen=result["cost_fen"],
        )

        return {
            "answer": result["reply"],
            "actions": result["actions"],
            "data": {
                "engine": "deepseek",
                "cost_fen": result["cost_fen"],
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
            },
            "fallback": False,
        }

    def _load_chat_history(self, session_key: str) -> list[dict]:
        key = f"chat_history:{session_key}"
        if self._chat_redis:
            raw = self._chat_redis.get(key)
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    pass
        return []

    def _save_chat_history(self, session_key: str, history: list[dict]) -> None:
        key = f"chat_history:{session_key}"
        payload = json.dumps(history, ensure_ascii=False)
        if self._chat_redis:
            self._chat_redis.setex(key, self._CHAT_HISTORY_TTL, payload)

    def _record_llm_cost(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        session_key: str,
        prompt_tokens: int,
        cached_tokens: int,
        completion_tokens: int,
        cost_fen: int,
    ) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO llm_chat_logs
                  (tenant_id, store_id, user_id, session_key,
                   prompt_tokens, cached_tokens, completion_tokens, cost_fen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, store_id, user_id, session_key,
                 prompt_tokens, cached_tokens, completion_tokens, cost_fen),
            )
            conn.execute(
                """
                UPDATE tenants
                SET monthly_llm_cost_fen = COALESCE(monthly_llm_cost_fen, 0) + ?
                WHERE id = ?
                """,
                (cost_fen, tenant_id),
            )

    # ── 规则引擎（原逻辑，其他套餐使用）────────────────────────────────────

    def _ai_chat_rules(
        self, *, tenant_id: int, store_id: int, user_id: int, message: str
    ) -> dict:
        text = message.strip().lower()
        use_english = should_answer_in_english(message)

        if any(keyword in text for keyword in ["book", "appointment", "预约", "下单", "到店"]):
            stylists = self.recommend_stylists(tenant_id=tenant_id, store_id=store_id, direction="female")
            return {
                "answer": (
                    "You can submit an appointment request. The store will see it in the merchant order list and confirm the final service in store."
                    if use_english
                    else "可以预约。你提交后，商家端会在订单管理里看到这条预约，再由门店确认到店时间、主理人、服务项目和最终价格。"
                ),
                "actions": [{"type": "create_order", "label": "Book now" if use_english else "去预约"}],
                "data": {"recommended_stylists": stylists},
                "fallback": False,
            }

        knowledge = self._match_ai_knowledge(tenant_id, store_id, text)
        if knowledge is not None:
            return {
                "answer": knowledge["answer"],
                "actions": [{"type": "knowledge_answer", "label": "Knowledge answer" if use_english else "知识库回答"}],
                "data": {"knowledge_item_id": knowledge["id"], "category": knowledge["category"]},
                "fallback": False,
            }

        if any(keyword in text for keyword in ["price", "cost", "多少钱", "价格", "费用"]):
            services = [item for item in self.list_service_items(tenant_id, store_id) if int(item.get("is_enabled", 1))]
            lines = [f"{self._service_display_name(item)}：¥{int(float(item['base_price']))}起" for item in services]
            return {
                "answer": (
                    "Here are the configured service reference prices. Final price must be confirmed in store."
                    if use_english
                    else "以下是门店已配置的服务参考价：\n" + "\n".join(lines[:8]) + "\n最终价格会根据发长、发量、是否漂发、是否烫发和现场方案确认。"
                ),
                "actions": [{"type": "view_services", "label": "View services" if use_english else "查看服务价目"}],
                "data": {"services": services},
                "fallback": False,
            }

        if any(keyword in text for keyword in ["发色", "颜色", "染发", "漂发", "bleach", "color"]):
            answer = self._chat_hair_color_answer(tenant_id, text)
            if answer is not None:
                return answer

        if any(keyword in text for keyword in ["造型", "发型", "短发", "中发", "长发", "刘海", "烫发", "hair", "style"]):
            answer = self._chat_hairstyle_answer(tenant_id, text)
            if answer is not None:
                return answer

        if any(keyword in text for keyword in ["ai", "试发"]):
            return {
                "answer": (
                    "AI styling can generate 3 temporary preview images from the customer's selfie. Images are not stored permanently."
                    if use_english
                    else "AI试发可以根据你的自拍生成临时发型预览图，图片仅用于本次预览，不会长期保存。"
                ),
                "actions": [{"type": "start_ai_style", "label": "Start AI styling" if use_english else "开始AI试发"}],
                "data": {},
                "fallback": False,
            }

        return {
            "answer": (
                "I can help with AI styling, services, pricing reference, and appointments. For other questions, please contact the store."
                if use_english
                else "我可以帮你了解AI试发、服务项目、价格参考和预约下单。其他问题请联系门店工作人员。"
            ),
            "actions": [{"type": "contact_store", "label": "Contact store" if use_english else "联系门店"}],
            "data": {},
            "fallback": True,
        }

    def _match_ai_knowledge(self, tenant_id: int, store_id: int, text: str) -> dict | None:
        for item in self.list_ai_knowledge_items(tenant_id, store_id):
            candidates = [item["question"], *item["keywords"]]
            for candidate in candidates:
                normalized = candidate.strip().lower()
                if normalized and normalized in text:
                    return item
        return None

    def ai_customer_context(self, tenant_id: int, store_id: int) -> dict:
        profile = self.store_public_profile(tenant_id, store_id)
        services = [
            dict(item) | {"display_name": self._service_display_name(item)}
            for item in self.list_service_items(tenant_id, store_id)
            if int(item.get("is_enabled", 1))
        ]
        styles = []
        colors = []
        for direction in ("female", "male", "neutral"):
            styles.extend(self.list_styles(tenant_id, direction=direction, recommended_only=True)[:8])
            colors.extend(self.list_colors(tenant_id, direction=direction, recommended_only=True)[:12])
        return {
            "store": profile,
            "services": services,
            "recommended_hairstyles": self._dedupe_by_name(styles, "style_name")[:20],
            "hair_colors": self._dedupe_by_name(colors, "color_name")[:60],
            "knowledge": self.list_ai_knowledge_items(tenant_id, store_id),
        }

    def _service_display_name(self, item: dict) -> str:
        mapping = {
            "Haircut": "剪发",
            "Color": "染发",
            "Perm": "烫发",
            "Styling": "造型",
            "Care": "护理",
            "haircut": "剪发",
            "color": "染发",
            "perm": "烫发",
            "styling": "造型",
            "care": "护理",
        }
        name = str(item.get("name") or "").strip()
        if name:
            return mapping.get(name, name)
        return mapping.get(str(item.get("category")), "服务项目")

    def _chat_hair_color_answer(self, tenant_id: int, text: str) -> dict | None:
        colors = []
        for direction in self._directions_for_chat_text(text):
            colors.extend(self.list_colors(tenant_id, direction=direction, recommended_only=True))
        colors = self._dedupe_by_name(colors, "color_name")
        matched = self._match_items_by_text(colors, text, "color_name", "tags")
        selected = matched[:6] if matched else colors[:8]
        if not selected:
            return None
        lines = []
        for color in selected:
            desc = self._extract_prefixed_tag(color.get("tags") or [], "顾客描述：")
            bleach = "需要漂发" if int(color.get("need_bleach") or 0) else "通常不需要漂发"
            short_desc = f"，{desc}" if desc else ""
            lines.append(f"{color['color_name']}：{bleach}{short_desc}")
        return {
            "answer": "门店发色库里可以参考：\n" + "\n".join(lines) + "\n具体是否漂发，还要看你的原生发色、发质和目标明度。",
            "actions": [{"type": "view_hair_colors", "label": "查看发色"}],
            "data": {"colors": selected},
            "fallback": False,
        }

    def _chat_hairstyle_answer(self, tenant_id: int, text: str) -> dict | None:
        styles = []
        for direction in self._directions_for_chat_text(text):
            styles.extend(self.list_styles(tenant_id, direction=direction, recommended_only=True))
        styles = self._dedupe_by_name(styles, "style_name")
        matched = self._match_items_by_text(styles, text, "style_name", "tags")
        selected = matched[:6] if matched else styles[:6]
        if not selected:
            return None
        lines = []
        for style in selected:
            desc = style.get("customer_description") or ""
            perm = "需要/可选烫发" if int(style.get("need_perm") or 0) else "一般不需要烫发"
            length = {"short": "短发", "medium": "中发", "long": "长发"}.get(style.get("hair_length"), style.get("hair_length") or "")
            short_desc = f"，{desc}" if desc else ""
            lines.append(f"{style['style_name']}：{length}，{perm}{short_desc}")
        return {
            "answer": "门店发型库里可以参考：\n" + "\n".join(lines) + "\n建议先用 AI 试发看整体感觉，再到店和主理人确认刘海、层次和发尾厚薄。",
            "actions": [{"type": "view_hairstyles", "label": "查看发型"}],
            "data": {"hairstyles": selected},
            "fallback": False,
        }

    def _match_items_by_text(self, items: list[dict], text: str, name_key: str, tags_key: str) -> list[dict]:
        scored: list[tuple[int, dict]] = []
        for item in items:
            score = 0
            name = str(item.get(name_key) or "").lower()
            if name and name in text:
                score += 10
            for tag in item.get(tags_key) or []:
                clean = str(tag).strip().lower()
                if not clean or clean.startswith(("ai参考", "顾客描述")):
                    continue
                if clean in text:
                    score += 2
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored]

    def _extract_prefixed_tag(self, tags: list[str], prefix: str) -> str:
        for tag in tags:
            text = str(tag)
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return ""

    def _dedupe_by_name(self, items: list[dict], name_key: str) -> list[dict]:
        seen: set[str] = set()
        result: list[dict] = []
        for item in items:
            name = str(item.get(name_key) or "")
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(item)
        return result

    def _directions_for_chat_text(self, text: str) -> tuple[str, ...]:
        if any(keyword in text for keyword in ["男士", "男生", "男发", "男性", "男款"]):
            return ("male", "neutral", "female")
        if any(keyword in text for keyword in ["女士", "女生", "女发", "女性", "女款"]):
            return ("female", "neutral", "male")
        if "中性" in text:
            return ("neutral", "female", "male")
        return ("female", "male", "neutral")

    def create_mock_paid_order(self, tenant_id: int, store_id: int, user_id: int, amount: float) -> str:
        pay_order_no = "PAY" + uuid4().hex[:16].upper()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO ai_payment_orders (tenant_id, store_id, user_id, pay_order_no, amount, pay_status)
                VALUES (?, ?, ?, ?, ?, 'paid')
                """,
                (tenant_id, store_id, user_id, pay_order_no, amount),
            )
            conn.execute(
                "UPDATE ai_payment_orders SET paid_at = CURRENT_TIMESTAMP WHERE pay_order_no = ?",
                (pay_order_no,),
            )
        return pay_order_no

    def create_pending_payment_order(self, tenant_id: int, store_id: int, user_id: int, amount: float) -> str:
        pay_order_no = "PAY" + uuid4().hex[:16].upper()
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO ai_payment_orders (tenant_id, store_id, user_id, pay_order_no, amount, pay_status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (tenant_id, store_id, user_id, pay_order_no, amount),
            )
        return pay_order_no

    def create_ai_payment(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        amount: float,
        mock_paid: bool = True,
    ) -> dict:
        if amount <= 0:
            raise BusinessError("amount must be greater than 0")
        if mock_paid:
            pay_order_no = self.create_mock_paid_order(tenant_id, store_id, user_id, amount)
            return {"pay_order_no": pay_order_no, "pay_status": "paid", "mode": "mock"}

        user = self.get_user(tenant_id, user_id)
        pay_order_no = self.create_pending_payment_order(tenant_id, store_id, user_id, amount)
        try:
            prepay = self.payment.create_mini_program_prepay(
                pay_order_no=pay_order_no,
                openid=user["openid"],
                amount_yuan=amount,
                description="AI试发付费次数",
            )
        except PaymentError as exc:
            raise BusinessError(str(exc)) from exc
        return {
            "pay_order_no": pay_order_no,
            "pay_status": "pending",
            "mode": self.payment.provider_name,
            "prepay": prepay,
        }

    def create_temp_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        file_ext: str,
        ttl_minutes: int = 30,
    ) -> dict:
        self._assert_active_tenant_store(tenant_id, store_id)
        self._assert_privacy_consent(tenant_id, user_id)
        try:
            return self.storage.create_temp_upload_url(
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                file_ext=file_ext,
                ttl_minutes=ttl_minutes,
            )
        except StorageError as exc:
            raise BusinessError(str(exc)) from exc

    def create_catalog_upload_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        asset_type: str,
        file_ext: str,
    ) -> dict:
        self._assert_active_tenant_store(tenant_id, store_id)
        try:
            return self.storage.create_catalog_upload_url(
                tenant_id=tenant_id,
                store_id=store_id,
                asset_type=asset_type,
                file_ext=file_ext,
            )
        except StorageError as exc:
            raise BusinessError(str(exc)) from exc

    def mark_payment_paid(self, pay_order_no: str) -> dict:
        with self.store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM ai_payment_orders WHERE pay_order_no = ?",
                (pay_order_no,),
            ).fetchone()
            if row is None:
                raise BusinessError("Payment order not found")
            conn.execute(
                """
                UPDATE ai_payment_orders
                SET pay_status = 'paid', paid_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE pay_order_no = ?
                """,
                (pay_order_no,),
            )
        return self.payment_order(pay_order_no)

    def payment_order(self, pay_order_no: str) -> dict:
        row = self.store.row("SELECT * FROM ai_payment_orders WHERE pay_order_no = ?", (pay_order_no,))
        if row is None:
            raise BusinessError("Payment order not found")
        return dict(row)

    def payment_order_for_customer(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        pay_order_no: str,
    ) -> dict:
        row = self.store.row(
            """
            SELECT * FROM ai_payment_orders
            WHERE pay_order_no = ? AND tenant_id = ? AND store_id = ? AND user_id = ?
            """,
            (pay_order_no, tenant_id, store_id, user_id),
        )
        if row is None:
            raise BusinessError("Payment order not found")
        return dict(row)

    def generate(self, req: GenerateRequest) -> dict:
        job = self.enqueue_generation(req)
        self.queue.remove(job["job_no"])
        processed = self.process_generation_job(job["job_no"])
        return self._public_job_view(processed)

    def enqueue_generation(self, req: GenerateRequest) -> dict:
        self._assert_active_tenant_store(req.tenant_id, req.store_id)
        self._assert_privacy_consent(req.tenant_id, req.user_id)
        existing = self.store.row(
            """
            SELECT * FROM ai_generation_jobs
            WHERE tenant_id = ? AND user_id = ? AND status IN ('queued', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (req.tenant_id, req.user_id),
        )
        if existing:
            existing_data = dict(existing)
            if existing_data["status"] == "success":
                existing_data["images"] = self._load_job_images(existing_data)
                existing_data["result_storage"] = "temporary_url_metadata"
            return self._public_job_view(existing_data)

        self._assert_generation_limits(req)
        # 订阅计划月度配额检查（次数包模式不受此限制）
        quota_info = self.check_monthly_ai_quota(req.tenant_id)
        if quota_info["remaining"] <= 0:
            from .plans import get_plan
            plan_name = get_plan(quota_info["plan"])["display_name"]
            raise BusinessError(
                f"本月AI生成次数已用完（{plan_name}套餐 {quota_info['quota']} 次/月），"
                "请升级套餐或等待下月重置。"
            )
        if req.billing_type == BillingType.PAID:
            self._assert_paid_order(req)
        elif req.billing_type == BillingType.FREE:
            self._assert_free_quota(req)
        elif req.billing_type == BillingType.GIFT:
            self._assert_gift_quota(req)

        job_no = "AI" + uuid4().hex[:16].upper()
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO ai_generation_jobs
                (tenant_id, store_id, user_id, job_no, direction, selected_style_id, selected_color_id,
                 billing_type, status, queue_position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0)
                """,
                (
                    req.tenant_id,
                    req.store_id,
                    req.user_id,
                    job_no,
                    req.direction.value,
                    req.selected_style_id,
                    req.selected_color_id,
                    req.billing_type.value,
                ),
            )
            job_id = cur.lastrowid
            if req.billing_type == BillingType.PAID and req.pay_order_no:
                self._attach_payment_order_to_job(conn, req.pay_order_no, job_id)
        queue_position = self.queue.push(QueuedGenerationJob(job_no=job_no, request=req))
        self._queued_requests[job_no] = req
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE ai_generation_jobs SET queue_position = ? WHERE job_no = ?",
                (queue_position, job_no),
            )
        return self.get_customer_job(
            tenant_id=req.tenant_id,
            store_id=req.store_id,
            user_id=req.user_id,
            job_no=job_no,
        )

    def process_next_generation_job(self) -> dict | None:
        queued = self.queue.pop()
        if queued is None:
            return None
        self._queued_requests[queued.job_no] = queued.request
        return self._public_job_view(self.process_generation_job(queued.job_no))

    def process_generation_job(self, job_no: str) -> dict:
        row = self.store.row("SELECT * FROM ai_generation_jobs WHERE job_no = ?", (job_no,))
        if row is None:
            raise BusinessError("Generation job not found")
        if row["status"] != JobStatus.QUEUED.value:
            return self.job(job_no)

        req = self._queued_requests.pop(
            job_no,
            GenerateRequest(
                tenant_id=row["tenant_id"],
                store_id=row["store_id"],
                user_id=row["user_id"],
                direction=Direction(row["direction"]),
                billing_type=BillingType(row["billing_type"]),
                selected_style_id=row["selected_style_id"],
                selected_color_id=row["selected_color_id"],
                customer_reference_type=None,
                hair_profile={},
            ),
        )
        queued_at = time.monotonic()

        started_at = time.monotonic()
        queue_wait_seconds = max(0, int(started_at - queued_at))
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE ai_generation_jobs
                SET status = 'running', started_at = CURRENT_TIMESTAMP, queue_wait_seconds = ?
                WHERE job_no = ?
                """,
                (queue_wait_seconds, job_no),
            )

        prepared = self.prepare_recommendations(
            req.tenant_id,
            req.direction.value,
            req.selected_style_id,
            req.selected_color_id,
        )
        try:
            result = self.dify.generate_hair_images(
                job_no=job_no,
                direction=req.direction.value,
                selected_style=prepared["selected_style"],
                selected_color=prepared["selected_color"],
                recommendations=prepared["recommendations"],
                photo_temp_url=req.photo_temp_url,
                customer_reference_url=req.customer_reference_url,
                customer_reference_type=req.customer_reference_type,
                hair_profile=req.hair_profile,
            )
        finally:
            for temp_url in (req.photo_temp_url, req.customer_reference_url):
                if not temp_url:
                    continue
                try:
                    self.storage.delete_temp_asset(temp_url)
                except StorageError:
                    # OSS lifecycle rules remain the fallback if active cleanup fails.
                    pass
        completed_at = time.monotonic()
        generate_duration_seconds = max(0, int(completed_at - started_at))

        result_slots = {image.slot for image in result.images}
        if result.status != JobStatus.SUCCESS or "main" not in result_slots:
            with self.store.transaction() as conn:
                conn.execute(
                    """
                    UPDATE ai_generation_jobs
                    SET status = ?, completed_at = CURRENT_TIMESTAMP, generate_duration_seconds = ?,
                        error_code = ?, error_message = ?
                    WHERE job_no = ?
                    """,
                    (
                        result.status.value,
                        generate_duration_seconds,
                        result.error_code or "IMAGE_GENERATION_FAILED",
                        result.error_message or "AI generation failed",
                        job_no,
                    ),
                )
            return self.job(job_no)

        images = [
            {
                "slot": image.slot,
                "title": image.title,
                "direction": image.direction,
                "style_id": image.style_id,
                "style_name": image.style_name,
                "color_id": image.color_id,
                "color_name": image.color_name,
                "temp_image_url": image.temp_image_url,
            }
            for image in result.images
        ]
        resolved_cost = self.resolve_generation_cost(
            reported_cost=result.internal_api_cost,
            image_count=len(images),
        )
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE ai_generation_jobs
                SET status = 'success', main_status = ?, recommend_1_status = ?,
                    recommend_2_status = ?, completed_at = CURRENT_TIMESTAMP,
                    generate_duration_seconds = ?, internal_api_cost = ?, images_json = ?
                WHERE job_no = ?
                """,
                (
                    "success",
                    "success" if "natural" in result_slots else "pending",
                    "success" if "advanced" in result_slots else "pending",
                    generate_duration_seconds,
                    resolved_cost,
                    json.dumps(images, ensure_ascii=False),
                    job_no,
                ),
            )
        self._job_images[job_no] = images
        self._deduct_successful_job(job_no, req.billing_type)
        final_job = self.job(job_no)
        self.enqueue_sync_event(
            tenant_id=req.tenant_id,
            store_id=req.store_id,
            event_type="ai_generation_job",
            payload={
                "job_no": final_job["job_no"],
                "status": final_job["status"],
                "billing_type": final_job["billing_type"],
                "queue_wait_seconds": final_job["queue_wait_seconds"],
                "generate_duration_seconds": final_job["generate_duration_seconds"],
                "is_count_deducted": final_job["is_count_deducted"],
                "internal_api_cost": final_job["internal_api_cost"],
            },
        )
        return self._public_job_view(final_job)

    def job(self, job_no: str) -> dict:
        row = self.store.row("SELECT * FROM ai_generation_jobs WHERE job_no = ?", (job_no,))
        if row is None:
            raise BusinessError("Generation job not found")
        data = dict(row)
        if data["status"] == "success" or data["main_status"] == "success":
            data["images"] = self._load_job_images(data)
            data["result_storage"] = "temporary_url_metadata"
            data["recommended_stylists"] = self.recommend_stylists(
                tenant_id=data["tenant_id"],
                store_id=data["store_id"],
                direction=data["direction"],
                selected_style_id=data["selected_style_id"],
                selected_color_id=data["selected_color_id"],
            )
        return data

    def get_customer_job(self, *, tenant_id: int, store_id: int, user_id: int, job_no: str) -> dict:
        row = self.store.row(
            """
            SELECT * FROM ai_generation_jobs
            WHERE job_no = ? AND tenant_id = ? AND store_id = ? AND user_id = ?
            """,
            (job_no, tenant_id, store_id, user_id),
        )
        if row is None:
            raise BusinessError("Generation job not found")
        data = dict(row)
        if data["status"] == "success" or data["main_status"] == "success":
            data["images"] = self._load_job_images(data)
            data["result_storage"] = "temporary_url_metadata"
            data["recommended_stylists"] = self.recommend_stylists(
                tenant_id=data["tenant_id"],
                store_id=data["store_id"],
                direction=data["direction"],
                selected_style_id=data["selected_style_id"],
                selected_color_id=data["selected_color_id"],
            )
        return self._public_job_view(data)

    def save_partial_generation_images(self, job_no: str, images: list[dict]) -> None:
        ordered = sorted(
            images,
            key=lambda image: {"main": 0, "natural": 1, "advanced": 2}.get(image.get("slot"), 99),
        )
        slots = {image.get("slot") for image in ordered}
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE ai_generation_jobs
                SET main_status = ?,
                    recommend_1_status = ?,
                    recommend_2_status = ?,
                    images_json = ?
                WHERE job_no = ?
                """,
                (
                    "success" if "main" in slots else "pending",
                    "success" if "natural" in slots else "pending",
                    "success" if "advanced" in slots else "pending",
                    json.dumps(ordered, ensure_ascii=False),
                    job_no,
                ),
            )
        self._job_images[job_no] = ordered

    def _load_job_images(self, job: dict) -> list[dict]:
        cached = self._job_images.get(job["job_no"])
        if cached is not None:
            return cached
        if not job.get("images_json"):
            return []
        try:
            images = json.loads(job["images_json"])
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(images, list):
            return []
        self._job_images[job["job_no"]] = images
        return images

    def result_detail(self, *, tenant_id: int, store_id: int, user_id: int, job_no: str) -> dict:
        job = self.get_customer_job(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            job_no=job_no,
        )
        images = job.get("images", [])
        stylists = job.get("recommended_stylists", [])
        return {
            "job_no": job["job_no"],
            "status": job["status"],
            "direction": job["direction"],
            "selected_style_id": job["selected_style_id"],
            "selected_color_id": job["selected_color_id"],
            "carousel": {
                "mode": "swipe",
                "images": images,
            },
            "recommended_stylists": stylists[:3],
            "default_stylist_id": stylists[0]["staff_id"] if stylists else None,
            "save_hint": "长按保存或截图，图片仅临时展示",
            "result_tags": self._result_tags(job),
        }

    def _result_tags(self, job: dict) -> list[dict]:
        tags: list[dict] = []
        if job.get("selected_style_id"):
            style = self.store.row(
                "SELECT name, need_perm FROM hairstyles WHERE tenant_id = ? AND style_id = ?",
                (job["tenant_id"], job["selected_style_id"]),
            )
            if style is not None:
                tags.append({"type": "style", "label": style["name"]})
                tags.append({"type": "need_perm", "label": "需要烫发" if int(style["need_perm"]) else "无需烫发"})
        color = None
        if job.get("selected_color_id"):
            color = self.store.row(
                "SELECT name, need_bleach FROM hair_colors WHERE tenant_id = ? AND color_id = ?",
                (job["tenant_id"], job["selected_color_id"]),
            )
        if color is not None:
            tags.append({"type": "color", "label": color["name"]})
            tags.append({"type": "need_bleach", "label": "需要漂发" if int(color["need_bleach"]) else "无需漂发"})
        return tags

    def create_poc_evaluation(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        job_no: str | None,
        direction: str,
        test_case_no: str,
        input_photo_label: str | None,
        selected_style_id: str | None,
        selected_color_id: str | None,
        is_like_customer: bool,
        only_changed_hair: bool,
        face_changed: bool,
        generated_three_images: bool,
        hair_color_accurate: bool,
        hairstyle_acceptable: bool,
        can_show_customer: bool,
        generate_duration_seconds: int | None,
        internal_api_cost: float,
        notes: str | None = None,
    ) -> dict:
        if direction not in {"male", "female", "neutral"}:
            raise BusinessError("direction must be male, female or neutral")
        if not test_case_no.strip():
            raise BusinessError("test_case_no is required")
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO poc_evaluation_records
                (tenant_id, store_id, job_no, direction, test_case_no, input_photo_label,
                 selected_style_id, selected_color_id, is_like_customer, only_changed_hair,
                 face_changed, generated_three_images, hair_color_accurate,
                 hairstyle_acceptable, can_show_customer, generate_duration_seconds,
                 internal_api_cost, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    job_no,
                    direction,
                    test_case_no,
                    input_photo_label,
                    selected_style_id,
                    selected_color_id,
                    int(is_like_customer),
                    int(only_changed_hair),
                    int(face_changed),
                    int(generated_three_images),
                    int(hair_color_accurate),
                    int(hairstyle_acceptable),
                    int(can_show_customer),
                    generate_duration_seconds,
                    internal_api_cost,
                    notes,
                ),
            )
            record_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM poc_evaluation_records WHERE id = ?", (record_id,)))

    def poc_evaluation_summary(self, tenant_id: int) -> dict:
        row = self.store.row(
            """
            SELECT COUNT(*) AS total_cases,
                   SUM(CASE WHEN generated_three_images = 1 THEN 1 ELSE 0 END) AS three_image_success,
                   SUM(CASE WHEN is_like_customer = 1 THEN 1 ELSE 0 END) AS like_customer_count,
                   SUM(CASE WHEN only_changed_hair = 1 THEN 1 ELSE 0 END) AS only_hair_count,
                   SUM(CASE WHEN can_show_customer = 1 THEN 1 ELSE 0 END) AS showable_count,
                   AVG(generate_duration_seconds) AS avg_generate_duration_seconds,
                   AVG(internal_api_cost) AS avg_internal_api_cost
            FROM poc_evaluation_records
            WHERE tenant_id = ?
            """,
            (tenant_id,),
        )
        total = int(row["total_cases"] or 0)
        return {
            "tenant_id": tenant_id,
            "total_cases": total,
            "three_image_success_rate": self._rate(row["three_image_success"], total),
            "like_customer_rate": self._rate(row["like_customer_count"], total),
            "only_hair_change_rate": self._rate(row["only_hair_count"], total),
            "showable_rate": self._rate(row["showable_count"], total),
            "avg_generate_duration_seconds": float(row["avg_generate_duration_seconds"] or 0),
            "avg_internal_api_cost": float(row["avg_internal_api_cost"] or 0),
        }

    def _rate(self, value, total: int) -> float:
        return float(value or 0) / total if total else 0

    def _public_job_view(self, job: dict) -> dict:
        hidden_fields = {"internal_api_cost"}
        return {key: value for key, value in job.items() if key not in hidden_fields}

    def quota_today(self, tenant_id: int, store_id: int, user_id: int) -> dict:
        today = date.today().isoformat()
        row = self.store.row(
            """
            SELECT * FROM ai_user_daily_quota
            WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND quota_date = ?
            """,
            (tenant_id, store_id, user_id, today),
        )
        if row is None:
            with self.store.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO ai_user_daily_quota (tenant_id, store_id, user_id, quota_date)
                    VALUES (?, ?, ?, ?)
                    """,
                    (tenant_id, store_id, user_id, today),
                )
            row = self.store.row(
                """
                SELECT * FROM ai_user_daily_quota
                WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND quota_date = ?
                """,
                (tenant_id, store_id, user_id, today),
            )
        assert row is not None
        gift_remaining = self.store.row(
            """
            SELECT COUNT(*) AS cnt
            FROM ai_gift_records
            WHERE tenant_id = ? AND store_id = ? AND customer_id = ? AND status = 'unused'
            """,
            (tenant_id, store_id, user_id),
        )
        return dict(row) | {
            "free_remaining": max(0, int(row["free_limit"]) - int(row["free_used"])),
            "gift_remaining": int(gift_remaining["cnt"] or 0) if gift_remaining else 0,
            "in_store": self.has_active_store_visit(tenant_id, store_id, user_id),
        }

    def set_customer_daily_free_limit(self, tenant_id: int, store_id: int, user_id: int, free_limit: int) -> dict:
        if free_limit < 0 or free_limit > 999:
            raise BusinessError("Free limit must be between 0 and 999")
        self._assert_active_tenant_store(tenant_id, store_id)
        user = self.get_user(tenant_id, user_id)
        if user.get("role") != "customer":
            raise BusinessError("Customer not found")
        self.quota_today(tenant_id, store_id, user_id)
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE ai_user_daily_quota
                SET free_limit = ?, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND quota_date = ?
                """,
                (free_limit, tenant_id, store_id, user_id, date.today().isoformat()),
            )
        return self.quota_today(tenant_id, store_id, user_id)

    def confirm_store_visit(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        qr_scene: str,
        ttl_hours: int = 8,
    ) -> dict:
        if not qr_scene.strip():
            raise BusinessError("qr_scene is required")
        self._assert_active_tenant_store(tenant_id, store_id)
        self.get_user(tenant_id, user_id)
        expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
        expires_text = expires_at.strftime("%Y-%m-%d %H:%M:%S")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE store_visit_sessions
                SET status = 'expired'
                WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND status = 'active'
                """,
                (tenant_id, store_id, user_id),
            )
            cur = conn.execute(
                """
                INSERT INTO store_visit_sessions (tenant_id, store_id, user_id, qr_scene, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tenant_id, store_id, user_id, qr_scene, expires_text),
            )
            session_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM store_visit_sessions WHERE id = ?", (session_id,)))

    def has_active_store_visit(self, tenant_id: int, store_id: int, user_id: int) -> bool:
        row = self.store.row(
            """
            SELECT id FROM store_visit_sessions
            WHERE tenant_id = ? AND store_id = ? AND user_id = ?
              AND status = 'active' AND expires_at > CURRENT_TIMESTAMP
            ORDER BY id DESC LIMIT 1
            """,
            (tenant_id, store_id, user_id),
        )
        return row is not None

    def list_store_customers(
        self,
        *,
        tenant_id: int,
        store_id: int,
        status: str | None = None,
        keyword: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        self._assert_active_tenant_store(tenant_id, store_id)
        if limit <= 0:
            raise BusinessError("limit must be positive")
        limit = min(limit, 100)
        allowed_status = {"all", "in_store", "trialed", "booked", "gifted", "today_active"}
        status = status or "all"
        if status not in allowed_status:
            raise BusinessError("Invalid customer status")

        filters = [
            "u.tenant_id = ?",
            "u.role = 'customer'",
            "COALESCE(u.status, 'active') != 'deleted'",
            """
            (
              u.store_id = ?
              OR EXISTS (SELECT 1 FROM store_visit_sessions v WHERE v.tenant_id = u.tenant_id AND v.store_id = ? AND v.user_id = u.id)
              OR EXISTS (SELECT 1 FROM ai_generation_jobs j WHERE j.tenant_id = u.tenant_id AND j.store_id = ? AND j.user_id = u.id)
              OR EXISTS (SELECT 1 FROM orders o WHERE o.tenant_id = u.tenant_id AND o.store_id = ? AND o.user_id = u.id)
            )
            """,
        ]
        params: list[object] = [tenant_id, store_id, store_id, store_id, store_id]
        if keyword and keyword.strip():
            like = f"%{keyword.strip()}%"
            filters.append("(u.nickname LIKE ? OR u.phone LIKE ? OR CAST(u.id AS TEXT) LIKE ?)")
            params.extend([like, like, like])
        if status == "in_store":
            filters.append(
                """
                EXISTS (
                  SELECT 1 FROM store_visit_sessions v
                  WHERE v.tenant_id = u.tenant_id AND v.store_id = ? AND v.user_id = u.id
                    AND v.status = 'active' AND v.expires_at > CURRENT_TIMESTAMP
                )
                """
            )
            params.append(store_id)
        elif status == "trialed":
            filters.append("EXISTS (SELECT 1 FROM ai_generation_jobs j WHERE j.tenant_id = u.tenant_id AND j.store_id = ? AND j.user_id = u.id)")
            params.append(store_id)
        elif status == "booked":
            filters.append("EXISTS (SELECT 1 FROM orders o WHERE o.tenant_id = u.tenant_id AND o.store_id = ? AND o.user_id = u.id)")
            params.append(store_id)
        elif status == "gifted":
            filters.append("EXISTS (SELECT 1 FROM ai_gift_records g WHERE g.tenant_id = u.tenant_id AND g.store_id = ? AND g.customer_id = u.id AND g.status = 'unused')")
            params.append(store_id)
        elif status == "today_active":
            # 今日活跃：今天新注册、到店、下单或做过 AI 试发的顾客
            filters.append(
                """
                (
                  date(u.created_at) = date('now')
                  OR EXISTS (SELECT 1 FROM store_visit_sessions v WHERE v.tenant_id = u.tenant_id AND v.store_id = ? AND v.user_id = u.id AND date(v.created_at) = date('now'))
                  OR EXISTS (SELECT 1 FROM orders o WHERE o.tenant_id = u.tenant_id AND o.store_id = ? AND o.user_id = u.id AND date(o.created_at) = date('now'))
                  OR EXISTS (SELECT 1 FROM ai_generation_jobs j WHERE j.tenant_id = u.tenant_id AND j.store_id = ? AND j.user_id = u.id AND date(j.created_at) = date('now'))
                )
                """
            )
            params.extend([store_id, store_id, store_id])

        where = " AND ".join(filters)
        params.append(limit)
        rows = self.store.rows(
            f"""
            SELECT u.id AS user_id,
                   u.nickname,
                   u.phone,
                   u.created_at,
                   COALESCE(u.status, 'active') AS status,
                   (SELECT v.created_at FROM store_visit_sessions v
                    WHERE v.tenant_id = u.tenant_id AND v.store_id = ? AND v.user_id = u.id
                      AND v.status = 'active' AND v.expires_at > CURRENT_TIMESTAMP
                    ORDER BY v.id DESC LIMIT 1) AS latest_visit_at,
                   (SELECT COUNT(*) FROM ai_generation_jobs j
                    WHERE j.tenant_id = u.tenant_id AND j.store_id = ? AND j.user_id = u.id) AS ai_job_count,
                   (SELECT j.job_no FROM ai_generation_jobs j
                    WHERE j.tenant_id = u.tenant_id AND j.store_id = ? AND j.user_id = u.id
                    ORDER BY j.id DESC LIMIT 1) AS latest_job_no,
                   (SELECT o.created_at FROM orders o
                    WHERE o.tenant_id = u.tenant_id AND o.store_id = ? AND o.user_id = u.id
                    ORDER BY o.id DESC LIMIT 1) AS latest_order_at,
                   (SELECT o.status FROM orders o
                    WHERE o.tenant_id = u.tenant_id AND o.store_id = ? AND o.user_id = u.id
                    ORDER BY o.id DESC LIMIT 1) AS latest_order_status,
                   (SELECT COUNT(*) FROM ai_gift_records g
                    WHERE g.tenant_id = u.tenant_id AND g.store_id = ? AND g.customer_id = u.id AND g.status = 'unused') AS gift_remaining
            FROM users u
            WHERE {where}
            ORDER BY latest_visit_at IS NULL ASC, latest_visit_at DESC, latest_order_at DESC, u.id DESC
            LIMIT ?
            """,
            (store_id, store_id, store_id, store_id, store_id, store_id, *params),
        )
        customers: list[dict] = []
        for row in rows:
            item = dict(row)
            quota = self.quota_today(tenant_id, store_id, int(item["user_id"]))
            item["display_name"] = item.get("nickname") or (item.get("phone") or "微信顾客")
            item["masked_phone"] = self._mask_phone(item.get("phone"))
            item["in_store"] = bool(item.get("latest_visit_at"))
            item["free_remaining"] = quota["free_remaining"]
            item["is_disabled"] = item.get("status") == "disabled"
            customers.append(item)
        return customers

    def merchant_customer_detail(self, *, tenant_id: int, store_id: int, customer_id: int) -> dict:
        self._assert_active_tenant_store(tenant_id, store_id)
        customer = self.get_user(tenant_id, customer_id)
        if customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        quota = self.quota_today(tenant_id, store_id, customer_id)
        active_visit = self.store.row(
            """
            SELECT * FROM store_visit_sessions
            WHERE tenant_id = ? AND store_id = ? AND user_id = ?
              AND status = 'active' AND expires_at > CURRENT_TIMESTAMP
            ORDER BY id DESC LIMIT 1
            """,
            (tenant_id, store_id, customer_id),
        )
        recent_jobs = [
            dict(row)
            for row in self.store.rows(
                """
                SELECT j.job_no, j.direction, j.selected_style_id, j.selected_color_id,
                       j.status, j.main_status, j.error_code, j.error_message,
                       j.created_at, j.completed_at,
                       h.name AS selected_style_name,
                       c.name AS selected_color_name
                FROM ai_generation_jobs j
                LEFT JOIN hairstyles h
                  ON h.tenant_id = j.tenant_id AND h.style_id = j.selected_style_id
                LEFT JOIN hair_colors c
                  ON c.tenant_id = j.tenant_id AND c.color_id = j.selected_color_id
                WHERE j.tenant_id = ? AND j.store_id = ? AND j.user_id = ?
                ORDER BY j.id DESC LIMIT 5
                """,
                (tenant_id, store_id, customer_id),
            )
        ]
        direction_text = {"female": "女性", "male": "男性", "neutral": "中性"}
        job_status_text = {
            "queued": "排队中",
            "running": "生成中",
            "success": "已完成",
            "failed": "失败",
            "timeout": "超时",
            "cancelled": "已取消",
        }
        for item in recent_jobs:
            item["direction_text"] = direction_text.get(item.get("direction"), item.get("direction") or "未填")
            item["status_text"] = job_status_text.get(item.get("status"), item.get("status") or "未知")
            item["style_display_name"] = item.get("selected_style_name") or "未选择发型"
            item["color_display_name"] = item.get("selected_color_name") or "未选择发色"
            if item.get("status") in {"failed", "timeout"}:
                item["failure_text"] = item.get("error_message") or "生成失败，本次未扣次数"
        recent_orders = [
            dict(row)
            for row in self.store.rows(
                """
                SELECT o.*, sp.display_name AS stylist_name
                FROM orders o
                LEFT JOIN staff_profiles sp
                  ON sp.tenant_id = o.tenant_id AND sp.store_id = o.store_id AND sp.staff_id = o.stylist_id
                WHERE o.tenant_id = ? AND o.store_id = ? AND o.user_id = ?
                ORDER BY o.id DESC LIMIT 5
                """,
                (tenant_id, store_id, customer_id),
            )
        ]
        gift_records = [
            dict(row)
            for row in self.store.rows(
                """
                SELECT g.*, sp.display_name AS gifted_by_name
                FROM ai_gift_records g
                LEFT JOIN staff_profiles sp
                  ON sp.tenant_id = g.tenant_id AND sp.store_id = g.store_id AND sp.staff_id = g.gifted_by_user_id
                WHERE g.tenant_id = ? AND g.store_id = ? AND g.customer_id = ?
                ORDER BY g.id DESC LIMIT 10
                """,
                (tenant_id, store_id, customer_id),
            )
        ]
        return {
            "customer": dict(customer) | {
                "display_name": customer.get("nickname") or (customer.get("phone") or "微信顾客"),
                "masked_phone": self._mask_phone(customer.get("phone")),
                "is_disabled": customer.get("status") == "disabled",
            },
            "quota": quota,
            "active_visit": dict(active_visit) if active_visit else None,
            "recent_jobs": recent_jobs,
            "recent_orders": recent_orders,
            "gift_records": gift_records,
            "gift_remaining": sum(1 for item in gift_records if item.get("status") == "unused"),
            "membership": self.customer_membership(tenant_id, store_id, customer_id),
            "customer_packages": self.list_customer_packages(tenant_id, store_id, customer_id),
        }

    def customer_self_profile(self, *, tenant_id: int, store_id: int, customer_id: int) -> dict:
        customer = self.get_user(tenant_id, customer_id)
        if not customer or customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        return {
            "customer": dict(customer) | {
                "display_name": customer.get("nickname") or (customer.get("phone") or "微信顾客"),
                "masked_phone": self._mask_phone(customer.get("phone")),
            },
            "quota": self.quota_today(tenant_id, store_id, customer_id),
            "membership": self.customer_membership(tenant_id, store_id, customer_id),
            "packages": self.list_customer_packages(tenant_id, store_id, customer_id),
        }

    def update_customer_self_profile(
        self,
        *,
        tenant_id: int,
        store_id: int,
        customer_id: int,
        nickname: str | None = None,
        birthday: str | None = None,
        gender: str | None = None,
        profile_note: str | None = None,
    ) -> dict:
        customer = self.get_user(tenant_id, customer_id)
        if not customer or customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        clean_gender = (gender or "").strip()
        if clean_gender and clean_gender not in {"female", "male", "neutral", "unknown"}:
            raise BusinessError("gender must be female, male, neutral or unknown")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE users
                SET nickname = COALESCE(?, nickname),
                    birthday = ?,
                    gender = ?,
                    profile_note = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (
                    (nickname or "").strip() or None,
                    (birthday or "").strip() or None,
                    clean_gender or None,
                    (profile_note or "").strip() or None,
                    tenant_id,
                    customer_id,
                ),
            )
        return self.customer_self_profile(tenant_id=tenant_id, store_id=store_id, customer_id=customer_id)

    def customer_membership(self, tenant_id: int, store_id: int, customer_id: int) -> dict:
        customer = self.get_user(tenant_id, customer_id)
        if not customer or customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        if not self.check_plan_feature(tenant_id, "member_card"):
            return {
                "enabled": False,
                "id": None,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "customer_id": customer_id,
                "level_name": "未开通",
                "discount_rate": 1.0,
                "balance": 0,
                "total_recharge": 0,
                "total_consume": 0,
                "notes": "当前免费试用不包含顾客储值/会员卡，活动期间付费版限时赠送",
                "transactions": [],
            }
        row = self.store.row(
            """
            SELECT * FROM customer_memberships
            WHERE tenant_id = ? AND store_id = ? AND customer_id = ?
            """,
            (tenant_id, store_id, customer_id),
        )
        if row is None:
            membership = {
                "id": None,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "customer_id": customer_id,
                "level_name": "普通会员",
                "discount_rate": 1.0,
                "balance": 0,
                "total_recharge": 0,
                "total_consume": 0,
                "notes": "",
            }
            transactions: list[dict] = []
        else:
            membership = dict(row)
            transactions = [
                dict(item)
                for item in self.store.rows(
                    """
                    SELECT * FROM customer_membership_transactions
                    WHERE tenant_id = ? AND store_id = ? AND customer_id = ?
                    ORDER BY id DESC LIMIT 10
                    """,
                    (tenant_id, store_id, customer_id),
                )
            ]
        return membership | {"enabled": True, "transactions": transactions}

    def list_marketing_packages(
        self,
        tenant_id: int,
        store_id: int | None = None,
        include_disabled: bool = False,
    ) -> list[dict]:
        enabled_filter = "" if include_disabled else " AND p.is_enabled = 1"
        if store_id is None:
            params: tuple = (tenant_id,)
            store_filter = ""
        else:
            params = (tenant_id, store_id)
            store_filter = " AND (p.store_id = ? OR p.store_id IS NULL)"
        rows = self.store.rows(
            f"""
            SELECT p.*
            FROM marketing_packages p
            WHERE p.tenant_id = ?{store_filter}{enabled_filter}
            ORDER BY p.sort_order ASC, p.id ASC
            """,
            params,
        )
        return [self._decorate_marketing_package(dict(row)) for row in rows]

    def _decorate_marketing_package(self, package: dict) -> dict:
        items = [
            dict(row) | {
                "service_name": self._service_display_name(dict(row)),
                "remaining_count": int(row["included_count"] or 0),
            }
            for row in self.store.rows(
                """
                SELECT mpi.*, si.name, si.category, si.base_price
                FROM marketing_package_items mpi
                LEFT JOIN service_items si
                  ON si.tenant_id = mpi.tenant_id AND si.id = mpi.service_item_id
                WHERE mpi.tenant_id = ? AND mpi.package_id = ?
                ORDER BY mpi.id ASC
                """,
                (package["tenant_id"], package["id"]),
            )
        ]
        return package | {"items": items}

    def create_marketing_package(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        name: str,
        package_type: str,
        sale_price: float,
        validity_days: int,
        items: list[dict],
        sort_order: int = 100,
    ) -> dict:
        if not name.strip():
            raise BusinessError("套餐名称不能为空")
        if package_type not in {"times_card", "bundle"}:
            raise BusinessError("套餐类型只能是 times_card 或 bundle")
        if sale_price < 0 or validity_days <= 0:
            raise BusinessError("套餐价格和有效期不正确")
        clean_items = self._validate_package_items(tenant_id, store_id, items)
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO marketing_packages
                (tenant_id, store_id, name, package_type, sale_price, validity_days, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, store_id, name.strip(), package_type, sale_price, validity_days, sort_order),
            )
            package_id = cur.lastrowid
            for item in clean_items:
                conn.execute(
                    """
                    INSERT INTO marketing_package_items
                    (tenant_id, package_id, service_item_id, included_count)
                    VALUES (?, ?, ?, ?)
                    """,
                    (tenant_id, package_id, item["service_item_id"], item["included_count"]),
                )
        return self._decorate_marketing_package(dict(self.store.row("SELECT * FROM marketing_packages WHERE id = ?", (package_id,))))

    def update_marketing_package(
        self,
        *,
        tenant_id: int,
        package_id: int,
        store_id: int | None = None,
        name: str | None = None,
        package_type: str | None = None,
        sale_price: float | None = None,
        validity_days: int | None = None,
        is_enabled: bool | None = None,
        items: list[dict] | None = None,
        sort_order: int | None = None,
    ) -> dict:
        existing = self.store.row("SELECT * FROM marketing_packages WHERE id = ? AND tenant_id = ?", (package_id, tenant_id))
        if existing is None:
            raise BusinessError("套餐不存在")
        clean_items = self._validate_package_items(tenant_id, store_id or existing["store_id"], items) if items is not None else None
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE marketing_packages
                SET store_id = COALESCE(?, store_id),
                    name = COALESCE(?, name),
                    package_type = COALESCE(?, package_type),
                    sale_price = COALESCE(?, sale_price),
                    validity_days = COALESCE(?, validity_days),
                    is_enabled = COALESCE(?, is_enabled),
                    sort_order = COALESCE(?, sort_order),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND tenant_id = ?
                """,
                (
                    store_id,
                    name.strip() if name is not None else None,
                    package_type,
                    sale_price,
                    validity_days,
                    None if is_enabled is None else int(is_enabled),
                    sort_order,
                    package_id,
                    tenant_id,
                ),
            )
            if clean_items is not None:
                conn.execute("DELETE FROM marketing_package_items WHERE tenant_id = ? AND package_id = ?", (tenant_id, package_id))
                for item in clean_items:
                    conn.execute(
                        """
                        INSERT INTO marketing_package_items
                        (tenant_id, package_id, service_item_id, included_count)
                        VALUES (?, ?, ?, ?)
                        """,
                        (tenant_id, package_id, item["service_item_id"], item["included_count"]),
                    )
        return self._decorate_marketing_package(dict(self.store.row("SELECT * FROM marketing_packages WHERE id = ?", (package_id,))))

    def _validate_package_items(self, tenant_id: int, store_id: int | None, items: list[dict]) -> list[dict]:
        if not items:
            raise BusinessError("套餐至少包含一个服务项目")
        clean_items: list[dict] = []
        seen: set[int] = set()
        for item in items:
            service_item_id = int(item.get("service_item_id") or 0)
            included_count = int(item.get("included_count") or 0)
            if service_item_id <= 0 or included_count <= 0:
                raise BusinessError("套餐项目和次数必须有效")
            if service_item_id in seen:
                raise BusinessError("同一个服务项目不能重复添加")
            service_item = self.store.row(
                """
                SELECT * FROM service_items
                WHERE id = ? AND tenant_id = ? AND is_enabled = 1 AND (? IS NULL OR store_id = ? OR store_id IS NULL)
                """,
                (service_item_id, tenant_id, store_id, store_id),
            )
            if service_item is None:
                raise BusinessError("套餐包含的服务项目不存在或已停用")
            seen.add(service_item_id)
            clean_items.append({"service_item_id": service_item_id, "included_count": included_count})
        return clean_items

    def grant_customer_package(
        self,
        *,
        tenant_id: int,
        store_id: int,
        customer_id: int,
        package_id: int,
        paid_amount: float | None = None,
        notes: str | None = None,
    ) -> dict:
        customer = self.get_user(tenant_id, customer_id)
        if not customer or customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        package = self.store.row(
            """
            SELECT * FROM marketing_packages
            WHERE id = ? AND tenant_id = ? AND is_enabled = 1 AND (store_id = ? OR store_id IS NULL)
            """,
            (package_id, tenant_id, store_id),
        )
        if package is None:
            raise BusinessError("营销套餐不存在或已停用")
        items = self.store.rows(
            "SELECT * FROM marketing_package_items WHERE tenant_id = ? AND package_id = ? ORDER BY id ASC",
            (tenant_id, package_id),
        )
        if not items:
            raise BusinessError("套餐没有配置服务项目")
        paid = float(package["sale_price"] if paid_amount is None else paid_amount)
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO customer_packages
                (tenant_id, store_id, customer_id, package_id, paid_amount, expires_at, notes)
                VALUES (?, ?, ?, ?, ?, datetime('now', ?), ?)
                """,
                (tenant_id, store_id, customer_id, package_id, paid, f"+{int(package['validity_days'])} days", notes),
            )
            customer_package_id = cur.lastrowid
            for item in items:
                conn.execute(
                    """
                    INSERT INTO customer_package_items
                    (tenant_id, customer_package_id, service_item_id, total_count, used_count)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (tenant_id, customer_package_id, item["service_item_id"], item["included_count"]),
                )
        return self.customer_package_detail(tenant_id, store_id, customer_package_id)

    def list_customer_packages(
        self,
        tenant_id: int,
        store_id: int,
        customer_id: int,
        active_only: bool = False,
        service_item_id: int | None = None,
    ) -> list[dict]:
        active_filter = " AND cp.status = 'active' AND (cp.expires_at IS NULL OR cp.expires_at > CURRENT_TIMESTAMP)" if active_only else ""
        rows = self.store.rows(
            f"""
            SELECT cp.*, mp.name AS package_name, mp.package_type, mp.sale_price, mp.validity_days
            FROM customer_packages cp
            LEFT JOIN marketing_packages mp ON mp.tenant_id = cp.tenant_id AND mp.id = cp.package_id
            WHERE cp.tenant_id = ? AND cp.store_id = ? AND cp.customer_id = ?{active_filter}
            ORDER BY cp.id DESC
            """,
            (tenant_id, store_id, customer_id),
        )
        packages = [self._decorate_customer_package(dict(row)) for row in rows]
        if service_item_id is not None:
            packages = [
                package for package in packages
                if any(int(item["service_item_id"]) == int(service_item_id) and int(item["remaining_count"]) > 0 for item in package["items"])
            ]
        return packages

    def customer_package_detail(self, tenant_id: int, store_id: int, customer_package_id: int) -> dict:
        row = self.store.row(
            """
            SELECT cp.*, mp.name AS package_name, mp.package_type, mp.sale_price, mp.validity_days
            FROM customer_packages cp
            LEFT JOIN marketing_packages mp ON mp.tenant_id = cp.tenant_id AND mp.id = cp.package_id
            WHERE cp.tenant_id = ? AND cp.store_id = ? AND cp.id = ?
            """,
            (tenant_id, store_id, customer_package_id),
        )
        if row is None:
            raise BusinessError("顾客套餐不存在")
        return self._decorate_customer_package(dict(row))

    def _decorate_customer_package(self, package: dict) -> dict:
        items = []
        for row in self.store.rows(
            """
            SELECT cpi.*, si.name, si.category, si.base_price
            FROM customer_package_items cpi
            LEFT JOIN service_items si
              ON si.tenant_id = cpi.tenant_id AND si.id = cpi.service_item_id
            WHERE cpi.tenant_id = ? AND cpi.customer_package_id = ?
            ORDER BY cpi.id ASC
            """,
            (package["tenant_id"], package["id"]),
        ):
            item = dict(row)
            item["service_name"] = self._service_display_name(item)
            item["remaining_count"] = max(0, int(item["total_count"] or 0) - int(item["used_count"] or 0))
            items.append(item)
        package["items"] = items
        package["remaining_total"] = sum(int(item["remaining_count"]) for item in items)
        return package

    def redeem_customer_package(
        self,
        *,
        tenant_id: int,
        store_id: int,
        customer_id: int,
        customer_package_id: int,
        service_item_id: int,
        order_id: int | None = None,
        service_record_id: int | None = None,
        created_by_user_id: int | None = None,
        note: str | None = None,
    ) -> dict:
        package_item = self.store.row(
            """
            SELECT cpi.*, cp.status, cp.expires_at
            FROM customer_package_items cpi
            JOIN customer_packages cp
              ON cp.tenant_id = cpi.tenant_id AND cp.id = cpi.customer_package_id
            WHERE cpi.tenant_id = ? AND cp.store_id = ? AND cp.customer_id = ?
              AND cpi.customer_package_id = ? AND cpi.service_item_id = ?
            """,
            (tenant_id, store_id, customer_id, customer_package_id, service_item_id),
        )
        if package_item is None:
            raise BusinessError("该顾客套餐不包含当前服务项目")
        if package_item["status"] != "active":
            raise BusinessError("该顾客套餐不可用")
        if package_item["expires_at"] and str(package_item["expires_at"]) <= self._now_text():
            raise BusinessError("该顾客套餐已过期")
        remaining = int(package_item["total_count"] or 0) - int(package_item["used_count"] or 0)
        if remaining <= 0:
            raise BusinessError("该服务项目次数已用完")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE customer_package_items
                SET used_count = used_count + 1
                WHERE id = ?
                """,
                (package_item["id"],),
            )
            cur = conn.execute(
                """
                INSERT INTO customer_package_usages
                (tenant_id, store_id, customer_id, customer_package_id, service_item_id,
                 used_count, order_id, service_record_id, created_by_user_id, note)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    customer_id,
                    customer_package_id,
                    service_item_id,
                    order_id,
                    service_record_id,
                    created_by_user_id,
                    note,
                ),
            )
            usage_id = cur.lastrowid
        package = self.customer_package_detail(tenant_id, store_id, customer_package_id)
        if package["remaining_total"] <= 0:
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE customer_packages SET status = 'used_up' WHERE id = ? AND tenant_id = ?",
                    (customer_package_id, tenant_id),
                )
            package = self.customer_package_detail(tenant_id, store_id, customer_package_id)
        return {
            "usage": dict(self.store.row("SELECT * FROM customer_package_usages WHERE id = ?", (usage_id,))),
            "package": package,
        }

    def _now_text(self) -> str:
        return str(self.store.row("SELECT CURRENT_TIMESTAMP AS now")["now"])

    def update_customer_membership(
        self,
        *,
        tenant_id: int,
        store_id: int,
        customer_id: int,
        level_name: str,
        discount_rate: float,
        notes: str | None = None,
    ) -> dict:
        self.assert_plan_feature(tenant_id, "member_card", "当前免费试用不包含顾客储值/会员卡，活动期间付费版限时赠送")
        customer = self.get_user(tenant_id, customer_id)
        if not customer or customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        if not level_name.strip():
            raise BusinessError("会员等级不能为空")
        if discount_rate <= 0 or discount_rate > 1:
            raise BusinessError("折扣需在 0 到 1 之间，例如 0.9 表示 9 折")
        with self.store.transaction() as conn:
            existing = conn.execute(
                """
                SELECT id FROM customer_memberships
                WHERE tenant_id = ? AND store_id = ? AND customer_id = ?
                """,
                (tenant_id, store_id, customer_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO customer_memberships
                    (tenant_id, store_id, customer_id, level_name, discount_rate, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (tenant_id, store_id, customer_id, level_name.strip(), discount_rate, notes),
                )
            else:
                conn.execute(
                    """
                    UPDATE customer_memberships
                    SET level_name = ?, discount_rate = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ? AND store_id = ? AND customer_id = ?
                    """,
                    (level_name.strip(), discount_rate, notes, tenant_id, store_id, customer_id),
                )
        return self.customer_membership(tenant_id, store_id, customer_id)

    def add_customer_membership_transaction(
        self,
        *,
        tenant_id: int,
        store_id: int,
        customer_id: int,
        transaction_type: str,
        amount: float,
        note: str | None = None,
        created_by_user_id: int | None = None,
    ) -> dict:
        if transaction_type not in {"recharge", "consume", "adjust"}:
            raise BusinessError("流水类型只能是 recharge、consume 或 adjust")
        if amount <= 0:
            raise BusinessError("金额必须大于 0")
        current = self.customer_membership(tenant_id, store_id, customer_id)
        self.update_customer_membership(
            tenant_id=tenant_id,
            store_id=store_id,
            customer_id=customer_id,
            level_name=current["level_name"],
            discount_rate=float(current["discount_rate"] or 1),
            notes=current.get("notes"),
        )
        with self.store.transaction() as conn:
            membership = conn.execute(
                """
                SELECT * FROM customer_memberships
                WHERE tenant_id = ? AND store_id = ? AND customer_id = ?
                """,
                (tenant_id, store_id, customer_id),
            ).fetchone()
            if membership is None:
                raise BusinessError("Membership not found")
            current_balance = float(membership["balance"] or 0)
            if transaction_type == "recharge":
                balance_after = current_balance + amount
                total_recharge = float(membership["total_recharge"] or 0) + amount
                total_consume = float(membership["total_consume"] or 0)
            elif transaction_type == "consume":
                if current_balance < amount:
                    raise BusinessError("会员余额不足")
                balance_after = current_balance - amount
                total_recharge = float(membership["total_recharge"] or 0)
                total_consume = float(membership["total_consume"] or 0) + amount
            else:
                balance_after = amount
                total_recharge = float(membership["total_recharge"] or 0)
                total_consume = float(membership["total_consume"] or 0)
            conn.execute(
                """
                UPDATE customer_memberships
                SET balance = ?, total_recharge = ?, total_consume = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (balance_after, total_recharge, total_consume, membership["id"]),
            )
            cur = conn.execute(
                """
                INSERT INTO customer_membership_transactions
                (tenant_id, store_id, customer_id, membership_id, transaction_type, amount,
                 balance_after, note, created_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    customer_id,
                    membership["id"],
                    transaction_type,
                    amount,
                    balance_after,
                    note,
                    created_by_user_id,
                ),
            )
            tx_id = cur.lastrowid
        return {
            "membership": self.customer_membership(tenant_id, store_id, customer_id),
            "transaction": dict(self.store.row("SELECT * FROM customer_membership_transactions WHERE id = ?", (tx_id,))),
        }

    def update_customer_status(
        self,
        *,
        tenant_id: int,
        store_id: int,
        customer_id: int,
        status: str,
    ) -> dict:
        """停用（disabled）或恢复（active）顾客账号。"""
        allowed = {"active", "disabled"}
        if status not in allowed:
            raise BusinessError(f"status 只能是 {allowed}")
        self._assert_active_tenant_store(tenant_id, store_id)
        customer = self.get_user(tenant_id, customer_id)
        if not customer or customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        # 确认该顾客属于本门店（有任何交互记录）
        self.store.row(
            """
            SELECT 1 FROM users WHERE id = ? AND tenant_id = ?
            """,
            (customer_id, tenant_id),
        )
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE users SET status = ? WHERE id = ? AND tenant_id = ?",
                (status, customer_id, tenant_id),
            )
        return {"customer_id": customer_id, "status": status}

    def delete_customer(
        self,
        *,
        tenant_id: int,
        store_id: int,
        customer_id: int,
    ) -> dict:
        """软删除顾客（标记为 deleted，保留历史数据）。"""
        self._assert_active_tenant_store(tenant_id, store_id)
        customer = self.get_user(tenant_id, customer_id)
        if not customer or customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE users SET status = 'deleted' WHERE id = ? AND tenant_id = ?",
                (customer_id, tenant_id),
            )
        return {"customer_id": customer_id, "deleted": True}

    def _mask_phone(self, phone: str | None) -> str:
        if not phone:
            return ""
        clean = str(phone)
        if len(clean) < 7:
            return clean
        return f"{clean[:3]}****{clean[-4:]}"

    def create_order(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        stylist_id: int | None,
        direction: str | None,
        hairstyle_id: str | None,
        hair_color_id: str | None,
        ai_job_no: str | None,
        appointment_time: str | None = None,
        notes: str | None = None,
    ) -> dict:
        self._assert_active_tenant_store(tenant_id, store_id)
        ai_job_id = None
        is_ai_converted = 0
        if ai_job_no:
            job = self.store.row(
                "SELECT id, tenant_id, store_id, user_id FROM ai_generation_jobs WHERE job_no = ?",
                (ai_job_no,),
            )
            if job is None:
                raise BusinessError("Generation job not found")
            if job["tenant_id"] != tenant_id or job["store_id"] != store_id or job["user_id"] != user_id:
                raise BusinessError("Generation job does not belong to this customer/store")
            ai_job_id = job["id"]
            is_ai_converted = 1

        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO orders
                (tenant_id, store_id, user_id, stylist_id, direction, hairstyle_id, hair_color_id,
                 is_ai_converted, ai_job_id, appointment_time, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    store_id,
                    user_id,
                    stylist_id,
                    direction,
                    hairstyle_id,
                    hair_color_id,
                    is_ai_converted,
                    ai_job_id,
                    appointment_time,
                    notes,
                ),
            )
            order_id = cur.lastrowid
            if ai_job_id is not None:
                conn.execute(
                    """
                    UPDATE ai_gift_records
                    SET order_id = ?
                    WHERE tenant_id = ? AND store_id = ? AND customer_id = ? AND generation_job_id = ?
                    """,
                    (order_id, tenant_id, store_id, user_id, ai_job_id),
                )
            if hairstyle_id:
                self._insert_asset_event(
                    conn,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    user_id=user_id,
                    asset_type="hairstyle",
                    asset_id=hairstyle_id,
                    event_type="order",
                    generation_job_id=ai_job_id,
                    order_id=order_id,
                )
            if hair_color_id:
                self._insert_asset_event(
                    conn,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    user_id=user_id,
                    asset_type="hair_color",
                    asset_id=hair_color_id,
                    event_type="order",
                    generation_job_id=ai_job_id,
                    order_id=order_id,
                )
        order = dict(self.store.row("SELECT * FROM orders WHERE id = ?", (order_id,)))
        self.enqueue_sync_event(
            tenant_id=tenant_id,
            store_id=store_id,
            event_type="order",
            payload=order,
        )
        return order

    def get_order(self, *, tenant_id: int, store_id: int, order_id: int) -> dict:
        row = self.store.row(
            """
            SELECT o.*,
                   u.nickname AS customer_name,
                   u.phone AS customer_phone,
                   sp.display_name AS stylist_name,
                   h.name AS hairstyle_name,
                   c.name AS hair_color_name,
                   si.name AS service_item_name,
                   s.name AS store_name
            FROM orders o
            LEFT JOIN users u ON u.id = o.user_id AND u.tenant_id = o.tenant_id
            LEFT JOIN staff_profiles sp
              ON sp.tenant_id = o.tenant_id
             AND sp.store_id = o.store_id
             AND sp.staff_id = o.stylist_id
            LEFT JOIN hairstyles h
              ON h.tenant_id = o.tenant_id
             AND h.style_id = o.hairstyle_id
            LEFT JOIN hair_colors c
              ON c.tenant_id = o.tenant_id
             AND c.color_id = o.hair_color_id
            LEFT JOIN service_items si
              ON si.tenant_id = o.tenant_id
             AND si.id = o.service_item_id
            LEFT JOIN stores s
              ON s.tenant_id = o.tenant_id
             AND s.id = o.store_id
            WHERE o.id = ? AND o.tenant_id = ? AND o.store_id = ?
            """,
            (order_id, tenant_id, store_id),
        )
        if row is None:
            raise BusinessError("Order not found")
        return dict(row)

    def list_customer_orders(
        self,
        *,
        tenant_id: int,
        user_id: int,
        store_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if status is not None and status not in {"pending", "confirmed", "arrived", "serving", "completed", "cancelled"}:
            raise BusinessError("Invalid order status")
        if limit <= 0:
            raise BusinessError("limit must be positive")
        limit = min(limit, 100)

        filters = ["o.tenant_id = ?", "o.user_id = ?"]
        params: list[object] = [tenant_id, user_id]
        if store_id is not None:
            filters.append("o.store_id = ?")
            params.append(store_id)
        if status is not None:
            filters.append("o.status = ?")
            params.append(status)
        params.append(limit)
        where = " AND ".join(filters)
        rows = self.store.rows(
            f"""
            SELECT o.*,
                   s.name AS store_name,
                   sp.display_name AS stylist_name,
                   h.name AS hairstyle_name,
                   c.name AS hair_color_name,
                   si.name AS service_item_name
            FROM orders o
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            LEFT JOIN staff_profiles sp
              ON sp.tenant_id = o.tenant_id
             AND sp.store_id = o.store_id
             AND sp.staff_id = o.stylist_id
            LEFT JOIN hairstyles h
              ON h.tenant_id = o.tenant_id
             AND h.style_id = o.hairstyle_id
            LEFT JOIN hair_colors c
              ON c.tenant_id = o.tenant_id
             AND c.color_id = o.hair_color_id
            LEFT JOIN service_items si
              ON si.tenant_id = o.tenant_id
             AND si.id = o.service_item_id
            WHERE {where}
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [dict(row) for row in rows]

    def list_merchant_orders(
        self,
        *,
        tenant_id: int,
        store_id: int,
        status: str | None = None,
        stylist_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if status is not None and status not in {"pending", "confirmed", "arrived", "serving", "completed", "cancelled"}:
            raise BusinessError("Invalid order status")
        if limit <= 0:
            raise BusinessError("limit must be positive")
        limit = min(limit, 100)

        filters = ["o.tenant_id = ?", "o.store_id = ?"]
        params: list[object] = [tenant_id, store_id]
        if status is not None:
            filters.append("o.status = ?")
            params.append(status)
        if stylist_id is not None:
            filters.append("o.stylist_id = ?")
            params.append(stylist_id)
        if date_from:
            filters.append("date(o.created_at) >= date(?)")
            params.append(date_from)
        if date_to:
            filters.append("date(o.created_at) <= date(?)")
            params.append(date_to)
        params.append(limit)
        where = " AND ".join(filters)
        rows = self.store.rows(
            f"""
            SELECT o.*,
                   u.nickname AS customer_name,
                   u.phone AS customer_phone,
                   sp.display_name AS stylist_name,
                   h.name AS hairstyle_name,
                   c.name AS hair_color_name,
                   si.name AS service_item_name
            FROM orders o
            JOIN users u ON u.id = o.user_id AND u.tenant_id = o.tenant_id
            LEFT JOIN staff_profiles sp
              ON sp.tenant_id = o.tenant_id
             AND sp.store_id = o.store_id
             AND sp.staff_id = o.stylist_id
            LEFT JOIN hairstyles h
              ON h.tenant_id = o.tenant_id
             AND h.style_id = o.hairstyle_id
            LEFT JOIN hair_colors c
              ON c.tenant_id = o.tenant_id
             AND c.color_id = o.hair_color_id
            LEFT JOIN service_items si
              ON si.tenant_id = o.tenant_id
             AND si.id = o.service_item_id
            WHERE {where}
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [dict(row) for row in rows]

    def complete_order(
        self,
        *,
        tenant_id: int,
        store_id: int,
        order_id: int,
        stylist_id: int,
        service_item_id: int,
        actual_amount: float,
        payment_method: str = "cash",
        customer_package_id: int | None = None,
    ) -> dict:
        if actual_amount < 0:
            raise BusinessError("actual_amount must be non-negative")
        if payment_method not in {"cash", "membership", "package"}:
            raise BusinessError("payment_method must be cash, membership or package")
        order = self.store.row(
            "SELECT * FROM orders WHERE id = ? AND tenant_id = ? AND store_id = ?",
            (order_id, tenant_id, store_id),
        )
        if order is None:
            raise BusinessError("Order not found")
        service_item = self.store.row(
            """
            SELECT * FROM service_items
            WHERE id = ? AND tenant_id = ? AND is_enabled = 1 AND (store_id = ? OR store_id IS NULL)
            """,
            (service_item_id, tenant_id, store_id),
        )
        if service_item is None:
            raise BusinessError("Service item not found or disabled")
        customer_id = int(order["user_id"] or 0)
        if payment_method in {"membership", "package"}:
            if customer_id <= 0:
                raise BusinessError("当前订单没有绑定顾客，不能使用会员卡或套餐")
            customer = self.get_user(tenant_id, customer_id)
            if not customer or customer.get("role") != "customer":
                raise BusinessError("Customer not found")
        if payment_method == "membership":
            membership = self.customer_membership(tenant_id, store_id, customer_id)
            if float(membership.get("balance") or 0) < float(actual_amount):
                raise BusinessError("会员余额不足")
        if payment_method == "package":
            if customer_package_id is None:
                raise BusinessError("请选择要核销的顾客套餐")
            packages = self.list_customer_packages(
                tenant_id,
                store_id,
                customer_id,
                active_only=True,
                service_item_id=service_item_id,
            )
            if not any(int(package["id"]) == int(customer_package_id) for package in packages):
                raise BusinessError("该顾客没有可核销的当前服务套餐")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE orders SET status = 'completed', stylist_id = ? WHERE id = ?",
                (stylist_id, order_id),
            )
            cur = conn.execute(
                """
                INSERT INTO service_records
                (tenant_id, store_id, order_id, stylist_id, service_item_id, actual_amount,
                 is_ai_converted, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    tenant_id,
                    store_id,
                    order_id,
                    stylist_id,
                    service_item_id,
                    actual_amount,
                    order["is_ai_converted"],
                ),
            )
            record_id = cur.lastrowid
            conn.execute(
                """
                UPDATE ai_gift_records
                SET revenue_amount = ?
                WHERE tenant_id = ? AND store_id = ? AND order_id = ?
                """,
                (actual_amount, tenant_id, store_id, order_id),
            )
        record = dict(self.store.row("SELECT * FROM service_records WHERE id = ?", (record_id,)))
        membership_transaction = None
        package_usage = None
        if payment_method == "membership":
            membership_transaction = self.add_customer_membership_transaction(
                tenant_id=tenant_id,
                store_id=store_id,
                customer_id=customer_id,
                transaction_type="consume",
                amount=actual_amount,
                note=f"订单 #{order_id} {self._service_display_name(dict(service_item))} 消费扣款",
                created_by_user_id=stylist_id,
            )
        if payment_method == "package" and customer_package_id is not None:
            package_usage = self.redeem_customer_package(
                tenant_id=tenant_id,
                store_id=store_id,
                customer_id=customer_id,
                customer_package_id=customer_package_id,
                service_item_id=service_item_id,
                order_id=order_id,
                service_record_id=record_id,
                created_by_user_id=stylist_id,
                note=f"订单 #{order_id} 套餐核销",
            )
        self.enqueue_sync_event(
            tenant_id=tenant_id,
            store_id=store_id,
            event_type="service_record",
            payload={
                **record,
                "payment_method": payment_method,
                "membership_transaction": membership_transaction,
                "package_usage": package_usage,
            },
        )
        return record | {
            "payment_method": payment_method,
            "membership_transaction": membership_transaction,
            "package_usage": package_usage,
        }

    def create_manual_service_record(
        self,
        *,
        tenant_id: int,
        store_id: int,
        stylist_id: int,
        service_item_id: int,
        actual_amount: float,
        customer_id: int | None = None,
        customer_package_id: int | None = None,
        payment_method: str = "cash",
        source: str = "walk_in",
        service_date: str | None = None,
        notes: str | None = None,
    ) -> dict:
        if actual_amount < 0:
            raise BusinessError("actual_amount must be non-negative")
        if payment_method not in {"cash", "membership", "package"}:
            raise BusinessError("payment_method must be cash, membership or package")
        self._assert_store_staff(tenant_id, store_id, stylist_id)
        service_item = self.store.row(
            """
            SELECT * FROM service_items
            WHERE id = ? AND tenant_id = ? AND is_enabled = 1 AND (store_id = ? OR store_id IS NULL)
            """,
            (service_item_id, tenant_id, store_id),
        )
        if service_item is None:
            raise BusinessError("Service item not found or disabled")
        if payment_method == "package" and customer_package_id is None:
            raise BusinessError("请选择要核销的顾客套餐")
        if payment_method in {"membership", "package"} and not customer_id:
            raise BusinessError("会员卡扣款或套餐核销需要填写顾客ID")
        if customer_id:
            customer = self.get_user(tenant_id, customer_id)
            if not customer or customer.get("role") != "customer":
                raise BusinessError("Customer not found")
        if payment_method == "membership":
            membership = self.customer_membership(tenant_id, store_id, int(customer_id or 0))
            if float(membership.get("balance") or 0) < float(actual_amount):
                raise BusinessError("会员余额不足")
        if payment_method == "package":
            packages = self.list_customer_packages(
                tenant_id,
                store_id,
                int(customer_id or 0),
                active_only=True,
                service_item_id=service_item_id,
            )
            if not any(int(package["id"]) == int(customer_package_id) for package in packages):
                raise BusinessError("该顾客没有可核销的当前服务套餐")
        completed_at = self._manual_service_completed_at(service_date)
        clean_source = source if source in {"walk_in", "old_customer", "phone", "other"} else "walk_in"
        order_notes = notes or f"线下补录服务：{clean_source}"
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO orders
                (tenant_id, store_id, user_id, stylist_id, service_item_id, status,
                 is_ai_converted, notes, created_at)
                VALUES (?, ?, ?, ?, ?, 'completed', 0, ?, ?)
                """,
                (tenant_id, store_id, customer_id or 0, stylist_id, service_item_id, order_notes, completed_at),
            )
            order_id = cur.lastrowid
            cur = conn.execute(
                """
                INSERT INTO service_records
                (tenant_id, store_id, order_id, stylist_id, service_item_id, actual_amount,
                 is_ai_converted, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (tenant_id, store_id, order_id, stylist_id, service_item_id, actual_amount, completed_at),
            )
            record_id = cur.lastrowid
        record = dict(self.store.row("SELECT * FROM service_records WHERE id = ?", (record_id,)))
        membership_transaction = None
        package_usage = None
        if payment_method == "membership" and customer_id:
            membership_transaction = self.add_customer_membership_transaction(
                tenant_id=tenant_id,
                store_id=store_id,
                customer_id=customer_id,
                transaction_type="consume",
                amount=actual_amount,
                note=notes or f"补录服务 {self._service_display_name(dict(service_item))} 消费扣款",
                created_by_user_id=stylist_id,
            )
        if payment_method == "package" and customer_package_id is not None and customer_id:
            package_usage = self.redeem_customer_package(
                tenant_id=tenant_id,
                store_id=store_id,
                customer_id=customer_id,
                customer_package_id=customer_package_id,
                service_item_id=service_item_id,
                order_id=order_id,
                service_record_id=record_id,
                created_by_user_id=stylist_id,
                note=notes or "补录服务核销",
            )
        self.enqueue_sync_event(
            tenant_id=tenant_id,
            store_id=store_id,
            event_type="manual_service_record",
            payload={
                **record,
                "source": clean_source,
                "notes": order_notes,
                "payment_method": payment_method,
                "membership_transaction": membership_transaction,
                "package_usage": package_usage,
            },
        )
        return record | {
            "payment_method": payment_method,
            "membership_transaction": membership_transaction,
            "package_usage": package_usage,
        }

    def _manual_service_completed_at(self, service_date: str | None) -> str:
        if not service_date:
            return datetime.now().replace(microsecond=0).isoformat(sep=" ")
        try:
            parsed = datetime.strptime(service_date, "%Y-%m-%d")
        except ValueError as exc:
            raise BusinessError("service_date must be YYYY-MM-DD") from exc
        return parsed.replace(hour=12, minute=0, second=0).isoformat(sep=" ")

    def update_order_status(
        self,
        *,
        tenant_id: int,
        store_id: int,
        order_id: int,
        status: str,
        stylist_id: int | None = None,
    ) -> dict:
        allowed = {
            "pending": {"confirmed", "cancelled"},
            "confirmed": {"arrived", "cancelled"},
            "arrived": {"serving", "cancelled"},
            "serving": {"cancelled"},
        }
        if status == "completed":
            raise BusinessError("Use complete_order to complete service and record revenue")
        order = self.store.row(
            "SELECT * FROM orders WHERE id = ? AND tenant_id = ? AND store_id = ?",
            (order_id, tenant_id, store_id),
        )
        if order is None:
            raise BusinessError("Order not found")
        current_status = order["status"]
        if current_status in {"completed", "cancelled"}:
            raise BusinessError("Terminal order cannot be changed")
        if status not in allowed.get(current_status, set()):
            raise BusinessError(f"Invalid order status transition: {current_status} -> {status}")
        assigned_stylist_id = stylist_id if stylist_id is not None else order["stylist_id"]
        if status == "serving" and assigned_stylist_id is None:
            raise BusinessError("Serving order requires an assigned stylist")
        if stylist_id is not None:
            self._assert_store_staff(tenant_id, store_id, stylist_id)
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = ?, stylist_id = COALESCE(?, stylist_id)
                WHERE id = ? AND tenant_id = ? AND store_id = ?
                """,
                (status, stylist_id, order_id, tenant_id, store_id),
            )
        return self.get_order(tenant_id=tenant_id, store_id=store_id, order_id=order_id)

    def assign_order_stylist(
        self,
        *,
        tenant_id: int,
        store_id: int,
        order_id: int,
        stylist_id: int,
    ) -> dict:
        self._assert_store_staff(tenant_id, store_id, stylist_id)
        order = self.store.row(
            "SELECT * FROM orders WHERE id = ? AND tenant_id = ? AND store_id = ?",
            (order_id, tenant_id, store_id),
        )
        if order is None:
            raise BusinessError("Order not found")
        if order["status"] in {"completed", "cancelled"}:
            raise BusinessError("Terminal order cannot be reassigned")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE orders SET stylist_id = ? WHERE id = ? AND tenant_id = ? AND store_id = ?",
                (stylist_id, order_id, tenant_id, store_id),
            )
        return self.get_order(tenant_id=tenant_id, store_id=store_id, order_id=order_id)

    def _assert_store_staff(self, tenant_id: int, store_id: int, staff_id: int) -> None:
        row = self.store.row(
            """
            SELECT sp.staff_id
            FROM staff_profiles sp
            JOIN users u ON u.id = sp.staff_id AND u.tenant_id = sp.tenant_id
            WHERE sp.tenant_id = ? AND sp.store_id = ? AND sp.staff_id = ?
              AND sp.is_enabled = 1 AND u.role IN ('staff', 'manager', 'boss')
            """,
            (tenant_id, store_id, staff_id),
        )
        if row is None:
            raise BusinessError("Stylist not found in this store")

    def _assert_active_tenant_store(self, tenant_id: int, store_id: int) -> None:
        row = self.store.row(
            """
            SELECT t.id AS tenant_id, s.id AS store_id
            FROM tenants t
            JOIN stores s ON s.tenant_id = t.id
            WHERE t.id = ? AND s.id = ? AND t.status = 'active' AND s.status = 'active'
            """,
            (tenant_id, store_id),
        )
        if row is None:
            raise BusinessError("Tenant or store is not active")

    def _assert_privacy_consent(self, tenant_id: int, user_id: int) -> None:
        status = self.privacy_consent_status(
            tenant_id=tenant_id,
            user_id=user_id,
            consent_scope="photo_ai_generation",
            consent_version="v1",
        )
        if not status["accepted"]:
            raise BusinessError("Photo AI generation privacy consent is required")

    def grant_ai_gift(self, tenant_id: int, store_id: int, customer_id: int, staff_id: int, count: int = 1) -> dict:
        if count <= 0 or count > 50:
            raise BusinessError("Gift count must be between 1 and 50")
        self._assert_active_tenant_store(tenant_id, store_id)
        customer = self.get_user(tenant_id, customer_id)
        if customer.get("role") != "customer":
            raise BusinessError("Customer not found")
        quota = self._staff_quota_today(tenant_id, store_id, staff_id)
        available = int(quota["daily_limit"]) + int(quota["extra_granted"]) - int(quota["used_count"])
        if available < count:
            raise BusinessError("Staff gift quota is used up")
        gift_ids: list[int] = []
        with self.store.transaction() as conn:
            for _ in range(count):
                cur = conn.execute(
                    """
                    INSERT INTO ai_gift_records (tenant_id, store_id, customer_id, gifted_by_user_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (tenant_id, store_id, customer_id, staff_id),
                )
                gift_ids.append(cur.lastrowid)
            conn.execute(
                """
                UPDATE staff_gift_quotas
                SET used_count = used_count + ?, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ? AND store_id = ? AND staff_id = ? AND quota_date = ?
                """,
                (count, tenant_id, store_id, staff_id, date.today().isoformat()),
            )
        gift = dict(self.store.row("SELECT * FROM ai_gift_records WHERE id = ?", (gift_ids[-1],)))
        gift["count"] = count
        gift["gift_ids"] = gift_ids
        self.enqueue_sync_event(
            tenant_id=tenant_id,
            store_id=store_id,
            event_type="ai_gift_record",
            payload=gift,
        )
        return gift

    def add_staff_gift_quota(self, tenant_id: int, store_id: int, staff_id: int, extra_count: int) -> dict:
        if extra_count <= 0:
            raise BusinessError("extra_count must be positive")
        self._staff_quota_today(tenant_id, store_id, staff_id)
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE staff_gift_quotas
                SET extra_granted = extra_granted + ?, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ? AND store_id = ? AND staff_id = ? AND quota_date = ?
                """,
                (extra_count, tenant_id, store_id, staff_id, date.today().isoformat()),
            )
        return self._staff_quota_today(tenant_id, store_id, staff_id)

    def list_tenants(self) -> list[dict]:
        return [
            dict(row)
            for row in self.store.rows(
                """
                SELECT id, tenant_code, name, logo_url, package_plan,
                       subscription_plan, subscription_expires_at,
                       COALESCE(monthly_llm_cost_fen, 0) AS monthly_llm_cost_fen,
                       notes,
                       status, created_at
                FROM tenants
                ORDER BY id ASC
                """
            )
        ]

    def platform_tenant_dashboard(self) -> list[dict]:
        tenants = self.list_tenants()
        dashboard: list[dict] = []
        for tenant in tenants:
            tenant_id = tenant["id"]
            stores = self.store.row(
                """
                SELECT COUNT(*) AS total_stores,
                       SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_stores,
                       SUM(daily_ai_limit) AS total_daily_ai_limit
                FROM stores
                WHERE tenant_id = ?
                """,
                (tenant_id,),
            )
            jobs = self.store.row(
                """
                SELECT COUNT(*) AS total_ai_jobs,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_ai_jobs,
                       SUM(CASE WHEN status IN ('failed', 'timeout') THEN 1 ELSE 0 END) AS failed_ai_jobs,
                       AVG(queue_wait_seconds) AS avg_queue_wait_seconds,
                       AVG(generate_duration_seconds) AS avg_generate_duration_seconds,
                       SUM(internal_api_cost) AS internal_api_cost
                FROM ai_generation_jobs
                WHERE tenant_id = ?
                """,
                (tenant_id,),
            )
            dashboard.append(
                tenant
                | {
                    "stores": {
                        "total": int(stores["total_stores"] or 0),
                        "active": int(stores["active_stores"] or 0),
                        "total_daily_ai_limit": int(stores["total_daily_ai_limit"] or 0),
                    },
                    "ai": {
                        "balance": self.account_balance(tenant_id),
                        "total_jobs": int(jobs["total_ai_jobs"] or 0),
                        "success_jobs": int(jobs["success_ai_jobs"] or 0),
                        "failed_jobs": int(jobs["failed_ai_jobs"] or 0),
                        "avg_queue_wait_seconds": float(jobs["avg_queue_wait_seconds"] or 0),
                        "avg_generate_duration_seconds": float(jobs["avg_generate_duration_seconds"] or 0),
                    },
                    "finance": {
                        "internal_api_cost": float(jobs["internal_api_cost"] or 0),
                    },
                }
            )
        return dashboard

    def create_tenant(
        self,
        *,
        tenant_code: str,
        name: str,
        package_plan: str | None = None,
        initial_ai_count: int = 0,
    ) -> dict:
        if not tenant_code.strip() or not name.strip():
            raise BusinessError("tenant_code and name are required")
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO tenants (tenant_code, name, package_plan)
                VALUES (?, ?, ?)
                """,
                (tenant_code, name, package_plan),
            )
            tenant_id = cur.lastrowid
            conn.execute(
                """
                INSERT INTO tenant_ai_accounts
                (tenant_id, total_purchased, total_used, total_gifted_adjustment)
                VALUES (?, ?, 0, 0)
                """,
                (tenant_id, initial_ai_count),
            )
        return dict(self.store.row("SELECT * FROM tenants WHERE id = ?", (tenant_id,)))

    def create_tenant_onboarding(
        self,
        *,
        tenant_code: str,
        name: str,
        package_plan: str | None = "trial",
        initial_ai_count: int = 0,
        notes: str | None = None,
        store_code: str,
        store_name: str,
        daily_ai_limit: int = 300,
        boss_name: str | None = None,
        boss_phone: str | None = None,
        boss_openid: str | None = None,
        boss_is_manager: bool = True,
        manager_name: str | None = None,
        manager_phone: str | None = None,
        manager_openid: str | None = None,
    ) -> dict:
        clean_tenant_code = tenant_code.strip()
        clean_name = name.strip()
        clean_store_code = store_code.strip()
        clean_store_name = store_name.strip()
        if not clean_tenant_code or not clean_name:
            raise BusinessError("tenant_code and name are required")
        if not clean_store_code or not clean_store_name:
            raise BusinessError("store_code and store_name are required")
        if initial_ai_count < 0:
            raise BusinessError("initial_ai_count cannot be negative")
        if daily_ai_limit < 0:
            raise BusinessError("daily_ai_limit cannot be negative")
        clean_plan = package_plan or "trial"
        clean_boss_name = (boss_name or f"{clean_name} 老板").strip()
        clean_manager_name = (manager_name or f"{clean_store_name} 店长").strip()
        clean_boss_openid = (boss_openid or f"{clean_tenant_code}_boss").strip()
        clean_manager_openid = (manager_openid or f"{clean_tenant_code}_{clean_store_code}_manager").strip()
        create_separate_manager = not boss_is_manager

        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO tenants (tenant_code, name, package_plan)
                VALUES (?, ?, ?)
                """,
                (clean_tenant_code, clean_name, clean_plan),
            )
            tenant_id = cur.lastrowid
            try:
                conn.execute(
                    """
                    UPDATE tenants
                    SET subscription_plan = ?, notes = ?
                    WHERE id = ?
                    """,
                    (clean_plan, notes, tenant_id),
                )
            except Exception:
                pass
            conn.execute(
                """
                INSERT INTO tenant_ai_accounts
                (tenant_id, total_purchased, total_used, total_gifted_adjustment)
                VALUES (?, ?, 0, 0)
                """,
                (tenant_id, initial_ai_count),
            )
            store_cur = conn.execute(
                """
                INSERT INTO stores (tenant_id, store_code, name, daily_ai_limit)
                VALUES (?, ?, ?, ?)
                """,
                (tenant_id, clean_store_code, clean_store_name, daily_ai_limit),
            )
            store_id = store_cur.lastrowid
            boss_cur = conn.execute(
                """
                INSERT INTO users (tenant_id, store_id, openid, phone, nickname, role)
                VALUES (?, ?, ?, ?, ?, 'boss')
                """,
                (tenant_id, store_id if boss_is_manager else None, clean_boss_openid, boss_phone, clean_boss_name),
            )
            boss_id = boss_cur.lastrowid
            manager_id = boss_id
            manager_display_name = clean_boss_name
            manager_role_label = "老板兼店长"
            if create_separate_manager:
                manager_cur = conn.execute(
                    """
                    INSERT INTO users (tenant_id, store_id, openid, phone, nickname, role)
                    VALUES (?, ?, ?, ?, ?, 'manager')
                    """,
                    (tenant_id, store_id, clean_manager_openid, manager_phone, clean_manager_name),
                )
                manager_id = manager_cur.lastrowid
                manager_display_name = clean_manager_name
                manager_role_label = "店长"
            conn.execute(
                """
                INSERT INTO staff_profiles
                (tenant_id, store_id, staff_id, display_name, title, directions,
                 skill_tags, availability_status, is_enabled, is_recommended, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'available', 1, 1, 10)
                """,
                (
                    tenant_id,
                    store_id,
                    manager_id,
                    manager_display_name,
                    manager_role_label,
                    json.dumps(["female", "male", "neutral"], ensure_ascii=False),
                    json.dumps(["剪发", "染发", "烫发", "造型"], ensure_ascii=False),
                ),
            )

        return {
            "tenant": dict(self.store.row("SELECT * FROM tenants WHERE id = ?", (tenant_id,))),
            "store": dict(self.store.row("SELECT * FROM stores WHERE id = ?", (store_id,))),
            "boss": self.get_user(tenant_id, boss_id),
            "manager": self.get_user(tenant_id, manager_id),
            "boss_is_manager": boss_is_manager,
            "ai_account": dict(self.store.row("SELECT * FROM tenant_ai_accounts WHERE tenant_id = ?", (tenant_id,))),
        }

    def update_tenant(
        self,
        *,
        tenant_id: int,
        name: str | None = None,
        logo_url: str | None = None,
        package_plan: str | None = None,
        status: str | None = None,
        notes: str | None = None,
    ) -> dict:
        existing = self.store.row("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        if existing is None:
            raise BusinessError("Tenant not found")
        if status is not None and status not in {"active", "paused", "expired"}:
            raise BusinessError("status must be active, paused or expired")
        if package_plan:
            plan = self.store.row("SELECT id FROM package_plans WHERE plan_code = ?", (package_plan,))
            if plan is None:
                raise BusinessError("Package plan not found")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE tenants
                SET name = COALESCE(?, name),
                    logo_url = COALESCE(?, logo_url),
                    package_plan = COALESCE(?, package_plan),
                    status = COALESCE(?, status),
                    notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (name, logo_url, package_plan, status, notes, tenant_id),
            )
        return dict(self.store.row("SELECT * FROM tenants WHERE id = ?", (tenant_id,)))

    # ── 订阅计划管理 ──────────────────────────────────────────────

    def get_tenant_subscription(self, tenant_id: int) -> dict:
        """返回租户当前订阅信息 + 计划功能配置 + 本月用量。"""
        row = self.store.row("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        if row is None:
            raise BusinessError("Tenant not found")
        tenant = dict(row)
        plan_key = tenant.get("subscription_plan") or "trial"
        # 月度用量自动重置判断
        reset_at_str = tenant.get("monthly_ai_reset_at") or ""
        try:
            reset_at = datetime.fromisoformat(reset_at_str[:10])  # 取 yyyy-mm-dd
            if reset_at.month != datetime.utcnow().month or reset_at.year != datetime.utcnow().year:
                self._reset_monthly_ai_usage(tenant_id)
                tenant["monthly_ai_used"] = 0
        except (ValueError, TypeError):
            pass

        plan = get_plan(plan_key)
        used = int(tenant.get("monthly_ai_used") or 0)
        quota = plan["monthly_ai_quota"]
        expires_at = tenant.get("subscription_expires_at")
        is_expired = False
        if expires_at:
            try:
                is_expired = datetime.fromisoformat(expires_at) < datetime.utcnow()
            except ValueError:
                pass
        return {
            "tenant_id": tenant_id,
            "subscription_plan": plan_key,
            "subscription_expires_at": expires_at,
            "is_expired": is_expired,
            "monthly_ai_used": used,
            "monthly_ai_quota": quota,
            "monthly_ai_remaining": max(0, quota - used),
            "plan_info": plan_summary(plan_key),
        }

    def set_tenant_subscription(
        self,
        *,
        tenant_id: int,
        plan: str,
        months: int = 1,
    ) -> dict:
        """设置或续费订阅计划（平台管理员调用）。"""
        if plan not in PLANS:
            raise BusinessError(f"未知计划 {plan!r}，可用：{list(PLANS.keys())}")
        row = self.store.row("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        if row is None:
            raise BusinessError("Tenant not found")
        tenant = dict(row)
        # 计算到期时间：已有到期时间且未过期则续费，否则从现在算
        now = datetime.utcnow()
        existing_expires = tenant.get("subscription_expires_at")
        base = now
        if existing_expires:
            try:
                base_dt = datetime.fromisoformat(existing_expires)
                if base_dt > now:
                    base = base_dt
            except ValueError:
                pass
        from datetime import timedelta
        new_expires = (base + timedelta(days=30 * months)).isoformat()
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE tenants
                SET subscription_plan = ?,
                    subscription_expires_at = ?,
                    monthly_ai_used = 0,
                    monthly_ai_reset_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (plan, new_expires, tenant_id),
            )
        return self.get_tenant_subscription(tenant_id)

    def _reset_monthly_ai_usage(self, tenant_id: int) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE tenants
                SET monthly_ai_used = 0,
                    monthly_ai_reset_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (tenant_id,),
            )

    def check_plan_feature(self, tenant_id: int, feature: str) -> bool:
        """检查租户是否有某项功能权限（自动处理到期降级）。"""
        row = self.store.row(
            "SELECT subscription_plan, subscription_expires_at FROM tenants WHERE id = ?",
            (tenant_id,),
        )
        if row is None:
            return False
        plan_key = row["subscription_plan"] or "trial"
        expires_at = row["subscription_expires_at"]
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.utcnow():
                    plan_key = "trial"  # 到期降级
            except ValueError:
                pass
        return check_feature(plan_key, feature)

    def assert_plan_feature(self, tenant_id: int, feature: str, msg: str | None = None) -> None:
        """检查功能权限，无权限时抛出 BusinessError。"""
        if not self.check_plan_feature(tenant_id, feature):
            raise BusinessError(msg or f"当前订阅计划不支持此功能，请升级套餐")

    def check_monthly_ai_quota(self, tenant_id: int) -> dict:
        """检查本月 AI 额度，返回剩余量。超出时抛 BusinessError。"""
        row = self.store.row(
            "SELECT subscription_plan, subscription_expires_at, monthly_ai_used, monthly_ai_reset_at FROM tenants WHERE id = ?",
            (tenant_id,),
        )
        if row is None:
            raise BusinessError("Tenant not found")
        plan_key = row["subscription_plan"] or "trial"
        # 到期降级
        expires_at = row["subscription_expires_at"]
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.utcnow():
                    plan_key = "trial"
            except ValueError:
                pass
        # 月度重置
        reset_at_str = str(row["monthly_ai_reset_at"] or "")
        try:
            reset_at = datetime.fromisoformat(reset_at_str[:10])
            if reset_at.month != datetime.utcnow().month or reset_at.year != datetime.utcnow().year:
                self._reset_monthly_ai_usage(tenant_id)
                used = 0
            else:
                used = int(row["monthly_ai_used"] or 0)
        except (ValueError, TypeError):
            used = int(row["monthly_ai_used"] or 0)
        plan = get_plan(plan_key)
        quota = plan["monthly_ai_quota"]
        remaining = quota - used
        return {"used": used, "quota": quota, "remaining": remaining, "plan": plan_key}

    def increment_monthly_ai_usage(self, tenant_id: int, count: int = 1) -> None:
        """AI 生成完成后调用，增加月度用量计数。"""
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE tenants SET monthly_ai_used = COALESCE(monthly_ai_used, 0) + ? WHERE id = ?",
                (count, tenant_id),
            )

    # ── 门店数量限制 ──────────────────────────────────────────────

    def check_store_limit(self, tenant_id: int) -> None:
        """新建门店前调用，超出计划门店数时抛 BusinessError。"""
        row = self.store.row("SELECT subscription_plan FROM tenants WHERE id = ?", (tenant_id,))
        plan_key = (row["subscription_plan"] if row else None) or "trial"
        plan = get_plan(plan_key)
        max_stores = plan["max_stores"]
        if max_stores == -1:
            return  # 不限
        current = self.store.row(
            "SELECT COUNT(*) as cnt FROM stores WHERE tenant_id = ? AND status = 'active'",
            (tenant_id,),
        )
        if int(current["cnt"]) >= max_stores:
            raise BusinessError(
                f"当前 {plan['display_name']} 最多支持 {max_stores} 家门店，请升级套餐"
            )

    def list_stores(self, tenant_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self.store.rows(
                """
                SELECT id, tenant_id, store_code, name, daily_ai_limit, status, created_at
                FROM stores
                WHERE tenant_id = ?
                ORDER BY id ASC
                """,
                (tenant_id,),
            )
        ]

    def create_store(
        self,
        *,
        tenant_id: int,
        store_code: str,
        name: str,
        daily_ai_limit: int = 300,
    ) -> dict:
        if not store_code.strip() or not name.strip():
            raise BusinessError("store_code and name are required")
        if daily_ai_limit < 0:
            raise BusinessError("daily_ai_limit cannot be negative")
        tenant = self.store.row("SELECT * FROM tenants WHERE id = ? AND status = 'active'", (tenant_id,))
        if tenant is None:
            raise BusinessError("Tenant not found or inactive")
        self.check_store_limit(tenant_id)
        existing = self.store.row(
            "SELECT id FROM stores WHERE tenant_id = ? AND store_code = ?",
            (tenant_id, store_code),
        )
        if existing is not None:
            raise BusinessError("store_code already exists for this tenant")
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO stores (tenant_id, store_code, name, daily_ai_limit)
                VALUES (?, ?, ?, ?)
                """,
                (tenant_id, store_code, name, daily_ai_limit),
            )
            store_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM stores WHERE id = ?", (store_id,)))

    def update_store(
        self,
        *,
        tenant_id: int,
        store_id: int,
        name: str | None = None,
        daily_ai_limit: int | None = None,
        status: str | None = None,
    ) -> dict:
        existing = self.store.row("SELECT * FROM stores WHERE tenant_id = ? AND id = ?", (tenant_id, store_id))
        if existing is None:
            raise BusinessError("Store not found")
        if daily_ai_limit is not None and daily_ai_limit < 0:
            raise BusinessError("daily_ai_limit cannot be negative")
        if status is not None and status not in {"active", "paused"}:
            raise BusinessError("status must be active or paused")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE stores
                SET name = COALESCE(?, name),
                    daily_ai_limit = COALESCE(?, daily_ai_limit),
                    status = COALESCE(?, status)
                WHERE tenant_id = ? AND id = ?
                """,
                (name, daily_ai_limit, status, tenant_id, store_id),
            )
        return dict(self.store.row("SELECT * FROM stores WHERE tenant_id = ? AND id = ?", (tenant_id, store_id)))

    def upsert_api_key_config(
        self,
        *,
        tenant_id: int | None,
        provider: str,
        key_name: str,
        secret_value: str,
        updated_by_user_id: int | None = None,
    ) -> dict:
        if provider not in {"dify", "dashscope", "oss", "wechat_pay", "feishu"}:
            raise BusinessError("Unsupported provider")
        if not key_name.strip() or not secret_value.strip():
            raise BusinessError("key_name and secret_value are required")
        ciphertext = self._encrypt_secret(secret_value)
        fingerprint = hashlib.sha256(secret_value.encode("utf-8")).hexdigest()[:16]
        masked = self._mask_secret(secret_value)
        with self.store.transaction() as conn:
            existing = conn.execute(
                """
                SELECT id FROM api_key_configs
                WHERE COALESCE(tenant_id, -1) = COALESCE(?, -1)
                  AND provider = ? AND key_name = ?
                """,
                (tenant_id, provider, key_name),
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO api_key_configs
                    (tenant_id, provider, key_name, secret_ciphertext, secret_fingerprint,
                     masked_secret, updated_by_user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        provider,
                        key_name,
                        ciphertext,
                        fingerprint,
                        masked,
                        updated_by_user_id,
                    ),
                )
                config_id = cur.lastrowid
            else:
                config_id = existing["id"]
                conn.execute(
                    """
                    UPDATE api_key_configs
                    SET secret_ciphertext = ?, secret_fingerprint = ?, masked_secret = ?,
                        status = 'active', updated_by_user_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (ciphertext, fingerprint, masked, updated_by_user_id, config_id),
                )
        return self._public_api_key_config(config_id)

    def list_api_key_configs(self, tenant_id: int | None = None) -> list[dict]:
        if tenant_id is None:
            rows = self.store.rows(
                """
                SELECT id, tenant_id, provider, key_name, secret_fingerprint, masked_secret,
                       status, updated_by_user_id, created_at, updated_at
                FROM api_key_configs
                ORDER BY tenant_id ASC, provider ASC, key_name ASC
                """
            )
        else:
            rows = self.store.rows(
                """
                SELECT id, tenant_id, provider, key_name, secret_fingerprint, masked_secret,
                       status, updated_by_user_id, created_at, updated_at
                FROM api_key_configs
                WHERE tenant_id = ? OR tenant_id IS NULL
                ORDER BY tenant_id ASC, provider ASC, key_name ASC
                """,
                (tenant_id,),
            )
        return [dict(row) for row in rows]

    def resolve_api_key_config(self, *, tenant_id: int, provider: str, key_name: str) -> dict:
        if provider not in {"dify", "dashscope", "oss", "wechat_pay", "feishu"}:
            raise BusinessError("Unsupported provider")
        row = self.store.row(
            """
            SELECT id, tenant_id, provider, key_name, secret_fingerprint, masked_secret,
                   status, updated_by_user_id, created_at, updated_at
            FROM api_key_configs
            WHERE provider = ? AND key_name = ? AND status = 'active'
              AND (tenant_id = ? OR tenant_id IS NULL)
            ORDER BY CASE WHEN tenant_id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (provider, key_name, tenant_id, tenant_id),
        )
        if row is None:
            raise BusinessError("Active API key config not found")
        scope = "tenant" if row["tenant_id"] == tenant_id else "platform"
        return dict(row) | {"resolved_scope": scope}

    def disable_api_key_config(self, config_id: int) -> dict:
        with self.store.transaction() as conn:
            row = conn.execute("SELECT id FROM api_key_configs WHERE id = ?", (config_id,)).fetchone()
            if row is None:
                raise BusinessError("API key config not found")
            conn.execute(
                "UPDATE api_key_configs SET status = 'disabled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (config_id,),
            )
        return self._public_api_key_config(config_id)

    def _public_api_key_config(self, config_id: int) -> dict:
        row = self.store.row(
            """
            SELECT id, tenant_id, provider, key_name, secret_fingerprint, masked_secret,
                   status, updated_by_user_id, created_at, updated_at
            FROM api_key_configs
            WHERE id = ?
            """,
            (config_id,),
        )
        if row is None:
            raise BusinessError("API key config not found")
        return dict(row)

    def _encrypt_secret(self, secret_value: str) -> str:
        key = os.getenv("PLATFORM_SECRET_ENCRYPTION_KEY", "local-dev-key")
        key_stream = hashlib.sha256(key.encode("utf-8")).digest()
        raw = secret_value.encode("utf-8")
        encrypted = bytes(value ^ key_stream[index % len(key_stream)] for index, value in enumerate(raw))
        return base64.urlsafe_b64encode(encrypted).decode("utf-8")

    def _decrypt_secret(self, ciphertext: str) -> str:
        """解密存储在数据库里的密钥（XOR 是对称的，加解密用同一函数）"""
        return self._encrypt_secret(
            base64.urlsafe_b64decode(ciphertext.encode("utf-8")).decode("latin-1")
        )

    def resolve_key(self, provider: str, key_name: str, fallback_env: str) -> str:
        """从数据库取有效密钥，数据库没有则回落到环境变量。
        供各服务商构建函数在每次请求时调用，实现后台改密钥即时生效。"""
        try:
            row = self.store.row(
                """
                SELECT secret_ciphertext FROM api_key_configs
                WHERE provider = ? AND key_name = ? AND status = 'active'
                  AND tenant_id IS NULL
                ORDER BY updated_at DESC LIMIT 1
                """,
                (provider, key_name),
            )
            if row and row["secret_ciphertext"]:
                enc_key = os.getenv("PLATFORM_SECRET_ENCRYPTION_KEY", "local-dev-key")
                key_stream = hashlib.sha256(enc_key.encode("utf-8")).digest()
                raw_bytes = base64.urlsafe_b64decode(row["secret_ciphertext"].encode("utf-8"))
                return bytes(b ^ key_stream[i % len(key_stream)] for i, b in enumerate(raw_bytes)).decode("utf-8")
        except Exception:
            pass
        return os.getenv(fallback_env, "")

    def _mask_secret(self, secret_value: str) -> str:
        if len(secret_value) <= 8:
            return "*" * len(secret_value)
        return f"{secret_value[:4]}***{secret_value[-4:]}"

    def upsert_package_plan(
        self,
        *,
        plan_code: str,
        name: str,
        monthly_fee: float,
        included_ai_count: int,
        store_limit: int,
        advanced_features: list[str],
        status: str = "active",
    ) -> dict:
        if not plan_code.strip() or not name.strip():
            raise BusinessError("plan_code and name are required")
        if monthly_fee < 0 or included_ai_count < 0 or store_limit < 0:
            raise BusinessError("package numeric fields cannot be negative")
        if status not in {"active", "disabled"}:
            raise BusinessError("status must be active or disabled")
        with self.store.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM package_plans WHERE plan_code = ?",
                (plan_code,),
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO package_plans
                    (plan_code, name, monthly_fee, included_ai_count, store_limit, advanced_features, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_code,
                        name,
                        monthly_fee,
                        included_ai_count,
                        store_limit,
                        json.dumps(advanced_features, ensure_ascii=False),
                        status,
                    ),
                )
                plan_id = cur.lastrowid
            else:
                plan_id = existing["id"]
                conn.execute(
                    """
                    UPDATE package_plans
                    SET name = ?, monthly_fee = ?, included_ai_count = ?, store_limit = ?,
                        advanced_features = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        name,
                        monthly_fee,
                        included_ai_count,
                        store_limit,
                        json.dumps(advanced_features, ensure_ascii=False),
                        status,
                        plan_id,
                    ),
                )
        return self.package_plan(plan_id)

    def package_plan(self, plan_id: int) -> dict:
        row = self.store.row("SELECT * FROM package_plans WHERE id = ?", (plan_id,))
        if row is None:
            raise BusinessError("Package plan not found")
        return dict(row) | {"advanced_features": json.loads(row["advanced_features"])}

    def list_package_plans(self, include_disabled: bool = False) -> list[dict]:
        if include_disabled:
            rows = self.store.rows("SELECT * FROM package_plans ORDER BY id ASC")
        else:
            rows = self.store.rows("SELECT * FROM package_plans WHERE status = 'active' ORDER BY id ASC")
        return [dict(row) | {"advanced_features": json.loads(row["advanced_features"])} for row in rows]

    def generate_monthly_bill(
        self,
        *,
        tenant_id: int,
        bill_month: str,
        tenant_settle_unit_price: float,
        bill_status: str = "draft",
    ) -> dict:
        if not self._is_valid_bill_month(bill_month):
            raise BusinessError("bill_month must be YYYY-MM")
        if tenant_settle_unit_price < 0:
            raise BusinessError("tenant_settle_unit_price cannot be negative")
        if bill_status not in {"draft", "issued", "paid", "overdue"}:
            raise BusinessError("Invalid bill_status")
        tenant = self.store.row("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        if tenant is None:
            raise BusinessError("Tenant not found")
        plan = None
        if tenant["package_plan"]:
            plan = self.store.row(
                "SELECT * FROM package_plans WHERE plan_code = ? AND status = 'active'",
                (tenant["package_plan"],),
            )
        package_fee = float(plan["monthly_fee"] or 0) if plan else 0
        included_ai_count = int(plan["included_ai_count"] or 0) if plan else 0
        purchased = self.store.row(
            """
            SELECT SUM(purchased_count) AS purchased_count, SUM(total_amount) AS purchased_amount
            FROM tenant_ai_package_orders
            WHERE tenant_id = ? AND payment_status = 'paid' AND substr(created_at, 1, 7) = ?
            """,
            (tenant_id, bill_month),
        )
        jobs = self.store.row(
            """
            SELECT COUNT(*) AS success_ai_uses, SUM(internal_api_cost) AS internal_api_cost
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND status = 'success' AND substr(completed_at, 1, 7) = ?
            """,
            (tenant_id, bill_month),
        )
        purchased_ai_count = int(purchased["purchased_count"] or 0)
        purchased_amount = float(purchased["purchased_amount"] or 0)
        success_ai_uses = int(jobs["success_ai_uses"] or 0)
        internal_api_cost = float(jobs["internal_api_cost"] or 0)
        available_included = included_ai_count + purchased_ai_count
        overage_ai_uses = max(0, success_ai_uses - available_included)
        ai_overage_revenue = overage_ai_uses * tenant_settle_unit_price
        total_bill_amount = package_fee + purchased_amount + ai_overage_revenue
        platform_gross_profit = total_bill_amount - internal_api_cost
        with self.store.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM tenant_monthly_bills WHERE tenant_id = ? AND bill_month = ?",
                (tenant_id, bill_month),
            ).fetchone()
            values = (
                tenant["package_plan"],
                package_fee,
                included_ai_count,
                purchased_ai_count,
                success_ai_uses,
                overage_ai_uses,
                tenant_settle_unit_price,
                ai_overage_revenue,
                total_bill_amount,
                internal_api_cost,
                platform_gross_profit,
                bill_status,
            )
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO tenant_monthly_bills
                    (tenant_id, bill_month, package_plan, package_fee, included_ai_count,
                     purchased_ai_count, success_ai_uses, overage_ai_uses, tenant_settle_unit_price,
                     ai_overage_revenue, total_bill_amount, internal_api_cost, platform_gross_profit,
                     bill_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (tenant_id, bill_month, *values),
                )
                bill_id = cur.lastrowid
            else:
                bill_id = existing["id"]
                conn.execute(
                    """
                    UPDATE tenant_monthly_bills
                    SET package_plan = ?, package_fee = ?, included_ai_count = ?,
                        purchased_ai_count = ?, success_ai_uses = ?, overage_ai_uses = ?,
                        tenant_settle_unit_price = ?, ai_overage_revenue = ?,
                        total_bill_amount = ?, internal_api_cost = ?, platform_gross_profit = ?,
                        bill_status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (*values, bill_id),
                )
        return self.monthly_bill(bill_id, include_platform_fields=True)

    def monthly_bill(self, bill_id: int, *, include_platform_fields: bool) -> dict:
        row = self.store.row("SELECT * FROM tenant_monthly_bills WHERE id = ?", (bill_id,))
        if row is None:
            raise BusinessError("Monthly bill not found")
        return self._bill_view(dict(row), include_platform_fields=include_platform_fields)

    def update_monthly_bill_status(
        self,
        *,
        bill_id: int,
        tenant_id: int,
        bill_status: str,
    ) -> dict:
        if bill_status not in {"draft", "issued", "paid", "overdue"}:
            raise BusinessError("Invalid bill_status")
        existing = self.store.row(
            "SELECT * FROM tenant_monthly_bills WHERE id = ? AND tenant_id = ?",
            (bill_id, tenant_id),
        )
        if existing is None:
            raise BusinessError("Monthly bill not found")
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE tenant_monthly_bills
                SET bill_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND tenant_id = ?
                """,
                (bill_status, bill_id, tenant_id),
            )
        return self.monthly_bill(bill_id, include_platform_fields=True)

    def list_monthly_bills(self, tenant_id: int | None = None, *, include_platform_fields: bool = True) -> list[dict]:
        if tenant_id is None:
            rows = self.store.rows("SELECT * FROM tenant_monthly_bills ORDER BY bill_month DESC, tenant_id ASC")
        else:
            rows = self.store.rows(
                "SELECT * FROM tenant_monthly_bills WHERE tenant_id = ? ORDER BY bill_month DESC",
                (tenant_id,),
            )
        return [self._bill_view(dict(row), include_platform_fields=include_platform_fields) for row in rows]

    def _bill_view(self, bill: dict, *, include_platform_fields: bool) -> dict:
        if include_platform_fields:
            return bill
        hidden = {"internal_api_cost", "platform_gross_profit"}
        return {key: value for key, value in bill.items() if key not in hidden}

    def _is_valid_bill_month(self, value: str) -> bool:
        if len(value) != 7 or value[4] != "-":
            return False
        year, month = value.split("-")
        return year.isdigit() and month.isdigit() and 1 <= int(month) <= 12

    def purchase_ai_package(
        self,
        *,
        tenant_id: int,
        package_name: str,
        purchased_count: int,
        unit_price: float,
        payment_status: str = "paid",
    ) -> dict:
        if purchased_count <= 0:
            raise BusinessError("purchased_count must be positive")
        if unit_price < 0:
            raise BusinessError("unit_price cannot be negative")
        total_amount = purchased_count * unit_price
        with self.store.transaction() as conn:
            tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
            if tenant is None:
                raise BusinessError("Tenant not found")
            cur = conn.execute(
                """
                INSERT INTO tenant_ai_package_orders
                (tenant_id, package_name, purchased_count, unit_price, total_amount, payment_status, paid_at)
                VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 'paid' THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (
                    tenant_id,
                    package_name,
                    purchased_count,
                    unit_price,
                    total_amount,
                    payment_status,
                    payment_status,
                ),
            )
            order_id = cur.lastrowid
            if payment_status == "paid":
                conn.execute(
                    """
                    UPDATE tenant_ai_accounts
                    SET total_purchased = total_purchased + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ?
                    """,
                    (purchased_count, tenant_id),
                )
        return dict(self.store.row("SELECT * FROM tenant_ai_package_orders WHERE id = ?", (order_id,)))

    def list_ai_package_orders(self, tenant_id: int | None = None) -> list[dict]:
        if tenant_id is None:
            rows = self.store.rows(
                """
                SELECT po.*, t.name AS tenant_name
                FROM tenant_ai_package_orders po
                JOIN tenants t ON t.id = po.tenant_id
                ORDER BY po.created_at DESC, po.id DESC
                """
            )
        else:
            rows = self.store.rows(
                """
                SELECT po.*, t.name AS tenant_name
                FROM tenant_ai_package_orders po
                JOIN tenants t ON t.id = po.tenant_id
                WHERE po.tenant_id = ?
                ORDER BY po.created_at DESC, po.id DESC
                """,
                (tenant_id,),
            )
        return [dict(row) for row in rows]

    def adjust_tenant_ai_balance(
        self,
        *,
        tenant_id: int,
        store_id: int,
        change_count: int,
        usage_type: str,
        remark: str,
        user_id: int | None = None,
    ) -> dict:
        if change_count == 0:
            raise BusinessError("change_count cannot be 0")
        if usage_type not in {"compensate", "admin_adjust"}:
            raise BusinessError("usage_type must be compensate or admin_adjust")
        if not remark.strip():
            raise BusinessError("remark is required")
        with self._deduct_lock:
            with self.store.transaction() as conn:
                account = conn.execute(
                    "SELECT * FROM tenant_ai_accounts WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
                if account is None:
                    raise BusinessError("Tenant AI account does not exist")
                before_balance = (
                    int(account["total_purchased"])
                    + int(account["total_gifted_adjustment"])
                    - int(account["total_used"])
                )
                after_balance = before_balance + change_count
                if after_balance < 0:
                    raise BusinessError("Adjustment would make AI balance negative")
                conn.execute(
                    """
                    UPDATE tenant_ai_accounts
                    SET total_gifted_adjustment = total_gifted_adjustment + ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ?
                    """,
                    (change_count, tenant_id),
                )
                cur = conn.execute(
                    """
                    INSERT INTO tenant_ai_usage_logs
                    (tenant_id, store_id, user_id, usage_type, change_count, balance_after, remark)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (tenant_id, store_id, user_id, usage_type, change_count, after_balance, remark),
                )
                log_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM tenant_ai_usage_logs WHERE id = ?", (log_id,)))

    def merchant_workbench(self, tenant_id: int, store_id: int) -> dict:
        start_date, end_date, period_label = self._performance_period_range("day", 0)
        store = self.store.row(
            "SELECT name FROM stores WHERE tenant_id = ? AND id = ?",
            (tenant_id, store_id),
        )
        orders = self.store.row(
            """
            SELECT COUNT(*) AS total_orders,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_orders,
                   SUM(CASE WHEN is_ai_converted = 1 THEN 1 ELSE 0 END) AS ai_converted_orders
            FROM orders
            WHERE tenant_id = ? AND store_id = ?
              AND DATE(created_at) >= ? AND DATE(created_at) < ?
            """,
            (tenant_id, store_id, start_date, end_date),
        )
        revenue = self.store.row(
            """
            SELECT COUNT(*) AS completed_services,
                   SUM(actual_amount) AS actual_revenue
            FROM service_records
            WHERE tenant_id = ? AND store_id = ?
              AND DATE(completed_at) >= ? AND DATE(completed_at) < ?
            """,
            (tenant_id, store_id, start_date, end_date),
        )
        prepaid_revenue = self._prepaid_revenue_summary(tenant_id, store_id, start_date, end_date)
        jobs = self.store.row(
            """
            SELECT COUNT(*) AS ai_jobs,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ai_success_jobs
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND store_id = ?
              AND DATE(created_at) >= ? AND DATE(created_at) < ?
            """,
            (tenant_id, store_id, start_date, end_date),
        )
        # FEAT-08: 本月用量（用于低余额预警参考）
        cur_month = date.today().strftime("%Y-%m")
        jobs_month = self.store.row(
            """
            SELECT SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS used_this_month
            FROM ai_generation_jobs
            WHERE tenant_id = ?
              AND strftime('%Y-%m', created_at) = ?
            """,
            (tenant_id, cur_month),
        )
        # FEAT-08: AI 次数余额
        remaining = self.account_balance(tenant_id)
        low_balance_threshold = int(os.getenv("LOW_BALANCE_THRESHOLD", "50"))
        critical_balance_threshold = int(os.getenv("CRITICAL_BALANCE_THRESHOLD", "20"))
        if remaining <= critical_balance_threshold:
            warning_level = "critical"
            warning_message = f"AI 次数即将耗尽（剩余 {remaining} 次），已暂停新顾客使用，请联系平台续费"
        elif remaining <= low_balance_threshold:
            warning_level = "low"
            warning_message = f"AI 次数仅剩 {remaining} 次，请联系平台续费"
        else:
            warning_level = None
            warning_message = None
        return {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "store_name": store["name"] if store else "门店",
            "period": "day",
            "period_range": {
                "start_date": start_date,
                "end_date": end_date,
                "label": period_label,
            },
            "total_orders": int(orders["total_orders"] or 0),
            "completed_orders": int(revenue["completed_services"] or 0),
            "ai_converted_orders": int(orders["ai_converted_orders"] or 0),
            "service_revenue": float(revenue["actual_revenue"] or 0),
            "prepaid_revenue": prepaid_revenue["prepaid_revenue"],
            "membership_recharge_revenue": prepaid_revenue["membership_recharge_revenue"],
            "package_sales_revenue": prepaid_revenue["package_sales_revenue"],
            "actual_revenue": float(revenue["actual_revenue"] or 0) + prepaid_revenue["prepaid_revenue"],
            "ai_jobs": int(jobs["ai_jobs"] or 0),
            "ai_success_jobs": int(jobs["ai_success_jobs"] or 0),
            # FEAT-08: AI 次数余额信息
            "ai_balance": {
                "remaining": remaining,
                "used_this_month": int(jobs_month["used_this_month"] or 0),
                "low_balance": remaining <= low_balance_threshold,
                "warning_level": warning_level,
                "warning_message": warning_message,
            },
        }

    def _prepaid_revenue_summary(
        self,
        tenant_id: int,
        store_id: int | None,
        start_date: str,
        end_date: str,
    ) -> dict:
        membership_filters = ["tenant_id = ?", "transaction_type = 'recharge'"]
        membership_params: list = [tenant_id]
        package_filters = ["tenant_id = ?"]
        package_params: list = [tenant_id]
        if store_id is not None:
            membership_filters.append("store_id = ?")
            membership_params.append(store_id)
            package_filters.append("store_id = ?")
            package_params.append(store_id)
        membership_filters.extend(["DATE(created_at) >= ?", "DATE(created_at) < ?"])
        membership_params.extend([start_date, end_date])
        package_filters.extend(["DATE(created_at) >= ?", "DATE(created_at) < ?"])
        package_params.extend([start_date, end_date])
        membership_where = " AND ".join(membership_filters)
        package_where = " AND ".join(package_filters)
        membership = self.store.row(
            f"""
            SELECT SUM(amount) AS revenue
            FROM customer_membership_transactions
            WHERE {membership_where}
            """,
            tuple(membership_params),
        )
        packages = self.store.row(
            f"""
            SELECT SUM(paid_amount) AS revenue
            FROM customer_packages
            WHERE {package_where}
            """,
            tuple(package_params),
        )
        membership_revenue = float(membership["revenue"] or 0)
        package_revenue = float(packages["revenue"] or 0)
        return {
            "membership_recharge_revenue": membership_revenue,
            "package_sales_revenue": package_revenue,
            "prepaid_revenue": membership_revenue + package_revenue,
        }

    def store_public_profile(self, tenant_id: int, store_id: int) -> dict:
        store = self.store.row(
            """
            SELECT s.id AS store_id, s.name AS store_name, s.store_code,
                   t.id AS tenant_id, t.name AS tenant_name, t.logo_url
            FROM stores s
            JOIN tenants t ON t.id = s.tenant_id
            WHERE s.tenant_id = ? AND s.id = ? AND s.status = 'active'
            """,
            (tenant_id, store_id),
        )
        if store is None:
            raise BusinessError("Store not found")
        config = self.store.row(
            """
            SELECT home_title, home_subtitle, store_photos
            FROM store_home_configs
            WHERE tenant_id = ? AND store_id = ?
            """,
            (tenant_id, store_id),
        )
        default_title = "灵感造型顾问"
        default_subtitle = "用一张自拍预览适合你的发型与发色"
        default_photos = self._default_store_photos()
        photos = default_photos
        if config is not None:
            try:
                parsed_photos = json.loads(config["store_photos"] or "[]")
            except json.JSONDecodeError:
                parsed_photos = []
            if parsed_photos:
                photos = parsed_photos
        return {
            "tenant_id": int(store["tenant_id"]),
            "store_id": int(store["store_id"]),
            "tenant_name": store["tenant_name"],
            "store_name": store["store_name"],
            "logo_url": store["logo_url"],
            "home_title": config["home_title"] if config and config["home_title"] else default_title,
            "home_subtitle": config["home_subtitle"] if config and config["home_subtitle"] else default_subtitle,
            "store_photos": photos,
        }

    def _default_store_photos(self) -> list[dict]:
        # FEAT-10: 新门店默认空白，不预填演示图片，由商家自行上传
        return []

    def update_store_home_config(
        self,
        *,
        tenant_id: int,
        store_id: int,
        store_name: str | None,
        home_title: str | None,
        home_subtitle: str | None,
        store_photos: list[dict],
    ) -> dict:
        store = self.store.row("SELECT * FROM stores WHERE tenant_id = ? AND id = ?", (tenant_id, store_id))
        if store is None:
            raise BusinessError("Store not found")
        clean_photos = self._clean_store_photos(store_photos)
        with self.store.transaction() as conn:
            if store_name is not None and store_name.strip():
                conn.execute(
                    "UPDATE stores SET name = ? WHERE tenant_id = ? AND id = ?",
                    (store_name.strip(), tenant_id, store_id),
                )
            conn.execute(
                """
                INSERT INTO store_home_configs
                (tenant_id, store_id, home_title, home_subtitle, store_photos, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, store_id) DO UPDATE SET
                  home_title = excluded.home_title,
                  home_subtitle = excluded.home_subtitle,
                  store_photos = excluded.store_photos,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    store_id,
                    (home_title or "").strip() or None,
                    (home_subtitle or "").strip() or None,
                    json.dumps(clean_photos, ensure_ascii=False),
                ),
            )
        return self.store_public_profile(tenant_id, store_id)

    def _clean_store_photos(self, store_photos: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        for item in store_photos[:5]:
            title = str(item.get("title") or "").strip()
            desc = str(item.get("desc") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title and not desc and not url:
                continue
            if url and not url.startswith(("http://", "https://")):
                raise BusinessError("轮播图链接必须以 http:// 或 https:// 开头")
            cleaned.append({"title": title, "desc": desc, "url": url})
        return cleaned  # FEAT-10: 清理后为空则返回空列表，不填充演示图片

    def merchant_performance(
        self,
        *,
        tenant_id: int,
        store_id: int | None = None,
        stylist_id: int | None = None,
        period: str = "month",
        offset: int = 0,
    ) -> dict:
        start_date, end_date, period_label = self._performance_period_range(period, offset)
        filters = ["sr.tenant_id = ?"]
        params: list = [tenant_id]
        if store_id is not None:
            filters.append("sr.store_id = ?")
            params.append(store_id)
        if stylist_id is not None:
            filters.append("sr.stylist_id = ?")
            params.append(stylist_id)
        filters.append("DATE(sr.completed_at) >= ?")
        params.append(start_date)
        filters.append("DATE(sr.completed_at) < ?")
        params.append(end_date)
        where = " AND ".join(filters)

        totals = self.store.row(
            f"""
            SELECT COUNT(*) AS completed_services,
                   SUM(sr.actual_amount) AS revenue,
                   SUM(CASE WHEN sr.is_ai_converted = 1 THEN 1 ELSE 0 END) AS ai_converted_services,
                   SUM(CASE WHEN sr.is_ai_converted = 1 THEN sr.actual_amount ELSE 0 END) AS ai_converted_revenue
            FROM service_records sr
            WHERE {where}
            """,
            tuple(params),
        )
        prepaid_revenue = self._prepaid_revenue_summary(tenant_id, store_id, start_date, end_date)
        order_filters = ["tenant_id = ?"]
        order_params: list = [tenant_id]
        if store_id is not None:
            order_filters.append("store_id = ?")
            order_params.append(store_id)
        if stylist_id is not None:
            order_filters.append("stylist_id = ?")
            order_params.append(stylist_id)
        order_filters.append("DATE(created_at) >= ?")
        order_params.append(start_date)
        order_filters.append("DATE(created_at) < ?")
        order_params.append(end_date)
        order_where = " AND ".join(order_filters)
        orders = self.store.row(
            f"""
            SELECT COUNT(*) AS total_orders,
                   SUM(CASE WHEN is_ai_converted = 1 THEN 1 ELSE 0 END) AS ai_converted_orders
            FROM orders
            WHERE {order_where}
            """,
            tuple(order_params),
        )
        job_filters = ["tenant_id = ?"]
        job_params: list = [tenant_id]
        if store_id is not None:
            job_filters.append("store_id = ?")
            job_params.append(store_id)
        job_filters.append("DATE(created_at) >= ?")
        job_params.append(start_date)
        job_filters.append("DATE(created_at) < ?")
        job_params.append(end_date)
        job_where = " AND ".join(job_filters)
        jobs = self.store.row(
            f"""
            SELECT COUNT(*) AS ai_jobs,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ai_success_jobs
            FROM ai_generation_jobs
            WHERE {job_where}
            """,
            tuple(job_params),
        )
        by_store = self.store.rows(
            f"""
            SELECT sr.store_id, s.name AS store_name, COUNT(*) AS completed_services,
                   SUM(sr.actual_amount) AS revenue,
                   SUM(CASE WHEN sr.is_ai_converted = 1 THEN 1 ELSE 0 END) AS ai_converted_services
            FROM service_records sr
            JOIN stores s ON s.id = sr.store_id AND s.tenant_id = sr.tenant_id
            WHERE {where}
            GROUP BY sr.store_id, s.name
            ORDER BY revenue DESC
            """,
            tuple(params),
        )
        by_stylist = self.store.rows(
            f"""
            SELECT sr.stylist_id, COALESCE(sp.display_name, u.nickname) AS stylist_name,
                   COUNT(*) AS completed_services,
                   SUM(sr.actual_amount) AS revenue,
                   SUM(CASE WHEN sr.is_ai_converted = 1 THEN 1 ELSE 0 END) AS ai_converted_services
            FROM service_records sr
            LEFT JOIN staff_profiles sp
              ON sp.tenant_id = sr.tenant_id AND sp.store_id = sr.store_id AND sp.staff_id = sr.stylist_id
            LEFT JOIN users u ON u.id = sr.stylist_id AND u.tenant_id = sr.tenant_id
            WHERE {where}
            GROUP BY sr.stylist_id, stylist_name
            ORDER BY revenue DESC
            """,
            tuple(params),
        )
        by_service = self.store.rows(
            f"""
            SELECT si.category, si.name AS service_name,
                   COUNT(*) AS completed_services,
                   SUM(sr.actual_amount) AS revenue,
                   SUM(CASE WHEN sr.is_ai_converted = 1 THEN 1 ELSE 0 END) AS ai_converted_services
            FROM service_records sr
            JOIN service_items si
              ON si.id = sr.service_item_id AND si.tenant_id = sr.tenant_id
            WHERE {where}
            GROUP BY si.category, si.name
            ORDER BY revenue DESC
            """,
            tuple(params),
        )
        by_category = self.store.rows(
            f"""
            SELECT si.category,
                   COUNT(*) AS completed_services,
                   SUM(sr.actual_amount) AS revenue,
                   SUM(CASE WHEN sr.is_ai_converted = 1 THEN 1 ELSE 0 END) AS ai_converted_services,
                   SUM(CASE WHEN sr.is_ai_converted = 1 THEN sr.actual_amount ELSE 0 END) AS ai_converted_revenue
            FROM service_records sr
            JOIN service_items si
              ON si.id = sr.service_item_id AND si.tenant_id = sr.tenant_id
            WHERE {where}
            GROUP BY si.category
            ORDER BY revenue DESC
            """,
            tuple(params),
        )
        ai_success_jobs = int(jobs["ai_success_jobs"] or 0)
        ai_converted_orders = int(orders["ai_converted_orders"] or 0)
        ai_converted_services = int(totals["ai_converted_services"] or 0)
        service_revenue = float(totals["revenue"] or 0)
        return {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "stylist_id": stylist_id,
            "period": period if period in {"day", "week", "month", "year"} else "month",
            "period_offset": offset,
            "period_range": {
                "start_date": start_date,
                "end_date": end_date,
                "label": period_label,
            },
            "totals": {
                "completed_services": int(totals["completed_services"] or 0),
                "service_revenue": service_revenue,
                "prepaid_revenue": prepaid_revenue["prepaid_revenue"],
                "membership_recharge_revenue": prepaid_revenue["membership_recharge_revenue"],
                "package_sales_revenue": prepaid_revenue["package_sales_revenue"],
                "revenue": service_revenue + prepaid_revenue["prepaid_revenue"],
                "ai_converted_services": int(totals["ai_converted_services"] or 0),
                "ai_converted_revenue": float(totals["ai_converted_revenue"] or 0),
            },
            "ai_conversion": {
                "ai_jobs": int(jobs["ai_jobs"] or 0),
                "ai_success_jobs": ai_success_jobs,
                "ai_converted_orders": ai_converted_orders,
                "ai_converted_services": ai_converted_services,
                "ai_converted_revenue": float(totals["ai_converted_revenue"] or 0),
                "order_conversion_rate": self._rate(ai_converted_orders, ai_success_jobs),
                "service_conversion_rate": self._rate(ai_converted_services, ai_success_jobs),
            },
            "by_store": [self._performance_row(row) for row in by_store],
            "by_stylist": [self._performance_row(row) for row in by_stylist],
            "by_category": [self._performance_row(row) for row in by_category],
            "by_service": [self._performance_row(row) for row in by_service],
        }

    def _performance_period_range(self, period: str, offset: int = 0) -> tuple[str, str, str]:
        today = date.today()
        if period == "day":
            start = today + timedelta(days=offset)
        elif period == "week":
            start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        elif period == "year":
            start = date(today.year + offset, 1, 1)
        else:
            month_index = today.year * 12 + today.month - 1 + offset
            start = date(month_index // 12, month_index % 12 + 1, 1)
        if period == "day":
            end = start + timedelta(days=1)
            label = start.isoformat()
        elif period == "week":
            end = start + timedelta(days=7)
            label = f"{start.isoformat()} 至 {(end - timedelta(days=1)).isoformat()}"
        elif period == "year":
            end = date(start.year + 1, 1, 1)
            label = f"{start.year}年"
        else:
            end = date(start.year + (1 if start.month == 12 else 0), 1 if start.month == 12 else start.month + 1, 1)
            label = f"{start.year}年{start.month}月"
        return start.isoformat(), end.isoformat(), label

    def merchant_gift_conversion(
        self,
        *,
        tenant_id: int,
        store_id: int | None = None,
        staff_id: int | None = None,
    ) -> dict:
        filters = ["g.tenant_id = ?"]
        params: list[object] = [tenant_id]
        if store_id is not None:
            filters.append("g.store_id = ?")
            params.append(store_id)
        if staff_id is not None:
            filters.append("g.gifted_by_user_id = ?")
            params.append(staff_id)
        where = " AND ".join(filters)
        totals = self.store.row(
            f"""
            SELECT COUNT(*) AS gifted_count,
                   SUM(CASE WHEN g.status = 'used' THEN 1 ELSE 0 END) AS used_count,
                   SUM(CASE WHEN g.order_id IS NOT NULL THEN 1 ELSE 0 END) AS order_count,
                   SUM(CASE WHEN g.revenue_amount > 0 THEN 1 ELSE 0 END) AS completed_order_count,
                   SUM(g.revenue_amount) AS revenue
            FROM ai_gift_records g
            WHERE {where}
            """,
            tuple(params),
        )
        by_staff = self.store.rows(
            f"""
            SELECT g.gifted_by_user_id AS staff_id,
                   COALESCE(sp.display_name, u.nickname) AS staff_name,
                   COUNT(*) AS gifted_count,
                   SUM(CASE WHEN g.status = 'used' THEN 1 ELSE 0 END) AS used_count,
                   SUM(CASE WHEN g.order_id IS NOT NULL THEN 1 ELSE 0 END) AS order_count,
                   SUM(CASE WHEN g.revenue_amount > 0 THEN 1 ELSE 0 END) AS completed_order_count,
                   SUM(g.revenue_amount) AS revenue
            FROM ai_gift_records g
            LEFT JOIN staff_profiles sp
              ON sp.tenant_id = g.tenant_id AND sp.store_id = g.store_id AND sp.staff_id = g.gifted_by_user_id
            LEFT JOIN users u ON u.id = g.gifted_by_user_id AND u.tenant_id = g.tenant_id
            WHERE {where}
            GROUP BY g.gifted_by_user_id, staff_name
            ORDER BY order_count DESC, gifted_count DESC
            """,
            tuple(params),
        )
        recent_records = self.store.rows(
            f"""
            SELECT g.id, g.customer_id, g.gifted_by_user_id AS staff_id,
                   g.status, g.created_at, g.used_at, g.order_id, g.revenue_amount,
                   COALESCE(c.nickname, printf('顾客C%04d', g.customer_id)) AS customer_name,
                   COALESCE(c.phone, '') AS customer_phone,
                   COALESCE(sp.display_name, u.nickname, '门店员工') AS staff_name
            FROM ai_gift_records g
            LEFT JOIN users c ON c.id = g.customer_id AND c.tenant_id = g.tenant_id
            LEFT JOIN staff_profiles sp
              ON sp.tenant_id = g.tenant_id AND sp.store_id = g.store_id AND sp.staff_id = g.gifted_by_user_id
            LEFT JOIN users u ON u.id = g.gifted_by_user_id AND u.tenant_id = g.tenant_id
            WHERE {where}
            ORDER BY g.id DESC
            LIMIT 20
            """,
            tuple(params),
        )
        return {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "staff_id": staff_id,
            "totals": self._gift_conversion_row(totals),
            "by_staff": [self._gift_conversion_row(row) for row in by_staff],
            "recent_records": [
                dict(row) | {"masked_phone": self._mask_phone(dict(row).get("customer_phone"))}
                for row in recent_records
            ],
        }

    def track_asset_event(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        user_id: int | None,
        asset_type: str,
        asset_id: str,
        event_type: str,
    ) -> dict:
        self._assert_valid_asset_event(tenant_id, asset_type, asset_id, event_type)
        with self.store.transaction() as conn:
            event_id = self._insert_asset_event(
                conn,
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                asset_type=asset_type,
                asset_id=asset_id,
                event_type=event_type,
            )
        row = self.store.row("SELECT * FROM asset_popularity_events WHERE id = ?", (event_id,))
        assert row is not None
        return dict(row)

    def asset_popularity(
        self,
        *,
        tenant_id: int,
        store_id: int | None = None,
        event_type: str | None = None,
        limit: int = 20,
    ) -> dict:
        if event_type is not None and event_type not in {"view", "select", "generate", "order"}:
            raise BusinessError("Invalid asset event_type")
        if limit <= 0:
            raise BusinessError("limit must be positive")
        limit = min(limit, 100)
        style_rows = self._asset_popularity_rows(
            tenant_id=tenant_id,
            store_id=store_id,
            asset_type="hairstyle",
            event_type=event_type,
            limit=limit,
        )
        color_rows = self._asset_popularity_rows(
            tenant_id=tenant_id,
            store_id=store_id,
            asset_type="hair_color",
            event_type=event_type,
            limit=limit,
        )
        return {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "event_type": event_type,
            "hairstyles": style_rows,
            "hair_colors": color_rows,
        }

    def _asset_popularity_rows(
        self,
        *,
        tenant_id: int,
        store_id: int | None,
        asset_type: str,
        event_type: str | None,
        limit: int,
    ) -> list[dict]:
        filters = ["e.tenant_id = ?", "e.asset_type = ?"]
        params: list[object] = [tenant_id, asset_type]
        if store_id is not None:
            filters.append("e.store_id = ?")
            params.append(store_id)
        if event_type is not None:
            filters.append("e.event_type = ?")
            params.append(event_type)
        params.append(limit)
        where = " AND ".join(filters)
        if asset_type == "hairstyle":
            sql = f"""
                SELECT e.asset_id, h.name, h.direction, h.hair_length, COUNT(*) AS event_count
                FROM asset_popularity_events e
                LEFT JOIN hairstyles h ON h.tenant_id = e.tenant_id AND h.style_id = e.asset_id
                WHERE {where}
                GROUP BY e.asset_id, h.name, h.direction, h.hair_length
                ORDER BY event_count DESC, e.asset_id ASC
                LIMIT ?
            """
        else:
            sql = f"""
                SELECT e.asset_id, c.name, c.direction, c.color_swatch, COUNT(*) AS event_count
                FROM asset_popularity_events e
                LEFT JOIN hair_colors c ON c.tenant_id = e.tenant_id AND c.color_id = e.asset_id
                WHERE {where}
                GROUP BY e.asset_id, c.name, c.direction, c.color_swatch
                ORDER BY event_count DESC, e.asset_id ASC
                LIMIT ?
            """
        return [dict(row) | {"event_count": int(row["event_count"] or 0)} for row in self.store.rows(sql, tuple(params))]

    def _insert_asset_event(
        self,
        conn,
        *,
        tenant_id: int,
        store_id: int | None,
        user_id: int | None,
        asset_type: str,
        asset_id: str,
        event_type: str,
        generation_job_id: int | None = None,
        order_id: int | None = None,
    ) -> int:
        cur = conn.execute(
            """
            INSERT INTO asset_popularity_events
            (tenant_id, store_id, user_id, asset_type, asset_id, event_type, generation_job_id, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tenant_id, store_id, user_id, asset_type, asset_id, event_type, generation_job_id, order_id),
        )
        return cur.lastrowid

    def _assert_valid_asset_event(self, tenant_id: int, asset_type: str, asset_id: str, event_type: str) -> None:
        if asset_type not in {"hairstyle", "hair_color"}:
            raise BusinessError("asset_type must be hairstyle or hair_color")
        if event_type not in {"view", "select", "generate", "order"}:
            raise BusinessError("Invalid asset event_type")
        if not asset_id.strip():
            raise BusinessError("asset_id is required")
        if asset_type == "hairstyle":
            row = self.store.row(
                "SELECT id FROM hairstyles WHERE tenant_id = ? AND style_id = ?",
                (tenant_id, asset_id),
            )
        else:
            row = self.store.row(
                "SELECT id FROM hair_colors WHERE tenant_id = ? AND color_id = ?",
                (tenant_id, asset_id),
            )
        if row is None:
            raise BusinessError("Asset not found")

    def _gift_conversion_row(self, row) -> dict:
        data = dict(row)
        gifted_count = int(data.get("gifted_count") or 0)
        used_count = int(data.get("used_count") or 0)
        order_count = int(data.get("order_count") or 0)
        completed_order_count = int(data.get("completed_order_count") or 0)
        data["gifted_count"] = gifted_count
        data["used_count"] = used_count
        data["order_count"] = order_count
        data["completed_order_count"] = completed_order_count
        data["revenue"] = float(data.get("revenue") or 0)
        data["use_rate"] = self._rate(used_count, gifted_count)
        data["order_conversion_rate"] = self._rate(order_count, gifted_count)
        data["completed_conversion_rate"] = self._rate(completed_order_count, gifted_count)
        return data

    def _performance_row(self, row) -> dict:
        data = dict(row)
        for key in ("completed_services", "ai_converted_services"):
            if key in data:
                data[key] = int(data[key] or 0)
        if "revenue" in data:
            data["revenue"] = float(data["revenue"] or 0)
        if "stylist_id" in data:
            rate = 0.10
            ai_bonus = 5.0
            ai_count = int(data.get("ai_converted_services") or 0)
            data["performance_rate"] = rate
            data["ai_bonus_per_order"] = ai_bonus
            data["estimated_performance"] = round(float(data.get("revenue") or 0) * rate + ai_count * ai_bonus, 2)
        return data

    def enqueue_sync_event(self, tenant_id: int, store_id: int | None, event_type: str, payload: dict) -> dict:
        with self.store.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO sync_events (tenant_id, store_id, event_type, payload)
                VALUES (?, ?, ?, ?)
                """,
                (tenant_id, store_id, event_type, json.dumps(payload, ensure_ascii=False)),
            )
            event_id = cur.lastrowid
        return dict(self.store.row("SELECT * FROM sync_events WHERE id = ?", (event_id,)))

    def sync_status(self, tenant_id: int) -> dict:
        rows = self.store.rows(
            """
            SELECT status, COUNT(*) AS count
            FROM sync_events
            WHERE tenant_id = ?
            GROUP BY status
            """,
            (tenant_id,),
        )
        return {
            "tenant_id": tenant_id,
            "counts": {row["status"]: int(row["count"]) for row in rows},
        }

    def list_sync_events(self, tenant_id: int, limit: int = 30) -> list[dict]:
        clean_limit = max(1, min(int(limit or 30), 100))
        rows = self.store.rows(
            """
            SELECT id, tenant_id, store_id, event_type, status, retry_count,
                   last_error, created_at, synced_at, payload
            FROM sync_events
            WHERE tenant_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (tenant_id, clean_limit),
        )
        events: list[dict] = []
        for row in rows:
            item = dict(row)
            try:
                payload = json.loads(item.get("payload") or "{}")
            except json.JSONDecodeError:
                payload = {}
            item["payload"] = payload
            item["summary"] = self._sync_event_summary(item["event_type"], payload)
            events.append(item)
        return events

    def _sync_event_summary(self, event_type: str, payload: dict) -> str:
        if event_type in {"order", "order_created"}:
            return f"新预约订单 #{payload.get('order_id') or payload.get('id') or '-'}"
        if event_type in {"service_record", "order_completed"}:
            return f"完成服务订单 #{payload.get('order_id') or payload.get('id') or '-'}"
        if event_type in {"manual_service_record", "manual_service_recorded"}:
            return f"补录服务 ¥{payload.get('actual_amount') or 0}"
        if event_type in {"ai_gift_record", "ai_gift_granted"}:
            return f"赠送 AI 次数给顾客 {payload.get('customer_id') or '-'}"
        if event_type in {"ai_job_completed", "ai_generation_job"}:
            return f"AI 试发完成 {payload.get('job_no') or '-'}"
        if event_type == "order_created":
            return f"新预约订单 #{payload.get('order_id') or payload.get('id') or '-'}"
        if event_type == "order_completed":
            return f"完成服务订单 #{payload.get('order_id') or payload.get('id') or '-'}"
        if event_type == "manual_service_recorded":
            return f"补录服务 ¥{payload.get('actual_amount') or 0}"
        if event_type == "ai_gift_granted":
            return f"赠送 AI 次数给顾客 {payload.get('customer_id') or '-'}"
        if event_type in {"ai_job_completed", "ai_generation_job"}:
            return f"AI 试发完成 {payload.get('job_no') or '-'}"
        return event_type

    def retry_sync_events(self, tenant_id: int) -> dict:
        with self.store.transaction() as conn:
            pending = conn.execute(
                """
                SELECT * FROM sync_events
                WHERE tenant_id = ? AND status IN ('pending', 'failed')
                ORDER BY id ASC
                """,
                (tenant_id,),
            ).fetchall()
            synced_count = 0
            failed_count = 0
            for event in pending:
                payload = json.loads(event["payload"])
                result = self.feishu.sync_event(event_type=event["event_type"], payload=payload)
                if result.get("ok"):
                    synced_count += 1
                    conn.execute(
                        """
                        UPDATE sync_events
                        SET status = 'synced', retry_count = retry_count + 1, synced_at = CURRENT_TIMESTAMP, last_error = NULL
                        WHERE id = ?
                        """,
                        (event["id"],),
                    )
                else:
                    failed_count += 1
                    conn.execute(
                        """
                        UPDATE sync_events
                        SET status = 'failed', retry_count = retry_count + 1, last_error = ?
                        WHERE id = ?
                        """,
                        ((result.get("error") or "Feishu sync failed")[:255], event["id"]),
                    )
        return {
            "tenant_id": tenant_id,
            "synced_count": synced_count,
            "failed_count": failed_count,
            "provider": self.feishu.provider_name,
        }

    def platform_usage(self, tenant_id: int, month: str | None = None) -> dict:
        # BUG-02: 支持按月过滤，month 格式 YYYY-MM
        month_filter = "AND strftime('%Y-%m', created_at) = ?" if month else ""
        params_base = (tenant_id,) + ((month,) if month else ())
        jobs = self.store.row(
            f"""
            SELECT COUNT(*) AS total_jobs,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_jobs,
                   AVG(queue_wait_seconds) AS avg_queue_wait_seconds,
                   AVG(generate_duration_seconds) AS avg_generate_duration_seconds
            FROM ai_generation_jobs
            WHERE tenant_id = ? {month_filter}
            """,
            params_base,
        )
        cost = self.store.row(
            f"SELECT SUM(internal_api_cost) AS internal_api_cost FROM ai_generation_jobs WHERE tenant_id = ? {month_filter}",
            params_base,
        )
        return {
            "tenant_id": tenant_id,
            "month": month,
            "balance": self.account_balance(tenant_id),
            "total_jobs": int(jobs["total_jobs"] or 0),
            "success_jobs": int(jobs["success_jobs"] or 0),
            "avg_queue_wait_seconds": float(jobs["avg_queue_wait_seconds"] or 0),
            "avg_generate_duration_seconds": float(jobs["avg_generate_duration_seconds"] or 0),
            "internal_api_cost": float(cost["internal_api_cost"] or 0),
        }

    def platform_costs(self, tenant_id: int, month: str | None = None) -> dict:
        # BUG-02: 支持按月过滤
        month_filter = "AND strftime('%Y-%m', created_at) = ?" if month else ""
        params_base = (tenant_id,) + ((month,) if month else ())
        row = self.store.row(
            f"""
            SELECT COUNT(*) AS total_calls,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_calls,
                   SUM(CASE WHEN status IN ('failed', 'timeout') THEN 1 ELSE 0 END) AS failed_calls,
                   SUM(internal_api_cost) AS internal_api_cost,
                   AVG(generate_duration_seconds) AS avg_generate_duration_seconds
            FROM ai_generation_jobs
            WHERE tenant_id = ? {month_filter}
            """,
            params_base,
        )
        success_calls = int(row["success_calls"] or 0)
        internal_api_cost = float(row["internal_api_cost"] or 0)
        return {
            "tenant_id": tenant_id,
            "month": month,
            "total_calls": int(row["total_calls"] or 0),
            "success_calls": success_calls,
            "failed_calls": int(row["failed_calls"] or 0),
            "internal_api_cost": internal_api_cost,
            "average_success_cost": internal_api_cost / success_calls if success_calls else 0,
            "avg_generate_duration_seconds": float(row["avg_generate_duration_seconds"] or 0),
            # 后端自算成本时使用的单张单价（元/张），便于平台核对成本口径。
            "configured_image_unit_cost": self._ai_image_unit_cost,
        }

    def platform_billing(self, tenant_id: int, tenant_settle_unit_price: float = 2.0, month: str | None = None) -> dict:
        # BUG-01: 默认单价改为 ¥2.0；BUG-02: 支持按月过滤
        usage = self.platform_usage(tenant_id, month=month)
        costs = self.platform_costs(tenant_id, month=month)
        ai_service_revenue = usage["success_jobs"] * tenant_settle_unit_price
        return {
            "tenant_id": tenant_id,
            "month": month,
            "success_ai_uses": usage["success_jobs"],
            "tenant_settle_unit_price": tenant_settle_unit_price,
            "ai_service_revenue": ai_service_revenue,
            "internal_api_cost": costs["internal_api_cost"],
            "platform_gross_profit": ai_service_revenue - costs["internal_api_cost"],
            "customer_visible_cost": ai_service_revenue,
        }

    def platform_overview(self, month: str | None = None) -> dict:
        # BUG-02: 支持按月过滤 AI 数据；租户/门店数不做时间过滤
        month_filter = "AND strftime('%Y-%m', created_at) = ?" if month else ""
        month_params = (month,) if month else ()
        tenants = self.store.row(
            """
            SELECT COUNT(*) AS total_tenants,
                   SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_tenants
            FROM tenants
            """
        )
        stores = self.store.row(
            """
            SELECT COUNT(*) AS total_stores,
                   SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_stores
            FROM stores
            """
        )
        jobs = self.store.row(
            f"""
            SELECT COUNT(*) AS total_ai_jobs,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_ai_jobs,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_ai_jobs,
                   SUM(internal_api_cost) AS internal_api_cost
            FROM ai_generation_jobs
            WHERE 1=1 {month_filter}
            """,
            month_params,
        )
        packages = self.store.row(
            """
            SELECT SUM(total_amount) AS package_revenue,
                   SUM(purchased_count) AS purchased_ai_count
            FROM tenant_ai_package_orders
            WHERE payment_status = 'paid'
            """
        )
        bills = self.store.row(
            """
            SELECT SUM(total_bill_amount) AS billed_amount,
                   SUM(platform_gross_profit) AS billed_gross_profit
            FROM tenant_monthly_bills
            """
        )
        accounts = self.store.rows(
            """
            SELECT total_purchased, total_used, total_gifted_adjustment
            FROM tenant_ai_accounts
            """
        )
        total_remaining_balance = sum(
            int(row["total_purchased"]) + int(row["total_gifted_adjustment"]) - int(row["total_used"])
            for row in accounts
        )
        internal_api_cost = float(jobs["internal_api_cost"] or 0)
        package_revenue = float(packages["package_revenue"] or 0)
        billed_amount = float(bills["billed_amount"] or 0)
        # BUG-01: 毛利按 ¥2/组估算
        settle_price = float(os.getenv("PLATFORM_AI_SETTLE_PRICE", "2.0"))
        success_jobs = int(jobs["success_ai_jobs"] or 0)
        estimated_revenue = success_jobs * settle_price
        return {
            "month": month,
            "tenants": {
                "total": int(tenants["total_tenants"] or 0),
                "active": int(tenants["active_tenants"] or 0),
            },
            "stores": {
                "total": int(stores["total_stores"] or 0),
                "active": int(stores["active_stores"] or 0),
            },
            "ai": {
                "total_jobs": int(jobs["total_ai_jobs"] or 0),
                "success_jobs": success_jobs,
                "failed_jobs": int(jobs["failed_ai_jobs"] or 0),
                "remaining_balance": total_remaining_balance,
                "purchased_ai_count": int(packages["purchased_ai_count"] or 0),
            },
            "finance": {
                "settle_price": settle_price,
                "estimated_revenue": estimated_revenue,
                "package_revenue": package_revenue,
                "billed_amount": billed_amount,
                "internal_api_cost": internal_api_cost,
                "estimated_gross_profit": estimated_revenue - internal_api_cost,
                "billed_gross_profit": float(bills["billed_gross_profit"] or 0),
            },
        }

    def billing_summary(self, month: str | None = None) -> dict:
        """FEAT-09: 平台月度计费概览，按租户汇总，用于收费清单"""
        if month is None:
            month = date.today().strftime("%Y-%m")
        settle_price = float(os.getenv("PLATFORM_AI_SETTLE_PRICE", "2.0"))
        tenant_rows = self.store.rows("SELECT id, name FROM tenants WHERE status = 'active' ORDER BY id")
        tenant_list = []
        platform_sets = 0
        platform_cost = 0.0
        for t in tenant_rows:
            tid = int(t["id"])
            row = self.store.row(
                """
                SELECT SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_sets,
                       SUM(internal_api_cost) AS api_cost
                FROM ai_generation_jobs
                WHERE tenant_id = ?
                  AND strftime('%Y-%m', created_at) = ?
                """,
                (tid, month),
            )
            success_sets = int(row["success_sets"] or 0)
            api_cost = float(row["api_cost"] or 0)
            amount_due = round(success_sets * settle_price, 2)
            gross_profit = round(amount_due - api_cost, 2)
            remaining = self.account_balance(tid)
            low_balance_threshold = int(os.getenv("LOW_BALANCE_THRESHOLD", "50"))
            tenant_list.append({
                "tenant_id": tid,
                "tenant_name": str(t["name"] or ""),
                "success_sets": success_sets,
                "amount_due": amount_due,
                "api_cost": round(api_cost, 4),
                "gross_profit": gross_profit,
                "balance_remaining": remaining,
                "balance_warning": remaining <= low_balance_threshold,
            })
            platform_sets += success_sets
            platform_cost += api_cost
        platform_revenue = round(platform_sets * settle_price, 2)
        return {
            "month": month,
            "unit_price": settle_price,
            "tenants": tenant_list,
            "platform_total": {
                "success_sets": platform_sets,
                "amount_due": platform_revenue,
                "api_cost": round(platform_cost, 4),
                "gross_profit": round(platform_revenue - platform_cost, 2),
            },
        }

    def platform_customer_stats(
        self,
        tenant_id: int,
        month: str | None = None,
        store_id: int | None = None,
    ) -> list[dict]:
        """FEAT-01: 按顾客聚合的生成统计（平台视角）"""
        if month is None:
            month = date.today().strftime("%Y-%m")
        settle_price = float(os.getenv("PLATFORM_AI_SETTLE_PRICE", "2.0"))
        store_filter = "AND j.store_id = ?" if store_id else ""
        params = [tenant_id, month] + ([store_id] if store_id else [])
        rows = self.store.rows(
            f"""
            SELECT j.user_id,
                   u.nickname,
                   COUNT(*) AS total_sets,
                   SUM(CASE WHEN j.status = 'success' THEN 1 ELSE 0 END) AS success_sets,
                   SUM(CASE WHEN j.main_status = 'success' THEN 1 ELSE 0 END) AS main_ok,
                   SUM(CASE WHEN j.recommend_1_status = 'success' THEN 1 ELSE 0 END) AS rec1_ok,
                   SUM(CASE WHEN j.recommend_2_status = 'success' THEN 1 ELSE 0 END) AS rec2_ok,
                   ROUND(SUM(j.internal_api_cost), 4) AS cost
            FROM ai_generation_jobs j
            LEFT JOIN users u ON u.id = j.user_id
            WHERE j.tenant_id = ?
              AND strftime('%Y-%m', j.created_at) = ?
              {store_filter}
            GROUP BY j.user_id
            ORDER BY success_sets DESC
            """,
            params,
        )
        result = []
        for r in rows:
            success_sets = int(r["success_sets"] or 0)
            main_ok = int(r["main_ok"] or 0)
            rec1_ok = int(r["rec1_ok"] or 0)
            rec2_ok = int(r["rec2_ok"] or 0)
            cost = float(r["cost"] or 0)
            result.append({
                "user_id": r["user_id"],
                "nickname": r["nickname"] or "未知用户",
                "total_sets": int(r["total_sets"] or 0),
                "success_sets": success_sets,
                "main_ok": main_ok,
                "rec1_ok": rec1_ok,
                "rec2_ok": rec2_ok,
                "total_photos": main_ok + rec1_ok + rec2_ok,
                "cost": cost,
                "revenue": round(success_sets * settle_price, 2),
            })
        return result

    def platform_stats_daily(
        self,
        start: str,
        end: str,
        period: str = "day",
        tenant_id: int | None = None,
    ) -> list[dict]:
        """FEAT-02: 按时间维度的成本统计（平台视角，支持日/周/月）"""
        settle_price = float(os.getenv("PLATFORM_AI_SETTLE_PRICE", "2.0"))
        if period == "week":
            period_expr = "strftime('%Y-W%W', created_at)"
        elif period == "month":
            period_expr = "strftime('%Y-%m', created_at)"
        else:
            period_expr = "DATE(created_at)"
        tenant_filter = "AND tenant_id = ?" if tenant_id else ""
        params: list = [start, end] + ([tenant_id] if tenant_id else [])
        rows = self.store.rows(
            f"""
            SELECT {period_expr} AS period,
                   COUNT(*) AS total_sets,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_sets,
                   SUM(CASE WHEN status IN ('failed','timeout') THEN 1 ELSE 0 END) AS failed_sets,
                   SUM(CASE WHEN main_status = 'success' THEN 1 ELSE 0 END) AS main_ok,
                   SUM(CASE WHEN recommend_1_status = 'success' THEN 1 ELSE 0 END) AS rec1_ok,
                   SUM(CASE WHEN recommend_2_status = 'success' THEN 1 ELSE 0 END) AS rec2_ok,
                   ROUND(SUM(internal_api_cost), 4) AS cost
            FROM ai_generation_jobs
            WHERE DATE(created_at) BETWEEN ? AND ?
              {tenant_filter}
            GROUP BY {period_expr}
            ORDER BY period
            """,
            params,
        )
        result = []
        for r in rows:
            total = int(r["total_sets"] or 0)
            success = int(r["success_sets"] or 0)
            cost = float(r["cost"] or 0)
            revenue = round(success * settle_price, 2)
            result.append({
                "period": r["period"],
                "total_sets": total,
                "success_sets": success,
                "failed_sets": int(r["failed_sets"] or 0),
                "main_ok": int(r["main_ok"] or 0),
                "rec1_ok": int(r["rec1_ok"] or 0),
                "rec2_ok": int(r["rec2_ok"] or 0),
                "total_photos": int(r["main_ok"] or 0) + int(r["rec1_ok"] or 0) + int(r["rec2_ok"] or 0),
                "cost": cost,
                "revenue": revenue,
                "gross_profit": round(revenue - cost, 2),
                "success_rate": f"{success / total * 100:.1f}%" if total else "0%",
            })
        return result

    def platform_jobs(
        self,
        tenant_id: int | None = None,
        store_id: int | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """FEAT-07: 平台生成记录详情，含三张图各自状态，支持按客户/门店过滤"""
        conditions = ["1=1"]
        params: list = []
        if tenant_id:
            conditions.append("j.tenant_id = ?")
            params.append(tenant_id)
        if store_id:
            conditions.append("j.store_id = ?")
            params.append(store_id)
        if status and status != "all":
            conditions.append("j.status = ?")
            params.append(status)
        if date_from:
            conditions.append("DATE(j.created_at) >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("DATE(j.created_at) <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        total_row = self.store.row(
            f"SELECT COUNT(*) AS cnt FROM ai_generation_jobs j WHERE {where}", params
        )
        total = int(total_row["cnt"] or 0)
        offset = (page - 1) * page_size
        rows = self.store.rows(
            f"""
            SELECT j.*, u.nickname, s.name AS store_name, t.name AS tenant_name
            FROM ai_generation_jobs j
            LEFT JOIN users u ON u.id = j.user_id
            LEFT JOIN stores s ON s.id = j.store_id AND s.tenant_id = j.tenant_id
            LEFT JOIN tenants t ON t.id = j.tenant_id
            WHERE {where}
            ORDER BY j.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        )
        items = []
        now_ts = time.time()
        for r in rows:
            images_raw = r["images_json"] if "images_json" in r.keys() else None
            try:
                images = json.loads(images_raw or "[]")
            except Exception:
                images = []
            img_map: dict[str, dict] = {}
            for img in images:
                slot = img.get("slot") or img.get("label") or ""
                img_map[slot] = img
            slot_defs = [
                ("main", "主图"),
                ("natural", "推荐图1（颜色交叉）"),
                ("advanced", "推荐图2（发型交叉）"),
            ]
            slots = []
            for slot_key, slot_label in slot_defs:
                img = img_map.get(slot_key, {})
                url = img.get("temp_image_url") or img.get("url") or img.get("image_url") or None
                # 粗判断 URL 是否过期：OSS 签名 URL 包含 Expires 参数
                url_expired = False
                if url:
                    import re as _re
                    m = _re.search(r"[?&]Expires=(\d+)", url)
                    if m and int(m.group(1)) < now_ts:
                        url_expired = True
                if slot_key == "main":
                    slot_status = r["main_status"] if "main_status" in r.keys() else "pending"
                elif slot_key == "natural":
                    slot_status = r["recommend_1_status"] if "recommend_1_status" in r.keys() else "pending"
                else:
                    slot_status = r["recommend_2_status"] if "recommend_2_status" in r.keys() else "pending"
                slots.append({
                    "slot": slot_key,
                    "label": slot_label,
                    "status": slot_status or "pending",
                    "image_url": url,
                    "url_expired": url_expired,
                    "style_name": img.get("style_name"),
                    "color_name": img.get("color_name"),
                })
            error_raw = r["error_message"] if "error_message" in r.keys() else None
            if error_raw:
                # 简化错误原因，不暴露完整堆栈
                if "ForbiddenInvoke" in error_raw:
                    error_summary = "抠发API权限未激活"
                elif "InvalidFile.Resolution" in error_raw:
                    error_summary = "图片分辨率超限(>2000px)"
                elif "Throttling" in error_raw:
                    error_summary = "API限流(QPS超限)"
                elif "InvalidImage.Region" in error_raw:
                    error_summary = "OSS区域与API不匹配"
                else:
                    error_summary = "生成失败"
            else:
                error_summary = None
            items.append({
                "job_no": r["job_no"],
                "created_at": r["created_at"],
                "tenant_id": r["tenant_id"],
                "tenant_name": r["tenant_name"] or f"客户#{r['tenant_id']}",
                "store_id": r["store_id"],
                "store_name": r["store_name"] or f"门店#{r['store_id']}",
                "user_id": r["user_id"],
                "nickname": r["nickname"] or "未知用户",
                "status": r["status"],
                "billing_type": r["billing_type"],
                "internal_api_cost": float(r["internal_api_cost"] or 0),
                "customer_settle_amount": float(r["customer_settle_amount"] or 0),
                "slots": slots,
                "error_summary": error_summary,
                "error_detail": str(r["error_message"] or "")[:200] if r["error_message"] else None,
            })
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }

    def _assert_paid_order(self, req: GenerateRequest) -> None:
        if not req.pay_order_no:
            raise BusinessError("Paid AI generation requires a paid order")
        row = self.store.row(
            """
            SELECT * FROM ai_payment_orders
            WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND pay_order_no = ? AND pay_status = 'paid'
            """,
            (req.tenant_id, req.store_id, req.user_id, req.pay_order_no),
        )
        if row is None:
            raise BusinessError("Payment order does not exist or is not paid")
        payment = dict(row)
        if payment["generation_job_id"] is None:
            return
        first_job = self.store.row("SELECT status FROM ai_generation_jobs WHERE id = ?", (payment["generation_job_id"],))
        if first_job is None:
            raise BusinessError("Payment order is linked to an invalid generation job")
        if first_job["status"] in {"queued", "running", "success"}:
            raise BusinessError("Payment order has already been used")
        if payment["retry_for_job_id"] is not None:
            raise BusinessError("Payment order free retry has already been used")

    def _attach_payment_order_to_job(self, conn, pay_order_no: str, job_id: int) -> None:
        payment = conn.execute(
            "SELECT * FROM ai_payment_orders WHERE pay_order_no = ?",
            (pay_order_no,),
        ).fetchone()
        if payment is None:
            raise BusinessError("Payment order not found")
        if payment["generation_job_id"] is None:
            conn.execute(
                """
                UPDATE ai_payment_orders
                SET generation_job_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE pay_order_no = ?
                """,
                (job_id, pay_order_no),
            )
            return
        conn.execute(
            """
            UPDATE ai_payment_orders
            SET retry_for_job_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE pay_order_no = ? AND retry_for_job_id IS NULL
            """,
            (job_id, pay_order_no),
        )

    def _assert_generation_limits(self, req: GenerateRequest) -> None:
        limits = self.ai_limits(req.tenant_id, req.store_id)
        active_statuses = ("queued", "running")
        user_active = self.store.row(
            f"""
            SELECT COUNT(*) AS count
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND user_id = ? AND status IN ({",".join("?" for _ in active_statuses)})
            """,
            (req.tenant_id, req.user_id, *active_statuses),
        )
        if int(user_active["count"] or 0) >= int(limits["user_concurrency_limit"]):
            raise BusinessError("User AI generation concurrency limit exceeded")

        store_active = self.store.row(
            f"""
            SELECT COUNT(*) AS count
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND store_id = ? AND status IN ({",".join("?" for _ in active_statuses)})
            """,
            (req.tenant_id, req.store_id, *active_statuses),
        )
        if int(store_active["count"] or 0) >= int(limits["store_concurrency_limit"]):
            raise BusinessError("Store AI generation concurrency limit exceeded")

        tenant_active = self.store.row(
            f"""
            SELECT COUNT(*) AS count
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND status IN ({",".join("?" for _ in active_statuses)})
            """,
            (req.tenant_id, *active_statuses),
        )
        if int(tenant_active["count"] or 0) >= int(limits["tenant_concurrency_limit"]):
            raise BusinessError("Tenant AI generation concurrency limit exceeded")

        platform_active = self.store.row(
            f"""
            SELECT COUNT(*) AS count
            FROM ai_generation_jobs
            WHERE status IN ({",".join("?" for _ in active_statuses)})
            """,
            active_statuses,
        )
        if int(platform_active["count"] or 0) >= int(limits["platform_concurrency_limit"]):
            raise BusinessError("Platform AI generation concurrency limit exceeded")

        today = date.today().isoformat()
        user_count = self.store.row(
            """
            SELECT COUNT(*) AS count
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND user_id = ? AND DATE(created_at) = ? AND status = 'success'
            """,
            (req.tenant_id, req.user_id, today),
        )
        if int(user_count["count"] or 0) >= int(limits["user_daily_limit"]):
            raise BusinessError("User daily AI generation limit exceeded")

        store_limit = self.store.row(
            "SELECT daily_ai_limit FROM stores WHERE id = ? AND tenant_id = ? AND status = 'active'",
            (req.store_id, req.tenant_id),
        )
        if store_limit is None:
            raise BusinessError("Store not found or paused")
        store_count = self.store.row(
            """
            SELECT COUNT(*) AS count
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND store_id = ? AND DATE(created_at) = ? AND status = 'success'
            """,
            (req.tenant_id, req.store_id, today),
        )
        if int(store_count["count"] or 0) >= int(store_limit["daily_ai_limit"]):
            raise BusinessError("Store daily AI generation limit exceeded")

        tenant_count = self.store.row(
            """
            SELECT COUNT(*) AS count
            FROM ai_generation_jobs
            WHERE tenant_id = ? AND DATE(created_at) = ? AND status = 'success'
            """,
            (req.tenant_id, today),
        )
        if int(tenant_count["count"] or 0) >= int(limits["tenant_daily_limit"]):
            raise BusinessError("Tenant daily AI generation limit exceeded")

    def _assert_free_quota(self, req: GenerateRequest) -> None:
        if not dev_allow_free_without_visit() and not self.has_active_store_visit(req.tenant_id, req.store_id, req.user_id):
            raise BusinessError("Free AI generation requires an active in-store QR scan")
        quota = self.quota_today(req.tenant_id, req.store_id, req.user_id)
        if quota["free_remaining"] <= 0:
            raise BusinessError("Daily free AI generation quota is used up")

    def _assert_gift_quota(self, req: GenerateRequest) -> None:
        row = self.store.row(
            """
            SELECT * FROM ai_gift_records
            WHERE tenant_id = ? AND store_id = ? AND customer_id = ? AND status = 'unused'
            ORDER BY id ASC LIMIT 1
            """,
            (req.tenant_id, req.store_id, req.user_id),
        )
        if row is None:
            raise BusinessError("No unused gift AI generation quota")

    def _staff_quota_today(self, tenant_id: int, store_id: int, staff_id: int) -> dict:
        today = date.today().isoformat()
        row = self.store.row(
            """
            SELECT * FROM staff_gift_quotas
            WHERE tenant_id = ? AND store_id = ? AND staff_id = ? AND quota_date = ?
            """,
            (tenant_id, store_id, staff_id, today),
        )
        if row is None:
            with self.store.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO staff_gift_quotas (tenant_id, store_id, staff_id, quota_date)
                    VALUES (?, ?, ?, ?)
                    """,
                    (tenant_id, store_id, staff_id, today),
                )
            row = self.store.row(
                """
                SELECT * FROM staff_gift_quotas
                WHERE tenant_id = ? AND store_id = ? AND staff_id = ? AND quota_date = ?
                """,
                (tenant_id, store_id, staff_id, today),
            )
        assert row is not None
        return dict(row)

    def _deduct_successful_job(self, job_no: str, billing_type: BillingType) -> None:
        with self._deduct_lock:
            with self.store.transaction() as conn:
                job = conn.execute("SELECT * FROM ai_generation_jobs WHERE job_no = ?", (job_no,)).fetchone()
                if job is None:
                    raise BusinessError("Generation job not found")
                if int(job["is_count_deducted"]):
                    return
                account = conn.execute(
                    "SELECT * FROM tenant_ai_accounts WHERE tenant_id = ?",
                    (job["tenant_id"],),
                ).fetchone()
                if account is None:
                    raise BusinessError("Tenant AI account does not exist")
                balance = (
                    int(account["total_purchased"])
                    + int(account["total_gifted_adjustment"])
                    - int(account["total_used"])
                )
                if balance <= 0:
                    raise BusinessError("Tenant AI balance is not enough")
                new_balance = balance - 1
                conn.execute(
                    """
                    UPDATE tenant_ai_accounts
                    SET total_used = total_used + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = ?
                    """,
                    (job["tenant_id"],),
                )
                conn.execute(
                    """
                    INSERT INTO tenant_ai_usage_logs
                    (tenant_id, store_id, user_id, generation_job_id, usage_type, change_count,
                     balance_after, internal_api_cost)
                    VALUES (?, ?, ?, ?, ?, -1, ?, ?)
                    """,
                    (
                        job["tenant_id"],
                        job["store_id"],
                        job["user_id"],
                        job["id"],
                        billing_type.value,
                        new_balance,
                        job["internal_api_cost"],
                    ),
                )
                # BUG-03: 写入客户应收金额（从环境变量读取单价，默认 ¥2.0）
                settle_price = float(os.getenv("PLATFORM_AI_SETTLE_PRICE", "2.0"))
                conn.execute(
                    """
                    UPDATE ai_generation_jobs
                    SET is_count_deducted = 1, customer_settle_amount = ?
                    WHERE id = ?
                    """,
                    (settle_price, job["id"]),
                )
                if job["selected_style_id"]:
                    self._insert_asset_event(
                        conn,
                        tenant_id=job["tenant_id"],
                        store_id=job["store_id"],
                        user_id=job["user_id"],
                        asset_type="hairstyle",
                        asset_id=job["selected_style_id"],
                        event_type="generate",
                        generation_job_id=job["id"],
                    )
                if job["selected_color_id"]:
                    self._insert_asset_event(
                        conn,
                        tenant_id=job["tenant_id"],
                        store_id=job["store_id"],
                        user_id=job["user_id"],
                        asset_type="hair_color",
                        asset_id=job["selected_color_id"],
                        event_type="generate",
                        generation_job_id=job["id"],
                    )
                today = date.today().isoformat()
                if billing_type == BillingType.FREE:
                    conn.execute(
                        """
                        UPDATE ai_user_daily_quota
                        SET free_used = free_used + 1, updated_at = CURRENT_TIMESTAMP
                        WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND quota_date = ?
                        """,
                        (job["tenant_id"], job["store_id"], job["user_id"], today),
                    )
                elif billing_type == BillingType.GIFT:
                    conn.execute(
                        """
                        UPDATE ai_user_daily_quota
                        SET gift_used = gift_used + 1, updated_at = CURRENT_TIMESTAMP
                        WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND quota_date = ?
                        """,
                        (job["tenant_id"], job["store_id"], job["user_id"], today),
                    )
                    gift = conn.execute(
                        """
                        SELECT * FROM ai_gift_records
                        WHERE tenant_id = ? AND store_id = ? AND customer_id = ? AND status = 'unused'
                        ORDER BY id ASC LIMIT 1
                        """,
                        (job["tenant_id"], job["store_id"], job["user_id"]),
                    ).fetchone()
                    if gift is not None:
                        conn.execute(
                            """
                            UPDATE ai_gift_records
                            SET status = 'used', used_at = CURRENT_TIMESTAMP, generation_job_id = ?
                            WHERE id = ?
                            """,
                            (job["id"], gift["id"]),
                        )
                elif billing_type == BillingType.PAID:
                    conn.execute(
                        """
                        UPDATE ai_user_daily_quota
                        SET paid_used = paid_used + 1, updated_at = CURRENT_TIMESTAMP
                        WHERE tenant_id = ? AND store_id = ? AND user_id = ? AND quota_date = ?
                        """,
                        (job["tenant_id"], job["store_id"], job["user_id"], today),
                    )
        # 订阅配额计数（事务外调用，失败不影响主流程）
        try:
            self.increment_monthly_ai_usage(int(job["tenant_id"]))
        except Exception:
            pass
