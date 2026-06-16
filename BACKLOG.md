# 平台后台问题记录 & 修复计划

> 记录时间：2026-06-08  
> 优先级：P0 = 立即修，P1 = 本周，P2 = 下个版本

---

## 一、数据现状（修复前的基线）

### 生成任务数据结构

每次 AI 生成 = **1 组 = 3 张图**，对应数据库 `ai_generation_jobs` 的一行：

| 字段 | 说明 |
|------|------|
| `status` | 整组状态（success = 三图全成） |
| `main_status` | 主图状态（顾客选定的发型+颜色） |
| `recommend_1_status` | 推荐图1（同发型+自然黑，交叉推荐） |
| `recommend_2_status` | 推荐图2（商家热门发型+选定颜色，进阶推荐） |
| `internal_api_cost` | 整组实际成本（¥0.444，三张合计） |
| `customer_settle_amount` | 客户应付金额（**目前全是 0，未设置**） |
| `billing_type` | 计费类型（free/gift/paid）|
| `user_id` | 生成的顾客 ID |
| `tenant_id` / `store_id` | 归属的发廊/门店 |

### 目前真实数据

- 共 63 次生成，51 次完整三图成功，12 次失败
- 失败原因：`ALIYUN_HAIR_TRYON_FAILED`（7次）、`IMAGE_GENERATION_FAILED`（5次）
- 失败率 **19%**（偏高，后续需单独排查）
- 所有 job 的 `billing_type` = **free**，`customer_settle_amount` = **0**
- `tenant_ai_package_orders`（次数包销售记录）= **空**
- `tenant_monthly_bills`（月度账单）= **空**
- `package_plans`（套餐产品定义）= **空**
- 初始手动充入 1000 次，已用 50 次，余额 950 次

### 每组图片的具体构成（来自 images_json）

```
slot: main     → 顾客选的发型 + 顾客选的颜色
slot: natural  → 顾客选的发型 + 自然黑（颜色交叉推荐）
slot: advanced → 门店热门发型 + 顾客选的颜色（发型交叉推荐）
```

---

## 二、问题清单 & 修复方案

---

### BUG-01 计费单价写死 ¥1.8，实际应为 ¥2

**影响**：后台展示的收入/毛利数字全都偏低

**位置**：
- `backend/app/main.py` 第 2037 行：`tenant_settle_unit_price: float = 1.8`
- `backend/app/services.py` `platform_billing()` 默认参数 `tenant_settle_unit_price=1.8`

**修复**：
```python
# main.py 和 services.py 均改为
tenant_settle_unit_price: float = 2.0
```

**优先级**：P0

---

### BUG-02 统计接口无时间维度，统计全时段数据

**影响**：`/platform/usage`、`/platform/billing`、`/platform/costs` 返回的是从创建至今的所有数据，无法看"本月""本周""今天"的数字

**位置**：`backend/app/services.py`
- `platform_usage()` 
- `platform_costs()`
- `platform_billing()`
- `platform_overview()`

**修复**：给以上方法加 `month: str | None = None`（格式 `2026-06`）参数，SQL 增加 `AND strftime('%Y-%m', created_at) = ?` 过滤

对应接口也要加 query 参数：
- `GET /platform/usage?tenant_id=1&month=2026-06`
- `GET /platform/billing?tenant_id=1&month=2026-06`
- `GET /platform/overview?month=2026-06`

**优先级**：P0

---

### BUG-03 `customer_settle_amount` 从未被写入

**影响**：每条 job 记录的客户应收金额都是 0，无法从历史记录里还原收入

**原因**：job 入队时字段默认 0，成功后 `_deduct_successful_job()` 不写这个字段

**修复**：在 `_deduct_successful_job()` 成功路径里加一行：
```python
conn.execute(
    "UPDATE ai_generation_jobs SET customer_settle_amount = 2.0 WHERE id = ?",
    (job["id"],),
)
```
注意：金额应从配置读取，而不是硬编码，建议增加 `PLATFORM_AI_SETTLE_PRICE` 环境变量

**优先级**：P1（现在历史数据已经无法追溯，但新数据要开始记录）

---

### BUG-04 充值入口缺失，次数包从未写入

**影响**：给发廊充值只能手动改数据库，`tenant_ai_package_orders` 表一直为空，财务记录缺失

**需要新增（前端）**：
- 在「客户与门店」页每个租户行加「充值」按钮
- 弹窗表单：充值次数（N）、备注（如"首批试用100次"）、收款金额（N × ¥2）
- 调用：`POST /platform/packages`（接口已有，无需改后端）

