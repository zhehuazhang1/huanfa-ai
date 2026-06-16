from __future__ import annotations

import io
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.request import urlopen

import httpx

from .storage import StorageError, TempStorageProvider


_SEGMENT_HAIR_RATE_LOCK = threading.Lock()
_SEGMENT_HAIR_LAST_CALL = 0.0
_SEGMENT_HAIR_MIN_INTERVAL_SECONDS = 0.6
_SEGMENT_HAIR_MAX_ATTEMPTS = 3


def wait_for_segment_hair_slot() -> None:
    global _SEGMENT_HAIR_LAST_CALL

    with _SEGMENT_HAIR_RATE_LOCK:
        delay = _SEGMENT_HAIR_MIN_INTERVAL_SECONDS - (time.monotonic() - _SEGMENT_HAIR_LAST_CALL)
        if delay > 0:
            time.sleep(delay)
        _SEGMENT_HAIR_LAST_CALL = time.monotonic()


class HairTryOnError(RuntimeError):
    pass


@dataclass
class HairTryOnResult:
    image_url: str
    segment_mask_url: str
    wanx_task_id: str


@dataclass
class FaceGeometry:
    box: tuple[int, int, int, int]
    landmarks: tuple[float, ...]


@dataclass
class FaceComparison:
    confidence: float
    threshold: float
    original_geometry: FaceGeometry
    generated_geometry: FaceGeometry


