from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import os
from threading import Lock

from .models import BillingType, Direction, GenerateRequest


@dataclass(frozen=True)
class QueuedGenerationJob:
    job_no: str
    request: GenerateRequest


class InMemoryAiJobQueue:
    """Redis replacement for local MVP tests. Keep the interface small."""

    def __init__(self) -> None:
        self._items: deque[QueuedGenerationJob] = deque()
        self._lock = Lock()

    def push(self, job: QueuedGenerationJob) -> int:
        with self._lock:
            self._items.append(job)
            return len(self._items)

    def pop(self) -> QueuedGenerationJob | None:
        with self._lock:
            if not self._items:
                return None
            return self._items.popleft()

    def remove(self, job_no: str) -> None:
        with self._lock:
            self._items = deque(item for item in self._items if item.job_no != job_no)

    def size(self) -> int:
        with self._lock:
            return len(self._items)


class RedisAiJobQueue:
    def __init__(self, redis_url: str, queue_name: str = "hair_ai:generation_jobs") -> None:
        import redis

        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._queue_name = queue_name

    def push(self, job: QueuedGenerationJob) -> int:
        self._redis.rpush(self._queue_name, self._serialize(job))
        return self.size()

    def pop(self) -> QueuedGenerationJob | None:
        raw = self._redis.lpop(self._queue_name)
        if raw is None:
            return None
        return self._deserialize(raw)

    def remove(self, job_no: str) -> None:
        items = []
        while True:
            raw = self._redis.lpop(self._queue_name)
            if raw is None:
                break
            job = self._deserialize(raw)
            if job.job_no != job_no:
                items.append(raw)
        if items:
            self._redis.rpush(self._queue_name, *items)

    def size(self) -> int:
        return int(self._redis.llen(self._queue_name))

    def _serialize(self, job: QueuedGenerationJob) -> str:
        req = job.request
        return json.dumps(
            {
                "job_no": job.job_no,
                "request": {
                    "tenant_id": req.tenant_id,
                    "store_id": req.store_id,
                    "user_id": req.user_id,
                    "direction": req.direction.value,
                    "billing_type": req.billing_type.value,
                    "selected_style_id": req.selected_style_id,
                    "selected_color_id": req.selected_color_id,
                    "photo_temp_url": req.photo_temp_url,
                    "customer_reference_url": req.customer_reference_url,
                    "customer_reference_type": req.customer_reference_type,
                    "hair_profile": req.hair_profile,
                    "pay_order_no": req.pay_order_no,
                },
            },
            ensure_ascii=False,
        )

    def _deserialize(self, raw: str) -> QueuedGenerationJob:
        data = json.loads(raw)
        req = data["request"]
        return QueuedGenerationJob(
            job_no=data["job_no"],
            request=GenerateRequest(
                tenant_id=req["tenant_id"],
                store_id=req["store_id"],
                user_id=req["user_id"],
                direction=Direction(req["direction"]),
                billing_type=BillingType(req["billing_type"]),
                selected_style_id=req.get("selected_style_id"),
                selected_color_id=req.get("selected_color_id"),
                photo_temp_url=req.get("photo_temp_url"),
                customer_reference_url=req.get("customer_reference_url"),
                customer_reference_type=req.get("customer_reference_type"),
                hair_profile=req.get("hair_profile") or {},
                pay_order_no=req.get("pay_order_no"),
            ),
        )


def build_queue_from_env() -> InMemoryAiJobQueue | RedisAiJobQueue:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return RedisAiJobQueue(redis_url)
    return InMemoryAiJobQueue()
