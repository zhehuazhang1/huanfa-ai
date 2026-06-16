from __future__ import annotations

import json
import pathlib
import time
import urllib.parse
import urllib.request


BASE = "http://54.255.168.182:8000"
ROOT = pathlib.Path(r"C:\Users\73177\Documents\美发\.tmp_hair_refs")
TENANT_ID = 1
STORE_ID = 1

LENGTH_MAP = {"SHORT": "short", "MEDIUM": "medium", "LONG": "long"}
LENGTH_CN = {"SHORT": "短发", "MEDIUM": "中发", "LONG": "长发"}
DIRECTION_MAP = {"女性": "female", "男性": "male"}
DIRECTION_CN = {"女性": "女发", "男性": "男发"}
KEYWORD_TAGS = {
    "korean": "韩系",
    "french": "法式",
    "japanese": "日系",
    "layered": "层次",
    "fringe": "刘海",
    "wool_curl": "羊毛卷",
    "wolfcut": "狼尾",
    "mullet": "鲻鱼头",
    "bob": "波波头",
    "buzz": "寸头",
    "crew": "圆寸",
    "crop_spike": "短刺",
    "blue_black": "蓝黑色",
    "cool_brown": "冷棕色",
    "red_brown": "红棕色",
    "dye": "染发",
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


def upload_file(path: pathlib.Path) -> str:
    upload = http_json(
        "POST",
        "/merchant/assets/upload-url",
        {
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "asset_type": "hairstyle",
            "file_ext": path.suffix.lstrip(".") or "jpg",
        },
    )
    request = urllib.request.Request(
        upload["upload_url"],
        data=path.read_bytes(),
        method="PUT",
        headers={"Content-Type": "application/octet-stream"},
    )
    with urllib.request.urlopen(request, timeout=60):
        pass
    return upload["asset_url"]


def existing_style_ids(direction: str) -> set[str]:
    query = urllib.parse.urlencode({"tenant_id": TENANT_ID, "direction": direction})
    rows = http_json("GET", "/hairstyles?" + query)
    return {row["style_id"] for row in rows}


def feature_tags(filename: str, item: dict) -> list[str]:
    stem = pathlib.Path(filename).stem.lower()
    tags = [DIRECTION_CN[item["gender"]], LENGTH_CN[item["length"]]]
    for keyword, tag in KEYWORD_TAGS.items():
        if keyword in stem and tag not in tags:
            tags.append(tag)
    if item.get("perm") in {"是", "可选"}:
        tags.append("可烫")
    if item.get("dye") in {"是", "可选"}:
        tags.append("可染")
    if item.get("bleach") == "是":
        tags.append("需漂")
    return list(dict.fromkeys(tags))[:8]


def display_metadata(item: dict, tags: list[str]) -> dict:
    ai_tags = [item["name"], LENGTH_CN[item["length"]], item["description"], *tags]
    ai_tags.extend(
        [
            "preserve the customer's original face, only change hairstyle",
            "do not copy model face, facial features, skin, body, clothes or background",
        ]
    )
    return {
        "customer_description": item["description"],
        "parameter_groups": [
            {"name": "性别方向", "values": [DIRECTION_CN[item["gender"]]]},
            {"name": "发长", "values": [LENGTH_CN[item["length"]]]},
            {"name": "烫发", "values": ["可选" if item.get("perm") == "可选" else ("需要" if item.get("perm") == "是" else "不需要")]},
            {"name": "染发", "values": ["可选" if item.get("dye") == "可选" else ("需要" if item.get("dye") == "是" else "不需要")]},
            {"name": "漂发", "values": ["需要" if item.get("bleach") == "是" else "不需要"]},
            {"name": "风格标签", "values": tags},
        ],
        "ai_reference_tags": list(dict.fromkeys(ai_tags)),
        "prompt": item.get("prompt", ""),
    }


def style_id_for(item: dict) -> str:
    stem = pathlib.Path(item["filename"]).stem.lower().replace("_style", "")
    return "asia_" + stem


def image_path_for(item: dict) -> pathlib.Path:
    image_path = ROOT / item["filename"]
    if image_path.exists():
        return image_path
    parts = pathlib.Path(item["filename"]).stem.split("_")
    if len(parts) >= 3:
        prefix = "_".join(parts[:3])
        matches = sorted(ROOT.glob(prefix + "_*.jpg"))
        if matches:
            return matches[0]
    return image_path


def main() -> None:
    items = json.loads((ROOT / "hairstyle_prompts.json").read_text(encoding="utf-8"))
    existing = {"female": existing_style_ids("female"), "male": existing_style_ids("male")}
    created = 0
    updated = 0
    failed: list[tuple[str, str]] = []

    for item in items:
        image_path = image_path_for(item)
        direction = DIRECTION_MAP[item["gender"]]
        style_id = style_id_for(item)
        tags = feature_tags(item["filename"], item)
        try:
            payload = {
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "style_id": style_id,
                "name": item["name"],
                "direction": direction,
                "hair_length": LENGTH_MAP[item["length"]],
                "thumbnail_url": upload_file(image_path),
                "display_tags": display_metadata(item, tags),
                "need_perm": item.get("perm") in {"是", "可选"},
                "is_enabled": True,
                "is_recommended": True,
                "sort_order": int(item["index"]),
            }
            if style_id in existing[direction]:
                update_payload = dict(payload)
                update_payload.pop("style_id", None)
                http_json("PUT", f"/merchant/hairstyles/{style_id}", update_payload)
                updated += 1
            else:
                http_json("POST", "/merchant/hairstyles", payload)
                existing[direction].add(style_id)
                created += 1
            if (created + updated) % 20 == 0:
                print(f"progress created={created} updated={updated}", flush=True)
        except Exception as exc:  # noqa: BLE001 - report import failures.
            failed.append((item["filename"], str(exc)[:240]))
        time.sleep(0.03)

    print(
        json.dumps(
            {
                "created": created,
                "updated": updated,
                "failed_count": len(failed),
                "failed": failed[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
