from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol

from .models import GenerationImage, GenerationResult, JobStatus


class HairImageProvider(Protocol):
    def generate_hair_images(
        self,
        *,
        job_no: str,
        direction: str,
        selected_style: dict | None,
        selected_color: dict | None,
        recommendations: list[dict],
        photo_temp_url: str | None = None,
        customer_reference_url: str | None = None,
        customer_reference_type: str | None = None,
        hair_profile: dict | None = None,
    ) -> GenerationResult:
        ...


class MockDifyClient:
    """POC-safe provider used until real Dify credentials are configured."""

    provider_name = "mock"

    def generate_hair_images(
        self,
        *,
        job_no: str,
        direction: str,
        selected_style: dict | None,
        selected_color: dict | None,
        recommendations: list[dict],
        photo_temp_url: str | None = None,
        customer_reference_url: str | None = None,
        customer_reference_type: str | None = None,
        hair_profile: dict | None = None,
    ) -> GenerationResult:
        main_style = selected_style or {}
        main_color = selected_color or {}
        images = [
            GenerationImage(
                slot="main",
                title="Selected style",
                direction=direction,
                style_id=main_style.get("style_id"),
                style_name=main_style.get("style_name"),
                color_id=main_color.get("color_id"),
                color_name=main_color.get("color_name"),
                temp_image_url=f"https://temp.local/{job_no}/main.jpg",
            )
        ]

        for item in recommendations:
            images.append(
                GenerationImage(
                    slot=item["slot"],
                    title=item["title"],
                    direction=direction,
                    style_id=item.get("style_id"),
                    style_name=item.get("style_name"),
                    color_id=item.get("color_id"),
                    color_name=item.get("color_name"),
                    temp_image_url=f"https://temp.local/{job_no}/{item['slot']}.jpg",
                )
            )

        return GenerationResult(
            status=JobStatus.SUCCESS,
            images=images,
            internal_api_cost=0.45,
        )


