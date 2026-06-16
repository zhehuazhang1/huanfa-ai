# 后端鉴权接入指南

本次新增了一套**不改动现有 80 个接口、可逐步迁移**的鉴权骨架，用来解决"后端无身份认证、前端可伪造 tenant_id / store_id 越权"这个上线前的最高优先级安全问题。

## 一、新增 / 改动的文件

| 文件 | 作用 |
|---|---|
| `app/auth.py` | JWT 签发与校验核心（标准库 HS256，无新依赖）。定义 `Principal` 身份对象。 |
| `app/dependencies.py` | FastAPI 鉴权依赖（`Depends` 守卫）：`require_customer / require_staff / require_manager / require_boss / require_merchant / require_platform_admin`，以及跨门店校验 `assert_can_access_store`。 |
| `app/main.py` | 新增登录发 token 接口和 3 个 `*_secure` 接入示例（与原接口并存，便于对照迁移）。 |
| `tests/test_auth.py` | JWT 单元测试（roundtrip / 过期 / 篡改 / 换密钥失效 / 生产强制密钥）。 |

## 二、核心思想（一句话）

> **身份只信 token，不信前端。** 业务里一律用 `principal.tenant_id` / `principal.store_id` / `principal.user_id`，删掉接口里来自请求体/查询参数的同名字段。

## 三、新增接口

- `POST /auth/wx-login`：顾客登录，返回 `access_token`（沿用原逻辑，额外签发 token）。
- `POST /auth/merchant-login`：商家（boss/manager/staff）登录，token 内含角色与门店。
- `POST /auth/platform-login`：平台管理员登录（账号密码来自环境变量）。
- `GET /auth/me`：用 token 换取当前身份，前端可用来确认登录态。

登录后，前端所有请求都带：`Authorization: Bearer <access_token>`。

## 四、如何把一个现有接口改成鉴权版（迁移模板）

以 `/merchant/orders` 为例，对照 `main.py` 里的 `list_merchant_orders_secure`：

改造前（信任前端，越权风险）：

```python
@app.get("/merchant/orders")
def list_merchant_orders(tenant_id: int = 1, store_id: int = 1, status: str | None = None, ...):
    return service.list_merchant_orders(tenant_id=tenant_id, store_id=store_id, status=status, ...)
```

改造后（身份以 token 为准）：

```python
@app.get("/merchant/orders")
def list_merchant_orders(
    status: str | None = None,
    store_id: int | None = None,                      # 仅老板切店时用
    principal: Principal = Depends(require_merchant),  # 守卫 + 拿身份
):
    effective_store_id = store_id if store_id is not None else principal.store_id
    assert_can_access_store(principal, effective_store_id)  # 店长/发型师不能跨店
    return service.list_merchant_orders(
        tenant_id=principal.tenant_id,     # 来自 token
        store_id=effective_store_id,
        status=status,
    )
```

要点：
1. 接口参数里删掉 `tenant_id`，它永远从 token 取。
2. `/merchant/*` 加 `Depends(require_merchant)`；`/platform/*` 加 `Depends(require_platform_admin)`；顾客接口加 `Depends(require_customer)`。
3. 凡是接口仍要接收 `store_id`（比如老板切换查看某店），调用 `assert_can_access_store(principal, store_id)` 做二次校验。

## 五、按角色划分的迁移清单（建议顺序）

1. `/platform/*` 全部加 `require_platform_admin` —— 风险最高（含密钥、计费、跨租户），先做。
2. `/merchant/*` 全部加 `require_merchant`，需要按店区分的再加 `assert_can_access_store`。
3. 顾客接口（`/ai/*`、`/orders`、`/privacy/*` 等）加 `require_customer`，并把 `user_id` 改为 `principal.user_id`。
4. 公开接口（如 `/health`、`/stores/public-profile`、登录接口本身）保持不鉴权。

## 六、必须配置的环境变量（生产）

```bash
JWT_SECRET=<一段足够长的随机字符串>     # 生产必填，否则启动签发即报错
JWT_TTL_SECONDS=604800                  # 可选，token 有效期，默认 7 天
PLATFORM_ADMIN_USER=admin               # 平台登录账号
PLATFORM_ADMIN_PASSWORD=<强密码>        # 平台登录密码，未配置则平台登录返回 500
APP_ENV=production                       # 生产环境标记（触发 JWT_SECRET 强校验）
```

> 注意：`auth.py` 在 `APP_ENV=production` 且未设 `JWT_SECRET` 时会直接抛错，这是有意为之——杜绝用弱默认密钥上线。

## 七、前端配合改动

- 顾客端：登录由"演示 openid"改为 `wx.login` 拿 code → 后端 `code2Session` 换真实 openid（`wx-login` 接口内已注明 TODO）→ 保存返回的 `access_token`，后续请求带 Bearer 头。
- 商家端：去掉写死的 `staffId=2`，改为 `merchant-login` 获取 token。
- 两端统一在请求封装里加 `Authorization` 头。

## 八、验证

```bash
# 仅 JWT 逻辑（无需 FastAPI）：
PYTHONPATH=backend python -m pytest backend/tests/test_auth.py -q

# 全量（装好 requirements 后）：
PYTHONPATH=backend python -m pytest backend/tests -q
```

本地已用等价手工断言验证：JWT roundtrip、角色标志、过期拒绝、篡改拒绝、换密钥失效、生产强制密钥、以及全部角色守卫和跨门店拦截，**均通过**。

## 九、还没做、需要后续接力的

1. 把以上守卫**实际套到全部 80 个接口**（本次只做了骨架 + 3 个示例，避免一次性大改引入风险）。
2. `wx-login` 接真实 `code2Session`；商家/平台登录接真实账号体系。
3. 平台敏感操作加审计日志。
4. 这套鉴权和"支付回调验签、密钥改真加密、隐私闭环"是并列的上线前必办项，建议同批推进。
