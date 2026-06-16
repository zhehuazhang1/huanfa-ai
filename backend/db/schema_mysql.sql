CREATE TABLE tenants (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_code VARCHAR(64) UNIQUE NOT NULL,
  name VARCHAR(100) NOT NULL,
  logo_url VARCHAR(255),
  package_plan VARCHAR(50),
  status ENUM('active','paused','expired') DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE stores (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_code VARCHAR(64) NOT NULL,
  name VARCHAR(100) NOT NULL,
  daily_ai_limit INT DEFAULT 300,
  status ENUM('active','paused') DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_store (tenant_id, store_code),
  KEY idx_stores_tenant (tenant_id)
);

CREATE TABLE users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  openid VARCHAR(80) NOT NULL,
  phone VARCHAR(30),
  nickname VARCHAR(80),
  role ENUM('boss','manager','staff','customer') DEFAULT 'customer',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_openid (tenant_id, openid),
  KEY idx_users_tenant_store (tenant_id, store_id)
);

CREATE TABLE user_privacy_consents (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  consent_scope VARCHAR(80) NOT NULL,
  consent_version VARCHAR(40) NOT NULL,
  status ENUM('accepted','revoked') DEFAULT 'accepted',
  accepted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  revoked_at DATETIME,
  UNIQUE KEY uk_user_privacy_consent (tenant_id, user_id, consent_scope, consent_version),
  KEY idx_user_privacy_consent_user (tenant_id, user_id, status)
);

CREATE TABLE ai_limit_configs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT,
  store_id BIGINT,
  user_concurrency_limit INT DEFAULT 1,
  store_concurrency_limit INT DEFAULT 5,
  tenant_concurrency_limit INT DEFAULT 20,
  platform_concurrency_limit INT DEFAULT 50,
  user_daily_limit INT DEFAULT 20,
  tenant_daily_limit INT DEFAULT 5000,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_ai_limits_scope (tenant_id, store_id)
);

CREATE TABLE staff_profiles (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  staff_id BIGINT NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  title VARCHAR(100),
  avatar_url VARCHAR(255),
  directions JSON,
  skill_tags JSON,
  availability_status ENUM('available','busy','off_duty','paused') DEFAULT 'available',
  is_enabled TINYINT DEFAULT 1,
  is_recommended TINYINT DEFAULT 1,
  sort_order INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_staff_profile (tenant_id, store_id, staff_id)
);

CREATE TABLE service_items (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  name VARCHAR(100) NOT NULL,
  category VARCHAR(50) NOT NULL,
  base_price DECIMAL(10,2) DEFAULT 0,
  is_enabled TINYINT DEFAULT 1,
  sort_order INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_service_items_scope (tenant_id, store_id)
);

CREATE TABLE ai_knowledge_items (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  category VARCHAR(80) DEFAULT 'general',
  question VARCHAR(255) NOT NULL,
  answer TEXT NOT NULL,
  keywords JSON,
  is_enabled TINYINT DEFAULT 1,
  sort_order INT DEFAULT 100,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_ai_knowledge_scope (tenant_id, store_id, is_enabled, sort_order)
);

CREATE TABLE hairstyles (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  style_id VARCHAR(100) NOT NULL,
  name VARCHAR(100) NOT NULL,
  direction ENUM('male','female','neutral') NOT NULL,
  hair_length ENUM('short','medium','long') DEFAULT 'medium',
  thumbnail_url VARCHAR(500),
  display_tags JSON,
  need_perm TINYINT DEFAULT 0,
  is_enabled TINYINT DEFAULT 1,
  is_recommended TINYINT DEFAULT 1,
  sort_order INT DEFAULT 0,
  UNIQUE KEY uk_tenant_style (tenant_id, style_id),
  KEY idx_hairstyles_scope (tenant_id, store_id, direction)
);

CREATE TABLE hair_colors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  color_id VARCHAR(100) NOT NULL,
  name VARCHAR(100) NOT NULL,
  direction ENUM('male','female','neutral') NOT NULL,
  color_swatch VARCHAR(50),
  thumbnail_url VARCHAR(500),
  display_tags JSON,
  need_bleach TINYINT DEFAULT 0,
  is_enabled TINYINT DEFAULT 1,
  is_recommended TINYINT DEFAULT 1,
  sort_order INT DEFAULT 0,
  UNIQUE KEY uk_tenant_color (tenant_id, color_id),
  KEY idx_hair_colors_scope (tenant_id, store_id, direction)
);