**请求体**：
```json
{
  "tenant_id": 1,
  "package_name": "首批试用100次",
  "purchased_count": 100,
  "unit_price": 2.0,
  "payment_status": "paid"
}
```

**优先级**：P0（这是收钱的入口）

---

### FEAT-01 新增顾客级生成统计

**需求**：能看到"哪个顾客生成了几组、几张照片"

**数据基础**：`ai_generation_jobs` 已有 `user_id`，可关联 `users.nickname`

**需新增后端接口**：`GET /platform/customer-stats`

**请求参数**：
```
tenant_id     int        必填
period        str        day / week / month / year
date          str        具体日期（day=2026-06-08, week=2026-W23, month=2026-06, year=2026）
store_id      int?       可选，按门店筛选
```

**返回字段**（按顾客聚合）：
```json
[
  {
    "user_id": 10,
    "nickname": "演示顾客",
    "total_sets":    51,   // 发起的组数（每组3张）
    "success_sets":  49,   // 成功完成的组数（计费依据）
    "main_ok":       52,   // 主图成功张数
    "rec1_ok":       52,   // 推荐图1成功张数
    "rec2_ok":       51,   // 推荐图2成功张数
    "total_photos":  155,  // 三者合计
    "cost":          21.8, // 平台成本（¥）
    "revenue":       98.0  // 应收（success_sets × ¥2）
  }
]
```

**优先级**：P1

---

### FEAT-02 新增按时间维度的成本统计接口

**需求**：按年/月/周/日查看生成量、成本、收入趋势，方便管理成本

**需新增后端接口**：`GET /platform/stats/daily`

**请求参数**：
```
tenant_id     int?       可选，不传则全平台汇总
period        str        day / week / month / year
start         str        起始日期，如 2026-06-01
end           str        截止日期，如 2026-06-30
```

**返回示例（按日分组）**：
```json
[
  {
    "period":        "2026-06-01",
    "total_sets":    42,
    "success_sets":  31,
    "failed_sets":   11,
    "main_ok":       32,
    "rec1_ok":       31,
    "rec2_ok":       31,
    "total_photos":  94,
    "cost":          13.78,
    "revenue":       62.0,
    "gross_profit":  48.22,
    "success_rate":  "73.8%"
  },
  ...
]
```

SQL 核心逻辑（按日）：
```sql
SELECT 
    DATE(created_at) AS period,
    COUNT(*) AS total_sets,
    SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_sets,
    SUM(CASE WHEN main_status='success' THEN 1 ELSE 0 END) AS main_ok,
    SUM(CASE WHEN recommend_1_status='success' THEN 1 ELSE 0 END) AS rec1_ok,
    SUM(CASE WHEN recommend_2_status='success' THEN 1 ELSE 0 END) AS rec2_ok,
    ROUND(SUM(internal_api_cost), 3) AS cost
FROM ai_generation_jobs
WHERE tenant_id = ?
  AND DATE(created_at) BETWEEN ? AND ?
GROUP BY DATE(created_at)
ORDER BY period
```

按周改为 `strftime('%Y-W%W', created_at)`，按月改为 `strftime('%Y-%m', created_at)`

**优先级**：P1

---

### FEAT-03 后台新增「用量统计」Tab

**需求**：在平台后台加一个专门的统计页面

**位置**：`admin/index.html` 新增 Tab「用量统计」

**页面包含**：

1. **时间筛选器**：日 / 周 / 月 / 年 切换 + 日期选择器

2. **顶部指标卡（当前选定时段）**：
   - 总发起组数 / 成功组数 / 失败组数 / 成功率
   - 总图片数（组数×3，分主图/推荐各自）
   - 平台成本（¥）/ 应收收入（¥）/ 毛利（¥）/ 毛利率（%）

3. **趋势折线图**（用 Canvas 或简单 SVG）：
   - 每天/每周/每月的成功组数 + 成本曲线

4. **顾客明细表**：
   - 顾客ID、昵称、成功组数、图片数、应收金额

5. **失败原因分布**：
   - `ALIYUN_HAIR_TRYON_FAILED`（目前 7 次）
   - `IMAGE_GENERATION_FAILED`（目前 5 次）

**优先级**：P1

---

### FEAT-04 后台「客户与门店」页补全操作功能

**需求**：现在只能看，不能操作

**需要加的操作**：

