from __future__ import annotations

import json
import urllib.parse
import urllib.request


BASE = "http://54.255.168.182:8000"
TENANT_ID = 1
STORE_ID = 1

ITEMS = [
    {
        "category": "campaign",
        "question": "最近有什么染发套餐活动？",
        "answer": "目前门店主推试发后到店沟通套餐：剪发 + 染发方案沟通 + 基础护理，具体价格会根据发长、发量、是否漂发和目标发色确认。建议先用 AI 试发图和主理人沟通，避免选色偏差。",
        "keywords": ["活动", "套餐", "染发套餐", "节日", "优惠"],
        "sort_order": 10,
    },
    {
        "category": "price",
        "question": "染发大概多少钱？",
        "answer": "染发价格主要看发长、发量、是否需要漂发和目标颜色。普通自然色通常比高明度潮色更便宜；需要漂发、挑染或多段色修正时，价格会更高。到店后主理人会先确认发质和方案再报价。",
        "keywords": ["多少钱", "价格", "费用", "染发多少钱", "报价"],
        "sort_order": 20,
    },
    {
        "category": "care",
        "question": "染烫后怎么护理？",
        "answer": "染烫后建议 48 小时内尽量不要频繁洗头，日常使用护色洗护和发膜。浅色、灰色、蓝紫粉等潮色褪色更快，需要按主理人建议做补色或护理。",
        "keywords": ["护理", "褪色", "洗头", "发膜", "护色"],
        "sort_order": 30,
    },
    {
        "category": "booking",
        "question": "怎么预约主理人？",
        "answer": "你可以先完成 AI 试发，在结果页选择主理人并提交预约；也可以在预约页选择服务项目、时间和备注。到店后主理人会根据试发图再确认最终方案。",
        "keywords": ["预约", "主理人", "到店", "时间", "怎么约"],
        "sort_order": 40,
    },
    {
        "category": "tryon",
        "question": "AI试发会不会换脸？",
        "answer": "AI 试发会尽量保留你的五官、脸型、表情和眼镜，只调整发型发色。但 AI 生成仍可能有偏差，如果结果明显不像本人，可以重新生成或到店让主理人辅助判断。",
        "keywords": ["换脸", "不像", "变形", "AI试发", "生成"],
        "sort_order": 50,
    },
]


def http_json(method: str, path: str, data: dict | None = None) -> dict | list:
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    query = urllib.parse.urlencode({"tenant_id": TENANT_ID, "store_id": STORE_ID, "include_disabled": True})
    existing = http_json("GET", "/merchant/ai-knowledge?" + query)
    existing_by_question = {item["question"]: item for item in existing}
    created = 0
    updated = 0
    for item in ITEMS:
        payload = {
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "category": item["category"],
            "question": item["question"],
            "answer": item["answer"],
            "keywords": item["keywords"],
            "is_enabled": True,
            "sort_order": item["sort_order"],
        }
        current = existing_by_question.get(item["question"])
        if current:
            http_json("PUT", f"/merchant/ai-knowledge/{current['id']}", payload)
            updated += 1
        else:
            http_json("POST", "/merchant/ai-knowledge", payload)
            created += 1
    print(json.dumps({"created": created, "updated": updated}, ensure_ascii=False))


if __name__ == "__main__":
    main()
