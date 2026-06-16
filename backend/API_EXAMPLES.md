# 后端 API 示例

默认演示数据：

```text
tenant_id = 1
store_id = 1
customer user_id = 1
staff user_id = 2
```

## 1. 健康检查

```bash
curl http://127.0.0.1:8000/health
```

## 2. 获取发型发色

```bash
curl "http://127.0.0.1:8000/hairstyles?tenant_id=1&direction=female"
curl "http://127.0.0.1:8000/hair-colors?tenant_id=1&direction=female"
curl "http://127.0.0.1:8000/inspiration?tenant_id=1&direction=female"
```

## 3. 到店扫码确认免费资格

```bash
curl -X POST http://127.0.0.1:8000/stores/scan-qr ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"qr_scene\":\"store:1:1\"}"
```

免费AI试发必须先有有效到店扫码会话；不在店的顾客可以走付费或赠送。

## 4. 推荐方案准备

```bash
curl -X POST http://127.0.0.1:8000/ai/style/prepare ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"direction\":\"female\",\"billing_type\":\"free\",\"selected_style_id\":\"style_010\",\"selected_color_id\":\"color_003\"}"
```

## 5. 创建自拍临时上传URL

```bash
curl -X POST http://127.0.0.1:8000/uploads/temp-url ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"file_ext\":\"jpg\"}"
```

返回里的 `photo_temp_url` 只用于本次AI生成，不写入 `ai_generation_jobs`。

返回会包含当前存储适配器：

```json
{
  "provider": "mock",
  "persistent_storage": false,
  "ttl_seconds": 1800
}
```

正式环境配置 `TEMP_STORAGE_PROVIDER=aliyun_oss` 后，后端返回阿里OSS短期上传URL；小程序端仍然不接触 OSS 密钥。

## 6. 免费AI试发生成

同步生成接口，适合本地调试：

```bash
curl -X POST http://127.0.0.1:8000/ai/style/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"direction\":\"female\",\"billing_type\":\"free\",\"selected_style_id\":\"style_010\",\"selected_color_id\":\"color_003\",\"photo_temp_url\":\"https://temp-object.local/temp/1/1/1/demo.jpg\"}"
```

正式小程序优先使用排队接口：

```bash
curl -X POST http://127.0.0.1:8000/ai/style/enqueue ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"direction\":\"female\",\"billing_type\":\"free\",\"selected_style_id\":\"style_010\",\"selected_color_id\":\"color_003\",\"photo_temp_url\":\"https://temp-object.local/temp/1/1/1/demo.jpg\"}"
```

Worker 消费下一条任务：

```bash
curl -X POST http://127.0.0.1:8000/worker/ai/process-next
```

## 7. 付费AI试发生成

先创建模拟已支付订单：

```bash
curl -X POST http://127.0.0.1:8000/ai/pay/create ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"amount\":9.9,\"mock_paid\":true}"
```

创建待支付订单并返回小程序支付参数：

```bash
curl -X POST http://127.0.0.1:8000/ai/pay/create ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"amount\":9.9,\"mock_paid\":false}"
```

POC/展示阶段 `PAYMENT_PROVIDER=mock`，返回 mock `wechat_pay_params`。正式商业MVP必须切到真实微信支付 Provider 后再上线收费。

再把返回的 `pay_order_no` 放进生成接口：

```bash
curl -X POST http://127.0.0.1:8000/ai/style/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"direction\":\"female\",\"billing_type\":\"paid\",\"selected_style_id\":\"style_010\",\"selected_color_id\":\"color_003\",\"pay_order_no\":\"PAYxxxx\"}"
```

查询支付单必须带当前租户、门店和用户，租户不匹配时返回 404：

```bash
curl "http://127.0.0.1:8000/ai/pay/orders/PAYxxxx?tenant_id=1&store_id=1&user_id=1"
curl "http://127.0.0.1:8000/ai/pay/orders/PAYxxxx?tenant_id=2&store_id=1&user_id=1"
```

查询AI任务也必须带当前租户、门店和用户。顾客视图不返回平台真实成本：

