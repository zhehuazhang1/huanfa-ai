from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fail(message: str) -> None:
    raise AssertionError(message)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def assert_ok(response: Any, label: str) -> dict | list:
    if response.status_code >= 400:
        fail(f"{label} failed: {response.status_code} {response.text}")
    return response.json()


def assert_not_found(response: Any, label: str) -> None:
    expect(response.status_code == 404, f"{label} should be isolated with 404, got {response.status_code}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair_ai_acceptance_", ignore_cleanup_errors=True) as temp_dir:
        os.environ["HAIR_AI_DB_PATH"] = str(Path(temp_dir) / "acceptance.sqlite3")
        os.environ.setdefault("PAYMENT_PROVIDER", "mock")
        os.environ.setdefault("FEISHU_SYNC_PROVIDER", "mock")
        os.environ.setdefault("TEMP_STORAGE_PROVIDER", "mock")

        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        print("1. health and catalog")
        health = assert_ok(client.get("/health"), "health")
        expect(health["status"] == "ok", "health status must be ok")

        female_styles = assert_ok(client.get("/hairstyles?tenant_id=1&direction=female"), "female hairstyles")
        male_styles = assert_ok(client.get("/hairstyles?tenant_id=1&direction=male"), "male hairstyles")
        neutral_styles = assert_ok(client.get("/hairstyles?tenant_id=1&direction=neutral"), "neutral hairstyles")
        colors = assert_ok(client.get("/hair-colors?tenant_id=1&direction=female"), "hair colors")
        expect(len(female_styles) > 0, "female style catalog must not be empty")
        expect(len(male_styles) > 0, "male style catalog must not be empty")
        expect(len(neutral_styles) > 0, "neutral style catalog must not be empty")
        expect(len(colors) > 0, "color catalog must not be empty")

        print("2. customer miniapp flow")
        login = assert_ok(
            client.post(
                "/auth/wx-login",
                json={
                    "tenant_id": 1,
                    "store_id": 1,
                    "openid": "acceptance_customer",
                    "phone": "13900001111",
                    "nickname": "Acceptance Customer",
                },
            ),
            "customer login",
        )
        user_id = login["user"]["id"]

        consent_before = assert_ok(
            client.get(f"/privacy/consent?tenant_id=1&user_id={user_id}"),
            "privacy status before consent",
        )
        expect(consent_before["accepted"] is False, "new customer should not have privacy consent")

        assert_ok(
            client.post("/privacy/consent", json={"tenant_id": 1, "user_id": user_id}),
            "privacy consent",
        )
        assert_ok(
            client.post(
                "/stores/scan-qr",
                json={"tenant_id": 1, "store_id": 1, "user_id": user_id, "qr_scene": "store:1:1"},
            ),
            "store QR scan",
        )
        quota = assert_ok(
            client.get(f"/ai/quota/today?tenant_id=1&store_id=1&user_id={user_id}"),
            "daily quota",
        )
        expect(quota["in_store"] is True, "QR scan must enable in-store free quota")
        expect(quota["free_remaining"] == 2, "first in-store customer should have 2 free trials")

        upload = assert_ok(
            client.post(
                "/uploads/temp-url",
                json={"tenant_id": 1, "store_id": 1, "user_id": user_id, "file_ext": "jpg"},
            ),
            "temporary upload URL",
        )
        expect("upload_url" in upload, "temporary upload response needs upload_url")

        prepare = assert_ok(
            client.post(
                "/ai/style/prepare",
                json={
                    "tenant_id": 1,
                    "store_id": 1,
                    "user_id": user_id,
                    "direction": "female",
                    "billing_type": "free",
                    "selected_style_id": female_styles[0]["style_id"],
                    "selected_color_id": colors[0]["color_id"],
                },
            ),
            "AI prepare",
        )
        expect(len(prepare["candidate_styles"]) > 0, "AI prepare should return candidate styles")
        expect(len(prepare["candidate_colors"]) > 0, "AI prepare should return candidate colors")
        expect(len(prepare["recommendations"]) == 2, "AI prepare should return 2 recommended AI looks")

        generation = assert_ok(
            client.post(
                "/ai/style/generate",
                json={
                    "tenant_id": 1,
                    "store_id": 1,
                    "user_id": user_id,
                    "direction": "female",
                    "billing_type": "free",
                    "selected_style_id": female_styles[0]["style_id"],
                    "selected_color_id": colors[0]["color_id"],
                    "photo_temp_url": upload["photo_temp_url"],
                },
            ),
            "AI generate",
        )
        job_no = generation["job_no"]
        expect(generation["status"] == "success", "AI generation should succeed in mock mode")
        expect(len(generation["images"]) == 3, "AI generation must return 3 images")
        expect(generation["is_count_deducted"] == 1, "successful generation should deduct exactly 1 count")
        expect(generation["queue_wait_seconds"] is not None, "generation should record queue wait seconds")
        expect(generation["generate_duration_seconds"] is not None, "generation should record duration seconds")
        expect("internal_api_cost" not in generation, "customer response must not leak platform real API cost")

        result = assert_ok(
            client.get(f"/ai/style/results/{job_no}?tenant_id=1&store_id=1&user_id={user_id}"),
            "AI result detail",
        )
        expect(len(result["carousel"]["images"]) == 3, "result page needs 3 swipeable images")
        expect(len(result["recommended_stylists"]) == 3, "result page needs 3 recommended stylists")
        stylist_id = result["recommended_stylists"][0]["staff_id"]

        order = assert_ok(
            client.post(
                "/orders",
                json={
                    "tenant_id": 1,
                    "store_id": 1,
                    "user_id": user_id,
                    "stylist_id": stylist_id,
                    "direction": "female",
                    "hairstyle_id": female_styles[0]["style_id"],
                    "hair_color_id": colors[0]["color_id"],
                    "ai_job_no": job_no,
                    "notes": "acceptance check order",
                },
            ),
            "create order",
        )
        order_id = order["id"]
        expect(order["is_ai_converted"] == 1, "order created from AI result must be marked as converted")

        print("3. merchant miniapp flow")
        merchant_orders = assert_ok(
            client.get("/merchant/orders?tenant_id=1&store_id=1"),
            "merchant order list",
        )
        expect(any(item["id"] == order_id for item in merchant_orders), "merchant must see tenant/store order")

        service_items = assert_ok(
            client.get("/merchant/service-items?tenant_id=1&store_id=1"),
            "merchant service items",
        )
        expect(len(service_items) > 0, "merchant needs at least one service item to complete order")

        completed_record = assert_ok(
            client.put(
                f"/merchant/orders/{order_id}/complete",
                json={
                    "tenant_id": 1,
                    "store_id": 1,
                    "stylist_id": stylist_id,
                    "service_item_id": service_items[0]["id"],
                    "actual_amount": 399,
                },
            ),
            "complete order",
        )
        expect(completed_record["order_id"] == order_id, "complete order should create a service record for the order")
        completed_order = assert_ok(
            client.get(f"/orders/{order_id}?tenant_id=1&store_id=1"),
            "completed order detail",
        )
        expect(completed_order["status"] == "completed", "merchant complete order should set status completed")

        performance = assert_ok(
            client.get("/merchant/performance?tenant_id=1&store_id=1"),
            "merchant performance",
        )
        expect(
            performance["totals"]["completed_services"] >= 1,
            "merchant performance should count completed services",
        )

        print("4. platform billing and cost visibility")
        usage = assert_ok(client.get("/platform/usage?tenant_id=1"), "platform usage")
        costs = assert_ok(client.get("/platform/costs?tenant_id=1"), "platform costs")
        billing = assert_ok(client.get("/platform/billing?tenant_id=1&tenant_settle_unit_price=2.0"), "platform billing")
        tenant_dashboard = assert_ok(client.get("/platform/tenant-dashboard"), "platform tenant dashboard")
        expect("balance" in usage, "platform usage should expose tenant balance")
        expect(costs["success_calls"] >= 1, "platform costs should count successful AI calls")
        expect(billing["ai_service_revenue"] >= 0, "platform billing should calculate tenant AI revenue")
        expect(
            any(item["id"] == 1 and item["stores"]["total"] >= 1 for item in tenant_dashboard),
            "platform tenant dashboard should expose per-tenant store metrics",
        )

        print("5. SaaS tenant isolation")
        tenant2 = assert_ok(
            client.post(
                "/platform/tenants",
                json={"tenant_code": "acceptance_tenant_2", "name": "Acceptance Tenant 2", "initial_ai_count": 20},
            ),
            "create tenant 2",
        )
        tenant2_id = tenant2["id"]
        store2 = assert_ok(
            client.post(
                "/platform/stores",
                json={"tenant_id": tenant2_id, "store_code": "acceptance_store_2", "name": "Tenant 2 Store"},
            ),
            "create tenant 2 store",
        )
        store2_id = store2["id"]
        login2 = assert_ok(
            client.post(
                "/auth/wx-login",
                json={
                    "tenant_id": tenant2_id,
                    "store_id": store2_id,
                    "openid": "acceptance_customer_tenant_2",
                    "phone": "13900002222",
                    "nickname": "Tenant 2 Customer",
                },
            ),
            "tenant 2 login",
        )
        user2_id = login2["user"]["id"]

        assert_not_found(
            client.get(f"/orders/{order_id}?tenant_id={tenant2_id}&store_id={store2_id}"),
            "tenant 2 reading tenant 1 order",
        )
        tenant2_orders = assert_ok(
            client.get(f"/orders?tenant_id={tenant2_id}&store_id={store2_id}&user_id={user2_id}"),
            "tenant 2 customer order list",
        )
        expect(all(item["id"] != order_id for item in tenant2_orders), "tenant 2 order list must not include tenant 1 order")
        assert_not_found(
            client.get(f"/ai/style/jobs/{job_no}?tenant_id={tenant2_id}&store_id={store2_id}&user_id={user2_id}"),
            "tenant 2 reading tenant 1 AI job",
        )
        tenant2_merchant_orders = assert_ok(
            client.get(f"/merchant/orders?tenant_id={tenant2_id}&store_id={store2_id}"),
            "tenant 2 merchant order list",
        )
        expect(
            all(item["id"] != order_id for item in tenant2_merchant_orders),
            "tenant 2 merchant list must not include tenant 1 order",
        )

        print("PASS acceptance check: customer, merchant, platform, and SaaS isolation are OK")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL acceptance check: {exc}")
        raise SystemExit(1)
