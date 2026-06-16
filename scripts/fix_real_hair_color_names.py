from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse
import urllib.request


BASE = "http://54.255.168.182:8000"
ROOT = pathlib.Path(
    "C:\\Users\\73177\\Documents\\\u53d1\u578b\u6536\u96c6\\"
    "\u53d1\u8272\u5361\u771f\u5b9e\u53d1\u675f\u5355\u5f20\u7248_001\\\u56fe\u7247"
)
TENANT_ID = 1
STORE_ID = 1
DIRECTIONS = ("female", "male", "neutral")
DIRECTION_CN = {"female": "\u5973\u6027", "male": "\u7537\u6027", "neutral": "\u4e2d\u6027"}

SWATCHES_BY_INDEX = {
    1: "#171412", 2: "#2b211c", 3: "#151b28", 4: "#4b2d21", 5: "#5a3b2d",
    6: "#704128", 7: "#5b4a3e", 8: "#7a563d", 9: "#8a603f", 10: "#a98262",
    11: "#6b5a4a", 12: "#9a5f2e", 13: "#9b7a58", 14: "#7f786b", 15: "#6f6861",
    16: "#786a5f", 17: "#9b9285", 18: "#c9c1b2", 19: "#b8b1a5", 20: "#a7a8aa",
    21: "#56595b", 22: "#777b80", 23: "#b6b6b8", 24: "#667988", 25: "#536879",
    26: "#0f6670", 27: "#1e4f9a", 28: "#263f32", 29: "#6f7354", 30: "#7d877c",
    31: "#b36a32", 32: "#b85a2d", 33: "#a55b35", 34: "#7f3429", 35: "#5b1f2b",
    36: "#9b2634", 37: "#8b4b48", 38: "#9a6a64", 39: "#b77968", 40: "#a76a67",
    41: "#e5a8b5", 42: "#c85a78", 43: "#756579", 44: "#a798c0", 45: "#58315f",
    46: "#b58139", 47: "#d1b075", 48: "#d8c083", 49: "#e2dcc8", 50: "#6c4a38",
}

BLEACH_REQUIRED_INDEXES = {
    18, 19, 20, 22, 23, 24, 25, 26, 27, 30, 41, 42, 43, 44, 47, 48, 49, 50
}
BLEACH_OPTIONAL_INDEXES = {
    10, 13, 14, 15, 16, 17, 21, 28, 29, 31, 32, 33, 36, 37, 38, 39, 40, 45, 46
}


def http_json(method: str, path: str, data: dict | None = None, timeout: int = 60) -> dict | list:
    body = None if data is None else json.dumps(data, ensure_ascii=True).encode("ascii")
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


def cards() -> list[dict]:
    result: list[dict] = []
    for path in sorted(ROOT.glob("*.png")):
        match = re.match(r"^(\d{2})_(.+)$", path.stem)
        if not match:
            continue
        result.append({"index": int(match.group(1)), "name": match.group(2)})
    return result


def color_id_for(index: int, direction: str) -> str:
    return f"real_strand_color_{index:02d}_{direction}"


def tone_tags(name: str) -> list[str]:
    tags: list[str] = []
    for keyword, tag in [
        ("\u9ed1", "\u6df1\u8272\u7cfb"),
        ("\u68d5", "\u68d5\u8272\u7cfb"),
        ("\u8336", "\u8336\u8272\u7cfb"),
        ("\u7070", "\u51b7\u8272\u7cfb"),
        ("\u84dd", "\u51b7\u8272\u7cfb"),
        ("\u7eff", "\u51b7\u8272\u7cfb"),
        ("\u6a58", "\u6696\u8272\u7cfb"),
        ("\u94dc", "\u6696\u8272\u7cfb"),
        ("\u91d1", "\u6696\u8272\u7cfb"),
        ("\u7ea2", "\u7ea2\u8272\u7cfb"),
        ("\u7c89", "\u7c89\u8272\u7cfb"),
        ("\u7d2b", "\u7d2b\u8272\u7cfb"),
    ]:
        if keyword in name and tag not in tags:
            tags.append(tag)
    return tags[:3]


def display_tags(item: dict, direction: str) -> list[str]:
    index = item["index"]
    if index in BLEACH_REQUIRED_INDEXES:
        bleach = "\u9700\u8981\u6f02\u53d1"
    elif index in BLEACH_OPTIONAL_INDEXES:
        bleach = "\u53ef\u9009\u6f02\u53d1"
    else:
        bleach = "\u65e0\u9700\u6f02\u53d1"
    name = item["name"]
    tags = [
        DIRECTION_CN[direction],
        bleach,
        "\u771f\u5b9e\u53d1\u675f\u56fe",
        *tone_tags(name),
        f"\u987e\u5ba2\u63cf\u8ff0\uff1a{name}\u771f\u5b9e\u53d1\u675f\u53c2\u8003\uff0c\u9002\u5408\u5230\u5e97\u6c9f\u901a\u67d3\u53d1\u6548\u679c\u3002",
        f"AI\u53c2\u8003\uff1a\u53ea\u8c03\u6574\u5ba2\u6237\u5934\u53d1\u989c\u8272\u4e3a{name}\uff0c\u4fdd\u7559\u5ba2\u6237\u539f\u4e94\u5b98\u3001\u8138\u578b\u3001\u8868\u60c5\u3001\u773c\u955c\u3001\u8eab\u4f53\u3001\u8863\u670d\u548c\u80cc\u666f\u3002",
    ]
    return list(dict.fromkeys(tags))


def main() -> None:
    items = cards()
    if len(items) != 50:
        raise SystemExit(f"Expected 50 images, got {len(items)} from {ROOT}")
    updated = 0
    failed: list[tuple[str, str, str]] = []
    for direction in DIRECTIONS:
        for item in items:
            payload = {
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "name": item["name"],
                "direction": direction,
                "color_swatch": SWATCHES_BY_INDEX.get(item["index"], "#6b4a38"),
                "display_tags": display_tags(item, direction),
                "need_bleach": item["index"] in BLEACH_REQUIRED_INDEXES,
                "is_enabled": True,
                "is_recommended": True,
                "sort_order": item["index"],
            }
            try:
                http_json(
                    "PUT",
                    f"/merchant/hair-colors/{quote_path_value(color_id_for(item['index'], direction))}",
                    payload,
                )
                updated += 1
            except Exception as exc:  # noqa: BLE001
                failed.append((direction, item["name"], str(exc)[:200]))
            time.sleep(0.01)
    print(json.dumps({"updated": updated, "failed": failed[:10]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