```bash
curl "http://127.0.0.1:8000/ai/style/jobs/AIxxxx?tenant_id=1&store_id=1&user_id=1"
curl "http://127.0.0.1:8000/ai/style/results/AIxxxx?tenant_id=1&store_id=1&user_id=1"
```

## 8. 商家赠送AI试发

```bash
curl -X POST http://127.0.0.1:8000/merchant/ai/gift ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"customer_id\":1,\"staff_id\":2}"
```

顾客使用赠送次数生成：

```bash
curl -X POST http://127.0.0.1:8000/ai/style/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"direction\":\"female\",\"billing_type\":\"gift\",\"selected_style_id\":\"style_010\",\"selected_color_id\":\"color_003\"}"
```

## 9. 下单与完成服务

```bash
curl -X POST http://127.0.0.1:8000/orders ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"stylist_id\":2,\"direction\":\"female\",\"hairstyle_id\":\"style_010\",\"hair_color_id\":\"color_003\",\"ai_job_no\":\"AIxxxx\"}"
```

读取订单必须带当前租户和门店，租户不匹配时返回 404：

```bash
curl "http://127.0.0.1:8000/orders/1?tenant_id=1&store_id=1"
curl "http://127.0.0.1:8000/orders/1?tenant_id=2&store_id=1"
```

```bash
curl -X PUT http://127.0.0.1:8000/merchant/orders/1/complete ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"stylist_id\":2,\"service_item_id\":101,\"actual_amount\":399}"
```

商家端订单流转：

```bash
curl -X PUT http://127.0.0.1:8000/merchant/orders/1/assign-stylist ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"stylist_id\":2}"

curl -X PUT http://127.0.0.1:8000/merchant/orders/1/status ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"status\":\"confirmed\"}"

curl -X PUT http://127.0.0.1:8000/merchant/orders/1/status ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"status\":\"arrived\"}"

curl -X PUT http://127.0.0.1:8000/merchant/orders/1/status ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"status\":\"serving\"}"
```

## 10. 平台统计

```bash
curl "http://127.0.0.1:8000/platform/usage?tenant_id=1"
curl "http://127.0.0.1:8000/platform/costs?tenant_id=1"
curl "http://127.0.0.1:8000/platform/billing?tenant_id=1&tenant_settle_unit_price=2.0"
curl "http://127.0.0.1:8000/platform/ai-limits?tenant_id=1&store_id=1"
curl "http://127.0.0.1:8000/platform/overview"
curl "http://127.0.0.1:8000/platform/deployment-readiness"
```

调整 AI 并发/日限额：

```bash
curl -X PUT http://127.0.0.1:8000/platform/ai-limits ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_concurrency_limit\":1,\"store_concurrency_limit\":5,\"tenant_concurrency_limit\":20,\"platform_concurrency_limit\":50,\"user_daily_limit\":20,\"tenant_daily_limit\":5000}"
```

## 11. 平台开客户和卖AI次数包

创建新客户：

```bash
curl -X POST http://127.0.0.1:8000/platform/tenants ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_code\":\"tenant_new\",\"name\":\"New Hair Brand\",\"package_plan\":\"store_plan\",\"initial_ai_count\":100}"
```

给客户创建门店：

```bash
curl -X POST http://127.0.0.1:8000/platform/stores ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_code\":\"store_016\",\"name\":\"New Store\",\"daily_ai_limit\":300}"
```

更新客户品牌/套餐和门店配置：

```bash
curl -X PUT http://127.0.0.1:8000/platform/tenants/1 ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Updated Brand\",\"logo_url\":\"https://temp.local/logo.png\",\"package_plan\":\"chain_growth\",\"status\":\"active\"}"

curl -X PUT "http://127.0.0.1:8000/platform/stores/1?tenant_id=1" ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Updated Store\",\"daily_ai_limit\":300,\"status\":\"active\"}"
```

配置平台/API密钥，列表只返回掩码和指纹：

```bash
curl -X POST http://127.0.0.1:8000/platform/api-keys ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":null,\"provider\":\"dashscope\",\"key_name\":\"platform_default\",\"secret_value\":\"sk-test-secret-123456\",\"updated_by_user_id\":3}"

curl "http://127.0.0.1:8000/platform/api-keys"
curl "http://127.0.0.1:8000/platform/api-keys/resolve?tenant_id=1&provider=dashscope&key_name=platform_default"
```