class AliyunHairTryOnProvider:
    """Segment hair, build a full-size edit mask, then run Wanxiang inpainting."""

    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        dashscope_api_key: str,
        storage: TempStorageProvider,
        imageseg_endpoint: str = "imageseg.cn-shanghai.aliyuncs.com",
        dashscope_base_url: str = "https://dashscope.aliyuncs.com",
        timeout_seconds: int = 180,
    ) -> None:
        from alibabacloud_imageseg20191230.client import Client as ImageSegClient
        from alibabacloud_facebody20191230.client import Client as FaceBodyClient
        from alibabacloud_tea_openapi import models as open_api_models

        config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        config.endpoint = imageseg_endpoint
        self.imageseg = ImageSegClient(config)
        facebody_config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        facebody_config.endpoint = "facebody.cn-shanghai.aliyuncs.com"
        self.facebody = FaceBodyClient(facebody_config)
        self.dashscope_api_key = dashscope_api_key
        self.dashscope_base_url = dashscope_base_url.rstrip("/")
        self.storage = storage
        self.timeout_seconds = timeout_seconds

    def generate(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        photo_temp_url: str,
        hairstyle: str | None,
        hair_color: str | None,
        hair_profile: dict | None = None,
        reference_type: str | None = None,
        hairstyle_reference_url: str | None = None,
    ) -> HairTryOnResult:
        if hairstyle_reference_url:
            if os.getenv("ALIYUN_WAN27_REFERENCE_OUTPUT_MODE", "composite") == "native":
                return self._generate_native_reference_result(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    user_id=user_id,
                    photo_temp_url=photo_temp_url,
                    hairstyle_reference_url=hairstyle_reference_url,
                    hairstyle=hairstyle,
                    hair_color=hair_color,
                    hair_profile=hair_profile,
                    reference_type=reference_type,
                )
            task_id = self._submit_wan27_reference_task(
                photo_temp_url=photo_temp_url,
                hairstyle_reference_url=hairstyle_reference_url,
                prompt=build_reference_hair_edit_prompt(hairstyle, hair_color, hair_profile, reference_type),
            )
            generated_url = self._wait_for_wan27_result(task_id)
            generated_transfer_bytes = optimize_image_for_upload(
                download_bytes(generated_url),
                max_dimension=2048,
                quality=95,
            )
            generated_shanghai_url = self.storage.upload_temp_bytes(
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                file_ext="jpg",
                content=generated_transfer_bytes,
                content_type="image/jpeg",
            )
            try:
                composite_bytes = self._compose_reference_result(
                    original_url=photo_temp_url,
                    generated_url=generated_shanghai_url,
                )
            finally:
                try:
                    self.storage.delete_temp_asset(generated_shanghai_url)
                except StorageError:
                    pass
            return HairTryOnResult(
                image_url=self.storage.upload_temp_bytes(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    user_id=user_id,
                    file_ext="jpg",
                    content=optimize_image_for_upload(
                        composite_bytes,
                        max_dimension=None,
                        quality=96,
                    ),
                    content_type="image/jpeg",
                ),
                segment_mask_url="",
                wanx_task_id=task_id,
            )
        mask_url = self._create_mask_url(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            photo_temp_url=photo_temp_url,
        )
        try:
            task_id = self._submit_wanx_task(
                photo_temp_url=photo_temp_url,
                mask_url=mask_url,
                prompt=build_hair_edit_prompt(hairstyle, hair_color, hair_profile),
            )
            image_url = self._wait_for_wanx_result(task_id)
            return HairTryOnResult(
                image_url=image_url,
                segment_mask_url=mask_url,
                wanx_task_id=task_id,
            )
        finally:
            try:
                self.storage.delete_temp_asset(mask_url)
            except StorageError:
                pass

    def _generate_native_reference_result(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        photo_temp_url: str,
        hairstyle_reference_url: str,
        hairstyle: str | None,
        hair_color: str | None,
        hair_profile: dict | None = None,
        reference_type: str | None = None,
    ) -> HairTryOnResult:
        face_qc_enabled = os.getenv("ALIYUN_WAN27_NATIVE_FACE_QC", "true").lower() not in {"0", "false", "no"}
        max_attempts = 2 if face_qc_enabled else 1
        last_reason = ""
        reference_url_for_model = hairstyle_reference_url
        cleanup_reference_url = ""
        if os.getenv("ALIYUN_WAN27_HAIR_ONLY_REFERENCE", "true").lower() not in {"0", "false", "no"}:
            reference_url_for_model = self._create_hair_only_reference_url(
                tenant_id=tenant_id,
                store_id=store_id,
                user_id=user_id,
                hairstyle_reference_url=hairstyle_reference_url,
            )
            cleanup_reference_url = reference_url_for_model

        try:
            for attempt in range(max_attempts):
                prompt = build_reference_hair_edit_prompt(hairstyle, hair_color, hair_profile, reference_type)
                if attempt:
                    prompt += " RETRY REQUIREMENT: the previous result changed the customer's face. Preserve IMAGE 2 facial identity exactly."
                task_id = self._submit_wan27_reference_task(
                    photo_temp_url=photo_temp_url,
                    hairstyle_reference_url=reference_url_for_model,
                    prompt=prompt,
                )
                generated_url = self._wait_for_wan27_result(task_id)
                if not face_qc_enabled:
                    return HairTryOnResult(image_url=generated_url, segment_mask_url="", wanx_task_id=task_id)

                passed, last_reason = self._check_native_face_quality(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    user_id=user_id,
                    original_url=photo_temp_url,
                    generated_url=generated_url,
                )
                if passed:
                    return HairTryOnResult(image_url=generated_url, segment_mask_url="", wanx_task_id=task_id)
        finally:
            if cleanup_reference_url:
                try:
                    self.storage.delete_temp_asset(cleanup_reference_url)
                except StorageError:
                    pass

        raise HairTryOnError(f"Wanxiang native face quality check failed after retry: {last_reason}")

    def _create_hair_only_reference_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        hairstyle_reference_url: str,
    ) -> str:
        element = self._segment_hair(hairstyle_reference_url)
        hair_only_bytes = build_hair_only_reference_image(
            reference_bytes=download_bytes(hairstyle_reference_url),
            hair_rgba_bytes=download_bytes(element.image_url),
            x=int(element.x),
            y=int(element.y),
            width=int(element.width),
            height=int(element.height),
        )
        return self.storage.upload_temp_bytes(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            file_ext="png",
            content=hair_only_bytes,
            content_type="image/png",
        )

    def _check_native_face_quality(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        original_url: str,
        generated_url: str,
    ) -> tuple[bool, str]:
        generated_transfer_bytes = optimize_image_for_upload(
            download_bytes(generated_url),
            max_dimension=1536,
            quality=90,
        )
        generated_shanghai_url = self.storage.upload_temp_bytes(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            file_ext="jpg",
            content=generated_transfer_bytes,
            content_type="image/jpeg",
        )
        try:
            face_compare_enabled = os.getenv("ALIYUN_WAN27_FACE_COMPARE_QC", "false").lower() not in {"0", "false", "no"}
            if face_compare_enabled:
                comparison = self._compare_faces(original_url, generated_shanghai_url)
                if comparison.confidence < comparison.threshold:
                    return False, f"face identity confidence {comparison.confidence:.3f} below {comparison.threshold:.3f}"
                return compare_face_geometry(comparison.original_geometry, comparison.generated_geometry)
            return compare_face_geometry(
                self._detect_face_geometry(original_url),
                self._detect_face_geometry(generated_shanghai_url),
            )
        finally:
            try:
                self.storage.delete_temp_asset(generated_shanghai_url)
            except StorageError:
                pass

    def _compare_faces(self, original_url: str, generated_url: str) -> FaceComparison:
        from alibabacloud_facebody20191230.models import CompareFaceRequest
        from alibabacloud_tea_util import models as util_models

        try:
            response = self.facebody.compare_face_with_options(
                CompareFaceRequest(image_urla=original_url, image_urlb=generated_url),
                util_models.RuntimeOptions(),
            )
        except Exception as exc:  # pragma: no cover - depends on Aliyun SDK
            raise HairTryOnError(f"CompareFace request failed: {exc}") from exc
        data = getattr(response.body, "data", None)
        if data is None:
            raise HairTryOnError("CompareFace returned no result")
        thresholds = getattr(data, "thresholds", None) or []
        dynamic_threshold = float(thresholds[0]) if thresholds else 0.0
        minimum_threshold = float(os.getenv("ALIYUN_WAN27_FACE_QC_MIN_IDENTITY_CONFIDENCE", "61"))
        return FaceComparison(
            confidence=float(getattr(data, "confidence", 0.0) or 0.0),
            threshold=max(dynamic_threshold, minimum_threshold),
            original_geometry=face_geometry_from_compare_result(
                getattr(data, "rect_alist", None),
                getattr(data, "landmarks_alist", None),
            ),
            generated_geometry=face_geometry_from_compare_result(
                getattr(data, "rect_blist", None),
                getattr(data, "landmarks_blist", None),
            ),
        )

    def _create_mask_url(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_id: int,
        photo_temp_url: str,
    ) -> str:
        element = self._segment_hair(photo_temp_url)
        mask_bytes = build_full_size_mask(
            original_bytes=download_bytes(photo_temp_url),
            hair_rgba_bytes=download_bytes(element.image_url),
            x=int(element.x),
            y=int(element.y),
            width=int(element.width),
            height=int(element.height),
        )
        return self.storage.upload_temp_bytes(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            file_ext="png",
            content=mask_bytes,
            content_type="image/png",
        )

    def _compose_reference_result(self, *, original_url: str, generated_url: str) -> bytes:
        original_element = self._segment_hair(original_url)
        generated_element = self._segment_hair(generated_url)
        original_face_box = self._detect_face_box(original_url)
        return composite_hair_edit(
            original_bytes=download_bytes(original_url),
            generated_bytes=download_bytes(generated_url),
            original_hair_rgba_bytes=download_bytes(original_element.image_url),
            original_box=element_box(original_element),
            generated_hair_rgba_bytes=download_bytes(generated_element.image_url),
            generated_box=element_box(generated_element),
            face_box=original_face_box,
        )

    def _segment_hair(self, image_url: str):
        from alibabacloud_imageseg20191230.models import SegmentHairRequest
        from alibabacloud_tea_util import models as util_models

        for attempt in range(_SEGMENT_HAIR_MAX_ATTEMPTS):
            wait_for_segment_hair_slot()
            try:
                response = self.imageseg.segment_hair_with_options(
                    SegmentHairRequest(image_url=image_url),
                    util_models.RuntimeOptions(),
                )
                break
            except Exception as exc:  # pragma: no cover - depends on Aliyun SDK
                if "Throttling" not in str(exc) or attempt == _SEGMENT_HAIR_MAX_ATTEMPTS - 1:
                    raise HairTryOnError(f"SegmentHair request failed: {exc}") from exc
                time.sleep(1)
        data = getattr(response.body, "data", None)
        if data is None or not getattr(data, "elements", None):
            raise HairTryOnError("SegmentHair returned no hair region")
        return data.elements[0]

    def _detect_face_box(self, image_url: str) -> tuple[int, int, int, int]:
        return self._detect_face_geometry(image_url).box

    def _detect_face_geometry(self, image_url: str) -> FaceGeometry:
        from alibabacloud_facebody20191230.models import DetectFaceRequest
        from alibabacloud_tea_util import models as util_models

        try:
            response = self.facebody.detect_face_with_options(
                DetectFaceRequest(image_url=image_url, landmark=True, max_face_number=1),
                util_models.RuntimeOptions(),
            )
        except Exception as exc:  # pragma: no cover - depends on Aliyun SDK
            raise HairTryOnError(f"DetectFace request failed: {exc}") from exc
        rectangles = getattr(response.body.data, "face_rectangles", None) or []
        if len(rectangles) < 4:
            raise HairTryOnError("DetectFace returned no face region")
        landmarks = getattr(response.body.data, "landmarks", None) or []
        return FaceGeometry(
            box=tuple(round(float(value)) for value in rectangles[:4]),
            landmarks=tuple(float(value) for value in landmarks),
        )

    def _submit_wanx_task(self, *, photo_temp_url: str, mask_url: str, prompt: str) -> str:
        response = httpx.post(
            self.dashscope_base_url + "/api/v1/services/aigc/image2image/image-synthesis",
            headers={
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            json={
                "model": "wanx2.1-imageedit",
                "input": {
                    "function": "description_edit_with_mask",
                    "prompt": prompt,
                    "base_image_url": photo_temp_url,
                    "mask_image_url": mask_url,
                },
                "parameters": {"n": 1},
            },
            timeout=30,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HairTryOnError(f"Wanxiang mask edit request failed: {response.text[:500]}") from exc
        task_id = response.json().get("output", {}).get("task_id")
        if not task_id:
            raise HairTryOnError("Wanxiang did not return a task_id")
        return str(task_id)

    def _submit_wan27_reference_task(
        self,
        *,
        photo_temp_url: str,
        hairstyle_reference_url: str,
        prompt: str,
    ) -> str:
        response = httpx.post(
            self.dashscope_base_url + "/api/v1/services/aigc/image-generation/generation",
            headers={
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            json={
                "model": os.getenv("ALIYUN_WAN27_REFERENCE_MODEL", "wan2.7-image"),
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"image": hairstyle_reference_url},
                                {"image": photo_temp_url},
                                {"text": prompt},
                            ],
                        }
                    ]
                },
                "parameters": {
                    "size": "1K",
                    "n": 1,
                    "watermark": False,
                },
            },
            timeout=30,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HairTryOnError(f"Wanxiang 2.7 reference edit request failed: {response.text[:500]}") from exc
        task_id = response.json().get("output", {}).get("task_id")
        if not task_id:
            raise HairTryOnError("Wanxiang 2.7 reference edit did not return a task_id")
        return str(task_id)

    def _wait_for_wanx_result(self, task_id: str) -> str:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = httpx.get(
                self.dashscope_base_url + f"/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {self.dashscope_api_key}"},
                timeout=20,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HairTryOnError(f"Wanxiang task query failed: {response.text[:500]}") from exc
            payload: dict[str, Any] = response.json()
            output = payload.get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED":
                results = output.get("results") or []
                if results and results[0].get("url"):
                    return str(results[0]["url"])
                raise HairTryOnError("Wanxiang completed without an image URL")
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise HairTryOnError(f"Wanxiang task failed: {output.get('message') or status}")
            time.sleep(2)
        raise HairTryOnError("Wanxiang task timed out")

    def _wait_for_wan27_result(self, task_id: str) -> str:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = httpx.get(
                self.dashscope_base_url + f"/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {self.dashscope_api_key}"},
                timeout=20,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HairTryOnError(f"Wanxiang 2.7 task query failed: {response.text[:500]}") from exc
            output = response.json().get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED":
                for choice in output.get("choices") or []:
                    for content in choice.get("message", {}).get("content") or []:
                        if content.get("image"):
                            return str(content["image"])
                raise HairTryOnError("Wanxiang 2.7 completed without an image URL")
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise HairTryOnError(f"Wanxiang 2.7 reference edit failed: {output.get('message') or status}")
            time.sleep(2)
        raise HairTryOnError("Wanxiang 2.7 reference edit timed out")


