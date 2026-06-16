from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def request_json(method: str, path: str, payload: dict | None = None) -> dict | list:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def get(path: str, params: dict | None = None) -> dict | list:
    if params:
        path = path + "?" + urllib.parse.urlencode(params)
    return request_json("GET", path)


def post(path: str, payload: dict) -> dict | list:
    return request_json("POST", path, payload)


def put(path: str, payload: dict) -> dict | list:
    return request_json("PUT", path, payload)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    suffix = int(time.time() * 1000)
    tenant_id = 1
    store_id = 1

    health = get("/health")
    expect(health["status"] == "ok", "backend health must be ok")
    print("OK health")

    login = post(
        "/auth/wx-login",
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "openid": f"live_customer_{suffix}",
            "phone": "13900008888",
            "nickname": "Live Smoke Customer",
        },
    )
    user_id = login["user"]["id"]
    print(f"OK customer login user_id={user_id}")

    post("/privacy/consent", {"tenant_id": tenant_id, "user_id": user_id})
    post(
        "/stores/scan-qr",
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "user_id": user_id,
            "qr_scene": "store:1:1",
        },
    )
    quota = get("/ai/quota/today", {"tenant_id": tenant_id, "store_id": store_id, "user_id": user_id})
    expect(quota["in_store"] is True and quota["free_remaining"] == 2, "QR scan should enable 2 free trials")
    print("OK QR quota")

    styles = get("/hairstyles", {"tenant_id": tenant_id, "direction": "female"})
    colors = get("/hair-colors", {"tenant_id": tenant_id, "direction": "female"})
    expect(len(styles) > 0 and len(colors) > 0, "style and color catalogs must not be empty")
    print("OK catalogs")

    upload = post(
        "/uploads/temp-url",
        {"tenant_id": tenant_id, "store_id": store_id, "user_id": user_id, "file_ext": "jpg"},
    )
    job = post(
        "/ai/style/generate",
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "user_id": user_id,
            "direction": "female",
            "billing_type": "free",
            "selected_style_id": styles[0]["style_id"],
            "selected_color_id": colors[0]["color_id"],
            "photo_temp_url": upload["photo_temp_url"],
        },
    )
    expect(job["status"] == "success", "AI generation should succeed in local mock mode")
    expect(len(job["images"]) == 3, "AI generation must return 3 images")
    print(f"OK AI generate job_no={job['job_no']}")

    result = get(
        f"/ai/style/results/{job['job_no']}",
        {"tenant_id": tenant_id, "store_id": store_id, "user_id": user_id},
    )
    expect(len(result["carousel"]["images"]) == 3, "result should expose 3 carousel images")
    expect(len(result["recommended_stylists"]) == 3, "result should recommend 3 stylists")
    print("OK result page")

    stylist_id = result["default_stylist_id"]
    order = post(
        "/orders",
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "user_id": user_id,
            "stylist_id": stylist_id,
            "direction": "female",
            "hairstyle_id": styles[0]["style_id"],
            "hair_color_id": colors[0]["color_id"],
            "ai_job_no": job["job_no"],
        },
    )
    print(f"OK create order order_id={order['id']}")

    put(
        f"/merchant/orders/{order['id']}/status",
        {"tenant_id": tenant_id, "store_id": store_id, "status": "confirmed"},
    )
    put(
        f"/merchant/orders/{order['id']}/status",
        {"tenant_id": tenant_id, "store_id": store_id, "status": "arrived"},
    )
    put(
        f"/merchant/orders/{order['id']}/status",
        {"tenant_id": tenant_id, "store_id": store_id, "status": "serving"},
    )
    service_items = get("/merchant/service-items", {"tenant_id": tenant_id, "store_id": store_id})
    put(
        f"/merchant/orders/{order['id']}/complete",
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "stylist_id": stylist_id,
            "service_item_id": service_items[0]["id"],
            "actual_amount": 399,
        },
    )
    print("OK merchant complete order")

    dashboard = get("/platform/tenant-dashboard")
    expect(any(item["id"] == tenant_id for item in dashboard), "platform dashboard should include tenant 1")
    print("OK platform dashboard")
    print("PASS live miniapp smoke")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL live miniapp smoke: {exc}")
        raise SystemExit(1)