配置套餐版本：

```bash
curl -X POST http://127.0.0.1:8000/platform/package-plans ^
  -H "Content-Type: application/json" ^
  -d "{\"plan_code\":\"chain_growth\",\"name\":\"Chain Growth\",\"monthly_fee\":2999,\"included_ai_count\":10000,\"store_limit\":20,\"advanced_features\":[\"ai_tags\",\"feishu_dashboard\"],\"status\":\"active\"}"

curl "http://127.0.0.1:8000/platform/package-plans"
```

## 15. 商家端主理人和AI客服知识库编辑

编辑主理人资料，停用后不会进入顾客推荐结果：

```bash
curl -X PUT http://127.0.0.1:8000/merchant/staff/2 ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"display_name\":\"Updated Stylist\",\"directions\":[\"male\"],\"skill_tags\":[\"short hair\",\"texture\"],\"availability_status\":\"available\",\"is_enabled\":false,\"is_recommended\":false,\"sort_order\":99}"
```

编辑AI客服知识库，停用后顾客AI咨询不会再命中：

```bash
curl -X PUT http://127.0.0.1:8000/merchant/ai-knowledge/1 ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"answer\":\"Color starts from 399. Final price is confirmed in store.\",\"keywords\":[\"color fee\"],\"is_enabled\":false}"

curl "http://127.0.0.1:8000/merchant/ai-knowledge?tenant_id=1&store_id=1&include_disabled=true"
```

生成客户月度账单：

```bash
curl -X POST http://127.0.0.1:8000/platform/monthly-bills/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"bill_month\":\"2026-05\",\"tenant_settle_unit_price\":1.8,\"bill_status\":\"issued\"}"

curl "http://127.0.0.1:8000/platform/monthly-bills?tenant_id=1"
curl "http://127.0.0.1:8000/merchant/monthly-bills?tenant_id=1"
```

记录POC效果评测：

```bash
curl -X POST http://127.0.0.1:8000/platform/poc-evaluations ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"job_no\":\"AI_POC_001\",\"direction\":\"female\",\"test_case_no\":\"POC-001\",\"input_photo_label\":\"female-01\",\"selected_style_id\":\"style_010\",\"selected_color_id\":\"color_003\",\"is_like_customer\":true,\"only_changed_hair\":true,\"face_changed\":false,\"generated_three_images\":true,\"hair_color_accurate\":true,\"hairstyle_acceptable\":true,\"can_show_customer\":true,\"generate_duration_seconds\":32,\"internal_api_cost\":0.88,\"notes\":\"good\"}"

curl "http://127.0.0.1:8000/platform/poc-evaluations/summary?tenant_id=1"
```

后台补偿/人工调账AI额度：

```bash
curl -X POST http://127.0.0.1:8000/platform/ai-balance/adjust ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"change_count\":10,\"usage_type\":\"compensate\",\"remark\":\"POC compensation\",\"user_id\":3}"
```

给客户购买次数包：

```bash
curl -X POST http://127.0.0.1:8000/platform/packages ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"package_name\":\"trial_500\",\"purchased_count\":500,\"unit_price\":1.5,\"payment_status\":\"paid\"}"

curl "http://127.0.0.1:8000/platform/packages?tenant_id=1"
```

## 12. 商家工作台

```bash
curl "http://127.0.0.1:8000/merchant/workbench?tenant_id=1&store_id=1"
```

商家新增发型/发色：

```bash
curl -X POST http://127.0.0.1:8000/merchant/hairstyles ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"style_id\":\"style_custom_001\",\"name\":\"Layered Medium Cut\",\"direction\":\"female\",\"hair_length\":\"medium\",\"thumbnail_url\":\"https://temp.local/style.jpg\",\"display_tags\":[\"layered\",\"soft\"],\"need_perm\":true,\"is_enabled\":true,\"is_recommended\":true}"

curl -X POST http://127.0.0.1:8000/merchant/hair-colors ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"color_id\":\"color_custom_001\",\"name\":\"Smoky Brown\",\"direction\":\"female\",\"color_swatch\":\"#8A6B5A\",\"display_tags\":[\"natural\",\"cool\"],\"need_bleach\":false,\"is_enabled\":true,\"is_recommended\":true}"
```