def build_full_size_mask(
    *,
    original_bytes: bytes,
    hair_rgba_bytes: bytes,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bytes:
    from PIL import Image
    from PIL import ImageFilter

    with Image.open(io.BytesIO(original_bytes)) as original:
        full_mask = Image.new("L", original.size, 0)
    with Image.open(io.BytesIO(hair_rgba_bytes)) as hair:
        alpha = hair.convert("RGBA").getchannel("A")
    if alpha.size != (width, height):
        alpha = alpha.resize((width, height), Image.Resampling.LANCZOS)
    alpha = alpha.filter(ImageFilter.MaxFilter(11))
    full_mask.paste(alpha, (x, y))
    output = io.BytesIO()
    full_mask.save(output, format="PNG")
    return output.getvalue()


def build_hair_only_reference_image(
    *,
    reference_bytes: bytes,
    hair_rgba_bytes: bytes,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bytes:
    from PIL import Image
    from PIL import ImageFilter

    with Image.open(io.BytesIO(reference_bytes)) as reference:
        reference_image = reference.convert("RGBA")
    with Image.open(io.BytesIO(hair_rgba_bytes)) as hair:
        hair_image = hair.convert("RGBA")
    if hair_image.size != (width, height):
        hair_image = hair_image.resize((width, height), Image.Resampling.LANCZOS)
    alpha = hair_image.getchannel("A").point(lambda value: 0 if value < 48 else value)
    alpha = alpha.filter(ImageFilter.MaxFilter(3))
    canvas = Image.new("RGBA", reference_image.size, (244, 244, 244, 255))
    canvas.alpha_composite(hair_image, (x, y))
    soft_mask = Image.new("L", reference_image.size, 0)
    soft_mask.paste(alpha, (x, y))
    output_image = Image.composite(canvas, Image.new("RGBA", reference_image.size, (244, 244, 244, 255)), soft_mask)
    output = io.BytesIO()
    output_image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def optimize_image_for_upload(content: bytes, *, max_dimension: int | None = 1536, quality: int = 88) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(content)) as source:
        image = source.convert("RGB")
        if max_dimension is not None:
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()


def composite_hair_edit(
    *,
    original_bytes: bytes,
    generated_bytes: bytes,
    original_hair_rgba_bytes: bytes,
    original_box: tuple[int, int, int, int],
    generated_hair_rgba_bytes: bytes,
    generated_box: tuple[int, int, int, int],
    face_box: tuple[int, int, int, int] | None = None,
) -> bytes:
    from PIL import Image
    from PIL import ImageChops
    from PIL import ImageFilter

    with Image.open(io.BytesIO(original_bytes)) as original_image:
        original = original_image.convert("RGBA")
    with Image.open(io.BytesIO(generated_bytes)) as generated_image:
        generated_size = generated_image.size
        generated = generated_image.convert("RGBA").resize(original.size, Image.Resampling.LANCZOS)
    original_mask = build_positioned_hair_mask(original.size, original_hair_rgba_bytes, original_box)
    generated_mask = build_positioned_hair_mask(
        original.size,
        generated_hair_rgba_bytes,
        scale_box(generated_box, generated_size, original.size),
    )
    edit_mask = ImageChops.lighter(original_mask, generated_mask)
    edit_mask = protect_core_face_pixels(
        edit_mask,
        generated_hair_mask=generated_mask,
        face_box=face_box,
    )
    composited = Image.composite(generated, original, edit_mask).convert("RGB")
    output = io.BytesIO()
    composited.save(output, format="PNG")
    return output.getvalue()


def protect_core_face_pixels(
    edit_mask,
    *,
    generated_hair_mask=None,
    face_box: tuple[int, int, int, int] | None = None,
):
    from PIL import Image
    from PIL import ImageChops
    from PIL import ImageDraw
    from PIL import ImageFilter

    width, height = edit_mask.size
    if face_box is None:
        face_box = (
            round(width * 0.25),
            round(height * 0.31),
            round(width * 0.50),
            round(height * 0.49),
        )
    x, y, face_width, face_height = face_box
    soft_protection = Image.new("L", edit_mask.size, 0)
    draw = ImageDraw.Draw(soft_protection)
    draw.ellipse(
        (
            round(x - face_width * 0.08),
            round(y - face_height * 0.04),
            round(x + face_width * 1.08),
            round(y + face_height * 1.06),
        ),
        fill=255,
    )
    soft_protection = soft_protection.filter(ImageFilter.GaussianBlur(max(2, round(max(width, height) * 0.012))))

    hard_core = Image.new("L", edit_mask.size, 0)
    draw = ImageDraw.Draw(hard_core)
    draw.ellipse(
        (
            x,
            y,
            x + face_width,
            y + face_height,
        ),
        fill=255,
    )
    protected_area = ImageChops.lighter(soft_protection, hard_core)
    if generated_hair_mask is not None:
        allowed_face_hair = keep_safe_face_hair_occlusion(generated_hair_mask, face_box)
        protected_area = ImageChops.subtract(protected_area, allowed_face_hair)
    return ImageChops.subtract(edit_mask, protected_area)


def keep_safe_face_hair_occlusion(generated_hair_mask, face_box: tuple[int, int, int, int]):
    from PIL import Image
    from PIL import ImageChops
    from PIL import ImageDraw

    x, y, face_width, face_height = face_box
    blocked_area = Image.new("L", generated_hair_mask.size, 0)
    draw = ImageDraw.Draw(blocked_area)

    # Keep the customer's central forehead and facial features clean. Side bangs
    # and hair outside the face box remain free to follow the generated style.
    draw.rectangle(
        (
            round(x + face_width * 0.24),
            round(y - face_height * 0.10),
            round(x + face_width * 0.76),
            round(y + face_height * 0.30),
        ),
        fill=255,
    )
    draw.ellipse(
        (
            round(x + face_width * 0.08),
            round(y + face_height * 0.23),
            round(x + face_width * 0.92),
            round(y + face_height * 1.02),
        ),
        fill=255,
    )
    return ImageChops.subtract(generated_hair_mask, blocked_area)


def build_positioned_hair_mask(
    canvas_size: tuple[int, int],
    hair_rgba_bytes: bytes,
    box: tuple[int, int, int, int],
):
    from PIL import Image
    from PIL import ImageFilter

    x, y, width, height = box
    mask = Image.new("L", canvas_size, 0)
    with Image.open(io.BytesIO(hair_rgba_bytes)) as hair:
        alpha = hair.convert("RGBA").getchannel("A")
    if alpha.size != (width, height):
        alpha = alpha.resize((width, height), Image.Resampling.LANCZOS)
    alpha = alpha.point(lambda value: 0 if value < 96 else value)
    alpha = alpha.filter(ImageFilter.MaxFilter(3))
    mask.paste(alpha, (x, y))
    return mask


def element_box(element) -> tuple[int, int, int, int]:
    return int(element.x), int(element.y), int(element.width), int(element.height)


def scale_box(
    box: tuple[int, int, int, int],
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    x, y, width, height = box
    source_width, source_height = source_size
    target_width, target_height = target_size
    return (
        round(x * target_width / source_width),
        round(y * target_height / source_height),
        round(width * target_width / source_width),
        round(height * target_height / source_height),
    )


def compare_face_geometry(original: FaceGeometry, generated: FaceGeometry) -> tuple[bool, str]:
    original_x, original_y, original_width, original_height = original.box
    generated_x, generated_y, generated_width, generated_height = generated.box
    del original_x, original_y, generated_x, generated_y
    if min(original_width, original_height, generated_width, generated_height) <= 0:
        return False, "invalid face rectangle"

    original_ratio = original_width / original_height
    generated_ratio = generated_width / generated_height
    aspect_ratio_drift = abs(generated_ratio / original_ratio - 1)
    max_aspect_ratio_drift = float(os.getenv("ALIYUN_WAN27_FACE_QC_MAX_ASPECT_RATIO_DRIFT", "0.18"))
    if aspect_ratio_drift > max_aspect_ratio_drift:
        return False, f"face rectangle drift {aspect_ratio_drift:.3f}"

    if len(original.landmarks) < 10 or len(generated.landmarks) != len(original.landmarks):
        return False, "missing or incompatible face landmarks"
    original_points = normalize_face_landmarks(original.landmarks, original.box)
    generated_points = normalize_face_landmarks(generated.landmarks, generated.box)
    landmark_error = sum(
        math.hypot(original_point[0] - generated_point[0], original_point[1] - generated_point[1])
        for original_point, generated_point in zip(original_points, generated_points)
    ) / len(original_points)
    max_landmark_error = float(os.getenv("ALIYUN_WAN27_FACE_QC_MAX_LANDMARK_ERROR", "0.085"))
    if landmark_error > max_landmark_error:
        return False, f"face landmark drift {landmark_error:.3f}"
    return True, ""


def face_geometry_from_compare_result(rectangle, landmarks) -> FaceGeometry:
    rectangle = rectangle or []
    landmarks = landmarks or []
    if len(rectangle) < 4:
        raise HairTryOnError("CompareFace returned no face rectangle")
    if len(landmarks) < 10:
        raise HairTryOnError("CompareFace returned no face landmarks")
    return FaceGeometry(
        box=tuple(round(float(value)) for value in rectangle[:4]),
        landmarks=tuple(float(value) for value in landmarks),
    )


def normalize_face_landmarks(
    landmarks: tuple[float, ...],
    box: tuple[int, int, int, int],
) -> list[tuple[float, float]]:
    x, y, width, height = box
    return [
        ((landmarks[index] - x) / width, (landmarks[index + 1] - y) / height)
        for index in range(0, len(landmarks) - 1, 2)
    ]


def build_hair_profile_prompt(hair_profile: dict | None) -> str:
    if not hair_profile:
        return ""
    label_maps = {
        "strand_thickness": {"fine": "发丝粗细：细软", "medium": "发丝粗细：中等", "coarse": "发丝粗细：粗硬"},
        "texture_hardness": {"soft": "发质软硬：偏软", "medium": "发质软硬：中等", "hard": "发质软硬：偏硬"},
        "damage_level": {
            "healthy": "头发状态：健康",
            "mild_damage": "头发状态：轻度受损",
            "damaged": "头发状态：中度受损",
            "severe_damage": "头发状态：极度受损",
        },
    }
    labels = []
    for key, options in label_maps.items():
        value = str(hair_profile.get(key) or "").strip()
        if value in options:
            labels.append(options[value])
    if not labels:
        return ""
    return (
        " 客户补充发质信息：" + "；".join(labels) + "。"
        "请根据这些信息调整发丝质感、蓬松度、顺滑度和高光强度：细软发避免过厚重，粗硬发保持结构感；"
        "偏软发避免僵硬发束，偏硬发避免过度贴头皮；受损发质避免过度光滑塑料感和不真实强反光。"
    )


def build_hair_edit_prompt(hairstyle: str | None, hair_color: str | None, hair_profile: dict | None = None) -> str:
    style = hairstyle or "保持当前发型轮廓"
    color = hair_color or "保持当前发色"
    profile_prompt = build_hair_profile_prompt(hair_profile)
    return (
        "请基于用户上传的原始自拍进行真实图像编辑。只修改遮罩区域内的人物头发，"
        "不要修改遮罩区域外的任何内容。"
        f"用户选择的发型是：{style}。用户选择的发色是：{color}。"
        "新发型需要自然贴合人物头部、脸型、发际线和原照片拍摄角度；"
        "新发色需要符合原照片光照，保留真实发丝纹理、发量、层次、明暗关系和自然高光。"
        "必须保持客户本人完全一致：脸型、五官、眼睛、眉毛、鼻子、嘴巴、耳朵、下巴、"
        "皮肤质感、肤色、表情、年龄、性别、眼镜、身体、衣服、背景、光线、构图都不能改变。"
        "禁止换脸，禁止美颜，禁止磨皮，禁止改变客户身份，禁止改变眼睛形状，禁止改变鼻子和嘴巴。"
        "刘海或发丝可以自然落在额头附近，但不能遮挡或改变眼睛、眉毛、鼻子、嘴巴等五官。"
        "生成真实照片风格，不要卡通、写真、海报、假发感或贴图感。"
        f"{profile_prompt}"
    )


def build_reference_hair_edit_prompt(
    hairstyle: str | None,
    hair_color: str | None,
    hair_profile: dict | None = None,
    reference_type: str | None = None,
) -> str:
    style = hairstyle or "the hairstyle shown in image 1"
    color = hair_color or "preserve the natural hair color from image 1"
    profile_prompt = build_hair_profile_prompt(hair_profile)
    if reference_type == "hair_color":
        reference_instruction = (
            "IMAGE 1 is a hair color reference only. Do not transfer IMAGE 1 hairstyle shape, length, bangs, parting, curl or volume. "
            "Use only the hair color, tonal variation, highlights and dye texture from IMAGE 1. "
        )
    else:
        reference_instruction = (
            "IMAGE 1 is a hairstyle reference only. Transfer only the hairstyle attributes from IMAGE 1: hair silhouette, length, bangs, parting, "
            "volume and strand texture. "
        )
    return (
        "TASK: virtual hairstyle try-on with strict identity preservation. "
        f"{reference_instruction}"
        "IMAGE 2 is the customer's original selfie and must remain the base image. "
        f"Edit IMAGE 2 only. Target hairstyle: {style}. Target hair color: {color}. "
        "Only reference IMAGE 1 hair shape, strand texture, volume, length, bangs, parting, curl, layers and hair color. "
        "Never reference IMAGE 1 face, facial features, expression, beard, skin, body, clothes, background or camera angle. "
        "ALLOWED EDIT REGION: hair pixels only. FORBIDDEN EDIT REGIONS: face, forehead skin, eyebrows, eyes, eyelids, "
        "nose, mouth, lips, ears, jawline, glasses, neck, body, clothes, accessories and background. "
        "The customer's identity in IMAGE 2 must be pixel-consistent: preserve exact facial geometry, expression, "
        "skin texture, skin tone, head angle, camera perspective, lighting and composition. "
        "Do not copy any identity, face shape, facial feature, glasses, body, clothes, background or pose from IMAGE 1. "
        "Do not copy IMAGE 1 beard, skin tone, facial mood, model temperament or gender cues into IMAGE 2. "
        "Do not reshape the face, do not swap the face, do not beautify, do not retouch skin, do not change age, gender or ethnicity. "
        "Bangs or hair strands may naturally fall near the forehead, but must not cover, deform or redraw the customer's eyes, eyebrows, nose or mouth. "
        "Fit the transferred hair naturally around the original head with a realistic hairline, strands, shadows and highlights. "
        "中文硬性规则：禁止换脸，禁止复制参考图模特的脸、五官、胡子、皮肤、身体、衣服、背景或气质；"
        "必须保持客户原自拍中的脸型、五官、眼睛、眉毛、鼻子、嘴巴、耳朵、下巴、皮肤质感、肤色、表情、年龄、性别、眼镜、身体、衣服、背景、光线和构图不变；"
        "只允许修改头发区域，刘海不能遮挡或改变五官。"
        f"{profile_prompt}"
        "Return exactly one photorealistic edited selfie based on IMAGE 2."
    )


def download_bytes(url: str) -> bytes:
    with urlopen(url, timeout=20) as response:
        return response.read()


def build_aliyun_hair_tryon_from_env(storage: TempStorageProvider, service=None) -> AliyunHairTryOnProvider:
    """构建阿里云试发服务。
    优先从数据库（api_key_configs）读取密钥，数据库没有则回落到环境变量。
    service 为 HairAiService 实例，传入后启用数据库优先模式。
    """
    def _resolve(provider: str, key_name: str, env_var: str) -> str:
        if service is not None:
            try:
                return service.resolve_key(provider, key_name, env_var)
            except Exception:
                pass
        return os.getenv(env_var, "")

    access_key_id     = _resolve("oss",        "access_key_id",     "OSS_ACCESS_KEY_ID")
    access_key_secret = _resolve("oss",        "access_key_secret",  "OSS_ACCESS_KEY_SECRET")
    dashscope_api_key = _resolve("dashscope",  "api_key",            "ALIYUN_DASHSCOPE_API_KEY")

    missing = [name for name, value in {
        "OSS_ACCESS_KEY_ID":     access_key_id,
        "OSS_ACCESS_KEY_SECRET": access_key_secret,
        "ALIYUN_DASHSCOPE_API_KEY": dashscope_api_key,
    }.items() if not value]
    if missing:
        raise HairTryOnError("Missing Aliyun AI config: " + ", ".join(missing))
    return AliyunHairTryOnProvider(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        dashscope_api_key=dashscope_api_key,
        storage=storage,
        imageseg_endpoint=os.getenv("ALIYUN_IMAGESEG_ENDPOINT", "imageseg.cn-shanghai.aliyuncs.com"),
        timeout_seconds=int(os.getenv("ALIYUN_WANX_TIMEOUT_SECONDS", "180")),
    )