CREATE TABLE asset_popularity_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  user_id BIGINT,
  asset_type ENUM('hairstyle','hair_color') NOT NULL,
  asset_id VARCHAR(100) NOT NULL,
  event_type ENUM('view','select','generate','order') NOT NULL,
  generation_job_id BIGINT,
  order_id BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_asset_popularity_scope (tenant_id, store_id, asset_type, event_type),
  KEY idx_asset_popularity_asset (tenant_id, asset_type, asset_id)
);

CREATE TABLE ai_generation_jobs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  job_no VARCHAR(80) UNIQUE NOT NULL,
  direction ENUM('male','female','neutral') NOT NULL,
  selected_style_id VARCHAR(100),
  selected_color_id VARCHAR(100),
  billing_type ENUM('free','gift','paid') NOT NULL,
  status ENUM('queued','running','success','failed','timeout','cancelled') DEFAULT 'queued',
  main_status ENUM('pending','success','failed') DEFAULT 'pending',
  recommend_1_status ENUM('pending','success','failed') DEFAULT 'pending',
  recommend_2_status ENUM('pending','success','failed') DEFAULT 'pending',
  queue_position INT DEFAULT 0,
  queue_wait_seconds INT,
  generate_duration_seconds INT,
  queued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  retry_count INT DEFAULT 0,
  error_code VARCHAR(80),
  error_message VARCHAR(255),
  customer_settle_amount DECIMAL(10,2) DEFAULT 0,
  internal_api_cost DECIMAL(10,4) DEFAULT 0,
  is_count_deducted TINYINT DEFAULT 0,
  images_json JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME,
  KEY idx_ai_jobs_tenant_user_status (tenant_id, user_id, status),
  KEY idx_ai_jobs_tenant_store_status (tenant_id, store_id, status),
  KEY idx_ai_jobs_created (tenant_id, store_id, created_at)
);

CREATE TABLE poc_evaluation_records (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  job_no VARCHAR(80),
  direction ENUM('male','female','neutral') NOT NULL,
  test_case_no VARCHAR(80) NOT NULL,
  input_photo_label VARCHAR(120),
  selected_style_id VARCHAR(100),
  selected_color_id VARCHAR(100),
  is_like_customer TINYINT DEFAULT 0,
  only_changed_hair TINYINT DEFAULT 0,
  face_changed TINYINT DEFAULT 0,
  generated_three_images TINYINT DEFAULT 0,
  hair_color_accurate TINYINT DEFAULT 0,
  hairstyle_acceptable TINYINT DEFAULT 0,
  can_show_customer TINYINT DEFAULT 0,
  generate_duration_seconds INT,
  internal_api_cost DECIMAL(10,4) DEFAULT 0,
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_poc_eval_scope (tenant_id, direction, created_at)
);

CREATE TABLE ai_payment_orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  pay_order_no VARCHAR(80) UNIQUE NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  pay_status ENUM('pending','paid','failed','closed','refunded') DEFAULT 'pending',
  paid_at DATETIME,
  generation_job_id BIGINT,
  retry_for_job_id BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_payment_customer (tenant_id, store_id, user_id, pay_order_no)
);

CREATE TABLE tenant_ai_accounts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL UNIQUE,
  total_purchased INT DEFAULT 0,
  total_used INT DEFAULT 0,
  total_gifted_adjustment INT DEFAULT 0,
  status ENUM('active','frozen') DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE tenant_ai_package_orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  package_name VARCHAR(100) NOT NULL,
  purchased_count INT NOT NULL,
  unit_price DECIMAL(10,4) NOT NULL,
  total_amount DECIMAL(10,2) NOT NULL,
  payment_status ENUM('pending','paid','cancelled','refunded') DEFAULT 'pending',
  paid_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_package_orders_tenant (tenant_id, created_at)
);