| 按钮 | 调用接口 | 说明 |
|------|---------|------|
| 充值次数 | `POST /platform/packages` | 卖次数包或单独充值 |
| 查看详情 | `GET /platform/usage?tenant_id=&month=` | 展开看该租户本月用量 |
| 查看流水 | `GET /platform/packages?tenant_id=` | 该租户的充值历史 |
| 生成账单 | `POST /platform/monthly-bills/generate` | 出月度账单 |

**优先级**：P0（充值）/ P1（其余）

---

### FEAT-05 总览首页改为当月数字

**需求**：首页四个指标卡（租户数、门店数、余额、毛利）改为显示当月而非全时段

**修复**：
- `loadDashboard()` 调用 `/platform/overview?month=2026-06`（自动取当前月）
- 同时展示：本月成功组数、本月收入（¥）、本月成本（¥）、本月毛利（¥）

**依赖**：BUG-02 修复后才能实现

**优先级**：P1

---

### FEAT-08 商家端：余额展示 + 低余额预警（预售提醒）

**需求**：发廊老板能在商家端看到"还剩多少次"，快用完时收到提醒，主动联系续费

**现状**：商家端接口完全没有余额字段。`/merchant/workbench` 和 `/merchant/performance` 只有用了多少次，没有剩多少次。

**修改**：`/merchant/workbench` 返回值增加余额字段：

```python
# 在 merchant_workbench() 返回值里加
"ai_balance": {
    "remaining":       950,    # 剩余次数
    "used_this_month": 51,     # 本月已用
    "low_balance":     False,  # 是否低于预警线（默认 50 次）
    "warning_message": None    # 低余额时提示文案
}
```

SQL：
```sql
-- remaining = total_purchased + total_gifted_adjustment - total_used
SELECT total_purchased + total_gifted_adjustment - total_used AS remaining
FROM tenant_ai_accounts WHERE tenant_id = ?
```

**前端（商家小程序/商家端）**：
- 工作台顶部显示「剩余 AI 次数：950 次」
- 余额 < 50 次时显示黄色警告条：「⚠️ AI 次数仅剩 XX 次，请联系平台续费」
- 余额 < 20 次时显示红色：「🔴 AI 次数即将耗尽，已暂停新顾客使用」

> ⚠️ 商家端**不展示**三张图各自的成功/失败明细，只展示整组成功/失败总数。
> 三张图的失败细节（哪张图、哪个错误码）仅在**平台后台**的生成记录（FEAT-07）里展示，供平台运营排查。

**修改文件**：`backend/app/services.py` → `merchant_workbench()` / `backend/app/main.py`

**优先级**：P0（这是促进预售的关键入口）

---

### FEAT-09 平台管理：月度计费概览（你要向谁收多少钱）

**需求**：后台首页/账单页能一眼看到"这个月每个客户用了多少次、应该收多少钱"

**现状**：`/platform/overview` 和 `/platform/tenant-dashboard` 都是全时段汇总，没有"本月"维度。`/platform/billing` 能算出来但需要手动传 tenant_id 和 month 参数，后台没有聚合展示。

**需新增**：`GET /platform/billing-summary?month=2026-06`

返回（按租户汇总，适合做收费清单）：
```json
{
  "month": "2026-06",
  "unit_price": 2.0,
  "tenants": [
    {
      "tenant_id":      1,
      "tenant_name":    "Demo Hair Chain",
      "success_sets":   51,       // 本月成功组数（计费依据）
      "amount_due":     102.0,    // 应收 = 51 × ¥2
      "api_cost":       22.66,    // 平台成本
      "gross_profit":   79.34,    // 毛利
      "balance_remaining": 950,  // 当前剩余次数
      "balance_warning": false   // 是否需要提醒续费
    }
  ],
  "platform_total": {
    "success_sets":   51,
    "amount_due":     102.0,
    "api_cost":       22.66,
    "gross_profit":   79.34
  }
}
```

**后台展示**（账单/总览 Tab 里）：
```
本月（2026年6月）计费概览                          [生成账单]
─────────────────────────────────────────────
 客户             本月成功组  应收     余额    状态
 Demo Hair Chain    51组     ¥102    950次   ✅正常
─────────────────────────────────────────────
 合计               51组     ¥102   成本¥22.66  毛利¥79.34
```

**修改文件**：新增 `services.py` → `billing_summary(month)` / `main.py` 新增接口 / `admin/index.html` 账单 Tab 改为实时数据

**优先级**：P0（核心收入管理）

---

