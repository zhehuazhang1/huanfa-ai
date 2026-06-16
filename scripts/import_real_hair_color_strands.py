from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse
import urllib.request
from http.client import RemoteDisconnected


BASE = "http://54.255.168.182:8000"
ROOT = pathlib.Path(r"C:\Users\73177\Documents\发型收集\发色卡真实发束单张版_001\图片")
CACHE = pathlib.Path(r"C:\Users\73177\Documents\美发\.tmp_hair_color_strand_uploads.json")
TENANT_ID = 1
STORE_ID = 1
DIRECTIONS = ("female", "male", "neutral")
DIRECTION_CN = {"female": "女性", "male": "男性", "neutral": "中性"}

SWATCHES = {
    "自然黑": "#171412",
    "黑茶色": "#2b211c",
    "蓝黑色": "#151b28",
    "巧克力棕": "#4b2d21",
    "摩卡棕": "#5a3b2d",
    "栗棕色": "#704128",
    "冷棕色": "#5b4a3e",
    "榛果棕": "#7a563d",
    "蜜茶棕": "#8a603f",
    "奶茶棕": "#a98262",
    "冷茶棕": "#6b5a4a",
    "焦糖棕": "#9a5f2e",
    "亚麻棕": "#9b7a58",
    "亚麻灰棕": "#7f786b",
    "灰棕色": "#6f6861",
    "雾感棕": "#786a5f",
    "奶灰棕": "#9b9285",
    "珍珠米灰": "#c9c1b2",
    "米灰色": "#b8b1a5",
    "银灰色": "#a7a8aa",
    "铅笔灰": "#56595b",
    "烟灰色": "#777b80",
    "奶奶灰": "#b6b6b8",
    "雾霾蓝": "#667988",
    "蓝灰色": "#536879",
    "孔雀蓝": "#0f6670",
    "宝石蓝": "#1e4f9a",
    "墨绿色": "#263f32",
    "橄榄绿": "#6f7354",
    "青木亚麻灰": "#7d877c",
    "蜜糖橘棕": "#b36a32",
    "橘棕色": "#b85a2d",
    "铜棕色": "#a55b35",
    "红棕色": "#7f3429",
    "酒红色": "#5b1f2b",
    "樱桃红": "#9b2634",
    "玫瑰棕": "#8b4b48",
    "豆沙粉棕": "#9a6a64",
    "蜜桃粉棕": "#b77968",
    "粉棕色": "#a76a67",
    "樱花粉": "#e5a8b5",
    "玫瑰粉": "#c85a78",
    "紫灰色": "#756579",
    "薰衣草紫": "#a798c0",
    "葡萄紫": "#58315f",
    "金棕色": "#b58139",
    "香槟金": "#d1b075",
    "奶油金": "#d8c083",
    "白金色": "#e2dcc8",
    "挂耳挑染综合色": "#6c4a38",
}

BLEACH_REQUIRED_INDEXES = {
    18, 19, 20, 22, 23, 24, 25, 26, 27, 30, 41, 42, 43, 44, 47, 48, 49, 50
}
BLEACH_OPTIONAL_INDEXES = {
    10, 13, 14, 15, 16, 17, 21, 28, 29, 31, 32, 33, 36, 37, 38, 39, 40, 45, 46
}


