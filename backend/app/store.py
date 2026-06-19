from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class AppStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_code TEXT UNIQUE NOT NULL,
              name TEXT NOT NULL,
              logo_url TEXT,
              package_plan TEXT,
              status TEXT DEFAULT 'active',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stores (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_code TEXT NOT NULL,
              name TEXT NOT NULL,
              daily_ai_limit INTEGER DEFAULT 300,
              status TEXT DEFAULT 'active',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, store_code)
            );

            CREATE TABLE IF NOT EXISTS ai_limit_configs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER,
              store_id INTEGER,
              user_concurrency_limit INTEGER DEFAULT 1,
              store_concurrency_limit INTEGER DEFAULT 5,
              tenant_concurrency_limit INTEGER DEFAULT 20,
              platform_concurrency_limit INTEGER DEFAULT 50,
              user_daily_limit INTEGER DEFAULT 20,
              tenant_daily_limit INTEGER DEFAULT 5000,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              openid TEXT NOT NULL,
              phone TEXT,
              nickname TEXT,
              birthday TEXT,
              gender TEXT,
              profile_note TEXT,
              role TEXT DEFAULT 'customer',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, openid)
            );

            CREATE TABLE IF NOT EXISTS user_privacy_consents (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              consent_scope TEXT NOT NULL,
              consent_version TEXT NOT NULL,
              status TEXT DEFAULT 'accepted',
              accepted_at TEXT DEFAULT CURRENT_TIMESTAMP,
              revoked_at TEXT,
              UNIQUE (tenant_id, user_id, consent_scope, consent_version)
            );

            CREATE TABLE IF NOT EXISTS staff_profiles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              staff_id INTEGER NOT NULL,
              display_name TEXT NOT NULL,
              title TEXT,
              avatar_url TEXT,
              directions TEXT DEFAULT '[]',
              skill_tags TEXT DEFAULT '[]',
              availability_status TEXT DEFAULT 'available',
              is_enabled INTEGER DEFAULT 1,
              is_recommended INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 0,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, store_id, staff_id)
            );

            CREATE TABLE IF NOT EXISTS service_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              name TEXT NOT NULL,
              category TEXT NOT NULL,
              base_price REAL DEFAULT 0,
              is_enabled INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 0,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ai_knowledge_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              category TEXT DEFAULT 'general',
              question TEXT NOT NULL,
              answer TEXT NOT NULL,
              keywords TEXT DEFAULT '[]',
              is_enabled INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 100,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS hairstyles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              style_id TEXT NOT NULL,
              name TEXT NOT NULL,
              direction TEXT NOT NULL,
              hair_length TEXT DEFAULT 'medium',
              thumbnail_url TEXT,
              display_tags TEXT DEFAULT '[]',
              need_perm INTEGER DEFAULT 0,
              is_enabled INTEGER DEFAULT 1,
              is_recommended INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 0,
              UNIQUE (tenant_id, style_id)
            );

            CREATE TABLE IF NOT EXISTS hair_colors (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              color_id TEXT NOT NULL,
              name TEXT NOT NULL,
              direction TEXT NOT NULL,
              color_swatch TEXT,
              thumbnail_url TEXT,
              display_tags TEXT DEFAULT '[]',
              need_bleach INTEGER DEFAULT 0,
              is_enabled INTEGER DEFAULT 1,
              is_recommended INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 0,
              UNIQUE (tenant_id, color_id)
            );

            CREATE TABLE IF NOT EXISTS asset_popularity_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              user_id INTEGER,
              asset_type TEXT NOT NULL,
              asset_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              generation_job_id INTEGER,
              order_id INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ai_generation_jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              job_no TEXT UNIQUE NOT NULL,
              direction TEXT NOT NULL,
              selected_style_id TEXT,
              selected_color_id TEXT,
              billing_type TEXT NOT NULL,
              status TEXT DEFAULT 'queued',
              main_status TEXT DEFAULT 'pending',
              recommend_1_status TEXT DEFAULT 'pending',
              recommend_2_status TEXT DEFAULT 'pending',
              queue_position INTEGER DEFAULT 0,
              queue_wait_seconds INTEGER,
              generate_duration_seconds INTEGER,
              queued_at TEXT DEFAULT CURRENT_TIMESTAMP,
              started_at TEXT,
              retry_count INTEGER DEFAULT 0,
              error_code TEXT,
              error_message TEXT,
              customer_settle_amount REAL DEFAULT 0,
              internal_api_cost REAL DEFAULT 0,
              is_count_deducted INTEGER DEFAULT 0,
              images_json TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS poc_evaluation_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              job_no TEXT,
              direction TEXT NOT NULL,
              test_case_no TEXT NOT NULL,
              input_photo_label TEXT,
              selected_style_id TEXT,
              selected_color_id TEXT,
              is_like_customer INTEGER DEFAULT 0,
              only_changed_hair INTEGER DEFAULT 0,
              face_changed INTEGER DEFAULT 0,
              generated_three_images INTEGER DEFAULT 0,
              hair_color_accurate INTEGER DEFAULT 0,
              hairstyle_acceptable INTEGER DEFAULT 0,
              can_show_customer INTEGER DEFAULT 0,
              generate_duration_seconds INTEGER,
              internal_api_cost REAL DEFAULT 0,
              notes TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ai_payment_orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              pay_order_no TEXT UNIQUE NOT NULL,
              amount REAL NOT NULL,
              pay_status TEXT DEFAULT 'pending',
              paid_at TEXT,
              generation_job_id INTEGER,
              retry_for_job_id INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tenant_ai_accounts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL UNIQUE,
              total_purchased INTEGER DEFAULT 0,
              total_used INTEGER DEFAULT 0,
              total_gifted_adjustment INTEGER DEFAULT 0,
              status TEXT DEFAULT 'active',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tenant_ai_package_orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              package_name TEXT NOT NULL,
              purchased_count INTEGER NOT NULL,
              unit_price REAL NOT NULL,
              total_amount REAL NOT NULL,
              payment_status TEXT DEFAULT 'pending',
              paid_at TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS package_plans (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              plan_code TEXT UNIQUE NOT NULL,
              name TEXT NOT NULL,
              monthly_fee REAL DEFAULT 0,
              included_ai_count INTEGER DEFAULT 0,
              store_limit INTEGER DEFAULT 1,
              advanced_features TEXT DEFAULT '[]',
              status TEXT DEFAULT 'active',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tenant_monthly_bills (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              bill_month TEXT NOT NULL,
              package_plan TEXT,
              package_fee REAL DEFAULT 0,
              included_ai_count INTEGER DEFAULT 0,
              purchased_ai_count INTEGER DEFAULT 0,
              success_ai_uses INTEGER DEFAULT 0,
              overage_ai_uses INTEGER DEFAULT 0,
              tenant_settle_unit_price REAL DEFAULT 0,
              ai_overage_revenue REAL DEFAULT 0,
              total_bill_amount REAL DEFAULT 0,
              internal_api_cost REAL DEFAULT 0,
              platform_gross_profit REAL DEFAULT 0,
              bill_status TEXT DEFAULT 'draft',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, bill_month)
            );

            CREATE TABLE IF NOT EXISTS tenant_ai_usage_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              user_id INTEGER,
              generation_job_id INTEGER,
              usage_type TEXT NOT NULL,
              change_count INTEGER NOT NULL,
              balance_after INTEGER NOT NULL,
              customer_paid_amount REAL DEFAULT 0,
              tenant_settle_unit_price REAL DEFAULT 0,
              internal_api_cost REAL DEFAULT 0,
              remark TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS api_key_configs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER,
              provider TEXT NOT NULL,
              key_name TEXT NOT NULL,
              secret_ciphertext TEXT NOT NULL,
              secret_fingerprint TEXT NOT NULL,
              masked_secret TEXT NOT NULL,
              status TEXT DEFAULT 'active',
              updated_by_user_id INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, provider, key_name)
            );

            CREATE TABLE IF NOT EXISTS ai_user_daily_quota (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              quota_date TEXT NOT NULL,
              free_limit INTEGER DEFAULT 2,
              free_used INTEGER DEFAULT 0,
              paid_used INTEGER DEFAULT 0,
              gift_used INTEGER DEFAULT 0,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, user_id, quota_date)
            );

            CREATE TABLE IF NOT EXISTS store_visit_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              qr_scene TEXT NOT NULL,
              status TEXT DEFAULT 'active',
              expires_at TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ai_gift_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              customer_id INTEGER NOT NULL,
              gifted_by_user_id INTEGER NOT NULL,
              status TEXT DEFAULT 'unused',
              generation_job_id INTEGER,
              order_id INTEGER,
              revenue_amount REAL DEFAULT 0,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              used_at TEXT
            );

            CREATE TABLE IF NOT EXISTS customer_memberships (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              customer_id INTEGER NOT NULL,
              level_name TEXT DEFAULT '普通会员',
              discount_rate REAL DEFAULT 1.0,
              balance REAL DEFAULT 0,
              total_recharge REAL DEFAULT 0,
              total_consume REAL DEFAULT 0,
              notes TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, store_id, customer_id)
            );

            CREATE TABLE IF NOT EXISTS customer_membership_transactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              customer_id INTEGER NOT NULL,
              membership_id INTEGER NOT NULL,
              transaction_type TEXT NOT NULL,
              amount REAL NOT NULL,
              balance_after REAL NOT NULL,
              note TEXT,
              created_by_user_id INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS marketing_packages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              name TEXT NOT NULL,
              package_type TEXT DEFAULT 'times_card',
              sale_price REAL DEFAULT 0,
              validity_days INTEGER DEFAULT 180,
              is_enabled INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 100,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS marketing_package_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              package_id INTEGER NOT NULL,
              service_item_id INTEGER NOT NULL,
              included_count INTEGER NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS customer_packages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              customer_id INTEGER NOT NULL,
              package_id INTEGER NOT NULL,
              paid_amount REAL DEFAULT 0,
              status TEXT DEFAULT 'active',
              starts_at TEXT DEFAULT CURRENT_TIMESTAMP,
              expires_at TEXT,
              notes TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS customer_package_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              customer_package_id INTEGER NOT NULL,
              service_item_id INTEGER NOT NULL,
              total_count INTEGER NOT NULL,
              used_count INTEGER DEFAULT 0,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS customer_package_usages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              customer_id INTEGER NOT NULL,
              customer_package_id INTEGER NOT NULL,
              service_item_id INTEGER NOT NULL,
              used_count INTEGER DEFAULT 1,
              order_id INTEGER,
              service_record_id INTEGER,
              created_by_user_id INTEGER,
              note TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS staff_gift_quotas (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              staff_id INTEGER NOT NULL,
              quota_date TEXT NOT NULL,
              daily_limit INTEGER DEFAULT 5,
              used_count INTEGER DEFAULT 0,
              extra_granted INTEGER DEFAULT 0,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, store_id, staff_id, quota_date)
            );

            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              stylist_id INTEGER,
              direction TEXT,
              hairstyle_id TEXT,
              hair_color_id TEXT,
              service_item_id INTEGER,
              appointment_time TEXT,
              status TEXT DEFAULT 'pending',
              is_ai_converted INTEGER DEFAULT 0,
              ai_job_id INTEGER,
              notes TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS service_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              order_id INTEGER NOT NULL,
              stylist_id INTEGER,
              service_item_id INTEGER,
              actual_amount REAL NOT NULL,
              is_ai_converted INTEGER DEFAULT 0,
              completed_at TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sync_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER,
              event_type TEXT NOT NULL,
              payload TEXT NOT NULL,
              status TEXT DEFAULT 'pending',
              retry_count INTEGER DEFAULT 0,
              last_error TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              synced_at TEXT
            );

            CREATE TABLE IF NOT EXISTS store_home_configs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER NOT NULL,
              store_id INTEGER NOT NULL,
              home_title TEXT,
              home_subtitle TEXT,
              store_photos TEXT DEFAULT '[]',
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (tenant_id, store_id)
            );

            CREATE TABLE IF NOT EXISTS platform_leads (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source TEXT DEFAULT 'website',
              name TEXT,
              phone TEXT,
              wechat TEXT,
              city TEXT,
              store_count INTEGER DEFAULT 1,
              interest TEXT,
              message TEXT,
              status TEXT DEFAULT 'new',
              follow_note TEXT,
              assigned_to TEXT,
              tenant_id INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              followed_at TEXT,
              converted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS platform_audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              actor_user_id INTEGER,
              actor_role TEXT DEFAULT 'platform_admin',
              action TEXT NOT NULL,
              target_type TEXT NOT NULL,
              target_id TEXT,
              tenant_id INTEGER,
              store_id INTEGER,
              before_json TEXT,
              after_json TEXT,
              ip_address TEXT,
              user_agent TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS platform_finance_transactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id INTEGER,
              store_id INTEGER,
              transaction_type TEXT NOT NULL,
              amount REAL NOT NULL,
              currency TEXT DEFAULT 'CNY',
              related_type TEXT,
              related_id INTEGER,
              payment_status TEXT DEFAULT 'paid',
              note TEXT,
              created_by_user_id INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS platform_announcements (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              level TEXT DEFAULT 'info',
              audience TEXT DEFAULT 'all',
              tenant_id INTEGER,
              status TEXT DEFAULT 'published',
              pinned INTEGER DEFAULT 0,
              created_by_user_id INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              published_at TEXT,
              expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS plan_overrides (
              plan_code TEXT PRIMARY KEY,
              annual_price_fen INTEGER,
              annual_included_ai_quota INTEGER,
              overage_price_fen INTEGER,
              max_stores INTEGER,
              updated_by_user_id INTEGER,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._run_lightweight_migrations()
        self.conn.commit()

    def _run_lightweight_migrations(self) -> None:
        self._add_column_if_missing("hairstyles", "thumbnail_url", "TEXT")
        self._add_column_if_missing("hair_colors", "thumbnail_url", "TEXT")
        self._add_column_if_missing("ai_generation_jobs", "images_json", "TEXT")
        self._add_column_if_missing("users", "status", "TEXT DEFAULT 'active'")
        self._add_column_if_missing("users", "birthday", "TEXT")
        self._add_column_if_missing("users", "gender", "TEXT")
        self._add_column_if_missing("users", "profile_note", "TEXT")
        # 订阅计划字段
        self._add_column_if_missing("tenants", "subscription_plan", "TEXT DEFAULT 'trial'")
        self._add_column_if_missing("tenants", "subscription_expires_at", "TEXT")
        self._add_column_if_missing("tenants", "monthly_ai_used", "INTEGER DEFAULT 0")
        self._add_column_if_missing("tenants", "monthly_ai_reset_at", "TEXT")
        # DeepSeek LLM 成本追踪
        self._add_column_if_missing("tenants", "monthly_llm_cost_fen", "INTEGER DEFAULT 0")
        self._ensure_llm_chat_logs_table()
        # 客户备注（仅平台运营方可见可编辑）
        self._add_column_if_missing("tenants", "notes", "TEXT")

    def _ensure_llm_chat_logs_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_chat_logs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id        INTEGER NOT NULL,
                store_id         INTEGER NOT NULL,
                user_id          INTEGER NOT NULL,
                session_key      TEXT,
                prompt_tokens    INTEGER DEFAULT 0,
                cached_tokens    INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost_fen         INTEGER DEFAULT 0,
                created_at       TEXT DEFAULT (datetime('now'))
            )
            """
        )

    def _add_column_if_missing(self, table_name: str, column_name: str, column_type: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def row(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def seed_demo(self) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO tenants (id, tenant_code, name, package_plan)
                VALUES (1, 'tenant_demo', 'Demo Hair Chain', 'chain_growth')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO stores (id, tenant_id, store_code, name, daily_ai_limit)
                VALUES (1, 1, 'store_001', 'People Square Store', 300)
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                (id, tenant_id, store_id, openid, phone, nickname, role)
                VALUES (1, 1, 1, 'customer_openid', '13800000000', 'Demo Customer', 'customer')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                (id, tenant_id, store_id, openid, phone, nickname, role)
                VALUES (2, 1, 1, 'staff_openid', '13900000000', 'Demo Stylist', 'staff')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                (id, tenant_id, store_id, openid, phone, nickname, role)
                VALUES (5, 1, 1, 'staff_openid_2', '13900000001', 'Demo Stylist 2', 'staff')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                (id, tenant_id, store_id, openid, phone, nickname, role)
                VALUES (6, 1, 1, 'staff_openid_3', '13900000002', 'Demo Stylist 3', 'staff')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                (id, tenant_id, store_id, openid, phone, nickname, role)
                VALUES (7, 1, 1, 'staff_openid_4', '13900000003', 'Demo Stylist 4', 'staff')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                (id, tenant_id, store_id, openid, phone, nickname, role)
                VALUES (3, 1, NULL, 'boss_openid', '13700000000', 'Demo Boss', 'boss')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                (id, tenant_id, store_id, openid, phone, nickname, role)
                VALUES (4, 1, 1, 'manager_openid', '13600000000', 'Demo Manager', 'manager')
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO stores (id, tenant_id, store_code, name, daily_ai_limit)
                VALUES (2, 1, 'store_002', 'Second Store', 300)
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO ai_limit_configs
                (id, tenant_id, store_id, user_concurrency_limit, store_concurrency_limit,
                 tenant_concurrency_limit, platform_concurrency_limit, user_daily_limit, tenant_daily_limit)
                VALUES (1, NULL, NULL, 1, 5, 20, 50, 20, 5000)
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO tenant_ai_accounts
                (tenant_id, total_purchased, total_used, total_gifted_adjustment)
                VALUES (1, 1000, 0, 0)
                """
            )

            staff_profiles = [
                (2, "Alex", "Senior Stylist", '["female","male","neutral"]', '["color","perm","short hair"]', "available", 10),
                (5, "Mia", "Color Specialist", '["female","neutral"]', '["color","medium hair","brightening"]', "available", 20),
                (6, "Chen", "Texture Stylist", '["male","female"]', '["short hair","texture","business"]', "available", 30),
                (7, "Kai", "Guest Stylist", '["female"]', '["long hair","korean"]', "off_duty", 40),
            ]
            for staff_id, display_name, title, directions, skill_tags, status, sort_order in staff_profiles:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO staff_profiles
                    (tenant_id, store_id, staff_id, display_name, title, directions, skill_tags, availability_status, sort_order)
                    VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (staff_id, display_name, title, directions, skill_tags, status, sort_order),
                )

            services = [
                ("剪发", "haircut", 88, 10),
                ("染发", "color", 299, 20),
                ("烫发", "perm", 399, 30),
                ("造型", "styling", 128, 40),
                ("护理", "care", 198, 50),
            ]
            for name, category, base_price, sort_order in services:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO service_items
                    (id, tenant_id, store_id, name, category, base_price, sort_order)
                    VALUES (?, 1, 1, ?, ?, ?, ?)
                    """,
                    (100 + sort_order, name, category, base_price, sort_order),
                )

            styles = [
                ("style_010", "Korean Medium Hair", "female", "medium", '["korean","natural","face shaping"]', 10),
                ("style_011", "Textured Short Hair", "female", "short", '["fresh","japanese","younger look"]', 20),
                ("style_012", "Air Bangs Collarbone Hair", "female", "medium", '["sweet","medium","slim face"]', 30),
                ("style_021", "Business Side Part", "male", "short", '["business","fresh","commute"]', 10),
                ("style_031", "Clean Neutral Bob", "neutral", "short", '["neutral","clean","low maintenance"]', 10),
                ("style_032", "Soft Layered Medium Hair", "neutral", "medium", '["neutral","soft","face shaping"]', 20),
            ]
            for style_id, name, direction, length, tags, sort_order in styles:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO hairstyles
                    (tenant_id, store_id, style_id, name, direction, hair_length, display_tags, sort_order)
                    VALUES (1, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (style_id, name, direction, length, tags, sort_order),
                )

            colors = [
                ("color_003", "Cool Brown", "female", "#6b4a38", '["natural","brightening","low key"]', 10),
                ("color_004", "Black Tea Brown", "female", "#30251f", '["commute","texture","skin friendly"]', 20),
                ("color_011", "Natural Black", "male", "#171412", '["natural","low maintenance"]', 10),
                ("color_021", "Neutral Ash Brown", "neutral", "#5b514a", '["neutral","natural","soft"]', 10),
            ]
            for color_id, name, direction, swatch, tags, sort_order in colors:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO hair_colors
                    (tenant_id, store_id, color_id, name, direction, color_swatch, display_tags, sort_order)
                    VALUES (1, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (color_id, name, direction, swatch, tags, sort_order),
                )

            knowledge_items = [
                ("try_on", "AI 试发会不会换脸？", "AI 会尽量保留顾客五官、脸型、表情、眼镜和原照片构图，仅调整发型发色。效果图适合作为到店沟通参考，最终方案仍建议由主理人结合真实发质确认。", '["换脸","不像我","变脸","五官","保留"]', 10),
                ("try_on", "发质参数一定要填写吗？", "不用强制填写。不填也可以直接生成；如果愿意补充发丝粗细、发质软硬和受损程度，AI 试发会更贴近实际发丝质感。", '["发质","细软","粗硬","受损","选填"]', 20),
                ("try_on", "自带参考图可以怎么用？", "自带参考图可以选择参考发型或参考发色。参考发型时主要看轮廓、刘海、层次和发量感；参考发色时主要看颜色、明暗和染发质感。", '["参考图","自带图片","参考发型","参考发色"]', 30),
                ("booking", "怎么预约到店？", "你可以先生成试发方案，再点击预约提交。预约提交后门店会在商家端看到，具体到店时间、主理人和价格以门店确认沟通为准。", '["预约","下单","到店","主理人"]', 40),
                ("membership", "会员和套餐在哪里看？", "在小程序底部「我的」里可以查看会员余额、充值流水、已购套餐和预约记录。到店充值或扣次时，可以向主理人报手机号。", '["会员","套餐","余额","次卡","手机号"]', 50),
                ("quota", "AI 次数不够怎么办？", "如果今日免费次数或赠送次数不够，可以到店联系主理人或店长增加次数。测试阶段门店也可以手动给指定手机号对应的顾客增加次数。", '["次数","免费次数","充值AI","试发次数"]', 60),
                ("service", "价格为什么没有直接写死？", "剪发、染发、烫发和护理会受到发长、发量、发质受损程度、漂染需求和主理人方案影响，系统只做参考，最终价格以到店沟通为准。", '["价格","多少钱","收费","报价"]', 70),
            ]
            for category, question, answer, keywords, sort_order in knowledge_items:
                exists = conn.execute(
                    """
                    SELECT 1 FROM ai_knowledge_items
                    WHERE tenant_id = 1 AND store_id = 1 AND question = ?
                    """,
                    (question,),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """
                        INSERT INTO ai_knowledge_items
                        (tenant_id, store_id, category, question, answer, keywords, sort_order)
                        VALUES (1, 1, ?, ?, ?, ?, ?)
                        """,
                        (category, question, answer, keywords, sort_order),
                    )