### FEAT-06 低余额告警

**需求**：某发廊余额 < 50 次时，后台首页出现红色提醒

**实现方式**：
- `loadDashboard()` 拿到 `tenant-dashboard` 数据后，检查 `ai.balance < 50`
- 在总览顶部显示黄色警告条："⚠️ Demo Hair Chain 余额仅剩 XX 次，建议联系续费"

**优先级**：P2

---

## 三、修改文件清单

| 文件 | 改动类型 | 涉及的问题/功能 |
|------|---------|----------------|
| `backend/app/services.py` | 修改 | BUG-01、BUG-02、BUG-03、FEAT-01、FEAT-02 |
| `backend/app/main.py` | 修改 | BUG-01、BUG-02，新增 FEAT-01/02 接口 |
| `backend/.env` | 新增变量 | `PLATFORM_AI_SETTLE_PRICE=2.0` |
| `admin/index.html` | 修改+新增 | BUG-04、FEAT-03、FEAT-04、FEAT-05、FEAT-06 |

---

## 四、执行顺序建议

```
第一批（本次会话）：
  BUG-01  单价 ¥1.8 → ¥2
  BUG-02  统计接口加月份过滤
  FEAT-04 后台加"充值"按钮（P0）
  FEAT-05 总览改为当月数字

第二批：
  BUG-03  customer_settle_amount 开始写入
  FEAT-01 新增顾客级统计接口
  FEAT-02 新增按时间维度统计接口
  FEAT-03 后台新增"用量统计"Tab

第三批：
  FEAT-06 低余额告警
  失败率排查（19% 偏高，需单独看 Dify 日志）
```

---

---

### BUG-05 ⚠️ 图片 URL 有效期仅约 80 分钟，管理后台无法查看历史图片

**影响**：后台「生成记录」里的图片，生成 80 分钟后就无法展示；失败排查时看不到当时的图片

**原因**：生成图片存入阿里云 OSS 时使用临时签名 URL，过期时间约 80 分钟（实测：1780897143 - 1780892409 = 4734 秒）

**修复方案（两选一）**：
- 方案 A（推荐）：成功完成后，后台把 OSS 临时图片复制到**永久存储 bucket**，存永久 URL 到 `images_json`
- 方案 B：将临时 URL 签名有效期从 80 分钟延长到 **7 天**（`expires = now + 604800`）

**优先级**：P1

---

### BUG-06 🔴 阿里云抠发 API 权限未申请，直接导致 7 次失败（失败率最大来源）

**原因**：7 次 `ALIYUN_HAIR_TRYON_FAILED` 都是同一个错误 `InvalidApi.ForbiddenInvoke`：

> 调用受限，请检查您调用的能力是否为受限能力，受限能力需要在控制台 https://vision.console.aliyun.com/ 找到相应能力申请经过审批或者手动激活之后才能调用。

阿里云的**发型分割（SegmentHair）** 接口需要单独申请授权，否则全部返回 400 被拒绝。

**修复**：立即去 https://vision.console.aliyun.com/ → 找到「图像分割」→「头发/发型分割」→ 手动激活

**优先级**：🔴 P0，立即处理，不处理这个失败率没法降

---

**其他失败原因（已从日志提取）**：

| 错误码 | 次数 | 原因 | 修复方式 |
|--------|------|------|---------|
| `InvalidApi.ForbiddenInvoke` | 7 | 抠发 API 权限未激活 | 阿里云控制台激活 |
| `IMAGE_GENERATION_FAILED` | 5 | Dify 工作流内部失败 | 查 Dify 日志 |
| `InvalidFile.Resolution` | 1 | 用户上传图片超过 2000×2000 | 前端上传前压缩图片 |
| `Throttling` | 1 | QPS 超限（当前上限 2）| 申请 QPS 提升，或加重试 |
| `InvalidImage.Region` | 1 | OSS bucket 地区与 imageseg 不匹配 | 确认 OSS bucket 和 imageseg 在同一区域（上海） |

---

### FEAT-07 后台生成记录详情（每组三张图状态 + 图片展示）

**需求**：后台能看到每组生成的详细情况，包括三张图各自成功/失败，以及成功的图片缩略图

**受众**：仅平台管理后台。商家端只展示整组成功/失败总数，不展示单张图明细。

**需新增后端接口**：`GET /platform/jobs`

**请求参数**：
```
tenant_id     int?      可选，不传则全平台
status        str?      success / failed / all
date_from     str?      2026-06-01
date_to       str?      2026-06-08
page          int       分页，默认第1页
page_size     int       默认20
```

