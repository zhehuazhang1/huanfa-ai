from dataclasses import dataclass
from enum import Enum
from typing import Any


class BillingType(str, Enum):
    FREE = "free"
    GIFT = "gift"
    PAID = "paid"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Direction(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class GenerateRequest:
    tenant_id: int
    store_id: int
    user_id: int
    direction: Direction
    billing_type: BillingType
    selected_style_id: str | None
    selected_color_id: str | None
    photo_temp_url: str | None = None
    customer_reference_url: str | None = None
    customer_reference_type: str | None = None
    hair_profile: dict[str, str] | None = None
    pay_order_no: str | None = None


@dataclass(frozen=True)
class GenerationImage:
    slot: str
    title: str
    direction: str
    style_id: str | None
    style_name: str | None
    color_id: str | None
    color_name: str | None
    temp_image_url: str


@dataclass(frozen=True)
class GenerationResult:
    status: JobStatus
    images: list[GenerationImage]
    internal_api_cost: float
    error_code: str | None = None
    error_message: str | None = None


JsonDict = dict[str, Any]