商家编辑/下架发型发色：

```bash
curl -X PUT http://127.0.0.1:8000/merchant/hairstyles/style_custom_001 ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"name\":\"Updated Layered Medium Cut\",\"display_tags\":[\"updated\",\"soft\"],\"need_perm\":false,\"is_enabled\":false}"

curl -X PUT http://127.0.0.1:8000/merchant/hair-colors/color_custom_001 ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"name\":\"Updated Smoky Brown\",\"display_tags\":[\"updated\",\"cool\"],\"need_bleach\":true,\"is_enabled\":false}"
```

商家编辑/停用服务项目：

```bash
curl -X PUT http://127.0.0.1:8000/merchant/service-items/160 ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"name\":\"Premium Scalp Spa\",\"category\":\"care\",\"base_price\":368,\"is_enabled\":false,\"sort_order\":61}"
```

商家新增主理人：

```bash
curl -X POST http://127.0.0.1:8000/merchant/staff ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"openid\":\"new_staff_openid\",\"phone\":\"13800000000\",\"display_name\":\"New Stylist\",\"title\":\"Senior Stylist\",\"directions\":[\"female\",\"neutral\"],\"skill_tags\":[\"color\",\"medium hair\"],\"avatar_url\":\"https://temp.local/staff.jpg\",\"role\":\"staff\",\"sort_order\":5}"
```

商家查看业绩统计：

```bash
curl "http://127.0.0.1:8000/merchant/performance?tenant_id=1&store_id=1"
curl "http://127.0.0.1:8000/merchant/performance?tenant_id=1&store_id=1&stylist_id=2"
```

商家维护AI客服知识库：

```bash
curl -X POST http://127.0.0.1:8000/merchant/ai-knowledge ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"category\":\"aftercare\",\"question\":\"How to care after perm\",\"answer\":\"Avoid washing hair for 48 hours after perm.\",\"keywords\":[\"after perm\",\"perm care\"],\"is_enabled\":true}"
```

## 16. Platform monthly bill status

```bash
curl -X PUT http://127.0.0.1:8000/platform/monthly-bills/1/status ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"bill_status\":\"paid\"}"
```

## 17. Merchant order list

```bash
curl "http://127.0.0.1:8000/merchant/orders?tenant_id=1&store_id=1&status=pending"
curl "http://127.0.0.1:8000/merchant/orders?tenant_id=1&store_id=1&stylist_id=2"
```

## 18. Merchant gift conversion

```bash
curl "http://127.0.0.1:8000/merchant/ai/gift-conversions?tenant_id=1&store_id=1"
curl "http://127.0.0.1:8000/merchant/ai/gift-conversions?tenant_id=1&store_id=1&staff_id=2"
```

## 19. Customer order list

```bash
curl "http://127.0.0.1:8000/orders?tenant_id=1&user_id=1&store_id=1"
curl "http://127.0.0.1:8000/orders?tenant_id=1&user_id=1&status=pending"
```

## 20. Asset popularity

```bash
curl -X POST http://127.0.0.1:8000/analytics/asset-events ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"store_id\":1,\"user_id\":1,\"asset_type\":\"hairstyle\",\"asset_id\":\"style_010\",\"event_type\":\"view\"}"

curl "http://127.0.0.1:8000/merchant/assets/popularity?tenant_id=1&store_id=1"
curl "http://127.0.0.1:8000/merchant/assets/popularity?tenant_id=1&store_id=1&event_type=order"
```

## 21. Privacy consent

```bash
curl "http://127.0.0.1:8000/privacy/consent?tenant_id=1&user_id=1"

curl -X POST http://127.0.0.1:8000/privacy/consent ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"user_id\":1,\"consent_scope\":\"photo_ai_generation\",\"consent_version\":\"v1\"}"

curl -X POST http://127.0.0.1:8000/privacy/consent/revoke ^
  -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":1,\"user_id\":1,\"consent_scope\":\"photo_ai_generation\",\"consent_version\":\"v1\"}"
```
