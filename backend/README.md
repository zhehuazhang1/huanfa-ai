# 美发AI小程序后端 MVP 骨架

这是根据 `美发AI小程序_云服务器Dify工作流_AI执行落地书.md` 落下来的第一版可执行后端骨架。

当前已实现：

- 多租户/门店基础数据
- 发型/发色候选库
- 顾客端发型灵感分组：热门、长发、中发、短发、发色
- AI试发任务表
- AI付费订单表
- 客户AI额度池和使用日志
- 免费/赠送/付费三类生成资格
- 到店扫码生成有效门店会话，免费AI试发必须基于有效扫码会话
- 三张图全部成功才扣1次
- 结果页详情接口：三张图滑动、推荐3位主理人、默认主理人、保存提示、结果标签
- 失败、超时不扣次数
- 排队时长 `queue_wait_seconds`
- 生成耗时 `generate_duration_seconds`
- 客户余额不存 `remaining_balance`，实时计算
- 扣次数使用事务锁语义，避免重复扣减
- Dify/通义万相先使用 Mock Provider，后续替换真实接口
- 顾客AI付费订单创建、支付回调模拟、支付单查询
- AI试发独立支付适配层：展示阶段 Mock，正式MVP预留微信支付 Provider
- 付费AI生成失败后，同一个支付单只允许免费重试一次
- 顾客AI转化下单
- 商家端订单流转：分配主理人、确认预约、确认到店、开始服务、取消、完成服务
- 商家端完成服务并记录成交金额
- 商家端主理人维护：新增、列表、在店状态、擅长标签
- 商家AI客服知识库维护：问答、关键词、门店/客户范围
- 商家端赠送顾客1次AI试发
- 店长/老板给主理人追加当天赠送额度
- 平台端使用量、真实成本、客户结算价、平台毛利统计
- 平台开客户、销售AI次数包、额度池入账
- 平台按客户创建门店并设置门店每日AI上限
- 平台客户/门店配置更新：品牌、LOGO、套餐、状态、门店AI上限
- 客户/门店禁用后阻止扫码、生成、下单等核心业务
- 平台 API 密钥配置管理：只展示掩码和指纹，不返回明文/密文
- 平台套餐版本配置管理：月费、套餐内AI额度、门店上限、进阶功能
- 平台月度账单生成：平台视图含真实成本/毛利，客户视图隐藏成本/毛利
- 平台AI额度后台补偿/人工调账，写入审计日志且不能调成负数
- 商家工作台统计订单、AI转化和成交金额
- 商家业绩统计：按门店、主理人、服务项目、AI转化拆分
- 商家服务项目维护：新增、编辑、启停、排序
- 商家图库维护：新增/编辑/启停发型发色、标签、推荐、是否需烫/漂
- 飞书统计同步适配层：展示阶段 Mock，生产可切 Webhook/开放平台同步
- 自拍临时上传URL，不把顾客自拍URL写入任务表
- 临时图片存储适配层：本地 `mock`，生产可切 `aliyun_oss`
- 生成结果三张图仅临时返回，当前骨架使用内存缓存
- 订单读取按 `tenant_id + store_id + order_id` 强制隔离
- AI任务读取按 `tenant_id + store_id + user_id + job_no` 强制隔离
- AI支付单读取按 `tenant_id + store_id + user_id + pay_order_no` 强制隔离
- 顾客端结果不返回平台真实 `internal_api_cost`
- 角色权限基础：老板全店、店长本店、主理人本人、顾客本人
- AI生成风控基础：单用户、门店、租户每日生成上限
- AI生成排队接口和 Worker 处理骨架
- 本地测试使用内存队列，部署环境配置 `REDIS_URL` 后使用 Redis
- AI并发限制配置化，默认用户1、门店5、租户20、平台50
- 平台可查看和调整 AI 并发/日限额
- 上线安全检查接口，生产环境可识别 Mock Provider 风险
- POC效果评测记录：生成效果、耗时、成本、可展示率
- MySQL 建表脚本：`db/schema_mysql.sql`
- 数据库适配层：本地 SQLite，生产可通过 `DATABASE_URL=mysql+pymysql://...` 切 MySQL

本地测试：

```bash
$env:PYTHONPATH='backend'
python -m pytest backend/tests -q
```

安装依赖后启动 FastAPI：

```bash
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend
```

部署相关：

- `../docker-compose.yml`：后端 API + Redis + MySQL 预留
- `../deploy/nginx.hair-ai.conf`：Nginx 反向代理示例
- `../deploy/README.md`：云服务器部署步骤
- `scripts/smoke_check.py`：接口冒烟检查
- `db/schema_mysql.sql`：生产 MySQL 建表脚本

当前说明：

- POC/展示阶段支付使用模拟支付。
- 正式商业MVP必须接微信支付。
- `PAYMENT_PROVIDER=mock` 时可返回模拟小程序支付参数，方便前后端联调。
- 真实收费上线前必须完成微信支付V3签名、回调验签、退款/失败重试策略。
- 服务订单仍为到店支付。
- `FEISHU_SYNC_PROVIDER=mock` 时只在本地标记同步成功。
- `FEISHU_SYNC_PROVIDER=feishu_webhook` 时通过 `FEISHU_WEBHOOK_URL` 推送统计事件；失败只标记 sync event，不影响顾客生成和下单主流程。
- AI试发付费是独立流程。
- 未配置 Dify 环境变量时，默认使用 Mock AI 生成。
- 配置 `DIFY_BASE_URL` 和 `DIFY_API_KEY` 后，会调用真实 Dify 工作流。
- `TEMP_STORAGE_PROVIDER=mock` 时返回本地演示URL。
- `TEMP_STORAGE_PROVIDER=aliyun_oss` 时返回短期 OSS 上传URL，需配置 `OSS_BUCKET`、`OSS_REGION` 或 `OSS_ENDPOINT`、`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`。

POC 相关文件：

- `DIFY_WORKFLOW_SPEC.md`：Dify 工作流输入输出规范
- `POC_CHECKLIST.md`：真实换发型发色效果和成本验证清单
- `.env.example`：后端环境变量模板

## 核心接口示例

启动后访问：

```bash
curl http://127.0.0.1:8000/health
```

查看发型候选：

```bash
curl "http://127.0.0.1:8000/hairstyles?tenant_id=1&direction=female"
```

到店扫码确认免费资格：

```bash
curl -X POST http://127.0.0.1:8000/stores/scan-qr ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"qr_scene\":\"store:1:1\"}"
```

发起AI生成：

```bash
curl -X POST http://127.0.0.1:8000/ai/style/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"direction\":\"female\",\"billing_type\":\"free\",\"selected_style_id\":\"style_010\",\"selected_color_id\":\"color_003\"}"
```

平台查看成本：

```bash
curl "http://127.0.0.1:8000/platform/costs?tenant_id=1"
curl "http://127.0.0.1:8000/platform/billing?tenant_id=1&tenant_settle_unit_price=2.0"
curl "http://127.0.0.1:8000/platform/deployment-readiness"
```

## Recent additions

- Merchant staff profiles can now be edited and disabled. Disabled staff are excluded from customer stylist recommendations while historical orders remain intact.
- Merchant AI knowledge items can now be edited, disabled, and listed with `include_disabled=true`. Disabled knowledge is ignored by customer AI chat.
- Current automated test result: `84 passed`.
