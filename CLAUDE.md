# CLAUDE.md — 美发 AI 小程序项目（AI 协作指南）

> 本文件供 AI 编程助手（Claude Code / Cursor / Cowork 等）阅读，帮助快速理解项目并安全地继续开发。
> 人类协作者也可读。最后更新：2026-06-07。

## 0. 给 AI 的首要须知（先读这一段）

1. **本项目是一套多租户 SaaS，处理顾客人脸照片、微信支付、15 家门店经营数据。安全第一。**
2. **当前最高优先级未完成项：后端没有完整鉴权。** 鉴权骨架已写好（`backend/app/auth.py`、`dependencies.py`），但**尚未套到全部接口**。在把后端暴露到公网前，必须先完成接入（见第 6 节）。
3. **编辑超大文件（`services.py` ~4700 行、`main.py` ~1900 行）时务必小心**：本项目历史上发生过对这两个文件做大段编辑时文件被截断的情况。改完**必须**立即跑 `python -c "import ast; ast.parse(open('文件').read())"` 校验语法，并检查文件结尾是否完整（最后一个函数/路由是否闭合）。优先用小范围、精确的局部编辑，避免一次性替换大段内容。
4. **项目当前尚未做任何 git commit**（`git ls-files` 为空）。改动前后建议提醒用户提交，以免丢失。

## 1. 项目是什么

面向连锁美发门店（约 15 家店、每店每月约 1000 客）的微信小程序 SaaS。核心体验：顾客自选发型+发色 → 上传自拍 → AI 同步生成换发预览（3 张图）→ 推荐备选发型和发型师 → 预约。

三方角色：
- **顾客**：选发型发色、AI 换发、预约、查订单。
- **商家**（boss 老板 / manager 店长 / staff 发型师）：工作台、订单流转、业绩、图库、AI 次数赠送。
- **平台**（platform_admin）：多租户管理、API 密钥、AI 次数包计费、账单、成本毛利。

商业模式两层：平台向商家卖 AI 次数包；商家向顾客卖"超出免费额度的 AI 付费试发"（走微信支付）。剪染烫等到店服务走线下结算，系统只记账。

## 2. 技术栈与目录结构

- 后端：Python + FastAPI，数据库 SQLite(开发) / MySQL(生产) 可切换，Redis 队列，Dify+通义万相做 AI 换发，阿里云 OSS 存临时图。
- 前端：两个微信小程序（原生 WXML/WXSS/JS）。
- 部署：Docker Compose（API + Worker + Redis + MySQL）+ Nginx。

```
美发/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 所有路由（~99 个接口）
│   │   ├── services.py        # 业务逻辑总汇（~4700 行，核心）
│   │   ├── auth.py            # 【新】JWT 签发/校验（标准库 HS256，无新依赖）
│   │   ├── dependencies.py    # 【新】FastAPI 鉴权守卫（Depends）
│   │   ├── models.py          # dataclass / Enum（BillingType, JobStatus, GenerateRequest...）
│   │   ├── db.py              # build_store_from_env：按 DATABASE_URL 选 SQLite/MySQL
│   │   ├── store.py / mysql_store.py  # 数据访问层
│   │   ├── dify_client.py     # Dify 调用 + MockDifyClient
│   │   ├── aliyun_hair_tryon.py # 通义万相换发
│   │   ├── payments.py        # 微信支付 provider（WeChatPayProvider 仍是空壳！）
│   │   ├── storage.py         # OSS 临时图 provider + Mock
│   │   ├── feishu.py          # 飞书同步 provider + Mock
│   │   ├── queue.py / worker.py  # AI 任务队列与 worker
│   │   └── ...
│   ├── tests/                 # pytest：test_auth/test_core/test_db/test_dify_client/...
│   ├── db/schema_mysql.sql    # MySQL 建表脚本
│   ├── .env.example           # 所有环境变量样例
│   ├── Dockerfile
│   └── AUTH_接入指南.md        # 鉴权如何接入全部接口（重要）
├── miniapp-customer/          # 顾客端小程序
├── miniapp-merchant/          # 商家端小程序
├── 平台后台展示小样_v1.html    # 平台后台展示页（读后端接口）
├── docker-compose.yml         # 云部署四件套
├── deploy/                    # nginx 配置 + 部署 README
├── 美发AI小程序_项目可行性分析报告.md  # 业务全景（务必读）
├── 上线配置清单.md             # 上线前 mock→真实 的清单（务必读）
└── 如何查看AI成本数据.md
```

## 3. 关键业务规则（改动时不能违反）

1. **性别硬过滤**：顾客选男客只能看 male+unisex，女客只能看 female+unisex。必须后端规则过滤，**不能只靠 AI 提示词**，AI 不得推荐数据库里不存在的发型/发色。
2. **多门店数据隔离**：boss 看全租户，manager 看本店，staff 看本人，customer 看本人。后端必须强制按身份过滤，**绝不信任前端传的 tenant_id/store_id**。（参见 `services.assert_scope_access`。）
3. **隐私**：顾客自拍只用于本次生成、用完即删、不入库。AI 调用前必须有隐私授权（`/privacy/consent`）。
4. **AI 计费类型**（`BillingType`）：`free`(免费额度) / `gift`(赠送) / `paid`(付费，走微信支付)。生成失败/超时/少于3图**不扣次数**。
5. **成本字段 `internal_api_cost`** 只给平台看，不能暴露给商家端/顾客端。