CREATE TABLE package_plans (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  plan_code VARCHAR(80) UNIQUE NOT NULL,
  name VARCHAR(120) NOT NULL,
  monthly_fee DECIMAL(10,2) DEFAULT 0,
  included_ai_count INT DEFAULT 0,
  store_limit INT DEFAULT 1,
  advanced_features JSON,
  status ENUM('active','disabled') DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE tenant_monthly_bills (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  bill_month CHAR(7) NOT NULL,
  package_plan VARCHAR(80),
  package_fee DECIMAL(10,2) DEFAULT 0,
  included_ai_count INT DEFAULT 0,
  purchased_ai_count INT DEFAULT 0,
  success_ai_uses INT DEFAULT 0,
  overage_ai_uses INT DEFAULT 0,
  tenant_settle_unit_price DECIMAL(10,4) DEFAULT 0,
  ai_overage_revenue DECIMAL(10,2) DEFAULT 0,
  total_bill_amount DECIMAL(10,2) DEFAULT 0,
  internal_api_cost DECIMAL(10,4) DEFAULT 0,
  platform_gross_profit DECIMAL(10,2) DEFAULT 0,
  bill_status ENUM('draft','issued','paid','overdue') DEFAULT 'draft',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_bill_month (tenant_id, bill_month),
  KEY idx_tenant_monthly_bills (tenant_id, bill_status)
);

CREATE TABLE tenant_ai_usage_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT,
  generation_job_id BIGINT,
  usage_type ENUM('free','gift','paid','compensate','admin_adjust') NOT NULL,
  change_count INT NOT NULL,
  balance_after INT NOT NULL,
  customer_paid_amount DECIMAL(10,2) DEFAULT 0,
  tenant_settle_unit_price DECIMAL(10,4) DEFAULT 0,
  internal_api_cost DECIMAL(10,4) DEFAULT 0,
  remark VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_usage_tenant_store (tenant_id, store_id, created_at)
);

CREATE TABLE api_key_configs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT,
  provider VARCHAR(80) NOT NULL,
  key_name VARCHAR(120) NOT NULL,
  secret_ciphertext TEXT NOT NULL,
  secret_fingerprint VARCHAR(120) NOT NULL,
  masked_secret VARCHAR(120) NOT NULL,
  status ENUM('active','disabled') DEFAULT 'active',
  updated_by_user_id BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_api_key_config (tenant_id, provider, key_name),
  KEY idx_api_key_provider (tenant_id, provider, status)
);

CREATE TABLE ai_user_daily_quota (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  quota_date DATE NOT NULL,
  free_limit INT DEFAULT 2,
  free_used INT DEFAULT 0,
  paid_used INT DEFAULT 0,
  gift_used INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_quota (tenant_id, user_id, quota_date)
);

CREATE TABLE store_visit_sessions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  qr_scene VARCHAR(120) NOT NULL,
  status ENUM('active','expired','revoked') DEFAULT 'active',
  expires_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_store_visit_active (tenant_id, store_id, user_id, status, expires_at)
);

CREATE TABLE ai_gift_records (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  gifted_by_user_id BIGINT NOT NULL,
  status ENUM('unused','used','expired','converted_order','completed') DEFAULT 'unused',
  generation_job_id BIGINT,
  order_id BIGINT,
  revenue_amount DECIMAL(10,2) DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  used_at DATETIME,
  KEY idx_gift_customer (tenant_id, store_id, customer_id, status)
);

CREATE TABLE staff_gift_quotas (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  staff_id BIGINT NOT NULL,
  quota_date DATE NOT NULL,
  daily_limit INT DEFAULT 5,
  used_count INT DEFAULT 0,
  extra_granted INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_staff_quota (tenant_id, store_id, staff_id, quota_date)
);

CREATE TABLE orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  stylist_id BIGINT,
  direction ENUM('male','female','neutral'),
  hairstyle_id VARCHAR(100),
  hair_color_id VARCHAR(100),
  service_item_id BIGINT,
  appointment_time DATETIME,
  status ENUM('pending','confirmed','arrived','serving','completed','cancelled') DEFAULT 'pending',
  is_ai_converted TINYINT DEFAULT 0,
  ai_job_id BIGINT,
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_orders_scope (tenant_id, store_id, user_id, status),
  KEY idx_orders_ai (tenant_id, store_id, ai_job_id)
);

CREATE TABLE service_records (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  order_id BIGINT NOT NULL,
  stylist_id BIGINT,
  service_item_id BIGINT,
  actual_amount DECIMAL(10,2) NOT NULL,
  is_ai_converted TINYINT DEFAULT 0,
  completed_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_service_records_scope (tenant_id, store_id, completed_at)
);

CREATE TABLE sync_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  event_type VARCHAR(80) NOT NULL,
  payload JSON NOT NULL,
  status ENUM('pending','synced','failed') DEFAULT 'pending',
  retry_count INT DEFAULT 0,
  last_error VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  synced_at DATETIME,
  KEY idx_sync_events_status (tenant_id, status, created_at)
);