class DifyWorkflowClient:
    """Real Dify workflow client for WF-01 hair image generation."""

    provider_name = "dify"

    def __init__(self, base_url: str, api_key: str, timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate_hair_images(
        self,
        *,
        job_no: str,
        direction: str,
        selected_style: dict | None,
        selected_color: dict | None,
        recommendations: list[dict],
        photo_temp_url: str | None = None,
        customer_reference_url: str | None = None,
        customer_reference_type: str | None = None,
        hair_profile: dict | None = None,
    ) -> GenerationResult:
        workflow_selected_style = selected_style
        if customer_reference_url:
            workflow_selected_style = dict(selected_style or {})
            workflow_selected_style["thumbnail_url"] = customer_reference_url
            if customer_reference_type == "hair_color":
                workflow_selected_style.setdefault("style_name", "顾客自带参考发色")
                workflow_selected_style["customer_description"] = (
                    "只参考顾客上传图片中的头发颜色、明暗层次和染发质感；"
                    "不参考参考图人物的发型结构、脸、五官、表情、皮肤、身体、衣服和背景。"
                )
            else:
                workflow_selected_style.setdefault("style_name", "顾客自带参考发型")
                workflow_selected_style["customer_description"] = (
                    "参考顾客上传图片中的发型轮廓、发长、刘海、分缝、卷度、层次和发量感；"
                    "只参考发型结构，不参考参考图人物的脸、五官、表情、皮肤、身体、衣服和背景。"
                )
            workflow_selected_style["ai_reference_tags"] = [
                "customer uploaded hair color reference" if customer_reference_type == "hair_color" else "customer uploaded hairstyle reference",
                "copy hair color only" if customer_reference_type == "hair_color" else "copy hairstyle only",
                "preserve the customer's original face",
                "do not copy the reference person's face",
            ]
        payload = {
            "inputs": {
                "job_no": job_no,
                "direction": direction,
                "selected_style": json.dumps(workflow_selected_style or {}, ensure_ascii=False),
                "selected_color": json.dumps(selected_color or {}, ensure_ascii=False),
                "recommendations": json.dumps(recommendations, ensure_ascii=False),
                "hair_profile": json.dumps(hair_profile or {}, ensure_ascii=False),
                "photo_temp_url": photo_temp_url,
                "customer_reference_url": customer_reference_url,
                "customer_reference_type": customer_reference_type,
            },
            "response_mode": "blocking",
            "user": f"hair-ai-{job_no}",
        }
        response = self._post_json("/v1/workflows/run", payload)
        return self._parse_generation_result(job_no, response)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            return {
                "status": "failed",
                "error_code": f"DIFY_HTTP_{exc.code}",
                "error_message": error_body[:300],
            }
        except urllib.error.URLError as exc:
            return {
                "status": "failed",
                "error_code": "DIFY_NETWORK_ERROR",
                "error_message": str(exc.reason),
            }

        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {
                "status": "failed",
                "error_code": "DIFY_INVALID_JSON",
                "error_message": body[:300],
            }

    def _parse_generation_result(self, job_no: str, response: dict[str, Any]) -> GenerationResult:
        if response.get("status") == "failed":
            return GenerationResult(
                status=JobStatus.FAILED,
                images=[],
                internal_api_cost=0,
                error_code=response.get("error_code") or "DIFY_WORKFLOW_FAILED",
                error_message=response.get("error_message") or "Dify workflow failed",
            )

        outputs = response.get("data", {}).get("outputs", response.get("outputs", response))
        raw_result = outputs.get("result", outputs)
        if isinstance(raw_result, str):
            try:
                raw_result = json.loads(raw_result)
            except json.JSONDecodeError:
                return GenerationResult(
                    status=JobStatus.FAILED,
                    images=[],
                    internal_api_cost=0,
                    error_code="DIFY_RESULT_INVALID_JSON",
                error_message=raw_result[:300],
            )

        if not isinstance(raw_result, dict):
            return GenerationResult(
                status=JobStatus.FAILED,
                images=[],
                internal_api_cost=0,
                error_code="DIFY_RESULT_INVALID_SCHEMA",
                error_message="Dify result must be a JSON object",
            )

        if raw_result.get("status") != "success":
            return GenerationResult(
                status=JobStatus.FAILED,
                images=[],
                internal_api_cost=float(raw_result.get("internal_api_cost") or 0),
                error_code=raw_result.get("error_code") or "IMAGE_GENERATION_FAILED",
                error_message=raw_result.get("error_message") or "Image generation failed",
            )

        images_result = self._parse_success_images(raw_result)
        if isinstance(images_result, GenerationResult):
            return images_result
        return GenerationResult(
            status=JobStatus.SUCCESS,
            images=images_result,
            internal_api_cost=float(raw_result.get("internal_api_cost") or 0),
        )

    def _parse_success_images(self, raw_result: dict[str, Any]) -> list[GenerationImage] | GenerationResult:
        raw_images = raw_result.get("images")
        internal_api_cost = float(raw_result.get("internal_api_cost") or 0)
        if not isinstance(raw_images, list):
            return self._invalid_schema("Dify result images must be a list", internal_api_cost)
        if not 1 <= len(raw_images) <= 3:
            return self._invalid_schema("Dify result must contain between 1 and 3 images", internal_api_cost)

        allowed_slots = {"main", "natural", "advanced"}
        slot_positions = {"main": 0, "natural": 1, "advanced": 2}
        images: list[GenerationImage] = []
        seen_slots: set[str] = set()
        for index, item in enumerate(raw_images):
            if not isinstance(item, dict):
                return self._invalid_schema("Each Dify image item must be an object", internal_api_cost)
            slot = item.get("slot")
            temp_image_url = item.get("temp_image_url")
            if (
                slot not in allowed_slots
                or slot in seen_slots
                or (index == 0 and slot != "main")
                or (images and slot_positions[slot] <= slot_positions[images[-1].slot])
            ):
                return self._invalid_schema(
                    "Dify image slots must start with main and use known slots",
                    internal_api_cost,
                )
            seen_slots.add(slot)
            if not isinstance(temp_image_url, str) or not temp_image_url.strip():
                return self._invalid_schema("Each Dify image item must include temp_image_url", internal_api_cost)
            images.append(
                GenerationImage(
                    slot=slot,
                    title=item.get("title") or slot,
                    direction=item.get("direction") or "",
                    style_id=item.get("style_id"),
                    style_name=item.get("style_name"),
                    color_id=item.get("color_id"),
                    color_name=item.get("color_name"),
                    temp_image_url=temp_image_url,
                )
            )
        return images

    def _invalid_schema(self, message: str, internal_api_cost: float = 0) -> GenerationResult:
        return GenerationResult(
            status=JobStatus.FAILED,
            images=[],
            internal_api_cost=internal_api_cost,
            error_code="DIFY_RESULT_INVALID_SCHEMA",
            error_message=message,
        )


def build_dify_client_from_env(service=None) -> HairImageProvider:
    """构建 Dify 客户端。
    优先从数据库（api_key_configs）读取 api_key，数据库没有则回落到环境变量。
    service 传入后，每次 workflow 调用前重新解析密钥（支持后台热更新）。
    """
    base_url = os.getenv("DIFY_BASE_URL", "")

    def _resolve_key() -> str:
        if service is not None:
            try:
                return service.resolve_key("dify", "api_key", "DIFY_API_KEY")
            except Exception:
                pass
        return os.getenv("DIFY_API_KEY", "")

    if not base_url:
        return MockDifyClient()

    # 包装成惰性客户端：每次调用前重新拿密钥，确保后台改密钥立即生效
    class _LazyDifyClient(HairImageProvider):
        @property
        def provider_name(self) -> str:
            return "dify_lazy"

        def generate_hair_images(self, *args, **kwargs):
            api_key = _resolve_key()
            if not api_key:
                return MockDifyClient().generate_hair_images(*args, **kwargs)
            timeout_seconds = int(os.getenv("DIFY_TIMEOUT_SECONDS", "60"))
            return DifyWorkflowClient(
                base_url=base_url, api_key=api_key, timeout_seconds=timeout_seconds
            ).generate_hair_images(*args, **kwargs)

    # 如果没有传 service，用旧的静态方式（兼容现有逻辑）
    if service is None:
        api_key = os.getenv("DIFY_API_KEY", "")
        if api_key:
            timeout_seconds = int(os.getenv("DIFY_TIMEOUT_SECONDS", "60"))
            return DifyWorkflowClient(base_url=base_url, api_key=api_key, timeout_seconds=timeout_seconds)
        return MockDifyClient()

    return _LazyDifyClient()
