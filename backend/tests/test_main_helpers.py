from app.main import build_hairstyle_ai_reference
from app.services import parse_hairstyle_display_metadata


def test_build_hairstyle_ai_reference_includes_catalog_parameters() -> None:
    prompt = build_hairstyle_ai_reference(
        {
            "style_name": "中分微卷",
            "hair_length": "medium",
            "tags": ["八字刘海", "蓬松发根", "自然层次"],
            "need_perm": 1,
        }
    )

    assert prompt == "中分微卷, medium-length hair, 八字刘海, 蓬松发根, 自然层次, permed or heat-styled texture"


def test_build_hairstyle_ai_reference_deduplicates_name_tag() -> None:
    prompt = build_hairstyle_ai_reference(
        {
            "style_name": "纹理短发",
            "hair_length": "short",
            "tags": ["纹理短发", "碎发层次"],
            "need_perm": 0,
        }
    )

    assert prompt == "纹理短发, short hair, 碎发层次"


def test_parse_hairstyle_display_metadata_supports_configurable_groups() -> None:
    metadata = parse_hairstyle_display_metadata(
        """
        {
          "customer_description": "发根自然蓬松，修饰脸型。",
          "parameter_groups": [
            {"name": "刘海", "values": ["八字刘海"]},
            {"name": "风格", "values": ["韩系", "自然"]}
          ],
          "ai_reference_tags": ["真实发丝纹理"]
        }
        """
    )

    assert metadata["customer_description"] == "发根自然蓬松，修饰脸型。"
    assert metadata["tags"] == ["八字刘海", "韩系", "自然"]
    assert metadata["ai_reference_tags"] == ["真实发丝纹理", "八字刘海", "韩系", "自然"]


def test_build_hairstyle_ai_reference_uses_customer_description_and_hidden_tags() -> None:
    prompt = build_hairstyle_ai_reference(
        {
            "style_name": "韩式中分微卷",
            "hair_length": "medium",
            "customer_description": "发根自然蓬松，修饰脸型。",
            "ai_reference_tags": ["八字刘海", "韩系", "真实发丝纹理"],
            "need_perm": 0,
        }
    )

    assert prompt == "韩式中分微卷, medium-length hair, 发根自然蓬松，修饰脸型。, 八字刘海, 韩系, 真实发丝纹理"