## 4. 本地运行与测试

```bash
# 安装依赖
pip install -r backend/requirements.txt

# 跑测试（务必在改动后运行）
PYTHONPATH=backend python -m pytest backend/tests -q

# 本地启动（mock 模式，SQLite）
APP_ENV=local PYTHONPATH=backend python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
# 健康检查
curl http://127.0.0.1:8000/health
```

提供商通过环境变量切 mock/真实：`PAYMENT_PROVIDER`、`TEMP_STORAGE_PROVIDER`、`FEISHU_SYNC_PROVIDER`、`DIFY_BASE_URL`/`DIFY_API_KEY`（留空即 Mock）。

## 5. 云服务器部署

```bash
cp backend/.env.example backend/.env   # 按"上线配置清单.md"填真实值
docker compose up -d --build           # 起 API + Worker + Redis + MySQL
curl http://127.0.0.1:8000/health
```

Nginx 用 `deploy/nginx.hair-ai.conf`，改 `server_name`，**必须配 HTTPS**（微信小程序强制）。
`docker-compose.yml` 里的 MySQL 密码是占位符 `change_this_*`，上线前必须改强密码；`.env` 不得进 git。

## 6. 待办（按优先级，AI 接活从这里挑）

### P0 — 上公网前必须完成
1. **鉴权接入全部接口**：用 `dependencies.py` 的 `require_customer/require_merchant/require_platform_admin` + `assert_can_access_store` 改造全部 `/merchant/*`、`/platform/*`、顾客接口；删掉接口里来自请求的 `tenant_id/store_id`，一律用 `principal.*`。详细模板见 `backend/AUTH_接入指南.md`。已有 3 个 `*_secure` 示例可参考。
2. **微信支付**：`payments.py` 的 `WeChatPayProvider` 是空壳（直接 raise）。需实现 V3 下单 + 证书签名；`/ai/pay/notify` 回调**必须验签**（当前凭订单号即标记已付，可被伪造）。
3. **密钥真加密**：`services._encrypt_secret` 现在是 XOR 异或混淆 + 默认密钥 `local-dev-key`，等于明文。换成 KMS 或 cryptography 的 Fernet(AES)，生产禁用默认密钥。
4. **隐私闭环自检**：确认自拍用完即删、有日志可证；微信敏感类目申报。

### P1
5. AI 真实成本：接通真实通义万相，跑样本测出单张真实价，回填 `AI_IMAGE_UNIT_COST`（成本逻辑见 `services.resolve_generation_cost`，已支持"服务商回填优先，否则按张数×单价自算"）。
6. 微信登录接 `code2Session`（现在顾客端用演示 openid、商家端写死 staffId=2）。
7. 灰度前压测排队/降级链路。

### P2
8. 拆分 `services.py`（4700 行）为按域模块。
9. 平台敏感操作加审计日志；接口幂等键。

## 7. 已完成的近期改动（避免重复劳动）
- `auth.py` + `dependencies.py`：JWT 鉴权骨架 + 角色守卫（已写测试 `test_auth.py`，全过）。
- `main.py`：新增 `/auth/wx-login`(发token)、`/auth/merchant-login`、`/auth/platform-login`、`/auth/me`，及 3 个 `*_secure` 接入示例。
- `services.py`：`resolve_generation_cost()` 让 AI 生成成本真实可算；`platform_costs` 返回 `configured_image_unit_cost`。
- `.env.example`：新增 `AI_IMAGE_UNIT_COST`、`JWT_SECRET`、`PLATFORM_ADMIN_*` 等。

## 8. 重要环境变量速查
- 身份：`JWT_SECRET`(生产必填)、`JWT_TTL_SECONDS`、`PLATFORM_ADMIN_USER/PASSWORD`
- 数据库：`DATABASE_URL`(mysql+pymysql://... 或 sqlite:///)、`HAIR_AI_DB_PATH`、`REDIS_URL`、`MYSQL_INIT_SCHEMA`
- AI：`DIFY_BASE_URL`/`DIFY_API_KEY`、`ALIYUN_DASHSCOPE_API_KEY`、`AI_IMAGE_UNIT_COST`
- 提供商开关：`PAYMENT_PROVIDER`、`TEMP_STORAGE_PROVIDER`、`FEISHU_SYNC_PROVIDER`
- OSS：`OSS_BUCKET/REGION/ENDPOINT/ACCESS_KEY_ID/ACCESS_KEY_SECRET`
- 微信：`WECHAT_APP_ID`、`WECHAT_PAY_MCH_ID`、`WECHAT_PAY_NOTIFY_URL`
- 运行环境：`APP_ENV`(local/staging/production)、`CORS_ALLOW_ORIGINS`(生产收紧勿用*)