def http_json(method: str, path: str, data: dict | None = None, timeout: int = 60) -> dict | list:
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def quote_path_value(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def upload_file(path: pathlib.Path) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            upload = http_json(
                "POST",
                "/merchant/assets/upload-url",
                {
                    "tenant_id": TENANT_ID,
                    "store_id": STORE_ID,
                    "asset_type": "hair_color",
                    "file_ext": path.suffix.lstrip(".") or "png",
                },
            )
            request = urllib.request.Request(
                upload["upload_url"],
                data=path.read_bytes(),
                method="PUT",
                headers={"Content-Type": "application/octet-stream"},
            )
            with urllib.request.urlopen(request, timeout=120):
                pass
            return upload["asset_url"]
        except (OSError, RemoteDisconnected) as exc:
            last_error = exc
            time.sleep(attempt * 1.5)
    raise RuntimeError(f"Upload failed for {path.name}: {last_error}")


def load_upload_cache() -> dict[str, str]:
    if not CACHE.exists():
        return {}
    return json.loads(CACHE.read_text(encoding="utf-8"))


def save_upload_cache(cache: dict[str, str]) -> None:
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def cards() -> list[dict]:
    result: list[dict] = []
    for path in sorted(ROOT.glob("*.png")):
        match = re.match(r"^(\d{2})_(.+)$", path.stem)
        if not match:
            continue
        index = int(match.group(1))
        name = match.group(2)
        result.append({"index": index, "name": name, "path": path})
    return result


def color_id_for(index: int, direction: str) -> str:
    return f"real_strand_color_{index:02d}_{direction}"


def tone_tags(name: str) -> list[str]:
    tags: list[str] = []
    for keyword, tag in [
        ("黑", "深色系"),
        ("棕", "棕色系"),
        ("茶", "茶色系"),
        ("灰", "冷色系"),
        ("蓝", "冷色系"),
        ("绿", "冷色系"),
        ("橘", "暖色系"),
        ("铜", "暖色系"),
        ("金", "暖色系"),
        ("红", "红色系"),
        ("粉", "粉色系"),
        ("紫", "紫色系"),
    ]:
        if keyword in name and tag not in tags:
            tags.append(tag)
    return tags[:3]


def display_tags(item: dict, direction: str) -> list[str]:
    index = item["index"]
    if index in BLEACH_REQUIRED_INDEXES:
        bleach = "需要漂发"
    elif index in BLEACH_OPTIONAL_INDEXES:
        bleach = "可选漂发"
    else:
        bleach = "无需漂发"
    tags = [
        DIRECTION_CN[direction],
        bleach,
        "真实发束图",
        *tone_tags(item["name"]),
        f"顾客描述：{item['name']}真实发束参考，适合到店沟通染发效果。",
        f"AI参考：只调整客户头发颜色为{item['name']}，保留客户原五官、脸型、表情、眼镜、身体、衣服和背景。",
    ]
    return list(dict.fromkeys(tags))


def disable_existing_colors() -> int:
    disabled = 0
    for direction in DIRECTIONS:
        query = urllib.parse.urlencode({"tenant_id": TENANT_ID, "direction": direction})
        for row in http_json("GET", "/hair-colors?" + query):
            http_json(
                "PUT",
                f"/merchant/hair-colors/{quote_path_value(row['color_id'])}",
                {"tenant_id": TENANT_ID, "is_enabled": False},
            )
            disabled += 1
            time.sleep(0.01)
    return disabled


def main() -> None:
    items = cards()
    if len(items) != 50:
        raise SystemExit(f"Expected 50 images, got {len(items)} from {ROOT}")

    upload_cache = load_upload_cache()
    image_urls: dict[int, str] = {}
    for item in items:
        key = item["path"].name
        if key not in upload_cache:
            upload_cache[key] = upload_file(item["path"])
            save_upload_cache(upload_cache)
        image_urls[item["index"]] = upload_cache[key]
    disabled = disable_existing_colors()
    created = 0
    failed: list[tuple[str, str, str]] = []

    for direction in DIRECTIONS:
        for item in items:
            payload = {
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "color_id": color_id_for(item["index"], direction),
                "name": item["name"],
                "direction": direction,
                "color_swatch": SWATCHES.get(item["name"], "#6b4a38"),
                "thumbnail_url": image_urls[item["index"]],
                "display_tags": display_tags(item, direction),
                "need_bleach": item["index"] in BLEACH_REQUIRED_INDEXES,
                "is_enabled": True,
                "is_recommended": True,
                "sort_order": item["index"],
            }
            try:
                http_json("POST", "/merchant/hair-colors", payload)
                created += 1
            except Exception:
                update_payload = dict(payload)
                update_payload.pop("color_id", None)
                try:
                    http_json(
                        "PUT",
                        f"/merchant/hair-colors/{quote_path_value(payload['color_id'])}",
                        update_payload,
                    )
                    created += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append((direction, item["name"], str(exc)[:240]))
            time.sleep(0.02)

    print(
        json.dumps(
            {
                "source": str(ROOT),
                "images": len(items),
                "disabled_old_colors": disabled,
                "created": created,
                "failed_count": len(failed),
                "failed": failed[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
