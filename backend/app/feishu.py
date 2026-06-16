from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from typing import Protocol


class FeishuSyncProvider(Protocol):
    provider_name: str

    def sync_event(self, *, event_type: str, payload: dict) -> dict:
        ...


class MockFeishuSyncProvider:
    provider_name = "mock"

    def sync_event(self, *, event_type: str, payload: dict) -> dict:
        return {
            "ok": True,
            "provider": self.provider_name,
            "event_type": event_type,
            "remote_id": f"mock_{event_type}",
        }


class FeishuWebhookSyncProvider:
    provider_name = "feishu_webhook"

    def __init__(self, webhook_url: str, secret: str = "", timeout_seconds: int = 8) -> None:
        self.webhook_url = webhook_url
        self.secret = secret.strip()
        self.timeout_seconds = timeout_seconds

    def sync_event(self, *, event_type: str, payload: dict) -> dict:
        body_payload = self._message_payload(event_type, payload)
        body = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            return {
                "ok": False,
                "provider": self.provider_name,
                "error": str(exc.reason),
            }
        return {
            "ok": 200 <= response.status < 300,
            "provider": self.provider_name,
            "status_code": response.status,
            "response": response_body[:300],
        }

    def _message_payload(self, event_type: str, payload: dict) -> dict:
        message: dict = {
            "msg_type": "text",
            "content": {
                "text": self._message_text(event_type, payload),
            },
        }
        if self.secret:
            timestamp = str(int(time.time()))
            message["timestamp"] = timestamp
            message["sign"] = self._sign(timestamp)
        return message

    def _sign(self, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{self.secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"),
            b"",
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _message_text(self, event_type: str, payload: dict) -> str:
        title = EVENT_TITLES.get(event_type, event_type)
        lines = [
            f"【焕发AI门店通知】{title}",
            f"事件类型：{event_type}",
        ]
        for label, key in DISPLAY_FIELDS:
            value = payload.get(key)
            if value not in (None, ""):
                lines.append(f"{label}：{value}")
        compact_payload = json.dumps(payload, ensure_ascii=False, default=str)
        if len(compact_payload) > 800:
            compact_payload = compact_payload[:800] + "..."
        lines.append(f"原始数据：{compact_payload}")
        return "\n".join(lines)


def build_feishu_sync_provider_from_env() -> FeishuSyncProvider:
    provider = (os.getenv("FEISHU_SYNC_PROVIDER") or "mock").lower()
    if provider == "mock":
        return MockFeishuSyncProvider()
    if provider in {"webhook", "feishu_webhook"}:
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "")
        if not webhook_url:
            raise RuntimeError("Missing FEISHU_WEBHOOK_URL")
        secret = os.getenv("FEISHU_WEBHOOK_SECRET") or os.getenv("FEISHU_WEBHOOK_SIGN_SECRET") or ""
        return FeishuWebhookSyncProvider(webhook_url=webhook_url, secret=secret)
    raise RuntimeError(f"Unsupported FEISHU_SYNC_PROVIDER: {provider}")


EVENT_TITLES = {
    "ai_generation_job": "AI试发完成",
    "ai_job_completed": "AI试发完成",
    "order": "顾客提交预约",
    "order_created": "顾客提交预约",
    "service_record": "服务完成入账",
    "order_completed": "服务完成入账",
    "manual_service_record": "线下服务补录",
    "manual_service_recorded": "线下服务补录",
    "ai_gift_record": "赠送AI试发次数",
    "ai_gift_granted": "赠送AI试发次数",
}


DISPLAY_FIELDS = [
    ("门店ID", "store_id"),
    ("顾客ID", "customer_id"),
    ("用户ID", "user_id"),
    ("主理人ID", "stylist_id"),
    ("订单ID", "order_id"),
    ("服务项目ID", "service_item_id"),
    ("AI任务号", "job_no"),
    ("状态", "status"),
    ("试发类型", "billing_type"),
    ("生成耗时", "generate_duration_seconds"),
    ("队列等待", "queue_wait_seconds"),
    ("是否扣次", "is_count_deducted"),
    ("内部成本", "internal_api_cost"),
    ("服务金额", "actual_amount"),
    ("预约时间", "appointment_time"),
    ("完成时间", "completed_at"),
    ("来源", "source"),
    ("备注", "notes"),
]
