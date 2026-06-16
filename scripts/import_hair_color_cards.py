from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse
import urllib.request


BASE = "http://54.255.168.182:8000"
TENANT_ID = 1
STORE_ID = 1
SOURCE = pathlib.Path(r"C:\Users\73177\Documents\发型收集\发色卡单张版_001\文档\50种发色卡标注.md")

DIRECTIONS = ("female", "male", "neutral")
DIRECTION_CN = {"female": "女士", "male": "男士", "neutral": "中性"}

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

BLEACH_MAP = {
    "否": (False, "无需漂发"),
    "是": (True, "需要漂发"),
    "可选": (False, "可选漂发"),
    "可能需要": (True, "可能需要漂发"),
}


def http_json(method: str, path: str, data: dict | None = None, timeout: int = 30) -> dict | list:
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


def parse_cards() -> list[dict]:
    rows: list[dict] = []
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or "序号" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 5 or not cells[0].isdigit():
            continue
        rows.append(
            {
                "index": int(cells[0]),
                "filename": cells[1],
                "name": cells[2],
                "bleach_text": cells[3],
                "description": cells[4],
            }
        )
    return rows


def color_id_for(item: dict, direction: str) -> str:
    return f"haircolor_card_{item['index']:02d}_{direction}"


def existing_ids(direction: str) -> set[str]:
    query = urllib.parse.urlencode({"tenant_id": TENANT_ID, "direction": direction})
    rows = http_json("GET", "/hair-colors?" + query)
    return {row["color_id"] for row in rows}


def tone_tags(name: str, description: str) -> list[str]:
    text = name + description
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
        ("显白", "显白"),
        ("低调", "低调自然"),
        ("职场", "职场友好"),
        ("通勤", "通勤"),
        ("潮", "潮色"),
    ]:
        if keyword in text and tag not in tags:
            tags.append(tag)
    return tags[:4]


def display_tags(item: dict) -> list[str]:
    need_bleach, bleach_label = BLEACH_MAP.get(item["bleach_text"], (False, item["bleach_text"]))
    tags = [bleach_label, *tone_tags(item["name"], item["description"])]
    if need_bleach and "潮色" not in tags and any(key in item["name"] for key in ("蓝", "紫", "粉", "银", "白金")):
        tags.append("潮色")
    tags.extend(
        [
            f"顾客描述：{item['description']}",
            f"AI参考：只调整头发颜色为{item['name']}，保留顾客原五官、脸型、表情、眼镜、身体、衣服和背景",
        ]
    )
    return list(dict.fromkeys(tags))


def payload_for(item: dict, direction: str) -> dict:
    need_bleach = BLEACH_MAP.get(item["bleach_text"], (False, ""))[0]
    return {
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "color_id": color_id_for(item, direction),
        "name": item["name"],
        "direction": direction,
        "color_swatch": SWATCHES.get(item["name"], "#6b4a38"),
        "display_tags": [DIRECTION_CN[direction], *display_tags(item)],
        "need_bleach": need_bleach,
        "is_enabled": True,
        "is_recommended": True,
        "sort_order": 1000 + item["index"],
    }


def disable_legacy_colors(cards: list[dict]) -> int:
    disabled = 0
    legacy_names = {"Cool Brown", "Black Tea Brown", "Natural Black"}
    desired_ids = {
        direction: {color_id_for(item, direction) for item in cards}
        for direction in DIRECTIONS
    }
    for direction in DIRECTIONS:
        query = urllib.parse.urlencode({"tenant_id": TENANT_ID, "direction": direction})
        for row in http_json("GET", "/hair-colors?" + query):
            color_id = str(row.get("color_id", ""))
            is_old_generated_id = color_id.startswith("haircolor_card_") and color_id not in desired_ids[direction]
            if row.get("color_name") in legacy_names or is_old_generated_id:
                http_json(
                    "PUT",
                    f"/merchant/hair-colors/{quote_path_value(row['color_id'])}",
                    {"tenant_id": TENANT_ID, "is_enabled": False},
                )
                disabled += 1
    return disabled


def main() -> None:
    cards = parse_cards()
    if len(cards) != 50:
        raise SystemExit(f"Expected 50 cards, got {len(cards)}")

    existing = {direction: existing_ids(direction) for direction in DIRECTIONS}
    created = 0
    updated = 0
    failed: list[tuple[str, str, str]] = []

    for direction in DIRECTIONS:
        for item in cards:
            payload = payload_for(item, direction)
            color_id = payload["color_id"]
            try:
                if color_id in existing[direction]:
                    update_payload = dict(payload)
                    update_payload.pop("color_id", None)
                    http_json("PUT", f"/merchant/hair-colors/{color_id}", update_payload)
                    updated += 1
                else:
                    http_json("POST", "/merchant/hair-colors", payload)
                    existing[direction].add(color_id)
                    created += 1
            except Exception as exc:  # noqa: BLE001 - importer should report every failed row.
                failed.append((direction, item["name"], str(exc)[:240]))
            time.sleep(0.02)

    disabled_legacy = disable_legacy_colors(cards)
    print(
        json.dumps(
            {
                "source": str(SOURCE),
                "cards": len(cards),
                "directions": list(DIRECTIONS),
                "created": created,
                "updated": updated,
                "disabled_legacy": disabled_legacy,
                "failed_count": len(failed),
                "failed": failed[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
