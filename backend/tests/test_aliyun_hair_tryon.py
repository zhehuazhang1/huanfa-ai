import io

import pytest
from PIL import Image

from app import aliyun_hair_tryon
from app.aliyun_hair_tryon import (
    AliyunHairTryOnProvider,
    FaceComparison,
    FaceGeometry,
    build_hair_edit_prompt,
    build_hair_only_reference_image,
    build_positioned_hair_mask,
    build_reference_hair_edit_prompt,
    compare_face_geometry,
    composite_hair_edit,
    optimize_image_for_upload,
    scale_box,
)


def _image_bytes(color: tuple[int, int, int, int], size: tuple[int, int] = (20, 20)) -> bytes:
    image = Image.new("RGBA", size, color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_composite_hair_edit_preserves_pixels_outside_hair_region() -> None:
    original = _image_bytes((12, 34, 56, 255))
    generated = _image_bytes((200, 100, 50, 255))
    hair = _image_bytes((255, 255, 255, 255), (6, 6))

    result = composite_hair_edit(
        original_bytes=original,
        generated_bytes=generated,
        original_hair_rgba_bytes=hair,
        original_box=(2, 2, 6, 6),
        generated_hair_rgba_bytes=hair,
        generated_box=(2, 2, 6, 6),
    )

    with Image.open(io.BytesIO(result)) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((18, 18)) == (12, 34, 56)
        assert rgb.getpixel((3, 3)) != (12, 34, 56)


def test_composite_hair_edit_preserves_core_face_pixels() -> None:
    original = _image_bytes((12, 34, 56, 255))
    generated = _image_bytes((200, 100, 50, 255))
    original_hair = _image_bytes((255, 255, 255, 255), (20, 20))
    generated_hair = _image_bytes((255, 255, 255, 0), (20, 20))

    result = composite_hair_edit(
        original_bytes=original,
        generated_bytes=generated,
        original_hair_rgba_bytes=original_hair,
        original_box=(0, 0, 20, 20),
        generated_hair_rgba_bytes=generated_hair,
        generated_box=(0, 0, 20, 20),
    )

    with Image.open(io.BytesIO(result)) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((10, 10)) == (12, 34, 56)
        assert rgb.getpixel((1, 1)) != (12, 34, 56)


def test_composite_hair_edit_allows_side_bangs_and_body_hair_but_protects_face_center() -> None:
    original = _image_bytes((12, 34, 56, 255), (100, 100))
    generated = _image_bytes((200, 100, 50, 255), (100, 100))
    hair = _image_bytes((255, 255, 255, 255), (100, 100))

    result = composite_hair_edit(
        original_bytes=original,
        generated_bytes=generated,
        original_hair_rgba_bytes=hair,
        original_box=(0, 0, 100, 100),
        generated_hair_rgba_bytes=hair,
        generated_box=(0, 0, 100, 100),
        face_box=(40, 20, 20, 35),
    )

    with Image.open(io.BytesIO(result)) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((50, 24)) == (12, 34, 56)
        assert rgb.getpixel((42, 24)) != (12, 34, 56)
        assert rgb.getpixel((50, 35)) == (12, 34, 56)
        assert rgb.getpixel((20, 80)) != (12, 34, 56)


def test_build_positioned_hair_mask_removes_low_alpha_haze() -> None:
    haze = _image_bytes((255, 255, 255, 64), (10, 10))

    mask = build_positioned_hair_mask((20, 20), haze, (5, 5, 10, 10))

    assert mask.getpixel((10, 10)) == 0


def test_build_hair_only_reference_image_removes_reference_face_pixels() -> None:
    reference = _image_bytes((20, 40, 60, 255), (20, 20))
    hair = _image_bytes((200, 100, 50, 255), (6, 6))

    result = build_hair_only_reference_image(
        reference_bytes=reference,
        hair_rgba_bytes=hair,
        x=2,
        y=2,
        width=6,
        height=6,
    )

    with Image.open(io.BytesIO(result)) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((3, 3)) == (200, 100, 50)
        assert rgb.getpixel((15, 15)) == (244, 244, 244)


def test_scale_box_maps_generated_coordinates_to_selfie_size() -> None:
    assert scale_box((10, 20, 30, 40), (100, 200), (200, 100)) == (20, 10, 60, 20)


def test_provider_keeps_generation_methods_on_class() -> None:
    assert hasattr(AliyunHairTryOnProvider, "_submit_wan27_reference_task")
    assert hasattr(AliyunHairTryOnProvider, "_submit_wanx_task")


def test_reference_prompt_contains_no_face_swap_guardrails() -> None:
    prompt = build_reference_hair_edit_prompt("男士中分微卷长发, 中分窗帘刘海", "深棕色")

    assert "do not swap the face" in prompt
    assert "Never reference IMAGE 1 face" in prompt
    assert "禁止换脸" in prompt
    assert "只允许修改头发区域" in prompt
    assert "刘海不能遮挡或改变五官" in prompt


def test_mask_prompt_contains_no_face_swap_guardrails() -> None:
    prompt = build_hair_edit_prompt("男士中分微卷长发", "深棕色")

    assert "禁止换脸" in prompt
    assert "禁止改变客户身份" in prompt
    assert "不能遮挡或改变眼睛" in prompt


def test_native_reference_mode_returns_original_wan27_result(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = object.__new__(AliyunHairTryOnProvider)
    provider.storage = object()
    monkeypatch.setenv("ALIYUN_WAN27_REFERENCE_OUTPUT_MODE", "native")
    monkeypatch.setenv("ALIYUN_WAN27_NATIVE_FACE_QC", "false")
    monkeypatch.setenv("ALIYUN_WAN27_HAIR_ONLY_REFERENCE", "false")
    monkeypatch.setattr(provider, "_submit_wan27_reference_task", lambda **kwargs: "task-native")
    monkeypatch.setattr(provider, "_wait_for_wan27_result", lambda task_id: "https://dashscope.local/native.png")
    monkeypatch.setattr(
        aliyun_hair_tryon,
        "download_bytes",
        lambda url: (_ for _ in ()).throw(AssertionError("native mode must not download or composite")),
    )

    result = provider.generate(
        tenant_id=1,
        store_id=1,
        user_id=1,
        photo_temp_url="https://temp.local/selfie.jpg",
        hairstyle="Long Hair",
        hair_color=None,
        hairstyle_reference_url="https://catalog.local/reference.jpg",
    )

    assert result.image_url == "https://dashscope.local/native.png"
    assert result.wanx_task_id == "task-native"


def test_native_reference_mode_submits_hair_only_reference_and_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = object.__new__(AliyunHairTryOnProvider)
    provider.storage = _QcStorage()
    monkeypatch.setenv("ALIYUN_WAN27_REFERENCE_OUTPUT_MODE", "native")
    monkeypatch.setenv("ALIYUN_WAN27_NATIVE_FACE_QC", "false")
    monkeypatch.setenv("ALIYUN_WAN27_HAIR_ONLY_REFERENCE", "true")
    monkeypatch.setattr(provider, "_create_hair_only_reference_url", lambda **kwargs: "https://temp.local/hair-only.png")
    submitted_urls: list[str] = []
    monkeypatch.setattr(
        provider,
        "_submit_wan27_reference_task",
        lambda **kwargs: submitted_urls.append(kwargs["hairstyle_reference_url"]) or "task-native",
    )
    monkeypatch.setattr(provider, "_wait_for_wan27_result", lambda task_id: "https://dashscope.local/native.png")

    result = provider.generate(
        tenant_id=1,
        store_id=1,
        user_id=1,
        photo_temp_url="https://temp.local/selfie.jpg",
        hairstyle="Long Hair",
        hair_color=None,
        hairstyle_reference_url="https://catalog.local/reference.jpg",
    )

    assert result.image_url == "https://dashscope.local/native.png"
    assert submitted_urls == ["https://temp.local/hair-only.png"]
    assert provider.storage.deleted == ["https://temp.local/hair-only.png"]


def test_native_reference_mode_retries_once_after_face_qc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = object.__new__(AliyunHairTryOnProvider)
    provider.storage = object()
    monkeypatch.setenv("ALIYUN_WAN27_REFERENCE_OUTPUT_MODE", "native")
    monkeypatch.setenv("ALIYUN_WAN27_NATIVE_FACE_QC", "true")
    monkeypatch.setenv("ALIYUN_WAN27_HAIR_ONLY_REFERENCE", "false")
    monkeypatch.setattr(provider, "_detect_face_geometry", lambda url: _face_geometry())
    submitted_prompts: list[str] = []
    monkeypatch.setattr(
        provider,
        "_submit_wan27_reference_task",
        lambda **kwargs: submitted_prompts.append(kwargs["prompt"]) or f"task-{len(submitted_prompts)}",
    )
    monkeypatch.setattr(provider, "_wait_for_wan27_result", lambda task_id: f"https://dashscope.local/{task_id}.png")
    qc_results = iter([(False, "face landmark drift 0.100"), (True, "")])
    monkeypatch.setattr(provider, "_check_native_face_quality", lambda **kwargs: next(qc_results))

    result = provider.generate(
        tenant_id=1,
        store_id=1,
        user_id=1,
        photo_temp_url="https://temp.local/selfie.jpg",
        hairstyle="Short Hair",
        hair_color=None,
        hairstyle_reference_url="https://catalog.local/reference.jpg",
    )

    assert result.image_url == "https://dashscope.local/task-2.png"
    assert result.wanx_task_id == "task-2"
    assert len(submitted_prompts) == 2
    assert "RETRY REQUIREMENT" in submitted_prompts[1]


def test_native_reference_mode_fails_after_second_face_qc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = object.__new__(AliyunHairTryOnProvider)
    provider.storage = object()
    monkeypatch.setenv("ALIYUN_WAN27_REFERENCE_OUTPUT_MODE", "native")
    monkeypatch.setenv("ALIYUN_WAN27_NATIVE_FACE_QC", "true")
    monkeypatch.setenv("ALIYUN_WAN27_HAIR_ONLY_REFERENCE", "false")
    monkeypatch.setattr(provider, "_detect_face_geometry", lambda url: _face_geometry())
    monkeypatch.setattr(provider, "_submit_wan27_reference_task", lambda **kwargs: "task-native")
    monkeypatch.setattr(provider, "_wait_for_wan27_result", lambda task_id: "https://dashscope.local/native.png")
    monkeypatch.setattr(provider, "_check_native_face_quality", lambda **kwargs: (False, "face landmark drift 0.100"))

    with pytest.raises(aliyun_hair_tryon.HairTryOnError, match="failed after retry"):
        provider.generate(
            tenant_id=1,
            store_id=1,
            user_id=1,
            photo_temp_url="https://temp.local/selfie.jpg",
            hairstyle="Short Hair",
            hair_color=None,
            hairstyle_reference_url="https://catalog.local/reference.jpg",
        )


def test_compare_face_geometry_rejects_landmark_drift() -> None:
    original = _face_geometry()
    changed = FaceGeometry(
        box=(100, 100, 200, 300),
        landmarks=(120, 130, 280, 130, 120, 370, 280, 370, 200, 250),
    )

    passed, reason = compare_face_geometry(original, changed)

    assert passed is False
    assert "landmark drift" in reason


def test_native_face_qc_rejects_identity_confidence_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = object.__new__(AliyunHairTryOnProvider)
    provider.storage = _QcStorage()
    monkeypatch.setenv("ALIYUN_WAN27_FACE_COMPARE_QC", "true")
    monkeypatch.setattr(aliyun_hair_tryon, "download_bytes", lambda url: _image_bytes((12, 34, 56, 255)))
    monkeypatch.setattr(
        provider,
        "_compare_faces",
        lambda original_url, generated_url: FaceComparison(
            confidence=58.0,
            threshold=61.0,
            original_geometry=_face_geometry(),
            generated_geometry=_face_geometry(),
        ),
    )

    passed, reason = provider._check_native_face_quality(
        tenant_id=1,
        store_id=1,
        user_id=1,
        original_url="https://temp.local/selfie.jpg",
        generated_url="https://dashscope.local/native.png",
    )

    assert passed is False
    assert "identity confidence" in reason
    assert provider.storage.deleted == ["https://temp.local/qc.jpg"]


class _QcStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def upload_temp_bytes(self, **kwargs) -> str:
        return "https://temp.local/qc.jpg"

    def delete_temp_asset(self, url: str) -> None:
        self.deleted.append(url)


def _face_geometry() -> FaceGeometry:
    return FaceGeometry(
        box=(100, 100, 200, 300),
        landmarks=(140, 160, 260, 160, 150, 300, 250, 300, 200, 230),
    )


def test_optimize_image_for_upload_returns_small_jpeg() -> None:
    original = _image_bytes((12, 34, 56, 255), (2048, 1024))

    result = optimize_image_for_upload(original, max_dimension=512)

    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.size == (512, 256)
    assert len(result) < len(original)


def test_optimize_image_for_upload_can_keep_original_dimensions() -> None:
    original = _image_bytes((12, 34, 56, 255), (2048, 1024))

    result = optimize_image_for_upload(original, max_dimension=None, quality=96)

    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.size == (2048, 1024)