**返回字段**（每条 job）：
```json
{
  "job_no":     "AI63D9EAD5315149D7",
  "created_at": "2026-06-07 05:38:52",
  "tenant_id":  1,
  "store_id":   1,
  "user_id":    10,
  "nickname":   "演示顾客",
  "status":     "success",
  "billing_type": "free",
  "internal_api_cost": 0.444,

  "slots": [
    {
      "slot":        "main",
      "label":       "主图",
      "status":      "success",
      "style_name":  "微分碎盖",
      "color_name":  "银灰色",
      "image_url":   "https://...",   // 可能已过期
      "url_expired": false
    },
    {
      "slot":        "natural",
      "label":       "推荐图1（颜色交叉）",
      "status":      "success",
      "style_name":  "微分碎盖",
      "color_name":  "自然黑",
      "image_url":   "https://...",
      "url_expired": false
    },
    {
      "slot":        "advanced",
      "label":       "推荐图2（发型交叉）",
      "status":      "success",
      "style_name":  "美式寸头",
      "color_name":  "银灰色",
      "image_url":   "https://...",
      "url_expired": false
    }
  ],

  "error_code":    null,
  "error_summary": null   // 失败时显示简短原因，不暴露完整堆栈
}
```

**失败 job 的 slots 展示**（all pending）：
```json
"slots": [
  {"slot": "main",     "label": "主图",       "status": "pending", "image_url": null, "error_summary": "抠发API权限未激活"},
  {"slot": "natural",  "label": "推荐图1",    "status": "pending", "image_url": null, "error_summary": "上游失败"},
  {"slot": "advanced", "label": "推荐图2",    "status": "pending", "image_url": null, "error_summary": "上游失败"}
]
```

**后台展示样式**（新增「生成记录」Tab）：

```
┌─────────────────────────────────────────────────────────────────────┐
│ 筛选：[全部状态 ▼] [日期范围] [租户 ▼]        共 63 条 / 第1页     │
├──────────┬──────┬─────┬──────┬────┬────┬────┬──────┬──────────────┤
│ 时间     │ 顾客 │ 状态│ 计费 │ 主图│推1│推2│ 成本 │ 操作         │
├──────────┼──────┼─────┼──────┼────┼────┼────┼──────┼──────────────┤
│ 06-07    │演示  │ ✅  │ 免费 │ ✅ │ ✅│ ✅│¥0.44│ [看图]       │
│ 06-05    │演示  │ ✅  │ 免费 │ ✅ │ ✅│ ✅│¥0.44│ [看图]       │
│ 06-01    │演示  │ ❌  │ 免费 │ ❌ │ ❌│ ❌│¥0.00│ 抠发API权限  │
└──────────┴──────┴─────┴──────┴────┴────┴────┴──────┴──────────────┘

[看图] → 弹窗显示三张缩略图，URL 已过期时显示"图片已过期"占位符
```

**优先级**：P1

---

---

### FEAT-10 商家端新店默认空白，不填充演示数据

**背景**：用户确认商家需要自己填写店铺信息，系统只提供功能框架

**现状问题**：`_default_store_photos()` 在商家没有配置轮播图时，自动填充 Unsplash 演示图片。新商家开通后看到的是别人家的店铺图片。

**修复**：`_default_store_photos()` 改为返回空列表 `[]`，商家端展示"暂未配置，点击添加门店照片"引导文案

**修改文件**：`backend/app/services.py` → `_default_store_photos()` 方法

**优先级**：P1

---

### FEAT-11 门店信息字段扩充（商家可配置）

**背景**：门店目前只有 name / daily_ai_limit / status / store_code，信息太少

**需要增加的字段**（商家端可填写，平台后台可见）：

| 字段 | 说明 |
|------|------|
| `address` | 门店地址（导航用） |
| `phone` | 门店电话 |
| `business_hours` | 营业时间（如 10:00-21:00） |
| `wechat_id` | 商家微信号（顾客联系用） |
| `description` | 门店介绍 |

**同步逻辑**（用户确认要求）：商家在商家端修改以上信息 → 立即同步到 `stores` 表 → 平台后台 `GET /platform/stores` 读到最新数据，无需额外同步机制（单库，天然一致）

**现状**：`StoreHomeConfigPayload` 只有 store_name / home_title / home_subtitle / store_photos，不包含地址电话等基础信息

