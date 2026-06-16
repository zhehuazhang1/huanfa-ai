import unittest
from datetime import date

from app.models import BillingType, Direction, GenerateRequest, GenerationImage, GenerationResult, JobStatus
from app.services import BusinessError, HairAiService
from app.store import AppStore
from app.storage import AliyunOssTempStorageProvider, MockTempStorageProvider


class FailingFeishuProvider:
    provider_name = "failing"

    def sync_event(self, *, event_type: str, payload: dict) -> dict:
        return {"ok": False, "error": "network unavailable"}


class FailingDifyClient:
    provider_name = "failing_dify"

    def generate_hair_images(self, **kwargs) -> GenerationResult:
        return GenerationResult(
            status=JobStatus.FAILED,
            images=[],
            internal_api_cost=0.12,
            error_code="MODEL_FAILED",
            error_message="model failed",
        )


class MainOnlyDifyClient:
    provider_name = "main_only_dify"

    def generate_hair_images(self, **kwargs) -> GenerationResult:
        return GenerationResult(
            status=JobStatus.SUCCESS,
            images=[
                GenerationImage(
                    slot="main",
                    title="Selected style",
                    direction="female",
                    style_id="style_010",
                    style_name="Korean Medium Hair",
                    color_id="color_003",
                    color_name="Cool Brown",
                    temp_image_url="https://temp.local/main.jpg",
                )
            ],
            internal_api_cost=0.15,
        )


class HairAiCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = AppStore()
        self.store.seed_demo()
        self.service = HairAiService(self.store)
        self.service.record_privacy_consent(tenant_id=1, user_id=1)
        self.service.confirm_store_visit(
            tenant_id=1,
            store_id=1,
            user_id=1,
            qr_scene="store:1:1",
        )

    def test_successful_free_generation_deducts_once(self) -> None:
        before = self.service.account_balance(1)
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )

        self.assertEqual(job["status"], "success")
        self.assertEqual(job["is_count_deducted"], 1)
        self.assertEqual(len(job["images"]), 3)
        self.assertEqual(job["selected_style_id"], "style_010")
        self.assertEqual(job["selected_color_id"], "color_003")
        self.assertEqual(len(job["recommended_stylists"]), 3)
        self.assertEqual(job["recommended_stylists"][0]["is_default"], True)
        self.assertEqual(job["result_storage"], "temporary_url_metadata")
        self.assertIsNotNone(job["queue_wait_seconds"])
        self.assertIsNotNone(job["generate_duration_seconds"])
        self.assertEqual(self.service.account_balance(1), before - 1)

        usage_rows = self.store.rows("SELECT * FROM tenant_ai_usage_logs")
        self.assertEqual(len(usage_rows), 1)
        self.assertEqual(usage_rows[0]["balance_after"], before - 1)

    def test_generation_supports_style_only_color_only_and_both(self) -> None:
        style_only = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id=None,
            )
        )
        color_only = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id=None,
                selected_color_id="color_003",
            )
        )
        pay_order_no = self.service.create_mock_paid_order(1, 1, 1, 9.9)
        both = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.PAID,
                selected_style_id="style_010",
                selected_color_id="color_003",
                pay_order_no=pay_order_no,
            )
        )

        self.assertEqual(style_only["status"], "success")
        self.assertEqual(color_only["status"], "success")
        self.assertEqual(both["status"], "success")
        self.assertIsNone(style_only["selected_color_id"])
        self.assertIsNone(color_only["selected_style_id"])

    def test_photo_ai_generation_requires_privacy_consent(self) -> None:
        store = AppStore()
        store.seed_demo()
        service = HairAiService(store)
        service.confirm_store_visit(
            tenant_id=1,
            store_id=1,
            user_id=1,
            qr_scene="store:1:1",
        )

        with self.assertRaises(BusinessError):
            service.create_temp_upload_url(
                tenant_id=1,
                store_id=1,
                user_id=1,
                file_ext="jpg",
            )
        with self.assertRaises(BusinessError):
            service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.FREE,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )

        consent = service.record_privacy_consent(tenant_id=1, user_id=1)
        self.assertEqual(consent["status"], "accepted")
        upload = service.create_temp_upload_url(
            tenant_id=1,
            store_id=1,
            user_id=1,
            file_ext="jpg",
        )
        self.assertIn("upload_url", upload)

        service.revoke_privacy_consent(tenant_id=1, user_id=1)
        self.assertFalse(service.privacy_consent_status(tenant_id=1, user_id=1)["accepted"])

    def test_free_generation_requires_in_store_qr_scan(self) -> None:
        user = self.service.wx_login(
            tenant_id=1,
            store_id=1,
            openid="not_in_store",
            phone="13600000000",
            nickname="Remote Customer",
        )["user"]

        with self.assertRaises(BusinessError):
            self.service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=user["id"],
                    direction=Direction.FEMALE,
                    billing_type=BillingType.FREE,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )

    def test_scan_store_qr_enables_free_quota_visibility(self) -> None:
        user = self.service.wx_login(
            tenant_id=1,
            store_id=1,
            openid="scan_customer",
            phone="13700000000",
            nickname="Scan Customer",
        )["user"]
        before = self.service.quota_today(1, 1, user["id"])
        self.assertFalse(before["in_store"])

        session = self.service.confirm_store_visit(
            tenant_id=1,
            store_id=1,
            user_id=user["id"],
            qr_scene="store:1:1",
        )
        after = self.service.quota_today(1, 1, user["id"])

        self.assertEqual(session["status"], "active")
        self.assertTrue(after["in_store"])
        self.assertEqual(after["free_remaining"], 2)

    def test_in_store_customer_has_two_daily_free_ai_trials(self) -> None:
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_011",
                selected_color_id="color_004",
            )
        )
        quota = self.service.quota_today(1, 1, 1)
        self.assertEqual(quota["free_used"], 2)
        self.assertEqual(quota["free_remaining"], 0)

        with self.assertRaises(BusinessError):
            self.service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.FREE,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )

    def test_enqueue_generation_waits_for_worker_to_process(self) -> None:
        before = self.service.account_balance(1)
        queued = self.service.enqueue_generation(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
                photo_temp_url="https://temp.local/selfie.jpg",
            )
        )
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(self.service.queue.size(), 1)
        self.assertEqual(self.service.account_balance(1), before)

        processed = self.service.process_next_generation_job()
        self.assertIsNotNone(processed)
        assert processed is not None
        self.assertEqual(processed["status"], "success")
        self.assertEqual(len(processed["images"]), 3)
        self.assertNotIn("photo_temp_url", processed)
        self.assertEqual(self.service.account_balance(1), before - 1)
        self.assertEqual(self.service.queue.size(), 0)

    def test_main_image_success_is_usable_when_recommendations_fail(self) -> None:
        before = self.service.account_balance(1)
        service = HairAiService(self.store, dify_client=MainOnlyDifyClient())
        job = service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )

        self.assertEqual(job["status"], "success")
        self.assertEqual(job["main_status"], "success")
        self.assertEqual(job["recommend_1_status"], "pending")
        self.assertEqual(job["recommend_2_status"], "pending")
        self.assertEqual(len(job["images"]), 1)
        self.assertEqual(job["images"][0]["slot"], "main")
        self.assertEqual(job["is_count_deducted"], 1)
        self.assertEqual(service.account_balance(1), before - 1)

    def test_wx_login_creates_and_reuses_customer(self) -> None:
        first = self.service.wx_login(
            tenant_id=1,
            store_id=1,
            openid="new_customer_openid",
            phone="13500000000",
            nickname="New Customer",
        )
        self.assertTrue(first["is_new"])
        self.assertEqual(first["user"]["role"], "customer")

        second = self.service.wx_login(
            tenant_id=1,
            store_id=1,
            openid="new_customer_openid",
            phone="13500000000",
            nickname="New Customer",
        )
        self.assertFalse(second["is_new"])
        self.assertEqual(second["user"]["id"], first["user"]["id"])

    def test_paid_generation_requires_paid_order(self) -> None:
        with self.assertRaises(BusinessError):
            self.service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.PAID,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )

    def test_mock_paid_order_allows_paid_generation(self) -> None:
        pay_order_no = self.service.create_mock_paid_order(1, 1, 1, 9.9)
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.PAID,
                selected_style_id="style_010",
                selected_color_id="color_003",
                pay_order_no=pay_order_no,
            )
        )
        self.assertEqual(job["status"], "success")
        self.assertNotIn("internal_api_cost", job)

    def test_paid_generation_failure_allows_one_free_retry_with_same_payment(self) -> None:
        pay_order_no = self.service.create_mock_paid_order(1, 1, 1, 9.9)
        failing_service = HairAiService(self.store, dify_client=FailingDifyClient())
        failed = failing_service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.PAID,
                selected_style_id="style_010",
                selected_color_id="color_003",
                pay_order_no=pay_order_no,
            )
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["is_count_deducted"], 0)

        retried = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.PAID,
                selected_style_id="style_010",
                selected_color_id="color_003",
                pay_order_no=pay_order_no,
            )
        )
        self.assertEqual(retried["status"], "success")

        with self.assertRaises(BusinessError):
            self.service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.PAID,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                    pay_order_no=pay_order_no,
                )
            )

    def test_failed_generation_does_not_use_daily_generation_limit(self) -> None:
        self.service.update_ai_limits(
            tenant_id=None,
            store_id=None,
            user_concurrency_limit=1,
            store_concurrency_limit=5,
            tenant_concurrency_limit=20,
            platform_concurrency_limit=50,
            user_daily_limit=1,
            tenant_daily_limit=5000,
        )
        failing_service = HairAiService(self.store, dify_client=FailingDifyClient())
        failed = failing_service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        retried = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["is_count_deducted"], 0)
        self.assertEqual(retried["status"], "success")
        self.assertEqual(self.service.quota_today(1, 1, 1)["free_used"], 1)

    def test_prepare_recommendations_uses_store_candidates(self) -> None:
        prepared = self.service.prepare_recommendations(1, "female", "style_010", "color_003")
        self.assertGreaterEqual(len(prepared["candidate_styles"]), 2)
        self.assertGreaterEqual(len(prepared["candidate_colors"]), 2)
        self.assertEqual(len(prepared["recommendations"]), 2)
        self.assertIn("style_id", prepared["recommendations"][0])
        natural, advanced = prepared["recommendations"]
        self.assertEqual(natural["slot"], "natural")
        self.assertEqual(natural["style_id"], "style_010")
        self.assertEqual(natural["color_id"], "color_004")
        self.assertEqual(advanced["slot"], "advanced")
        self.assertEqual(advanced["style_id"], "style_011")
        self.assertEqual(advanced["color_id"], "color_003")

    def test_prepare_recommendations_uses_selected_color_with_hot_style_when_no_style_selected(self) -> None:
        prepared = self.service.prepare_recommendations(1, "female", None, "color_003")
        natural, advanced = prepared["recommendations"]

        self.assertEqual(natural["style_id"], "style_010")
        self.assertEqual(natural["color_id"], "color_003")
        self.assertEqual(advanced["style_id"], "style_011")
        self.assertEqual(advanced["color_id"], "color_003")

    def test_prepare_recommendations_uses_selected_style_with_hot_color_when_no_color_selected(self) -> None:
        prepared = self.service.prepare_recommendations(1, "female", "style_010", None)
        natural, advanced = prepared["recommendations"]

        self.assertEqual(natural["style_id"], "style_010")
        self.assertEqual(natural["color_id"], "color_003")
        self.assertEqual(advanced["style_id"], "style_011")

    def test_prepare_recommendations_passes_hairstyle_reference_image(self) -> None:
        created = self.service.create_hairstyle(
            tenant_id=1,
            store_id=1,
            style_id="style_reference_001",
            name="Reference hairstyle",
            direction="female",
            hair_length="medium",
            thumbnail_url="https://catalog.local/reference-style.jpg",
            display_tags=["reference"],
            need_perm=False,
            is_enabled=True,
            is_recommended=True,
        )

        prepared = self.service.prepare_recommendations(1, "female", created["style_id"], None)

        self.assertEqual(
            prepared["selected_style"]["thumbnail_url"],
            "https://catalog.local/reference-style.jpg",
        )
        self.assertTrue(any("thumbnail_url" in item for item in prepared["recommendations"]))

    def test_customer_inspiration_groups_hot_lengths_and_colors(self) -> None:
        inspiration = self.service.hairstyle_inspiration(1, "female")
        tabs = {tab["key"]: tab for tab in inspiration["tabs"]}

        self.assertIn("hot", tabs)
        self.assertIn("medium", tabs)
        self.assertIn("short", tabs)
        self.assertIn("colors", tabs)
        self.assertGreaterEqual(len(tabs["hot"]["items"]), 1)
        self.assertTrue(all(item["hair_length"] == "medium" for item in tabs["medium"]["items"]))
        self.assertGreaterEqual(len(tabs["colors"]["items"]), 1)

    def test_pending_payment_can_be_marked_paid(self) -> None:
        pay_order_no = self.service.create_pending_payment_order(1, 1, 1, 9.9)
        pending = self.service.payment_order(pay_order_no)
        self.assertEqual(pending["pay_status"], "pending")

        paid = self.service.mark_payment_paid(pay_order_no)
        self.assertEqual(paid["pay_status"], "paid")

    def test_create_ai_payment_returns_mini_program_prepay_params(self) -> None:
        payment = self.service.create_ai_payment(
            tenant_id=1,
            store_id=1,
            user_id=1,
            amount=9.9,
            mock_paid=False,
        )

        self.assertEqual(payment["pay_status"], "pending")
        self.assertEqual(payment["mode"], "mock")
        self.assertIn("wechat_pay_params", payment["prepay"])
        self.assertIn("package", payment["prepay"]["wechat_pay_params"])

        order = self.service.payment_order_for_customer(
            tenant_id=1,
            store_id=1,
            user_id=1,
            pay_order_no=payment["pay_order_no"],
        )
        self.assertEqual(order["pay_status"], "pending")

    def test_create_ai_payment_rejects_zero_amount(self) -> None:
        with self.assertRaises(BusinessError):
            self.service.create_ai_payment(
                tenant_id=1,
                store_id=1,
                user_id=1,
                amount=0,
                mock_paid=False,
            )

    def test_tenant_2_cannot_read_tenant_1_payment_order(self) -> None:
        pay_order_no = self.service.create_mock_paid_order(1, 1, 1, 9.9)
        visible_to_tenant_1 = self.service.payment_order_for_customer(
            tenant_id=1,
            store_id=1,
            user_id=1,
            pay_order_no=pay_order_no,
        )
        self.assertEqual(visible_to_tenant_1["pay_order_no"], pay_order_no)

        with self.assertRaises(BusinessError):
            self.service.payment_order_for_customer(
                tenant_id=2,
                store_id=1,
                user_id=1,
                pay_order_no=pay_order_no,
            )

    def test_tenant_2_cannot_read_tenant_1_ai_job(self) -> None:
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        visible_to_tenant_1 = self.service.get_customer_job(
            tenant_id=1,
            store_id=1,
            user_id=1,
            job_no=job["job_no"],
        )
        self.assertEqual(visible_to_tenant_1["job_no"], job["job_no"])
        self.assertNotIn("internal_api_cost", visible_to_tenant_1)

        with self.assertRaises(BusinessError):
            self.service.get_customer_job(
                tenant_id=2,
                store_id=1,
                user_id=1,
                job_no=job["job_no"],
            )

    def test_result_detail_returns_swipe_carousel_and_three_stylists(self) -> None:
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        detail = self.service.result_detail(
            tenant_id=1,
            store_id=1,
            user_id=1,
            job_no=job["job_no"],
        )

        self.assertEqual(detail["carousel"]["mode"], "swipe")
        self.assertEqual(len(detail["carousel"]["images"]), 3)
        self.assertEqual(len(detail["recommended_stylists"]), 3)
        self.assertEqual(detail["default_stylist_id"], detail["recommended_stylists"][0]["staff_id"])
        self.assertIn("save_hint", detail)
        self.assertIn("result_tags", detail)
        self.assertNotIn("internal_api_cost", detail)

    def test_result_detail_supports_style_without_color(self) -> None:
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id=None,
            )
        )
        detail = self.service.result_detail(
            tenant_id=1,
            store_id=1,
            user_id=1,
            job_no=job["job_no"],
        )

        self.assertEqual(detail["selected_style_id"], "style_010")
        self.assertIsNone(detail["selected_color_id"])
        self.assertTrue(any(tag["type"] == "style" for tag in detail["result_tags"]))
        self.assertFalse(any(tag["type"] == "color" for tag in detail["result_tags"]))

    def test_result_images_survive_service_restart(self) -> None:
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )

        restarted_service = HairAiService(self.store)
        restored = restarted_service.result_detail(
            tenant_id=1,
            store_id=1,
            user_id=1,
            job_no=job["job_no"],
        )

        self.assertEqual(len(restored["carousel"]["images"]), 3)

    def test_result_detail_returns_main_image_while_recommendations_are_running(self) -> None:
        self.store.conn.execute(
            """
            INSERT INTO ai_generation_jobs
            (tenant_id, store_id, user_id, job_no, direction, billing_type, status, main_status,
             selected_style_id, selected_color_id)
            VALUES (1, 1, 1, 'AI_PARTIAL', 'female', 'free', 'running', 'pending',
                    'style_010', 'color_003')
            """
        )
        self.store.conn.commit()
        self.service.save_partial_generation_images(
            "AI_PARTIAL",
            [
                {
                    "slot": "main",
                    "title": "Selected style",
                    "direction": "female",
                    "style_id": "style_010",
                    "style_name": "Korean Medium Hair",
                    "color_id": "color_003",
                    "color_name": "Cool Brown",
                    "temp_image_url": "https://temp.local/main.jpg",
                }
            ],
        )

        detail = self.service.result_detail(
            tenant_id=1,
            store_id=1,
            user_id=1,
            job_no="AI_PARTIAL",
        )

        self.assertEqual(detail["status"], "running")
        self.assertEqual(len(detail["carousel"]["images"]), 1)
        self.assertEqual(detail["carousel"]["images"][0]["slot"], "main")

    def test_duplicate_running_job_returns_public_existing_job(self) -> None:
        self.store.conn.execute(
            """
            INSERT INTO ai_generation_jobs
            (tenant_id, store_id, user_id, job_no, direction, billing_type, status, internal_api_cost)
            VALUES (1, 1, 1, 'AI_RUNNING', 'female', 'free', 'running', 9.99)
            """
        )
        self.store.conn.commit()

        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        self.assertEqual(job["job_no"], "AI_RUNNING")
        self.assertEqual(job["status"], "running")
        self.assertNotIn("internal_api_cost", job)

    def test_user_concurrency_limit_returns_existing_active_job(self) -> None:
        self.store.conn.execute(
            """
            INSERT INTO ai_generation_jobs
            (tenant_id, store_id, user_id, job_no, direction, billing_type, status)
            VALUES (1, 1, 1, 'AI_ACTIVE_USER', 'female', 'free', 'running')
            """
        )
        self.store.conn.commit()

        job = self.service.enqueue_generation(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        self.assertEqual(job["job_no"], "AI_ACTIVE_USER")
        self.assertEqual(job["status"], "running")

    def test_store_concurrency_limit_is_configurable(self) -> None:
        self.store.conn.execute(
            """
            UPDATE ai_limit_configs
            SET user_concurrency_limit = 10, store_concurrency_limit = 1
            WHERE id = 1
            """
        )
        self.store.conn.execute(
            """
            INSERT INTO ai_generation_jobs
            (tenant_id, store_id, user_id, job_no, direction, billing_type, status)
            VALUES (1, 1, 99, 'AI_ACTIVE_STORE', 'female', 'free', 'running')
            """
        )
        self.store.conn.commit()

        with self.assertRaises(BusinessError):
            self.service.enqueue_generation(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.FREE,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )

    def test_platform_can_update_ai_limits(self) -> None:
        config = self.service.update_ai_limits(
            tenant_id=1,
            store_id=1,
            user_concurrency_limit=2,
            store_concurrency_limit=6,
            tenant_concurrency_limit=21,
            platform_concurrency_limit=55,
            user_daily_limit=30,
            tenant_daily_limit=6000,
        )
        self.assertEqual(config["user_concurrency_limit"], 2)
        limits = self.service.ai_limits(1, 1)
        self.assertEqual(limits["store_concurrency_limit"], 6)
        self.assertEqual(limits["tenant_daily_limit"], 6000)

    def test_deployment_readiness_blocks_production_with_mock_providers(self) -> None:
        readiness = self.service.deployment_readiness("production")
        self.assertFalse(readiness["ready_for_production"])
        self.assertIn("dify", readiness["providers"])
        self.assertGreaterEqual(len(readiness["blockers"]), 3)

    def test_deployment_readiness_warns_in_local_with_mock_providers(self) -> None:
        readiness = self.service.deployment_readiness("local")
        self.assertTrue(readiness["ready_for_production"])
        self.assertEqual(readiness["blockers"], [])
        self.assertGreaterEqual(len(readiness["warnings"]), 3)

    def test_poc_evaluation_summary_tracks_effect_and_cost(self) -> None:
        self.service.create_poc_evaluation(
            tenant_id=1,
            store_id=1,
            job_no="AI_POC_001",
            direction="female",
            test_case_no="POC-001",
            input_photo_label="female-01",
            selected_style_id="style_010",
            selected_color_id="color_003",
            is_like_customer=True,
            only_changed_hair=True,
            face_changed=False,
            generated_three_images=True,
            hair_color_accurate=True,
            hairstyle_acceptable=True,
            can_show_customer=True,
            generate_duration_seconds=32,
            internal_api_cost=0.88,
            notes="good",
        )
        self.service.create_poc_evaluation(
            tenant_id=1,
            store_id=1,
            job_no="AI_POC_002",
            direction="male",
            test_case_no="POC-002",
            input_photo_label="male-01",
            selected_style_id="style_021",
            selected_color_id=None,
            is_like_customer=False,
            only_changed_hair=False,
            face_changed=True,
            generated_three_images=False,
            hair_color_accurate=False,
            hairstyle_acceptable=False,
            can_show_customer=False,
            generate_duration_seconds=52,
            internal_api_cost=0.42,
            notes="bad",
        )

        summary = self.service.poc_evaluation_summary(1)
        self.assertEqual(summary["total_cases"], 2)
        self.assertEqual(summary["three_image_success_rate"], 0.5)
        self.assertEqual(summary["like_customer_rate"], 0.5)
        self.assertEqual(summary["only_hair_change_rate"], 0.5)
        self.assertEqual(summary["showable_rate"], 0.5)
        self.assertEqual(summary["avg_generate_duration_seconds"], 42)
        self.assertEqual(summary["avg_internal_api_cost"], 0.65)

    def test_staff_can_gift_and_customer_can_use_gift_generation(self) -> None:
        gift = self.service.grant_ai_gift(1, 1, customer_id=1, staff_id=2)
        self.assertEqual(gift["status"], "unused")

        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.GIFT,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        self.assertEqual(job["status"], "success")

        gift_after = self.store.row("SELECT * FROM ai_gift_records WHERE id = ?", (gift["id"],))
        self.assertEqual(gift_after["status"], "used")

    def test_gift_ai_trial_conversion_tracks_order_and_revenue(self) -> None:
        gift = self.service.grant_ai_gift(1, 1, customer_id=1, staff_id=2)
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.GIFT,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=job["job_no"],
        )
        gift_after_order = self.store.row("SELECT * FROM ai_gift_records WHERE id = ?", (gift["id"],))
        self.assertEqual(gift_after_order["order_id"], order["id"])

        self.service.complete_order(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            stylist_id=2,
            service_item_id=110,
            actual_amount=399,
        )
        stats = self.service.merchant_gift_conversion(tenant_id=1, store_id=1)
        self.assertEqual(stats["totals"]["gifted_count"], 1)
        self.assertEqual(stats["totals"]["used_count"], 1)
        self.assertEqual(stats["totals"]["order_count"], 1)
        self.assertEqual(stats["totals"]["completed_order_count"], 1)
        self.assertEqual(stats["totals"]["revenue"], 399)
        self.assertEqual(stats["totals"]["completed_conversion_rate"], 1.0)
        self.assertEqual(stats["by_staff"][0]["staff_id"], 2)

    def test_recommend_stylists_returns_three_available_store_staff(self) -> None:
        stylists = self.service.recommend_stylists(
            tenant_id=1,
            store_id=1,
            direction="female",
            selected_style_id="style_010",
            selected_color_id="color_003",
        )
        self.assertEqual(len(stylists), 3)
        self.assertEqual(stylists[0]["is_default"], True)
        self.assertTrue(all(item["availability_status"] == "available" for item in stylists))
        self.assertNotIn(7, [item["staff_id"] for item in stylists])

    def test_merchant_can_create_and_list_staff(self) -> None:
        staff = self.service.create_staff(
            tenant_id=1,
            store_id=1,
            openid="new_staff_openid",
            phone="13800000000",
            display_name="New Stylist",
            title="Senior Stylist",
            directions=["female", "neutral"],
            skill_tags=["color", "medium hair"],
            avatar_url="https://temp.local/staff.jpg",
            role="staff",
            sort_order=5,
        )
        self.assertEqual(staff["display_name"], "New Stylist")
        self.assertEqual(staff["directions"], ["female", "neutral"])
        self.assertEqual(staff["skill_tags"], ["color", "medium hair"])

        staff_list = self.service.list_staff(1, 1)
        self.assertIn(staff["staff_id"], [item["staff_id"] for item in staff_list])

    def test_merchant_can_update_and_disable_staff_profile(self) -> None:
        staff = self.service.update_staff_profile(
            tenant_id=1,
            store_id=1,
            staff_id=2,
            display_name="Updated Stylist",
            directions=["male"],
            skill_tags=["short hair", "texture"],
            availability_status="available",
            is_enabled=False,
            is_recommended=False,
            sort_order=99,
        )
        self.assertEqual(staff["display_name"], "Updated Stylist")
        self.assertEqual(staff["directions"], ["male"])
        self.assertEqual(staff["is_enabled"], 0)

        stylists = self.service.recommend_stylists(
            tenant_id=1,
            store_id=1,
            direction="male",
            selected_style_id="style_021",
            selected_color_id=None,
        )
        self.assertNotIn(2, [item["staff_id"] for item in stylists])

    def test_busy_or_paused_staff_are_not_recommended(self) -> None:
        self.service.update_staff_status(
            tenant_id=1,
            store_id=1,
            staff_id=2,
            availability_status="busy",
        )
        stylists = self.service.recommend_stylists(
            tenant_id=1,
            store_id=1,
            direction="female",
            selected_style_id="style_010",
            selected_color_id="color_003",
        )
        self.assertNotIn(2, [item["staff_id"] for item in stylists])

    def test_tenant_2_cannot_recommend_tenant_1_stylists(self) -> None:
        stylists = self.service.recommend_stylists(
            tenant_id=2,
            store_id=1,
            direction="female",
            selected_style_id="style_010",
            selected_color_id="color_003",
        )
        self.assertEqual(stylists, [])

    def test_manager_can_add_staff_gift_quota(self) -> None:
        quota = self.service.add_staff_gift_quota(1, 1, staff_id=2, extra_count=3)
        self.assertEqual(quota["extra_granted"], 3)

    def test_merchant_can_list_and_create_service_items(self) -> None:
        services = self.service.list_service_items(1, 1)
        self.assertGreaterEqual(len(services), 5)
        created = self.service.create_service_item(
            tenant_id=1,
            store_id=1,
            name="Scalp Spa",
            category="care",
            base_price=268,
            sort_order=60,
        )
        self.assertEqual(created["name"], "Scalp Spa")
        services_after = self.service.list_service_items(1, 1)
        self.assertIn(created["id"], [item["id"] for item in services_after])

        updated = self.service.update_service_item(
            tenant_id=1,
            service_item_id=created["id"],
            name="Premium Scalp Spa",
            category="care",
            base_price=368,
            is_enabled=False,
            sort_order=61,
        )
        self.assertEqual(updated["name"], "Premium Scalp Spa")
        self.assertEqual(updated["base_price"], 368)
        services_enabled = self.service.list_service_items(1, 1)
        self.assertNotIn(created["id"], [item["id"] for item in services_enabled])
        services_all = self.service.list_service_items(1, 1, include_disabled=True)
        self.assertIn(created["id"], [item["id"] for item in services_all])

        reenabled = self.service.update_service_item(
            tenant_id=1,
            service_item_id=created["id"],
            is_enabled=True,
        )
        self.assertEqual(reenabled["is_enabled"], 1)
        services_reenabled = self.service.list_service_items(1, 1)
        self.assertIn(created["id"], [item["id"] for item in services_reenabled])

    def test_ai_asset_tags_are_suggestions_not_auto_saved(self) -> None:
        suggestion = self.service.suggest_asset_tags(
            tenant_id=1,
            store_id=1,
            asset_type="hairstyle",
            image_url="https://temp.local/style.jpg",
        )
        self.assertEqual(suggestion["asset_type"], "hairstyle")
        self.assertFalse(suggestion["auto_saved"])
        self.assertIn("display_tags", suggestion["suggestion"])

    def test_ai_asset_tags_reject_invalid_asset_type(self) -> None:
        with self.assertRaises(BusinessError):
            self.service.suggest_asset_tags(
                tenant_id=1,
                store_id=1,
                asset_type="unknown",
                image_url="https://temp.local/style.jpg",
            )

    def test_merchant_can_create_hairstyle_with_tags(self) -> None:
        item = self.service.create_hairstyle(
            tenant_id=1,
            store_id=1,
            style_id="style_custom_001",
            name="Layered Medium Cut",
            direction="female",
            hair_length="medium",
            thumbnail_url="https://temp.local/style_custom_001.jpg",
            display_tags=["layered", "soft"],
            need_perm=True,
            is_enabled=True,
            is_recommended=True,
            sort_order=1,
        )
        self.assertEqual(item["style_id"], "style_custom_001")
        styles = self.service.list_styles(1, "female")
        created = next(style for style in styles if style["style_id"] == "style_custom_001")
        self.assertEqual(created["tags"], ["layered", "soft"])
        self.assertEqual(created["thumbnail_url"], "https://temp.local/style_custom_001.jpg")

        updated = self.service.update_hairstyle(
            tenant_id=1,
            style_id="style_custom_001",
            name="Updated Layered Medium Cut",
            display_tags=["updated", "soft"],
            need_perm=False,
            is_enabled=False,
        )
        self.assertEqual(updated["name"], "Updated Layered Medium Cut")
        styles_after = self.service.list_styles(1, "female")
        self.assertNotIn("style_custom_001", [style["style_id"] for style in styles_after])

    def test_merchant_can_create_hair_color_with_tags(self) -> None:
        item = self.service.create_hair_color(
            tenant_id=1,
            store_id=1,
            color_id="color_custom_001",
            name="Smoky Brown",
            direction="female",
            color_swatch="#8A6B5A",
            display_tags=["natural", "cool"],
            need_bleach=False,
            is_enabled=True,
            is_recommended=True,
            sort_order=1,
        )
        self.assertEqual(item["color_id"], "color_custom_001")
        colors = self.service.list_colors(1, "female")
        created = next(color for color in colors if color["color_id"] == "color_custom_001")
        self.assertEqual(created["tags"], ["natural", "cool"])
        self.assertEqual(created["color_swatch"], "#8A6B5A")

        updated = self.service.update_hair_color(
            tenant_id=1,
            color_id="color_custom_001",
            name="Updated Smoky Brown",
            display_tags=["updated", "cool"],
            need_bleach=True,
            is_enabled=False,
        )
        self.assertEqual(updated["name"], "Updated Smoky Brown")
        colors_after = self.service.list_colors(1, "female")
        self.assertNotIn("color_custom_001", [color["color_id"] for color in colors_after])

    def test_asset_popularity_tracks_views_generation_and_orders(self) -> None:
        self.service.track_asset_event(
            tenant_id=1,
            store_id=1,
            user_id=1,
            asset_type="hairstyle",
            asset_id="style_010",
            event_type="view",
        )
        self.service.track_asset_event(
            tenant_id=1,
            store_id=1,
            user_id=1,
            asset_type="hair_color",
            asset_id="color_003",
            event_type="view",
        )
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=job["job_no"],
        )

        all_popularity = self.service.asset_popularity(tenant_id=1, store_id=1)
        self.assertEqual(all_popularity["hairstyles"][0]["asset_id"], "style_010")
        self.assertEqual(all_popularity["hairstyles"][0]["event_count"], 3)
        self.assertEqual(all_popularity["hair_colors"][0]["asset_id"], "color_003")
        self.assertEqual(all_popularity["hair_colors"][0]["event_count"], 3)

        order_popularity = self.service.asset_popularity(
            tenant_id=1,
            store_id=1,
            event_type="order",
        )
        self.assertEqual(order_popularity["hairstyles"][0]["event_count"], 1)

    def test_ai_chat_answers_service_price_from_configured_services(self) -> None:
        answer = self.service.ai_chat(
            tenant_id=1,
            store_id=1,
            user_id=1,
            message="How much does color cost?",
        )
        self.assertFalse(answer["fallback"])
        self.assertEqual(answer["actions"][0]["type"], "view_services")
        self.assertIn("reference prices", answer["answer"])
        self.assertGreaterEqual(len(answer["data"]["services"]), 1)

    def test_ai_chat_defaults_to_chinese_for_chinese_message(self) -> None:
        answer = self.service.ai_chat(
            tenant_id=1,
            store_id=1,
            user_id=1,
            message="发型试发怎么用？",
        )

        self.assertFalse(answer["fallback"])
        self.assertIn("AI试发", answer["answer"])
        self.assertEqual(answer["actions"][0]["label"], "开始AI试发")

    def test_ai_chat_fallbacks_for_unrelated_questions(self) -> None:
        answer = self.service.ai_chat(
            tenant_id=1,
            store_id=1,
            user_id=1,
            message="What is the weather?",
        )
        self.assertTrue(answer["fallback"])
        self.assertEqual(answer["actions"][0]["type"], "contact_store")
        self.assertIn("AI styling", answer["answer"])

    def test_ai_chat_uses_merchant_knowledge_base(self) -> None:
        item = self.service.create_ai_knowledge_item(
            tenant_id=1,
            store_id=1,
            category="aftercare",
            question="How to care after perm",
            answer="Avoid washing hair for 48 hours after perm.",
            keywords=["after perm", "perm care"],
            is_enabled=True,
            sort_order=1,
        )
        answer = self.service.ai_chat(
            tenant_id=1,
            store_id=1,
            user_id=1,
            message="Can you tell me after perm care?",
        )

        self.assertFalse(answer["fallback"])
        self.assertEqual(answer["answer"], "Avoid washing hair for 48 hours after perm.")
        self.assertEqual(answer["data"]["knowledge_item_id"], item["id"])

    def test_merchant_can_update_and_disable_ai_knowledge(self) -> None:
        item = self.service.create_ai_knowledge_item(
            tenant_id=1,
            store_id=1,
            category="pricing",
            question="How much is hair color",
            answer="Color starts from 299.",
            keywords=["hair color price"],
            is_enabled=True,
            sort_order=1,
        )
        updated = self.service.update_ai_knowledge_item(
            tenant_id=1,
            item_id=item["id"],
            answer="Color starts from 399. Final price is confirmed in store.",
            keywords=["color fee"],
            is_enabled=False,
        )
        self.assertEqual(updated["answer"], "Color starts from 399. Final price is confirmed in store.")
        self.assertEqual(updated["keywords"], ["color fee"])
        self.assertEqual(updated["is_enabled"], 0)

        visible = self.service.list_ai_knowledge_items(1, 1)
        self.assertNotIn(item["id"], [row["id"] for row in visible])
        all_items = self.service.list_ai_knowledge_items(1, 1, include_disabled=True)
        self.assertIn(item["id"], [row["id"] for row in all_items])

        answer = self.service.ai_chat(tenant_id=1, store_id=1, user_id=1, message="color fee")
        self.assertNotEqual(answer["data"].get("knowledge_item_id"), item["id"])

    def test_ai_converted_order_and_service_record(self) -> None:
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=job["job_no"],
        )
        self.assertEqual(order["is_ai_converted"], 1)

        record = self.service.complete_order(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            stylist_id=2,
            service_item_id=110,
            actual_amount=399,
        )
        self.assertEqual(record["actual_amount"], 399)
        self.assertEqual(record["is_ai_converted"], 1)

    def test_merchant_order_status_flow_and_assign_stylist(self) -> None:
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=None,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=None,
        )

        assigned = self.service.assign_order_stylist(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            stylist_id=2,
        )
        self.assertEqual(assigned["stylist_id"], 2)

        confirmed = self.service.update_order_status(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            status="confirmed",
        )
        self.assertEqual(confirmed["status"], "confirmed")

        arrived = self.service.update_order_status(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            status="arrived",
        )
        self.assertEqual(arrived["status"], "arrived")

        serving = self.service.update_order_status(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            status="serving",
        )
        self.assertEqual(serving["status"], "serving")

        with self.assertRaises(BusinessError):
            self.service.update_order_status(
                tenant_id=1,
                store_id=1,
                order_id=order["id"],
                status="arrived",
            )

    def test_merchant_can_list_orders_by_status_and_stylist(self) -> None:
        order_1 = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=None,
        )
        order_2 = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=3,
            direction="female",
            hairstyle_id="style_011",
            hair_color_id="color_004",
            ai_job_no=None,
        )
        self.service.update_order_status(
            tenant_id=1,
            store_id=1,
            order_id=order_2["id"],
            status="confirmed",
        )

        pending_orders = self.service.list_merchant_orders(
            tenant_id=1,
            store_id=1,
            status="pending",
        )
        self.assertIn(order_1["id"], [item["id"] for item in pending_orders])
        self.assertNotIn(order_2["id"], [item["id"] for item in pending_orders])
        self.assertIn("customer_name", pending_orders[0])
        self.assertIn("stylist_name", pending_orders[0])

        stylist_orders = self.service.list_merchant_orders(
            tenant_id=1,
            store_id=1,
            stylist_id=3,
        )
        self.assertEqual([item["id"] for item in stylist_orders], [order_2["id"]])

        tenant_2_orders = self.service.list_merchant_orders(
            tenant_id=2,
            store_id=1,
        )
        self.assertEqual(tenant_2_orders, [])

    def test_serving_order_requires_assigned_stylist(self) -> None:
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=None,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=None,
        )
        self.service.update_order_status(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            status="confirmed",
        )
        self.service.update_order_status(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            status="arrived",
        )
        with self.assertRaises(BusinessError):
            self.service.update_order_status(
                tenant_id=1,
                store_id=1,
                order_id=order["id"],
                status="serving",
            )

    def test_tenant_2_cannot_read_tenant_1_order(self) -> None:
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=None,
        )

        visible_to_tenant_1 = self.service.get_order(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
        )
        self.assertEqual(visible_to_tenant_1["id"], order["id"])

        with self.assertRaises(BusinessError):
            self.service.get_order(
                tenant_id=2,
                store_id=1,
                order_id=order["id"],
            )

    def test_customer_can_list_only_own_orders(self) -> None:
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=None,
        )
        self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=4,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_011",
            hair_color_id="color_004",
            ai_job_no=None,
        )

        orders = self.service.list_customer_orders(tenant_id=1, user_id=1, store_id=1)
        self.assertEqual([item["id"] for item in orders], [order["id"]])
        self.assertIn("store_name", orders[0])
        self.assertIn("stylist_name", orders[0])

        tenant_2_orders = self.service.list_customer_orders(tenant_id=2, user_id=1)
        self.assertEqual(tenant_2_orders, [])

    def test_platform_costs_and_billing_hide_customer_cost_boundary(self) -> None:
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        costs = self.service.platform_costs(1)
        billing = self.service.platform_billing(1, tenant_settle_unit_price=2.0)

        self.assertEqual(costs["success_calls"], 1)
        self.assertGreater(costs["internal_api_cost"], 0)
        self.assertEqual(billing["customer_visible_cost"], 2.0)
        self.assertGreater(billing["platform_gross_profit"], 0)

    def test_platform_can_create_tenant_and_purchase_ai_package(self) -> None:
        tenant = self.service.create_tenant(
            tenant_code="tenant_new",
            name="New Hair Brand",
            package_plan="store_plan",
            initial_ai_count=100,
        )
        self.assertEqual(tenant["name"], "New Hair Brand")
        self.assertEqual(self.service.account_balance(tenant["id"]), 100)

        package_order = self.service.purchase_ai_package(
            tenant_id=tenant["id"],
            package_name="trial_500",
            purchased_count=500,
            unit_price=1.5,
        )
        self.assertEqual(package_order["total_amount"], 750)
        self.assertEqual(self.service.account_balance(tenant["id"]), 600)
        package_orders = self.service.list_ai_package_orders(tenant_id=tenant["id"])
        self.assertEqual([item["id"] for item in package_orders], [package_order["id"]])
        self.assertEqual(package_orders[0]["tenant_name"], "New Hair Brand")

    def test_platform_can_adjust_ai_balance_with_audit_log(self) -> None:
        before = self.service.account_balance(1)
        log = self.service.adjust_tenant_ai_balance(
            tenant_id=1,
            store_id=1,
            change_count=10,
            usage_type="compensate",
            remark="POC compensation",
            user_id=3,
        )
        self.assertEqual(log["usage_type"], "compensate")
        self.assertEqual(log["change_count"], 10)
        self.assertEqual(log["balance_after"], before + 10)
        self.assertEqual(self.service.account_balance(1), before + 10)

        negative = self.service.adjust_tenant_ai_balance(
            tenant_id=1,
            store_id=1,
            change_count=-5,
            usage_type="admin_adjust",
            remark="Correction",
            user_id=3,
        )
        self.assertEqual(negative["balance_after"], before + 5)
        self.assertEqual(self.service.account_balance(1), before + 5)

    def test_platform_ai_balance_adjustment_cannot_make_balance_negative(self) -> None:
        balance = self.service.account_balance(1)
        with self.assertRaises(BusinessError):
            self.service.adjust_tenant_ai_balance(
                tenant_id=1,
                store_id=1,
                change_count=-(balance + 1),
                usage_type="admin_adjust",
                remark="Invalid correction",
                user_id=3,
            )

    def test_platform_package_plans_are_configurable(self) -> None:
        plan = self.service.upsert_package_plan(
            plan_code="chain_growth",
            name="Chain Growth",
            monthly_fee=2999,
            included_ai_count=10000,
            store_limit=20,
            advanced_features=["ai_tags", "feishu_dashboard"],
            status="active",
        )
        self.assertEqual(plan["included_ai_count"], 10000)
        self.assertEqual(plan["advanced_features"], ["ai_tags", "feishu_dashboard"])

        updated = self.service.upsert_package_plan(
            plan_code="chain_growth",
            name="Chain Growth Pro",
            monthly_fee=3999,
            included_ai_count=15000,
            store_limit=30,
            advanced_features=["ai_tags", "feishu_dashboard", "ai_chat"],
            status="active",
        )
        self.assertEqual(plan["id"], updated["id"])
        self.assertEqual(updated["name"], "Chain Growth Pro")
        self.assertEqual(len(self.service.list_package_plans()), 1)

    def test_platform_overview_summarizes_multi_tenant_business(self) -> None:
        tenant = self.service.create_tenant(
            tenant_code="tenant_overview",
            name="Overview Brand",
            package_plan=None,
            initial_ai_count=50,
        )
        self.service.create_store(
            tenant_id=tenant["id"],
            store_code="overview_store",
            name="Overview Store",
            daily_ai_limit=100,
        )
        self.service.purchase_ai_package(
            tenant_id=tenant["id"],
            package_name="overview_100",
            purchased_count=100,
            unit_price=2,
            payment_status="paid",
        )
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )

        overview = self.service.platform_overview()
        self.assertGreaterEqual(overview["tenants"]["total"], 2)
        self.assertGreaterEqual(overview["stores"]["total"], 2)
        self.assertGreaterEqual(overview["ai"]["success_jobs"], 1)
        self.assertGreaterEqual(overview["ai"]["remaining_balance"], 149)
        self.assertEqual(overview["finance"]["package_revenue"], 200)
        self.assertGreater(overview["finance"]["estimated_gross_profit"], 0)

    def test_platform_tenant_dashboard_returns_per_tenant_business_metrics(self) -> None:
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        tenant = self.service.create_tenant(
            tenant_code="tenant_dashboard",
            name="Dashboard Brand",
            package_plan=None,
            initial_ai_count=80,
        )
        self.service.create_store(
            tenant_id=tenant["id"],
            store_code="dashboard_store",
            name="Dashboard Store",
            daily_ai_limit=120,
        )

        dashboard = self.service.platform_tenant_dashboard()
        demo = next(item for item in dashboard if item["id"] == 1)
        created = next(item for item in dashboard if item["id"] == tenant["id"])

        self.assertEqual(demo["stores"]["active"], 2)
        self.assertGreaterEqual(demo["ai"]["success_jobs"], 1)
        self.assertGreater(demo["finance"]["internal_api_cost"], 0)
        self.assertEqual(created["stores"]["total"], 1)
        self.assertEqual(created["stores"]["total_daily_ai_limit"], 120)
        self.assertEqual(created["ai"]["balance"], 80)

    def test_platform_can_update_tenant_brand_package_and_status(self) -> None:
        self.service.upsert_package_plan(
            plan_code="trial",
            name="Trial",
            monthly_fee=0,
            included_ai_count=100,
            store_limit=1,
            advanced_features=[],
            status="active",
        )
        tenant = self.service.update_tenant(
            tenant_id=1,
            name="Updated Brand",
            logo_url="https://temp.local/logo.png",
            package_plan="trial",
            status="active",
        )

        self.assertEqual(tenant["name"], "Updated Brand")
        self.assertEqual(tenant["logo_url"], "https://temp.local/logo.png")
        self.assertEqual(tenant["package_plan"], "trial")

    def test_platform_can_update_store_limit_and_status(self) -> None:
        store = self.service.update_store(
            tenant_id=1,
            store_id=1,
            name="Updated Store",
            daily_ai_limit=88,
            status="active",
        )

        self.assertEqual(store["name"], "Updated Store")
        self.assertEqual(store["daily_ai_limit"], 88)

    def test_disabled_store_blocks_core_business_operations(self) -> None:
        self.service.update_store(tenant_id=1, store_id=1, status="disabled")

        with self.assertRaises(BusinessError):
            self.service.confirm_store_visit(
                tenant_id=1,
                store_id=1,
                user_id=1,
                qr_scene="store:1:1",
            )
        with self.assertRaises(BusinessError):
            self.service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.FREE,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )
        with self.assertRaises(BusinessError):
            self.service.create_order(
                tenant_id=1,
                store_id=1,
                user_id=1,
                stylist_id=2,
                direction="female",
                hairstyle_id="style_010",
                hair_color_id="color_003",
                ai_job_no=None,
            )

    def test_disabled_tenant_blocks_core_business_operations(self) -> None:
        self.service.update_tenant(tenant_id=1, status="disabled")

        with self.assertRaises(BusinessError):
            self.service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.FREE,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )

    def test_platform_can_generate_monthly_bill_and_customer_view_hides_cost(self) -> None:
        current_month = date.today().strftime("%Y-%m")
        self.service.upsert_package_plan(
            plan_code="chain_growth",
            name="Chain Growth",
            monthly_fee=2999,
            included_ai_count=0,
            store_limit=20,
            advanced_features=["ai_tags"],
            status="active",
        )
        self.store.conn.execute(
            "UPDATE tenants SET package_plan = 'chain_growth' WHERE id = 1"
        )
        self.store.conn.commit()
        self.service.purchase_ai_package(
            tenant_id=1,
            package_name="extra_1",
            purchased_count=1,
            unit_price=2,
            payment_status="paid",
        )
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )

        bill = self.service.generate_monthly_bill(
            tenant_id=1,
            bill_month=current_month,
            tenant_settle_unit_price=3,
            bill_status="issued",
        )
        self.assertEqual(bill["package_fee"], 2999)
        self.assertEqual(bill["purchased_ai_count"], 1)
        self.assertEqual(bill["success_ai_uses"], 2)
        self.assertEqual(bill["overage_ai_uses"], 1)
        self.assertEqual(bill["ai_overage_revenue"], 3)
        self.assertIn("internal_api_cost", bill)
        self.assertIn("platform_gross_profit", bill)

        customer_bill = self.service.list_monthly_bills(tenant_id=1, include_platform_fields=False)[0]
        self.assertNotIn("internal_api_cost", customer_bill)
        self.assertNotIn("platform_gross_profit", customer_bill)
        self.assertEqual(customer_bill["total_bill_amount"], 3004)

        paid_bill = self.service.update_monthly_bill_status(
            bill_id=bill["id"],
            tenant_id=1,
            bill_status="paid",
        )
        self.assertEqual(paid_bill["bill_status"], "paid")
        customer_paid_bill = self.service.list_monthly_bills(tenant_id=1, include_platform_fields=False)[0]
        self.assertEqual(customer_paid_bill["bill_status"], "paid")
        self.assertNotIn("internal_api_cost", customer_paid_bill)
        self.assertNotIn("platform_gross_profit", customer_paid_bill)

        with self.assertRaises(BusinessError):
            self.service.update_monthly_bill_status(
                bill_id=bill["id"],
                tenant_id=2,
                bill_status="overdue",
            )

    def test_platform_can_create_store_for_tenant(self) -> None:
        tenant = self.service.create_tenant(
            tenant_code="tenant_store_test",
            name="Store Test Brand",
            package_plan="store_plan",
            initial_ai_count=0,
        )
        store = self.service.create_store(
            tenant_id=tenant["id"],
            store_code="store_001",
            name="First Store",
            daily_ai_limit=120,
        )
        self.assertEqual(store["tenant_id"], tenant["id"])
        self.assertEqual(store["daily_ai_limit"], 120)

        stores = self.service.list_stores(tenant["id"])
        self.assertEqual(len(stores), 1)
        self.assertEqual(stores[0]["store_code"], "store_001")

        with self.assertRaises(BusinessError):
            self.service.create_store(
                tenant_id=tenant["id"],
                store_code="store_001",
                name="Duplicate Store",
                daily_ai_limit=120,
            )

    def test_platform_api_key_configs_never_return_plain_secret(self) -> None:
        config = self.service.upsert_api_key_config(
            tenant_id=None,
            provider="dashscope",
            key_name="platform_default",
            secret_value="sk-test-secret-123456",
            updated_by_user_id=3,
        )

        self.assertEqual(config["provider"], "dashscope")
        self.assertEqual(config["masked_secret"], "sk-t***3456")
        self.assertNotIn("secret_ciphertext", config)
        self.assertNotIn("sk-test-secret-123456", str(config))

        configs = self.service.list_api_key_configs()
        self.assertEqual(len(configs), 1)
        self.assertNotIn("secret_ciphertext", configs[0])
        self.assertNotIn("sk-test-secret-123456", str(configs[0]))

        disabled = self.service.disable_api_key_config(config["id"])
        self.assertEqual(disabled["status"], "disabled")

    def test_platform_api_key_config_can_be_updated_without_duplicate(self) -> None:
        first = self.service.upsert_api_key_config(
            tenant_id=1,
            provider="dify",
            key_name="tenant_workflow",
            secret_value="secret-old-1234",
            updated_by_user_id=3,
        )
        second = self.service.upsert_api_key_config(
            tenant_id=1,
            provider="dify",
            key_name="tenant_workflow",
            secret_value="secret-new-5678",
            updated_by_user_id=3,
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["masked_secret"], "secr***5678")
        self.assertNotEqual(first["secret_fingerprint"], second["secret_fingerprint"])

    def test_api_key_resolution_prefers_tenant_key_then_platform_default(self) -> None:
        platform_key = self.service.upsert_api_key_config(
            tenant_id=None,
            provider="dashscope",
            key_name="default",
            secret_value="platform-secret-1234",
            updated_by_user_id=3,
        )
        tenant_key = self.service.upsert_api_key_config(
            tenant_id=1,
            provider="dashscope",
            key_name="default",
            secret_value="tenant-secret-5678",
            updated_by_user_id=3,
        )

        resolved_tenant = self.service.resolve_api_key_config(
            tenant_id=1,
            provider="dashscope",
            key_name="default",
        )
        self.assertEqual(resolved_tenant["id"], tenant_key["id"])
        self.assertEqual(resolved_tenant["resolved_scope"], "tenant")
        self.assertNotIn("secret_ciphertext", resolved_tenant)
        self.assertNotIn("tenant-secret-5678", str(resolved_tenant))

        resolved_platform = self.service.resolve_api_key_config(
            tenant_id=2,
            provider="dashscope",
            key_name="default",
        )
        self.assertEqual(resolved_platform["id"], platform_key["id"])
        self.assertEqual(resolved_platform["resolved_scope"], "platform")

    def test_temp_upload_url_is_not_persisted_on_generation_job(self) -> None:
        upload = self.service.create_temp_upload_url(
            tenant_id=1,
            store_id=1,
            user_id=1,
            file_ext="jpg",
        )
        self.assertFalse(upload["persistent_storage"])
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
                photo_temp_url=upload["photo_temp_url"],
            )
        )
        self.assertEqual(job["status"], "success")
        self.assertNotIn("photo_temp_url", job)
        self.assertNotIn(upload["photo_temp_url"], self.service.storage.temp_assets)

    def test_temp_upload_uses_configured_storage_provider(self) -> None:
        storage = MockTempStorageProvider()
        service = HairAiService(self.store, storage_provider=storage)
        upload = service.create_temp_upload_url(
            tenant_id=1,
            store_id=1,
            user_id=1,
            file_ext=".png",
            ttl_minutes=10,
        )

        self.assertEqual(upload["provider"], "mock")
        self.assertEqual(upload["ttl_seconds"], 600)
        self.assertFalse(upload["persistent_storage"])
        self.assertIn(upload["photo_temp_url"], storage.temp_assets)

    def test_aliyun_oss_temp_upload_url_keeps_tenant_store_user_path(self) -> None:
        storage = AliyunOssTempStorageProvider(
            bucket="hair-ai-demo",
            endpoint="https://hair-ai-demo.oss-cn-shanghai.aliyuncs.com",
            access_key_id="test-key",
            access_key_secret="test-secret",
        )
        upload = storage.create_temp_upload_url(
            tenant_id=7,
            store_id=8,
            user_id=9,
            file_ext="webp",
        )

        self.assertEqual(upload["provider"], "aliyun_oss")
        self.assertFalse(upload["persistent_storage"])
        self.assertTrue(upload["object_key"].startswith("temp/7/8/9/"))
        self.assertIn("OSSAccessKeyId=test-key", upload["upload_url"])
        self.assertIn("Signature=", upload["upload_url"])
        self.assertIn("OSSAccessKeyId=test-key", upload["photo_temp_url"])
        self.assertIn("Signature=", upload["photo_temp_url"])

    def test_temp_upload_rejects_non_image_extension(self) -> None:
        with self.assertRaises(BusinessError):
            self.service.create_temp_upload_url(
                tenant_id=1,
                store_id=1,
                user_id=1,
                file_ext="exe",
            )

    def test_catalog_upload_uses_persistent_catalog_path(self) -> None:
        storage = AliyunOssTempStorageProvider(
            bucket="hair-ai-demo",
            endpoint="https://hair-ai-demo.oss-cn-shanghai.aliyuncs.com",
            access_key_id="test-key",
            access_key_secret="test-secret",
        )
        upload = storage.create_catalog_upload_url(
            tenant_id=7,
            store_id=8,
            asset_type="hairstyle",
            file_ext="jpg",
        )

        self.assertTrue(upload["persistent_storage"])
        self.assertTrue(upload["object_key"].startswith("catalog/7/8/hairstyle/"))
        self.assertIn("OSSAccessKeyId=test-key", upload["asset_url"])

    def test_merchant_workbench_counts_ai_conversion_and_revenue(self) -> None:
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=job["job_no"],
        )
        self.service.complete_order(
            tenant_id=1,
            store_id=1,
            order_id=order["id"],
            stylist_id=2,
            service_item_id=110,
            actual_amount=399,
        )
        workbench = self.service.merchant_workbench(1, 1)
        self.assertEqual(workbench["total_orders"], 1)
        self.assertEqual(workbench["ai_converted_orders"], 1)
        self.assertEqual(workbench["actual_revenue"], 399)

    def test_merchant_performance_breaks_down_store_stylist_and_service(self) -> None:
        job = self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        ai_order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=job["job_no"],
        )
        self.service.complete_order(
            tenant_id=1,
            store_id=1,
            order_id=ai_order["id"],
            stylist_id=2,
            service_item_id=110,
            actual_amount=399,
        )
        normal_order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=5,
            direction="female",
            hairstyle_id="style_011",
            hair_color_id="color_004",
            ai_job_no=None,
        )
        self.service.complete_order(
            tenant_id=1,
            store_id=1,
            order_id=normal_order["id"],
            stylist_id=5,
            service_item_id=120,
            actual_amount=299,
        )

        performance = self.service.merchant_performance(tenant_id=1, store_id=1)

        self.assertEqual(performance["totals"]["completed_services"], 2)
        self.assertEqual(performance["totals"]["revenue"], 698)
        self.assertEqual(performance["totals"]["ai_converted_services"], 1)
        self.assertEqual(performance["totals"]["ai_converted_revenue"], 399)
        self.assertEqual(performance["ai_conversion"]["ai_success_jobs"], 1)
        self.assertEqual(performance["ai_conversion"]["ai_converted_orders"], 1)
        self.assertEqual(performance["ai_conversion"]["ai_converted_services"], 1)
        self.assertEqual(performance["ai_conversion"]["ai_converted_revenue"], 399)
        self.assertEqual(performance["by_store"][0]["store_id"], 1)
        self.assertEqual({item["stylist_id"] for item in performance["by_stylist"]}, {2, 5})
        self.assertEqual(
            {item["category"] for item in performance["by_service"]},
            {"haircut", "color"},
        )
        self.assertEqual(
            {item["category"] for item in performance["by_category"]},
            {"haircut", "color"},
        )

        stylist_performance = self.service.merchant_performance(tenant_id=1, store_id=1, stylist_id=2)
        self.assertEqual(stylist_performance["totals"]["completed_services"], 1)
        self.assertEqual(stylist_performance["totals"]["revenue"], 399)

    def test_feishu_sync_events_are_enqueued_and_retryable(self) -> None:
        self.service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )
        status = self.service.sync_status(1)
        self.assertEqual(status["counts"]["pending"], 1)

        retried = self.service.retry_sync_events(1)
        self.assertEqual(retried["synced_count"], 1)
        status_after = self.service.sync_status(1)
        self.assertEqual(status_after["counts"]["synced"], 1)

    def test_order_and_gift_records_enqueue_feishu_sync_events(self) -> None:
        gift = self.service.grant_ai_gift(1, 1, customer_id=1, staff_id=2)
        order = self.service.create_order(
            tenant_id=1,
            store_id=1,
            user_id=1,
            stylist_id=2,
            direction="female",
            hairstyle_id="style_010",
            hair_color_id="color_003",
            ai_job_no=None,
        )
        events = self.store.rows(
            """
            SELECT event_type, payload FROM sync_events
            WHERE tenant_id = 1 AND store_id = 1
            ORDER BY id ASC
            """
        )
        self.assertEqual([event["event_type"] for event in events], ["ai_gift_record", "order"])
        self.assertIn(str(gift["id"]), events[0]["payload"])
        self.assertIn(str(order["id"]), events[1]["payload"])

    def test_feishu_sync_failure_marks_event_failed_without_breaking_business(self) -> None:
        service = HairAiService(self.store, feishu_provider=FailingFeishuProvider())
        service.generate(
            GenerateRequest(
                tenant_id=1,
                store_id=1,
                user_id=1,
                direction=Direction.FEMALE,
                billing_type=BillingType.FREE,
                selected_style_id="style_010",
                selected_color_id="color_003",
            )
        )

        retried = service.retry_sync_events(1)
        self.assertEqual(retried["synced_count"], 0)
        self.assertEqual(retried["failed_count"], 1)
        status_after = service.sync_status(1)
        self.assertEqual(status_after["counts"]["failed"], 1)

    def test_role_scope_access_rules(self) -> None:
        self.service.assert_scope_access(
            actor_tenant_id=1,
            actor_user_id=3,
            target_tenant_id=1,
            target_store_id=2,
        )
        self.service.assert_scope_access(
            actor_tenant_id=1,
            actor_user_id=4,
            target_tenant_id=1,
            target_store_id=1,
        )
        with self.assertRaises(BusinessError):
            self.service.assert_scope_access(
                actor_tenant_id=1,
                actor_user_id=4,
                target_tenant_id=1,
                target_store_id=2,
            )
        self.service.assert_scope_access(
            actor_tenant_id=1,
            actor_user_id=2,
            target_tenant_id=1,
            target_store_id=1,
            target_user_id=2,
        )
        with self.assertRaises(BusinessError):
            self.service.assert_scope_access(
                actor_tenant_id=1,
                actor_user_id=2,
                target_tenant_id=1,
                target_store_id=1,
                target_user_id=1,
            )
        self.service.assert_scope_access(
            actor_tenant_id=1,
            actor_user_id=1,
            target_tenant_id=1,
            target_store_id=1,
            target_user_id=1,
        )
        with self.assertRaises(BusinessError):
            self.service.assert_scope_access(
                actor_tenant_id=1,
                actor_user_id=1,
                target_tenant_id=2,
                target_store_id=1,
                target_user_id=1,
            )

    def test_store_daily_limit_blocks_generation(self) -> None:
        self.store.conn.execute(
            "UPDATE stores SET daily_ai_limit = 0 WHERE id = 1 AND tenant_id = 1"
        )
        self.store.conn.commit()
        with self.assertRaises(BusinessError):
            self.service.generate(
                GenerateRequest(
                    tenant_id=1,
                    store_id=1,
                    user_id=1,
                    direction=Direction.FEMALE,
                    billing_type=BillingType.FREE,
                    selected_style_id="style_010",
                    selected_color_id="color_003",
                )
            )

    def test_demo_catalog_has_male_female_and_neutral_assets(self) -> None:
        for direction in ("female", "male", "neutral"):
            with self.subTest(direction=direction):
                styles = self.service.list_styles(1, direction)
                colors = self.service.list_colors(1, direction)
                self.assertGreaterEqual(len(styles), 1)
                self.assertGreaterEqual(len(colors), 1)


if __name__ == "__main__":
    unittest.main()
