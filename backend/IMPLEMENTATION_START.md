# 美发AI小程序执行启动记录

## 当前完成

已完成第一版后端 MVP 骨架，目标是把执行书里的关键业务规则先变成可测试代码。

已落地能力：

1. 多租户、门店、用户基础表。
2. 发型、发色候选库。
3. AI生成任务表，包含排队时长和生成耗时。
4. AI付费订单表。
5. 客户AI额度池，不存 `remaining_balance` 冗余字段。
6. AI次数包、使用日志。
7. 免费/付费AI试发流程。
8. Mock Dify 工作流，模拟一次生成3张图。
9. 三张图成功才扣1次。
10. 失败、超时不扣次数的代码结构。
11. 平台使用统计接口的业务逻辑。
12. 单元测试覆盖核心扣次和付费规则。
13. 顾客AI转化下单。
14. 商家完成服务并记录实际成交金额。
15. 主理人赠送顾客AI试发。
16. 店长/老板追加主理人当天赠送额度。
17. 平台真实成本和客户结算账单统计。
18. 平台创建客户。
19. 平台销售AI次数包并给客户额度池入账。
20. 商家工作台统计订单、AI转化和成交金额。
21. 订单读取接口按 `tenant_id + store_id + order_id` 强制隔离，租户2不能查到租户1订单。
22. AI任务读取接口按 `tenant_id + store_id + user_id + job_no` 强制隔离。
23. AI支付单读取接口按 `tenant_id + store_id + user_id + pay_order_no` 强制隔离。
24. 顾客端AI任务结果不返回平台真实 `internal_api_cost`。
25. 角色权限基础：老板全店、店长本店、主理人本人、顾客本人。
26. AI生成风控基础：单用户、门店、租户每日生成上限。
27. Dockerfile、docker-compose、Nginx 示例和部署说明。
28. 后端支持 `HAIR_AI_DB_PATH` 环境变量。
29. 服务器接口冒烟检查脚本。
30. AI生成支持排队接口 `/ai/style/enqueue`。
31. Worker 支持消费队列任务 `/worker/ai/process-next` 和 `python -m app.worker`。
32. 本地测试默认内存队列，部署环境配置 `REDIS_URL` 后使用 Redis 队列。
33. AI并发限制配置化：用户1、门店5、租户20、平台50为默认值。
34. 平台接口支持查看和调整 AI 并发/日限额。
35. 生成生产 MySQL 建表脚本 `backend/db/schema_mysql.sql`。
36. 新增数据库适配层，本地 SQLite，生产可配置 MySQL URL。

## 已验证

```bash
$env:PYTHONPATH='backend'
python -m pytest backend/tests -q
```

结果：

```text
84 passed
```

## 下一步执行顺序

### 1. POC验证

1. 申请并配置阿里云百炼/通义万相真实 API Key。
2. 部署或本地启动 Dify。
3. 将 `MockDifyClient` 替换为真实 Dify 工作流调用器。
4. 准备男性、女性、中性自拍测试图。
5. 测试只换发型、只换发色、发型+发色。
6. 记录成功率、耗时、真实成本。

### 2. FastAPI 联调

1. 安装 `backend/requirements.txt`。
2. 启动：

```bash
uvicorn app.main:app --reload --app-dir backend
```

3. 验证：

```bash
GET /health
GET /hairstyles?tenant_id=1&direction=female
POST /ai/style/prepare
POST /ai/style/generate
GET /platform/usage
```

### 3. 微信小程序联调

1. 顾客端小样接后端接口。
2. 上传自拍先走临时URL。
3. 结果页只展示临时图。
4. 退出后不提供历史找回。

### 4. 商家端联调

1. 接订单列表。
2. 接AI次数统计。
3. 接赠送AI次数。
4. 接完成服务和业绩统计。

### 5. 平台后台