**修改**：`StoreHomeConfigPayload` 增加上述字段，`stores` 表加列，`update_store_home_config()` 同步写入

**优先级**：P1

---

### FEAT-12 顾客未到店跟进流程

**背景**：用户确认的场景 — 顾客预约后未到店，可通过 AI 对话或微信联系商家，商家可以：
- 赠送免费 AI 次数作为挽回（复用现有 gift 系统）
- 引导顾客自己付费重新预约

**现状缺失**：
- `orders` 没有 `no_show` 状态（只有 pending / completed / cancelled）
- 没有"预约时间已过、顾客未到"的检测机制
- AI 对话（`POST /ai/chat`）和赠送次数（`POST /merchant/ai/gift`）接口都已存在，但没有和预约流程打通

**需要新增**：

1. `orders.status` 加 `no_show` 状态
2. 商家端可手动标记订单为"未到店"
3. 标记后顾客端展示选项：
   - 「联系商家（AI对话）」→ 打开 AI 聊天，知识库里配置"未到店挽回话术"
   - 「微信联系」→ 跳转商家微信 ID（从 FEAT-11 的 wechat_id 字段取）
4. 商家在 AI 对话里可触发赠送 1 次免费 AI（调用 gift 接口）

**修改文件**：
- `backend/app/store.py`：orders 表加状态
- `backend/app/services.py`：加 `mark_order_no_show()` 方法
- `backend/app/main.py`：加 `PUT /merchant/orders/{id}/no-show` 接口
- AI 知识库增加"未到店挽回"分类（merchant 端配置）

**优先级**：P2

---

### FEAT-13 AI 生成等待动画（顾客端前端）

**背景**：用户说"AI生成界面有三条等待信息，你可以把它做成动态动画"

**现状**：后端已有 `status` 字段（queued → running → success），`queue_position` 和 `queue_wait_seconds`，顾客端轮询 `GET /ai/style/jobs/{job_no}` 获取进度

**后端已有**（无需改动）：
```json
{
  "status": "running",
  "queue_position": 0,
  "queue_wait_seconds": 2,
  "main_status": "success",
  "recommend_1_status": "pending",
  "recommend_2_status": "pending"
}
```

**前端需要改动**（顾客小程序）：

三个阶段对应三条等待信息，改为逐步点亮的动画：

```
阶段1（queued）：   ⏳ 正在分析您的脸型...        ← 动画中
                    ○ AI 正在生成主效果图...         ← 未开始（灰色）
                    ○ 智能推荐两款搭配方案...        ← 未开始（灰色）

阶段2（running，main pending）：
                    ✅ 脸型分析完成                  ← 已完成（绿色）
                    ⏳ AI 正在生成主效果图...  ← 动画中
                    ○ 智能推荐两款搭配方案...        ← 未开始

阶段3（main_status=success，recommend pending）：
                    ✅ 脸型分析完成
                    ✅ 主效果图生成完成
                    ⏳ 智能推荐两款搭配方案...  ← 动画中
```

动画效果：未完成的条目显示省略号滚动（...）或呼吸灯效果

**修改文件**：顾客端小程序 AI 生成结果页（前端）

**优先级**：P1

---

### 已确认功能（不需要开发，已存在）

| 功能 | 代码位置 | 说明 |
|------|---------|------|
| 提醒顾客保存照片 | `services.py` `_public_generation_result()` 里 `save_hint: "长按保存或截图，图片仅临时展示"` | ✅ 已有 |
| AI 生成后直接预约 | `orders` 表 `is_ai_converted=1` + `POST /orders` | ✅ 已有 |
| 不经过 AI 直接预约 | `orders` 表 `is_ai_converted=0` | ✅ 已有 |
| 微信支付接口预留 | `payments.py` MockPaymentProvider，接口签名完整 | ✅ 已预留 |
| 商家修改店铺同步平台 | 单库，`update_store_home_config()` 写 `stores` 表，平台读同一张表 | ✅ 天然同步 |
| 不存储顾客照片 | OSS 临时 URL，后端不持久化原图 | ✅ 已有 |

---

## 五、遗留问题（不在本次范围）

- **微信支付**：目前 mock，`billing_type=paid`（顾客直接付钱）路径未测试
- **Feishu 同步**：目前 mock，报表无法推到飞书
- **历史数据**：已生成的 51 组 job 的 `customer_settle_amount` 均为 0，历史收入无法回溯
- **SQLite → MySQL 迁移**：MySQL 容器已在运行，但后端仍接 SQLite