1. 客户管理。
2. 门店管理。
3. AI次数包充值。
4. 真实API成本统计。
5. 客户账单。
6. 飞书同步配置。

## 当前保留的 Mock

1. Dify/通义万相调用仍为 Mock。
2. 微信支付仍为 Mock Provider，已隔离为 `PaymentProvider`。
3. Redis 分布式锁暂用进程内锁表达规则。
4. MySQL 生产库暂用 SQLite 骨架验证逻辑。
5. 自拍/生成图存储默认是 Mock 临时URL，已隔离为 `TempStorageProvider`，生产环境切 `TEMP_STORAGE_PROVIDER=aliyun_oss`。

## 本轮新增

1. 新增 `backend/app/storage.py` 临时图片存储适配层。
2. `HairAiService` 不再自己拼上传URL，改为调用存储Provider。
3. `/health` 增加 `temp_storage`，便于上线排查当前环境是否仍是 Mock。
4. `.env.example` 增加 OSS 配置项。
5. 单元测试增加 Mock 存储、OSS object key 隔离、签名URL结构校验。
6. 新增 `backend/app/payments.py` AI试发支付适配层。
7. `/ai/pay/create` 支持创建待支付订单并返回小程序支付参数结构。
8. `/health` 增加 `payment`，便于上线排查是否误用 Mock 支付。
9. 新增 `backend/app/feishu.py` 飞书同步适配层。
10. `/sync/feishu/retry` 会调用 Provider，同步失败只标记事件失败，不影响主流程。
11. 新增 `/platform/deployment-readiness` 上线安全检查接口，生产环境会拦截 Mock Dify、Mock 存储、Mock 支付。
12. 新增门店扫码会话 `store_visit_sessions` 和 `/stores/scan-qr`。
13. 免费AI试发必须基于有效到店扫码会话，不在店顾客需走付费或赠送。
14. 付费AI生成失败后，同一支付单只允许免费重试一次，成功后不可复用。
15. 商家端订单流转接口补齐：分配主理人、确认预约、确认到店、开始服务、取消；完成服务仍走带金额的完成接口。
16. 商家图库新增接口补齐：发型/发色可录入方向、标签、推荐、启用、是否需烫/漂等字段。
17. 平台按门店开通接口补齐：可为客户创建门店并设置门店每日AI上限。
18. 商家主理人新增/列表接口补齐：支持方向、擅长标签、头像、职级、排序。
19. Dify 工作流输出解析测试补齐：成功、失败、非法JSON都会被测试覆盖。
20. 平台 API 密钥配置管理补齐：只返回掩码和指纹，不返回明文/密文，同名配置可更新。
21. 平台套餐版本配置管理补齐：月费、套餐内AI额度、门店上限、进阶功能可配置。
22. 平台月度账单生成补齐：平台视图含真实成本/毛利，客户视图隐藏成本/毛利。
23. 平台AI额度后台补偿/人工调账补齐：写入审计日志，余额不能调成负数。
24. 平台客户/门店配置更新补齐：品牌、LOGO、套餐、状态、门店AI上限可调整。
25. 客户/门店禁用风控补齐：扫码、生成、下单等核心业务会被阻止。
26. AI客服知识库补齐：商家可维护问答和关键词，顾客咨询时优先命中知识库。
27. 商家业绩统计补齐：可按门店、主理人、服务项目、AI转化拆分。
28. 商家服务项目维护补齐：新增、编辑、启停、排序。
29. 商家发型/发色素材更新补齐：编辑、改标签、改推荐、启停下架。
30. 顾客端发型灵感分组接口补齐：热门、长发、中发、短发、发色一次返回。
31. 结果页详情接口补齐：三张图滑动、推荐3位主理人、默认主理人、保存提示、结果标签。
32. POC效果评测记录补齐：记录真实效果、耗时、成本，并汇总成功率/可展示率/平均成本。

以上 Mock 都已经隔离在明确位置，后续可以逐个替换。
