# 美发AI小程序 云服务器+Dify工作流 AI执行落地书

版本：v1.0  
日期：2026-05-25  
目标：指导AI从零搭建可落地项目，包括云服务器、Dify工作流、后端API、微信小程序、飞书统计、验证与上线。  
当前产品定位：面向多个美发连锁客户的SaaS产品，不是单客户一次性定制项目。

---

## 0. AI执行总原则

本文件是后续AI开发和部署的最高执行依据。任何AI开始写代码、部署服务器、搭建Dify工作流、小程序页面或飞书同步前，必须先读取本文件。

### 0.1 不允许偏离的核心产品逻辑

当前项目已敲定为：

1. 顾客可到店扫码或自行打开微信小程序。
2. 顾客微信手机号登录。
3. 顾客进入AI造型。
4. 顾客选择造型方向：女性、男性、中性。
5. 顾客选择发型、发色，或只选发型，或只选发色。
6. 顾客自拍或上传照片。
7. 系统通过Dify工作流调用通义万相图像编辑能力，在用户原自拍上生成3张图。
8. 3张图包括：1张用户自选方案、2张系统推荐方案。
9. 3张图都基于用户自拍生成。
10. 结果页横向滑动查看3张图，展示方案信息、商家可编辑标签、3位推荐主理人、下单按钮。
11. 点开大图时只显示AI生成图，右下角客户LOGO水印。
12. 平台不保存顾客自拍，不保存AI生成图，只临时展示。
13. 用户长按保存或截图，退出后不可找回。
14. 服务订单到店支付。
15. AI试发可免费、赠送或付费。
16. MySQL是主数据库，飞书是统计看板。

### 0.2 本项目不再使用的旧策略

以下旧设想不得继续作为主方案：

1. 主图Face++、推荐图阿里的混合模型策略。
2. Face++人脸融合接口作为主图生成核心能力。
3. 纯问答式AI推荐作为顾客主入口。
4. 飞书作为核心业务主数据库。
5. 保存顾客生成图到用户档案。

当前统一策略：

```text
主图、推荐图1、推荐图2均使用通义万相图像编辑/图生图能力。
Dify负责编排工作流、固定提示词、调用模型/API、固定输出JSON。
```

### 0.3 AI执行五问

每次修改、部署、配置前必须自检：

1. 是否遵守“不保存顾客自拍和生成图”的规则？
2. 是否所有数据都带 `tenant_id` 和必要的 `store_id`？
3. 是否区分客户视图和平台内部视图，避免暴露真实API成本？
4. 是否所有推荐都来自商家库，不让AI凭空编造发型、发色、主理人？
5. 是否写了可验证的接口、数据、权限、生成、同步测试？

如果任意答案不确定，停止执行，先补充验证。

---

## 1. 总体架构

### 1.1 系统组成

```text
微信小程序
  ↓
FastAPI后端
  ↓
MySQL主数据库
Redis缓存/队列
Dify工作流服务
阿里云百炼/通义万相图像编辑
飞书多维表格统计看板
OSS临时文件/短期缓存，或等价临时对象存储
```

### 1.2 数据主从关系

```text
小程序业务操作
→ FastAPI
→ MySQL主数据库
→ 同步到飞书
→ 飞书做统计和看板
```

原则：

1. MySQL是唯一主数据库。
2. 飞书只做统计展示和报表，不做核心业务操作入口。
3. 小程序所有业务操作必须先写MySQL。
4. 飞书同步失败不得影响小程序使用。
5. 飞书同步失败进入重试队列。

### 1.3 多客户SaaS架构

项目不是单客户定制，必须支持多客户。

核心概念：

```text
tenant_id = 客户/品牌/公司ID
store_id = 门店ID
```

所有核心表必须带 `tenant_id`。门店相关表必须同时带 `store_id`。

示例：

```text
平台方
  ├─ 客户A tenant_a
  │   ├─ 门店 store_001
  │   └─ 门店 store_002
  └─ 客户B tenant_b
      ├─ 门店 store_101
      └─ 门店 store_102
```

### 1.4 可分店售卖的产品拆分

本项目必须设计成可复制销售的SaaS产品，而不是为单个客户单独部署一套代码。

销售和开通层级：

```text
平台方，也就是系统所有者
→ 客户/品牌 tenant
→ 门店 store
→ 员工/主理人 staff
→ 顾客 customer
```

售卖方式建议：

1. 按客户开通租户。
2. 按门店开通使用权限。
3. 按AI试发次数包或月度额度收费。
4. 超出额度按次结算。
5. 进阶功能，如AI自动标签、批量上架、AI客服、飞书高级看板，可按套餐开通。

示例：

```text
客户A购买连锁版
包含15家门店
包含每月10000次AI试发
超出按平台配置单价结算
```

必须支持：

1. 一个客户多个门店。
2. 一个门店多个主理人。
3. 每个门店独立二维码。
4. 每个门店独立AI每日上限。
5. 每个客户独立品牌LOGO和小程序展示信息。
6. 每个客户只能看到自己的数据。
7. 平台方可以看到所有客户和所有门店。

### 1.5 平台后台定位

平台后台是系统所有者使用的管理后台，不是门店员工使用的小程序商家端。

平台后台必须管理：

1. 客户管理。
2. 门店管理。
3. 套餐管理。
4. AI额度管理。
5. API密钥管理。
6. AI成本和使用量。
7. 客户账单。
8. 飞书同步配置。
9. 异常和风控。

第一阶段可以先做简洁管理后台，不追求复杂UI，但必须能看清：

```text
谁在用
用了多少
还剩多少
该收多少钱
真实成本是多少
平台毛利是多少
是否有异常刷量或失败率过高
```

平台后台和小程序商家端分工：

```text
小程序商家端 = 门店现场操作台
飞书 = 客户和平台统计看板
平台后台 = 平台方管理客户、套餐、额度、密钥、账单和真实成本
```

### 1.6 平台后台模块

#### 1.6.1 客户管理

字段：

```text
tenant_id
客户名称
品牌名称
品牌LOGO
联系人
联系电话
套餐版本
开通时间
到期时间
状态：启用/暂停/到期
绑定小程序AppID
绑定飞书配置
```

功能：

1. 新增客户。
2. 暂停客户。
3. 修改客户套餐。
4. 查看客户所有门店。
5. 查看客户AI使用和账单。

#### 1.6.2 门店管理

字段：

```text
store_id
tenant_id
门店名称
门店地址
联系电话
店长账号
门店二维码
每日AI生成上限
门店状态
```

功能：

1. 新增门店。
2. 生成门店二维码。
3. 配置门店AI每日上限。
4. 暂停门店。
5. 查看门店使用量。

#### 1.6.3 套餐管理

套餐必须可配置，不要写死在代码中。

字段：

```text
套餐名称
月服务费
包含门店数
包含AI试发次数
超额单价
是否开通AI自动标签
是否开通AI客服
是否开通飞书高级统计
是否开通多门店老板视图
```

建议套餐类型：

```text
门店版
智能运营版
连锁增长版
```

注意：

```text
具体价格暂不写死，因为真实API成本还需POC验证。
```

#### 1.6.4 AI额度管理

平台后台必须能按客户和门店查看：

```text
套餐内额度
已用次数
剩余次数
免费次数
赠送次数
付费次数
超额次数
本月预计应收
```

规则：

1. 一次AI试发 = 生成3张图。
2. 只按成功任务扣次数。
3. 失败和超时不扣次数。
4. 付费成功但生成失败，允许免费重试一次。

AI次数包售卖规则：

1. 平台方可以按AI试发次数包卖给客户，次数包是本产品的重要盈利方式。
2. 客户购买次数包后，形成客户级AI额度池。
3. 第一版建议采用客户级共享额度池，15家门店共用，但每家门店仍可单独设置每日上限。
4. 所有成功AI试发任务都从客户AI额度池扣1次，包括到店免费、员工赠送、顾客付费、后台补偿。
5. 失败、超时、取消任务不扣客户额度。
6. 客户向顾客收费的AI试发价格由客户自行配置，平台只记录客户收款金额，不参与门店现场服务收款。
7. 平台向客户结算的是AI次数包价格或超额单价，不向客户暴露真实通义万相API成本。
8. 客户可以通过顾客付费试发、AI转烫染护理订单、主理人推荐转化赚取收益。
9. 平台可以通过次数包售价和真实API成本之间的差价赚钱。
10. 平台后台必须同时统计客户余额、客户AI收入、平台真实成本、平台毛利，但客户老板端只能看到客户自己的经营数据和平台结算价。

建议次数包类型：

```text
体验包：用于新客户试用，小额度，便于成交。
门店运营包：适合单店或小连锁，按月购买。
连锁共享包：适合15家门店这类客户，多门店共享额度池。
大客户预充值包：一次购买更多次数，单次结算价更低。
```

客户收益逻辑：

```text
客户购买平台AI次数包
→ 到店顾客每天免费2次，提升体验和转化
→ 免费用完后顾客可付费继续试发
→ 店员可赠送1次推动成交
→ 顾客看到效果后下单到店支付
→ 客户赚AI付费收入和美发服务收入
→ 平台赚AI次数包差价和后续套餐服务费
```

#### 1.6.5 API成本管理

平台内部可见，客户不可见。

必须统计：

```text
通义万相调用次数
成功次数
失败次数
真实API成本
平均单次成本
Dify工作流调用次数
平均生成耗时
失败率
重试率
```

客户老板端只能看到：

```text
AI服务成本，也就是平台卖给客户的结算价
```

客户不可见：

```text
真实API成本
底层模型供应商成本
平台毛利
```

#### 1.6.6 账单管理

每月按客户生成账单。

账单字段：

```text
客户
月份
套餐费用
套餐内AI额度
实际使用次数
超额次数
超额单价
本月应收
真实API成本，平台内部可见
平台毛利，平台内部可见
账单状态：待确认/已出账/已收款/逾期
```

客户账单视图不得显示真实API成本和平台毛利。

#### 1.6.7 飞书配置管理

平台后台需要为每个客户配置飞书同步：

```text
飞书AppID
飞书AppSecret
多维表格AppToken
客户视图表ID
平台内部表ID
同步状态
最后同步时间
```

如果客户没有自己的飞书空间，平台可使用统一飞书空间并按客户建立独立表或独立视图。

#### 1.6.8 异常和风控

平台后台必须展示：

```text
高频用户
高频设备
高频门店
失败率异常
排队时间异常
赠送次数异常
付费失败异常
单客户AI消耗异常
```

风控操作：

1. 暂停某个用户AI生成。
2. 暂停某个门店AI生成。
3. 调整门店每日上限。
4. 调整租户并发或日限额。
5. 查看异常明细。

### 1.7 API密钥管理策略

默认策略：

```text
平台统一持有和管理Dify、通义万相、OSS、飞书、微信等API密钥。
客户按AI试发次数或套餐向平台购买服务。
```

不建议第一阶段让客户自带API Key，因为：

1. 客户配置复杂。
2. 售后成本高。
3. 不利于平台按AI次数包盈利。
4. 不利于统一风控和成本统计。

高级企业定制可选：

```text
客户自带阿里云/百炼/API密钥
```

但必须作为企业定制能力，不作为默认能力。

密钥保存规则：

1. 密钥不得写入前端小程序。
2. 密钥不得写入代码仓库。
3. 密钥必须存储在服务端环境变量或加密配置表中。
4. 后台页面不得明文展示完整密钥。
5. 后台只显示：已配置、未配置、最后更新时间。
6. 密钥更新必须记录操作人和时间。

建议表：

```sql
CREATE TABLE platform_secrets (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT,
  secret_type VARCHAR(50) NOT NULL,
  secret_name VARCHAR(100) NOT NULL,
  encrypted_value TEXT NOT NULL,
  status ENUM('active','disabled') DEFAULT 'active',
  updated_by BIGINT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

`tenant_id` 为空表示平台统一密钥。  
`tenant_id` 不为空表示某个企业客户自带密钥。

### 1.8 Dify多客户使用规则

第一阶段建议：

```text
一个平台Dify
多个工作流
后端通过tenant_id/store_id隔离数据
```

后端调用Dify时必须传：

```json
{
  "tenant_id": "tenant_001",
  "store_id": "store_001",
  "user_id": 123
}
```

隔离原则：

1. Dify不直接跨客户查数据库。
2. 后端先按 `tenant_id`、`store_id` 筛选商家库候选。
3. Dify只在后端传入的候选发型、发色、主理人中选择。
4. Dify输出必须回到后端校验。
5. 后端校验不通过，不返回给小程序。

### 1.9 临时图片存储与OSS规则

后端必须提供统一的临时图片存储适配层，微信小程序不能直接持有 OSS、通义万相、Dify 等平台密钥。

第一版实现规则：
1. POC/客户展示阶段使用 `TEMP_STORAGE_PROVIDER=mock`。
2. 正式MVP使用 `TEMP_STORAGE_PROVIDER=aliyun_oss`。
3. 自拍上传先由后端生成短期 `upload_url`。
4. 小程序上传成功后，只把 `photo_temp_url` 传给生成接口。
5. `photo_temp_url` 不写入 `ai_generation_jobs`，只在本次 Dify 工作流调用期间传递。
6. OSS object key 必须包含 `tenant_id/store_id/user_id` 路径，例如 `temp/1/1/1/xxx.jpg`。
7. 临时图片必须短 TTL，过期后不可访问。
8. 平台不长期保存顾客自拍和AI生成图。
9. 后端 `/health` 必须能显示当前临时存储 provider，避免生产环境误用 Mock。

### 1.10 AI试发支付Provider规则

AI试发付费是独立支付流程，和到店服务订单支付分开。

第一版实现规则：
1. POC/客户展示阶段使用 `PAYMENT_PROVIDER=mock`。
2. 商业MVP上线收费前必须切换真实微信支付 Provider。
3. `/ai/pay/create` 必须能创建待支付订单，并返回小程序端可调用 `wx.requestPayment` 的支付参数结构。
4. 支付回调必须由后端验签后更新 `ai_payment_orders`。
5. 付费成功但AI生成失败，允许免费重试一次。
6. 同一个支付单首次生成失败、超时或取消后，只允许绑定一次免费重试任务。
7. 支付单首次任务成功、排队中或运行中时，不允许重复创建生成任务。
8. 服务订单仍然到店支付，不在小程序内支付美发服务费。
9. 后端 `/health` 必须能显示当前 payment provider，避免生产环境误用 Mock。

### 1.11 飞书统计同步Provider规则

飞书统计是异步辅助能力，不能影响顾客生成、下单、商家接单等主流程。

第一版实现规则：
1. POC/客户展示阶段使用 `FEISHU_SYNC_PROVIDER=mock`。
2. 正式MVP可使用 `FEISHU_SYNC_PROVIDER=feishu_webhook` 或后续开放平台应用。
3. 业务事件先写入 `sync_events`。
4. `/sync/feishu/retry` 或后台定时任务负责推送飞书。
5. 飞书同步成功，事件状态改为 `synced`。
6. 飞书同步失败，事件状态改为 `failed` 并记录 `last_error`。
7. 飞书同步失败不得回滚AI生成、扣次、下单、服务完成等主流程。
8. 飞书同步的“排队时长”和“生成耗时”必须来自 `ai_generation_jobs.queue_wait_seconds` 与 `ai_generation_jobs.generate_duration_seconds`。

### 1.12 上线安全检查规则

系统必须提供上线安全检查接口，避免客户已经付费上线但底层仍使用 Mock 能力。

第一版实现规则：
1. 后端提供 `/platform/deployment-readiness`。
2. 接口必须返回当前 `dify`、`temp_storage`、`payment`、`feishu` Provider。
3. `APP_ENV=production` 时，如果 Dify、临时存储、支付仍为 Mock，必须返回 blockers。
4. 本地/展示环境允许 Mock，但必须返回 warnings。
5. 飞书 Mock 不阻断生产主流程，但必须给出 warning。
6. 正式收费上线前，平台方必须确认 `ready_for_production=true`。

### 1.13 到店扫码免费资格规则

为防止顾客不在店里或同行恶意白嫖 AI 试发，免费AI试发必须绑定门店扫码会话。

第一版实现规则：
1. 每个门店有独立二维码。
2. 顾客扫码后调用 `/stores/scan-qr`。
3. 后端创建 `store_visit_sessions` 到店会话。
4. 到店会话默认有效期 8 小时。
5. `billing_type=free` 的 AI 生成必须存在有效到店会话。
6. 不在店顾客仍可使用 AI 试发，但必须走付费或商家赠送。
7. 店员赠送次数不要求到店扫码，但必须记录赠送人并统计转化率。
8. 到店扫码免费生成成功后，仍然从客户AI额度池扣1次。
9. 顾客使用赠送AI试发后下单，赠送记录必须绑定订单ID。
10. 赠送AI试发转化成完成服务后，赠送记录必须记录成交金额。
11. 商家端必须能按门店和主理人查看赠送数、使用数、下单数、成交数、成交金额和转化率。

### 1.13.1 AI结果页展示规则

结果页必须适配顾客端小样的滑动体验。

第一版规则：
1. 生成成功后返回3张图：用户选择方案1张、AI推荐方案2张。
2. 前端通过横向滑动查看，不使用上一张/下一张按钮。
3. 推荐主理人最多3位。
4. 默认第一位为最匹配主理人。
5. 下单按钮文案使用“下单”。
6. 图片只临时展示，提示用户长按保存或截图。
7. 顾客视图不得返回平台真实API成本。
8. 结果页可展示商家可编辑标签，如是否需烫、是否需漂。

### 1.14 商家端订单流转规则

商家端订单状态必须支持门店真实接待流程。

第一版实现规则：
1. 顾客下单后订单状态为 `pending`。
2. 店长/前台可将订单改为 `confirmed`。
3. 顾客到店后可改为 `arrived`。
4. 开始服务时改为 `serving`，且必须已有主理人。
5. 服务完成必须调用完成服务接口，写入服务项目和实际成交金额。
6. `completed` 和 `cancelled` 是终态，不允许继续修改。
7. 主理人可在订单未完成/未取消前重新分配。
8. 订单读取和修改必须受 `tenant_id + store_id + order_id` 隔离。
9. 商家端订单页必须支持按门店查看订单列表。
10. 订单列表必须支持按订单状态、主理人筛选。
11. 订单列表必须返回顾客展示信息和主理人展示名，便于前台快速接待。
12. 订单列表必须受 `tenant_id + store_id` 隔离，客户A不能看到客户B订单。

### 1.15 商家图库维护规则

商家端必须支持维护自己的发型、发色素材库，供顾客浏览、AI生成和推荐方案使用。

发型字段：
1. 名称。
2. 所属方向：男性/女性/中性。
3. 发长：短发/中发/长发。
4. 缩略图。
5. `style_id`。
6. 展示标签。
7. 是否启用。
8. 是否推荐。
9. 是否需要烫发。

发色字段：
1. 名称。
2. 所属方向：男性/女性/中性。
3. 色卡。
4. `color_id`。
5. 展示标签。
6. 是否启用。
7. 是否推荐。
8. 是否需要漂。

规则：
1. 商家可手动增加展示标签。
2. 进阶套餐可通过 AI 自动生成标签，商家确认后入库。
3. 未启用素材不得出现在顾客端选择列表。
4. Dify 只能在后端传入的已启用素材中选择，不允许编造发型/发色ID。
5. 商家可编辑素材名称、标签、推荐状态、启用状态、是否需烫/漂。
6. 素材下架后不进入顾客选择列表，但历史订单/生成记录不删除。
7. 顾客端发型灵感页必须支持热门、长发、中发、短发、发色分组。
8. 热门来自商家标记的推荐素材。

### 1.16 平台按门店开通规则

平台后台必须支持把产品拆分成可按客户、按门店售卖的 SaaS 能力。

第一版实现规则：
1. 平台可创建客户 `tenant`。
2. 平台可在客户下创建多个门店 `store`。
3. 同一个客户下 `store_code` 不允许重复。
4. 每个门店可配置 `daily_ai_limit`。
5. 每个门店后续对应独立二维码和独立数据统计。
6. 客户AI额度池第一版按客户共享，门店通过每日上限做风控。

### 1.17 主理人维护规则

商家端必须支持维护主理人档案，供推荐、预约、业绩统计和赠送AI次数使用。

第一版字段：
1. 微信 openid。
2. 手机号。
3. 展示名称。
4. 职级/头衔。
5. 头像。
6. 擅长方向：男性/女性/中性。
7. 擅长标签。
8. 在店状态：available/busy/offline。
9. 是否启用。
10. 是否推荐。
11. 排序。

规则：
1. 主理人必须归属某个租户和门店。
2. 主理人推荐只从启用且可服务的主理人中选择。
3. 店长/老板可维护主理人在不在店状态。
4. 主理人赠送AI次数、订单转化、服务成交必须能归因到具体主理人。
5. 店长/老板可编辑主理人展示名称、手机号、职级、头像、擅长方向、擅长标签、排序、是否启用、是否推荐。
6. 主理人停用后不得出现在顾客推荐结果里，但历史订单和业绩统计保留。

### 1.18 API密钥配置管理规则

平台后台必须支持管理供应商密钥配置，但绝不允许前端小程序接触密钥。

第一版实现规则：
1. 支持平台统一密钥：`tenant_id = null`。
2. 预留客户自带密钥：`tenant_id != null`。
3. 支持 provider：Dify、通义/百炼、OSS、微信支付、飞书。
4. 密钥写入后，接口只返回 `masked_secret` 和 `secret_fingerprint`。
5. 列表接口不得返回明文密钥，也不得返回密文字段。
6. 同一 `tenant_id + provider + key_name` 重复提交时更新原配置，不新增重复配置。
7. 密钥更新必须记录操作人 `updated_by_user_id` 和更新时间。
8. 正式生产环境必须使用更强的密钥管理方式，如 KMS 或云厂商密钥管理服务。

### 1.19 套餐版本配置规则

套餐必须可配置，不能写死在代码里。

第一版套餐字段：
1. 套餐编码 `plan_code`。
2. 套餐名称。
3. 月费。
4. 套餐内AI额度。
5. 可开通门店数上限。
6. 进阶功能列表，如 AI自动标签、飞书高级看板、AI客服。
7. 状态：active/disabled。

规则：
1. 平台可新增或更新套餐。
2. 同一 `plan_code` 重复提交时更新原套餐。
3. 客户可绑定套餐编码。
4. AI次数包仍作为套餐外增购项单独销售。

### 1.20 月度账单生成规则

平台后台必须能按客户和月份生成账单，用于对账和收费。

第一版账单字段：
1. 客户ID。
2. 账单月份。
3. 客户套餐。
4. 套餐费用。
5. 套餐内AI额度。
6. 当月额外购买AI次数。
7. 当月成功AI使用次数。
8. 超额AI使用次数。
9. 客户结算单价。
10. 超额AI费用。
11. 总账单金额。
12. 账单状态：draft/issued/paid/overdue。

平台内部可见字段：
1. 真实API成本。
2. 平台毛利。

客户/商家可见规则：
1. 不得显示真实API成本。
2. 不得显示平台毛利。
3. 只显示客户应付金额、套餐、额度、使用量和账单状态。
4. 平台后台可更新账单状态：draft、issued、paid、overdue。
5. 更新账单状态必须校验租户归属，客户A的账单不能被客户B接口修改。

### 1.21 AI额度补偿与人工调账规则

平台后台必须支持补偿客户AI额度和人工修正额度，但不能直接手改余额。

第一版实现规则：
1. 补偿和人工调账统一写入 `tenant_ai_usage_logs`。
2. 支持 `usage_type=compensate`。
3. 支持 `usage_type=admin_adjust`。
4. `change_count` 可正可负，但不能为0。
5. 调账后客户AI余额不得小于0。
6. 必须记录 `remark`。
7. 必须记录操作人 `user_id`。
8. `tenant_ai_accounts` 仍然不保存 `remaining_balance`，余额实时计算。

### 1.22 客户与门店配置更新规则

平台后台必须支持客户和门店上线后的配置调整。

客户可调整字段：
1. 品牌名称。
2. LOGO。
3. 套餐版本。
4. 状态：active/disabled。

门店可调整字段：
1. 门店名称。
2. 每日AI上限。
3. 状态：active/disabled。

规则：
1. 客户禁用后，后续应阻止该客户新增业务操作。
2. 门店禁用后，后续应阻止扫码、生成、下单等门店业务。
3. 套餐切换必须校验套餐存在。
4. 门店每日AI上限不能为负数。

### 1.23 AI客服知识库规则

AI客服必须优先基于商家维护的知识库回答，不能编造价格、服务承诺或主理人信息。

第一版字段：
1. 客户ID。
2. 门店ID，可为空表示客户通用知识。
3. 分类。
4. 问题。
5. 答案。
6. 关键词。
7. 是否启用。
8. 排序。

规则：
1. 商家可维护门店级和客户级知识。
2. 顾客咨询先匹配知识库。
3. 匹配不到时，再走固定业务意图：价格、AI试发、预约/下单。
4. 仍无法回答时，引导联系门店。
5. AI客服不得编造不在系统内的价格、折扣、主理人或承诺。
6. 商家可编辑知识库分类、问题、答案、关键词、启用状态和排序。
7. 停用的知识库内容不得被顾客AI咨询命中，但商家后台可查看历史配置。

### 1.24 商家业绩统计规则

商家端必须支持老板、店长、主理人查看不同范围的业绩。

第一版统计维度：
1. 总完成服务数。
2. 总成交金额。
3. AI转化服务数。
4. AI转化成交金额。
5. 按门店统计。
6. 按主理人统计。
7. 按服务项目/服务类型统计，如美发、染发、造型、护理。

规则：
1. 老板可看客户下全部门店。
2. 店长/前台看本店。
3. 主理人看本人。
4. 服务项目类别由商家维护，不写死。
5. AI转化数据来自订单和服务记录的 `is_ai_converted` 字段。

### 1.25 服务项目维护规则

商家端必须支持维护服务项目，服务维度不能写死。

第一版字段：
1. 名称。
2. 类型/分类，如 haircut/color/perm/styling/care。
3. 参考价格。
4. 是否启用。
5. 排序。
6. 适用门店，可为空表示客户通用。

规则：
1. 商家可新增服务项目。
2. 商家可编辑服务项目。
3. 商家可停用服务项目，停用后不进入下单/完成服务选择。
4. 历史服务记录保留原成交数据，不因服务项目停用而删除。

### 1.26 POC效果评测记录规则

POC阶段不能只凭主观感觉判断“效果还行”，必须把每次AI试发的效果、速度、成本结构化记录下来，作为是否进入MVP开发和套餐定价的依据。

第一版字段：
1. 测试编号。
2. 客户ID。
3. 性别方向：男性、女性、中性。
4. 生成类型：只换发型、只换发色、发型+发色。
5. 主图是否调用成功。
6. 推荐图是否调用成功。
7. 是否像本人。
8. 是否只改头发。
9. 是否保留五官、脸型、服装和背景。
10. 生成耗时秒数。
11. 排队时长秒数。
12. 单次真实API成本。
13. 人工验收结论：pass/fail。
14. 失败原因。

规则：
1. 男性、女性、中性都必须覆盖。
2. 只换发型、只换发色、发型+发色都必须覆盖。
3. 平台后台必须能录入POC评测结果。
4. 平台后台必须能汇总POC通过率、平均耗时、平均成本。
5. POC未达到可接受效果和成本前，不进入正式商业MVP上线。
6. POC记录只用于内部验证和成本测算，不展示给顾客。

后续当客户数量大、隔离要求高时，可以升级为：

```text
重点客户独立Dify空间或独立Dify实例
```

但MVP不需要一开始就这么复杂。

---

## 2. 服务器部署方案

### 2.1 推荐服务器

第一阶段测试/单客户试点：

```text
CPU：8核
内存：32GB
硬盘：200GB SSD
系统：Ubuntu 22.04 LTS
带宽：10Mbps+
```

如果预算有限，16GB可做测试，但不建议作为15店正式生产配置。

### 2.2 生产建议拆分

MVP可先单机部署：

```text
Nginx
FastAPI
MySQL
Redis
Dify Docker
同步任务
```

正式多客户SaaS建议逐步拆分：

```text
应用服务器：FastAPI + Nginx
AI工作流服务器：Dify
数据库：云MySQL或独立MySQL
缓存队列：Redis
文件：OSS临时存储
统计：飞书
```

### 2.3 域名规划

建议：

```text
api.yourdomain.com        后端API
dify.yourdomain.com       Dify管理后台
admin.yourdomain.com      平台后台，后续
```

微信小程序生产环境必须使用HTTPS域名。

### 2.4 Dify部署

按Dify官方Docker Compose自托管方式部署。

执行要点：

1. 使用官方Docker Compose部署。
2. 配置Dify域名和HTTPS。
3. 配置Dify环境变量。
4. 配置模型供应商：阿里云百炼/通义千问/通义万相。
5. 不把Dify API Key放到微信小程序端。
6. 后端FastAPI代理调用Dify。

参考命令结构：

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker compose up -d
```

部署后必须验证：

```bash
docker compose ps
curl https://dify.yourdomain.com
```

---

## 3. Dify工作流设计

### 3.1 工作流列表

第一阶段必须搭建以下工作流：

```text
WF-01 AI试发生成工作流
WF-02 推荐方案选择工作流
WF-03 主理人推荐工作流
WF-04 AI客服工作流
WF-05 AI自动标签工作流，进阶套餐
```

### 3.2 WF-01 AI试发生成工作流

目标：

基于用户自拍、用户选择、推荐方案，调用通义万相生成3张图。

输入：

```json
{
  "tenant_id": "tenant_001",
  "store_id": "store_001",
  "user_id": 123,
  "direction": "male",
  "photo_temp_url": "https://temporary-object-url",
  "main_style": {
    "style_id": "style_001",
    "style_name": "商务侧分"
  },
  "main_color": {
    "color_id": "color_001",
    "color_name": "冷棕色"
  },
  "recommendations": [
    {
      "type": "natural",
      "style_id": "style_002",
      "style_name": "纹理短发",
      "color_id": "color_001",
      "color_name": "冷棕色"
    },
    {
      "type": "advanced",
      "style_id": "style_001",
      "style_name": "商务侧分",
      "color_id": "color_002",
      "color_name": "黑茶色"
    }
  ]
}
```

输出必须固定为：

```json
{
  "job_no": "AI202605250001",
  "status": "success",
  "images": [
    {
      "slot": "main",
      "title": "你选择的方案",
      "direction": "male",
      "style_id": "style_001",
      "style_name": "商务侧分",
      "color_id": "color_001",
      "color_name": "冷棕色",
      "temp_image_url": "https://temporary-result-url-1"
    },
    {
      "slot": "natural",
      "title": "自然推荐",
      "direction": "male",
      "style_id": "style_002",
      "style_name": "纹理短发",
      "color_id": "color_001",
      "color_name": "冷棕色",
      "temp_image_url": "https://temporary-result-url-2"
    },
    {
      "slot": "advanced",
      "title": "进阶推荐",
      "direction": "male",
      "style_id": "style_001",
      "style_name": "商务侧分",
      "color_id": "color_002",
      "color_name": "黑茶色",
      "temp_image_url": "https://temporary-result-url-3"
    }
  ]
}
```

生成提示词要求：

```text
在用户原自拍上进行真实自然的发型/发色编辑。
保留用户五官、脸型、表情、肤色、服装和背景。
只修改头发区域。
不要改变人物身份。
不要把人物变成模特。
不要改变性别特征。
根据指定发型和发色生成真实沙龙效果。
画面应自然、真实、适合微信小程序展示。
```

失败输出：

```json
{
  "job_no": "AI202605250001",
  "status": "failed",
  "error_code": "IMAGE_GENERATION_FAILED",
  "error_message": "推荐图生成失败"
}
```

扣费规则：

```text
三张图全部成功才扣1次。
任意失败或超时不扣次数。
```

### 3.3 WF-02 推荐方案选择工作流

目标：

从商家库中为用户选择2个推荐方案。

输入：

```json
{
  "tenant_id": "tenant_001",
  "store_id": "store_001",
  "direction": "female",
  "selected_style_id": "style_010",
  "selected_color_id": "color_003",
  "candidate_styles": [
    {
      "style_id": "style_010",
      "style_name": "韩系中长发",
      "direction": "female",
      "hair_length": "medium",
      "tags": ["韩系", "自然", "修饰脸型"],
      "need_perm": true,
      "is_recommended": true,
      "sort_order": 10
    },
    {
      "style_id": "style_011",
      "style_name": "纹理短发",
      "direction": "female",
      "hair_length": "short",
      "tags": ["清爽", "日系", "减龄"],
      "need_perm": false,
      "is_recommended": true,
      "sort_order": 20
    },
    {
      "style_id": "style_012",
      "style_name": "空气刘海锁骨发",
      "direction": "female",
      "hair_length": "medium",
      "tags": ["甜美", "中发", "显脸小"],
      "need_perm": true,
      "is_recommended": true,
      "sort_order": 30
    }
  ],
  "candidate_colors": [
    {
      "color_id": "color_003",
      "color_name": "冷棕色",
      "direction": "female",
      "tags": ["自然", "显白", "低调"],
      "need_bleach": false,
      "is_recommended": true,
      "sort_order": 10
    },
    {
      "color_id": "color_004",
      "color_name": "黑茶色",
      "direction": "female",
      "tags": ["通勤", "质感", "不挑肤色"],
      "need_bleach": false,
      "is_recommended": true,
      "sort_order": 20
    }
  ]
}
```

规则：

1. 推荐必须来自商家库候选。
2. 不允许编造发型。
3. 不允许编造发色。
4. 必须同方向：男性、女性、中性。
5. 商家上传内容默认全部参与推荐。
6. 优先标签相似、排序靠前、已启用、默认推荐。

输出：

```json
{
  "recommendations": [
    {
      "slot": "natural",
      "style_id": "style_011",
      "color_id": "color_003",
      "reason": "更自然，适合第一次尝试。"
    },
    {
      "slot": "advanced",
      "style_id": "style_010",
      "color_id": "color_004",
      "reason": "更有变化，适合想提升造型感。"
    }
  ]
}
```

### 3.4 WF-03 主理人推荐工作流

目标：

为结果页推荐3位主理人，默认第一位为最匹配主理人，顾客可自主选择其余主理人。

推荐优先级：

```text
当前门店
→ 擅长当前方向
→ 擅长当前发型
→ 擅长当前发色
→ 有相关作品
→ 当前可预约
→ 店长设置优先推荐
```

输出：

```json
{
  "stylists": [
    {
      "id": 18,
      "name": "Kevin",
      "title": "高级主理人",
      "is_default": true,
      "reason": "擅长男士短发和冷棕色染发。",
      "portfolio_ids": [101, 102, 103]
    },
    {
      "id": 22,
      "name": "Mia",
      "title": "资深主理人",
      "is_default": false,
      "reason": "擅长自然发色和日常通勤风格。",
      "portfolio_ids": [111, 112, 113]
    },
    {
      "id": 25,
      "name": "Allen",
      "title": "创意主理人",
      "is_default": false,
      "reason": "擅长个性层次和造型设计。",
      "portfolio_ids": [121, 122, 123]
    }
  ],
  "fallback": false
}
```

### 3.5 WF-04 AI客服工作流

目标：

回答顾客关于门店、服务、价格、预约、AI试发、发型发色、主理人、会员的问题。

规则：

1. 基于知识库和数据库内容回答。
2. 不承诺最终效果100%一致。
3. 不编造价格。
4. 不编造主理人。
5. 不回答无关问题。
6. 无法回答时引导联系门店。

输出：

```json
{
  "answer": "黑茶色通常不需要漂，适合自然显白效果。最终是否需要漂，建议到店由主理人根据发质判断。",
  "actions": [
    {
      "type": "contact_store",
      "label": "联系门店"
    }
  ]
}
```

### 3.6 WF-05 AI自动标签工作流

套餐属性：

```text
进阶套餐功能
```

目标：

商家上传发型/发色图片后，AI自动生成标签，商家确认后入库。

输入：

```json
{
  "image_url": "https://image-url",
  "asset_type": "hairstyle"
}
```

输出：

```json
{
  "direction": "male",
  "display_tags": ["商务", "清爽", "低维护"],
  "internal_tags": ["男士短发", "通勤", "无需烫"],
  "need_perm": false,
  "need_bleach": null,
  "maintenance_level": "low",
  "confidence": 0.86
}
```

规则：

```text
AI只做建议，不自动保存。
必须商家确认后入库。
```

---

## 4. 后端API执行方案

### 4.1 后端职责

FastAPI后端负责：

1. 微信登录和手机号绑定。
2. 多租户权限。
3. 门店二维码和到店权益。
4. AI试发免费/赠送/付费资格判断。
5. 图片临时上传和临时展示。
6. 调用Dify工作流。
7. 订单和预约。
8. 商家端操作。
9. 飞书同步。
10. 平台后台数据。

### 4.2 关键接口

顾客端：

```text
POST /auth/wx-login
GET  /stores/current
GET  /ai/quota/today
GET  /hairstyles
GET  /hair-colors
POST /ai/style/prepare
POST /ai/pay/create
POST /ai/pay/notify
GET  /ai/pay/orders/{pay_order_no}
POST /ai/style/generate
GET  /ai/style/jobs/{job_no}
POST /orders
GET  /orders/my
POST /ai/chat
```

商家端：

```text
GET  /merchant/workbench
GET  /merchant/orders
PUT  /merchant/orders/{id}/confirm
PUT  /merchant/orders/{id}/arrived
PUT  /merchant/orders/{id}/start-service
PUT  /merchant/orders/{id}/complete
POST /merchant/ai/gift
POST /merchant/staff/{id}/gift-quota/add
GET  /merchant/performance
POST /merchant/hairstyles
POST /merchant/hair-colors
POST /merchant/assets/ai-tags
```

平台端：

```text
GET  /platform/tenants
POST /platform/tenants
GET  /platform/usage
GET  /platform/billing
GET  /platform/costs
POST /platform/packages
```

飞书同步：

```text
POST /sync/feishu/push
POST /sync/feishu/retry
GET  /sync/feishu/status
```

### 4.2.1 顾客AI试发付费立场

本项目必须明确区分“客户演示/POC”和“正式商业MVP”：

```text
客户演示小样：可以展示付费确认页面，但不接真实微信支付，可使用模拟支付状态。
POC验证阶段：可以暂不接微信支付，只验证AI生成效果、成本、速度和流程。
正式商业MVP：必须接入微信支付，不能只写“付费确认”但没有支付接口。
```

正式商业MVP必须包含：

1. `POST /ai/pay/create` 创建AI试发支付单，返回微信支付参数。
2. `POST /ai/pay/notify` 接收微信支付回调，更新支付状态。
3. `GET /ai/pay/orders/{pay_order_no}` 查询支付单状态。
4. 支付成功后，才允许创建 `billing_type = paid` 的AI生成任务。
5. 付费成功但AI生成失败或超时，不重复扣顾客费用，允许免费重试一次。
6. 顾客支付金额记入客户收入统计，平台真实API成本只在平台内部统计。
7. 服务订单仍为到店支付，AI试发付费和到店服务支付是两条独立流程。

如果某个版本明确不做真实微信支付，则页面和接口文案必须统一改为：

```text
免费/赠送资格确认
```

不得保留“付费确认”却没有支付接口，避免AI开发时自行猜测实现。

### 4.3 AI生成前后端校验

生成前必须校验：

1. 用户已登录。
2. 用户手机号已授权。
3. tenant_id有效。
4. store_id有效。
5. 发型/发色来自当前租户商家库。
6. 发型/发色已启用。
7. 用户有免费、赠送或付费资格。
8. 同一用户未超每日总上限。
9. 门店未超每日总上限。
10. 用户未被风控限制。

生成后必须处理：

1. 三张成功才扣次数。
2. 失败不扣次数。
3. 付费成功但生成失败，允许免费重试一次。
4. 记录调用状态。
5. 记录客户可见结算价。
6. 记录平台内部真实成本。
7. 同步明细到飞书。

### 4.4 AI生成并发与排队控制

AI生成必须通过后端任务队列执行，不允许微信小程序直接调用Dify或通义万相，也不允许前端重复点击直接发起多个生成请求。

推荐架构：

```text
微信小程序
→ POST /ai/style/generate
→ FastAPI创建 ai_generation_jobs
→ Redis队列入队
→ AI Worker消费任务
→ 调用Dify工作流
→ Dify调用通义万相
→ 写回任务状态
→ 小程序轮询 /ai/style/jobs/{job_no}
```

#### 4.4.1 并发限制

第一阶段建议默认限制：

```text
单个用户：同一时间最多1个生成任务
单个门店：同一时间最多5个生成任务
单个租户/客户：同一时间最多20个生成任务
全平台：同一时间最多50个生成任务
```

以上数字必须做成后台配置项，后续可按服务器和通义万相额度调整。

#### 4.4.2 排队规则

如果超过并发限制：

1. 后端不拒绝合法请求，而是进入排队。
2. 返回任务号和排队位置。
3. 小程序进入“排队生成中”页面。
4. 前端每2-3秒轮询一次任务状态。

接口返回示例：

```json
{
  "job_no": "AI202605260001",
  "status": "queued",
  "queue_position": 3,
  "estimated_wait_seconds": 45
}
```

小程序文案：

```text
当前AI造型人数较多，正在为你排队生成。
请勿退出页面，生成结果仅临时展示。
```

#### 4.4.3 同一用户重复点击控制

同一用户如果已有 `queued` 或 `running` 状态任务：

```text
不创建新任务
直接返回已有任务 job_no
```

避免用户连续点击导致重复扣费、重复消耗API。

#### 4.4.4 任务状态

AI生成任务状态必须包含：

```text
queued      排队中
running     生成中
success     成功
failed      失败
timeout     超时
cancelled   已取消
```

#### 4.4.5 超时规则

建议：

```text
排队最长等待：3分钟
生成最长执行：45秒
总任务最长生命周期：5分钟
```

超时处理：

1. 任务标记为 `timeout`。
2. 不扣AI试发次数。
3. 付费用户不重复收费，可重新生成一次。
4. 记录失败原因，用于平台内部统计。

#### 4.4.6 失败与重试

规则：

1. 三张图全部成功才扣1次。
2. 任意图片失败，本次任务失败。
3. 失败不扣次数。
4. 付费成功但生成失败，可免费重试一次。
5. Worker可对模型网络错误自动重试1次。
6. 如果重试仍失败，任务失败并提示用户稍后再试。

#### 4.4.7 门店和租户限流

除了并发限制，还要有每日总量限制：

```text
单用户每日总生成上限
单门店每日总生成上限
单租户每日总生成上限
全平台每日安全上限
```

超过上限时：

```text
提示联系门店或平台方
不再进入生成队列
```

#### 4.4.8 飞书统计字段

AI试发记录同步到飞书时，应增加：

```text
排队时长
生成耗时
队列位置
是否排队
失败原因
是否重试
是否扣次数
```

用于判断高峰期是否需要扩容或提高模型额度。

---

## 5. 数据库核心表

### 5.1 多租户基础表

```sql
CREATE TABLE tenants (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_code VARCHAR(64) UNIQUE NOT NULL,
  name VARCHAR(100) NOT NULL,
  logo_url VARCHAR(255),
  package_plan VARCHAR(50),
  status ENUM('active','paused','expired') DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

```sql
CREATE TABLE stores (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_code VARCHAR(64) NOT NULL,
  name VARCHAR(100) NOT NULL,
  address TEXT,
  phone VARCHAR(30),
  daily_ai_limit INT DEFAULT 300,
  status ENUM('active','paused') DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_store (tenant_id, store_code)
);
```

### 5.2 用户和角色

```sql
CREATE TABLE users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  openid VARCHAR(80) NOT NULL,
  phone VARCHAR(30),
  nickname VARCHAR(80),
  role ENUM('boss','manager','staff','customer') DEFAULT 'customer',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_openid (tenant_id, openid)
);
```

### 5.3 发型发色

```sql
CREATE TABLE hairstyles (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  name VARCHAR(100) NOT NULL,
  direction ENUM('male','female','neutral') NOT NULL,
  browse_gender ENUM('male','female','universal') DEFAULT 'universal',
  hair_length ENUM('short','medium','long') DEFAULT 'medium',
  hairstyle_api_id VARCHAR(100),
  thumbnail_url VARCHAR(255),
  display_tags JSON,
  internal_tags JSON,
  face_tags JSON,
  style_tags JSON,
  service_type_tags JSON,
  need_perm TINYINT DEFAULT 0,
  is_enabled TINYINT DEFAULT 1,
  is_recommended TINYINT DEFAULT 1,
  sort_order INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

```sql
CREATE TABLE hair_colors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT,
  name VARCHAR(100) NOT NULL,
  direction ENUM('male','female','neutral') NOT NULL,
  color_api_id VARCHAR(100),
  color_swatch VARCHAR(50),
  thumbnail_url VARCHAR(255),
  display_tags JSON,
  internal_tags JSON,
  need_bleach TINYINT DEFAULT 0,
  is_enabled TINYINT DEFAULT 1,
  is_recommended TINYINT DEFAULT 1,
  sort_order INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5.4 AI生成任务

```sql
CREATE TABLE ai_generation_jobs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  job_no VARCHAR(80) UNIQUE NOT NULL,
  direction ENUM('male','female','neutral') NOT NULL,
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
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME
);
```

注意：

```text
客户可见字段命名使用“主图调用是否成功”“推荐图调用是否成功”。
平台内部可记录真实供应商和真实成本。
```

时间字段规则：

1. `queue_wait_seconds` = `started_at - queued_at` 的秒数。
2. `generate_duration_seconds` = `completed_at - started_at` 的秒数。
3. 任务进入 `running` 时写入 `started_at` 和 `queue_wait_seconds`。
4. 任务进入 `success`、`failed` 或 `timeout` 时写入 `completed_at` 和 `generate_duration_seconds`。
5. 飞书同步的“排队时长”和“生成耗时”必须来自这两个字段，不允许同步时临时猜测。

### 5.5 AI次数和赠送

```sql
CREATE TABLE ai_payment_orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  pay_order_no VARCHAR(80) UNIQUE NOT NULL,
  wx_transaction_id VARCHAR(100),
  amount DECIMAL(10,2) NOT NULL,
  pay_status ENUM('pending','paid','failed','closed','refunded') DEFAULT 'pending',
  paid_at DATETIME,
  generation_job_id BIGINT,
  retry_for_job_id BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

说明：

1. `ai_payment_orders` 只记录AI试发付费订单，不记录到店服务订单。
2. 到店服务仍走线下到店支付。
3. 支付成功后再创建或放行 `billing_type = paid` 的AI生成任务。
4. AI生成失败或超时时，支付单不重复收款，允许绑定一次免费重试任务。

```sql
CREATE TABLE tenant_ai_accounts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  total_purchased INT DEFAULT 0,
  total_used INT DEFAULT 0,
  total_gifted_adjustment INT DEFAULT 0,
  status ENUM('active','frozen') DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tenant_ai_account (tenant_id)
);
```

```sql
CREATE TABLE tenant_ai_package_orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  package_name VARCHAR(100) NOT NULL,
  purchased_count INT NOT NULL,
  unit_price DECIMAL(10,4) NOT NULL,
  total_amount DECIMAL(10,2) NOT NULL,
  payment_status ENUM('pending','paid','cancelled','refunded') DEFAULT 'pending',
  paid_at DATETIME,
  created_by BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

```sql
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
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

说明：

1. `tenant_ai_accounts` 是客户AI额度池。
2. `tenant_ai_package_orders` 记录平台卖给客户的次数包订单。
3. `tenant_ai_usage_logs` 记录每一次扣减、补偿、赠送和后台调整。
4. `customer_paid_amount` 是顾客向客户支付的AI试发金额。
5. `tenant_settle_unit_price` 是平台卖给客户的单次AI结算价。
6. `internal_api_cost` 只允许平台内部查看。
7. AI任务只有成功后才写入扣减日志。
8. `tenant_ai_accounts` 不保存 `remaining_balance` 冗余字段，查询时按 `total_purchased + total_gifted_adjustment - total_used` 实时计算。
9. 扣减AI额度必须使用数据库事务，先 `SELECT ... FOR UPDATE` 锁定对应 `tenant_ai_accounts` 行，再更新 `total_used`。
10. Worker并发扣减前必须加Redis分布式锁，锁粒度为 `tenant_id + generation_job_id`，避免同一成功任务重复扣减。
11. `tenant_ai_usage_logs.balance_after` 只是扣减完成后的审计快照，不作为主余额来源。
12. `ai_generation_jobs.is_count_deducted` 必须和 `tenant_ai_usage_logs` 在同一个事务内更新。

```sql
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
```

```sql
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
  used_at DATETIME
);
```

### 5.6 订单和业绩

```sql
CREATE TABLE orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  store_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  stylist_id BIGINT,
  direction ENUM('male','female','neutral'),
  hairstyle_id BIGINT,
  hair_color_id BIGINT,
  service_item_id BIGINT,
  appointment_time DATETIME,
  status ENUM('pending','confirmed','arrived','serving','completed','cancelled') DEFAULT 'pending',
  is_ai_converted TINYINT DEFAULT 0,
  ai_job_id BIGINT,
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

```sql
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
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. 微信小程序执行方案

### 6.1 顾客端页面

```text
pages/login/index            微信登录
pages/home/index             AI造型首页
pages/style-direction/index  女性/男性/中性
pages/style-select/index     发型/发色选择
pages/photo/index            自拍/上传
pages/generate-confirm/index 免费/付费确认
pages/generating/index       生成中
pages/result/index           结果页
pages/image-preview/index    大图预览，仅图片+LOGO水印
pages/order/index            下单到店
pages/orders/index           我的订单
pages/ai-chat/index          AI客服
```

### 6.1.1 顾客端首页UI规则

首页必须按最新展示小样设计：

1. 顶部展示客户LOGO/品牌名和当前门店。
2. 页面核心动作为圆形“开始AI造型”按钮。
3. 圆形按钮使用统一品牌视觉：玫瑰红 + 墨绿 + 深咖黑。
4. 到店扫码用户显示今日免费AI试发次数。
5. 自行打开用户显示付费生成提示。
6. 中间空余区域展示商家上传照片，照片自动滚动更换。
7. `发型灵感`、`我的订单`、`AI咨询` 三个入口放在页面底部最下面。
8. 首页不得做传统九宫格功能堆叠。

### 6.1.2 发型/发色选择页UI规则

选择页必须按最新展示小样设计：

1. 分类菜单放在页面最左侧。
2. 内容展示区放在右侧。
3. 分类项固定为：

```text
热门
发色
长发
中发
短发
```

4. `热门`展示顾客上一级所选方向，男性/女性/中性中的商家推荐内容。
5. 右侧以图片卡片展示发型/发色。
6. 用户可只选发型、只选发色、或同时选择发型+发色。
7. 选择页按钮和选中态必须与首页圆形按钮保持同一视觉体系。

### 6.2 商家端页面

```text
pages/merchant/workbench     工作台
pages/merchant/orders        订单
pages/merchant/ai-quota      AI次数
pages/merchant/performance   业绩
pages/merchant/gallery       图库
pages/merchant/hairstyles    发型库
pages/merchant/colors        发色库
pages/merchant/stylists      主理人
pages/merchant/services      服务项目
pages/merchant/settings      设置
```

### 6.2.1 商家端UI规则

商家端是门店现场操作台，不是营销页面。必须突出效率和数据：

1. 工作台展示今日预约、待确认、AI试发、AI转下单。
2. 订单页支持确认预约、确认到店、开始服务、完成服务、取消订单、分配主理人。
3. AI次数页支持查看免费/赠送/付费次数、给顾客赠送1次、给主理人追加当天赠送额度。
4. 业绩页展示本店成交、AI转化率、客单价、AI转成交、主理人排行、服务项目统计。
5. 图库页展示发型、发色、标签、作品和AI自动标签入口。
6. 主理人页管理可预约、忙碌、不在店、暂停接单状态，状态影响推荐。
7. 服务页管理美发、染发、烫发、造型、护理等自定义服务项目。
8. 商家端底部导航可先展示：工作台、订单、AI次数、业绩、图库。
9. 主理人和服务项目可从工作台或图库/设置入口进入，后续可扩展到底部导航。

### 6.3 顾客端结果页规则

结果页展示：

1. 顶部客户LOGO或品牌名。
2. 三张生成图横向滑动查看，不使用“上一张/下一张”按钮。
3. 当前方案信息。
4. 商家可编辑标签。
5. 保存提醒。
6. 推荐3位主理人，第一位为默认最匹配。
7. 顾客可自主选择其他主理人。
8. 下单按钮统一命名为“下单”，不得写“找TA下单”。

点开照片：

```text
只显示大图 + 右下角客户LOGO水印
```

不得显示：

1. 发型名。
2. 发色名。
3. 标签。
4. 保存提示。
5. 任何文字说明。

---

## 7. 飞书同步执行方案

### 7.1 飞书表

第一阶段创建：

```text
客户表
门店表
主理人表
订单表
AI试发记录表
AI赠送记录表
服务完成记录表
发型热度表
发色热度表
月度结算表
异常风控表
```

### 7.2 客户视图和平台内部视图

客户老板视图可见：

1. 全店订单。
2. 成交金额。
3. AI试发次数。
4. 免费/赠送/付费次数。
5. AI付费收入。
6. AI服务成本，按平台卖给客户的价格。
7. AI转订单数。
8. AI转成交金额。
9. 主理人AI推荐转化排行。
10. 门店AI转化排行。

平台内部视图可见：

1. 真实API成本。
2. 平台毛利。
3. 应收金额。
4. 通义万相调用量。
5. 失败率。
6. 客户账单。

客户不可见：

```text
真实API成本
平台毛利
底层供应商成本
```

---

## 8. 验证清单

### 8.1 服务启动验证

```bash
curl https://api.yourdomain.com/health
```

必须返回：

```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok",
  "dify": "ok"
}
```

### 8.2 Dify工作流验证

必须验证：

1. WF-01能接收用户自拍临时URL。
2. WF-01能生成3张图。
3. WF-01输出固定JSON。
4. WF-02不编造商家库外的发型/发色。
5. WF-03不推荐不在店或暂停接单主理人。
6. WF-04无法回答时能引导联系门店。
7. WF-05只给建议，不自动保存标签。

### 8.3 AI生成验证

测试场景：

1. 只选发型。
2. 只选发色。
3. 发型+发色。
4. 男性方向。
5. 女性方向。
6. 中性方向。
7. 生成失败。
8. 生成超时。
9. 付费成功但生成失败。

通过标准：

1. 三张都成功才扣1次。
2. 失败不扣次数。
3. 生成图尽量保留原自拍五官、背景和服装。
4. 结果页临时展示。
5. 大图有右下角LOGO水印。

### 8.4 权限验证

必须测试：

1. 老板看全店。
2. 店长只看本店。
3. 主理人只看本人业绩。
4. 顾客只看本人订单。
5. 客户A不能看客户B数据。
6. 飞书客户视图不显示平台真实成本。

### 8.5 飞书同步验证

必须测试：

1. 订单写入MySQL后同步飞书。
2. AI试发记录同步飞书。
3. 赠送记录同步飞书。
4. 服务完成记录同步飞书。
5. 飞书同步失败不影响小程序。
6. 失败记录自动重试。

### 8.6 隐私验证

必须测试：

1. 拍照前弹隐私授权。
2. 不同意不能继续。
3. 数据库无顾客自拍URL长期字段。
4. 数据库无生成图长期URL字段。
5. 日志不打印图片base64。
6. 临时图过期后不可访问。

---

## 9. 上线步骤

### 9.1 POC阶段

目标：

验证通义万相是否能稳定在用户原自拍上换发型发色。

必须准备：

1. 男性自拍3张。
2. 女性自拍3张。
3. 中性风格自拍3张。
4. 只换发型测试。
5. 只换发色测试。
6. 发型+发色测试。

验收：

1. 是否像本人。
2. 是否只改头发。
3. 是否明显改脸。
4. 发色是否准确。
5. 发型是否可接受。
6. 生成速度是否小于45秒。
7. 单次成本是否可控。

### 9.2 MVP阶段

必须完成：

1. 微信登录。
2. AI造型主流程。
3. 发型/发色库。
4. Dify工作流。
5. 通义万相生成。
6. 结果页。
7. 主理人推荐。
8. 下单到店。
9. 商家端订单。
10. AI次数。
11. 飞书同步。

### 9.3 灰度阶段

不要15家门店同时上线。

建议：

```text
第1周：1家店
第2周：3家店
第3周：8家店
第4周：15家店
```

观察：

1. 生成成功率。
2. 平均生成时间。
3. API成本。
4. 顾客保存率。
5. 试发转下单率。
6. 下单转成交率。
7. 门店员工赠送使用情况。

---

## 10. AI执行交付标准

AI只有在以下全部满足时，才能声明第一阶段完成：

1. Dify部署成功。
2. Dify工作流可调用。
3. 小程序能完成完整AI造型流程。
4. 通义万相能生成3张图。
5. 三张成功才扣次数。
6. 不保存顾客自拍和生成图。
7. 结果页符合展示规则。
8. 点开大图只有水印。
9. 下单到店流程可用。
10. 商家端能确认订单、赠送次数、追加额度、完成服务。
11. 飞书同步可用。
12. 权限隔离通过。
13. 客户视图不显示平台真实成本。
14. 平台内部视图能看真实成本和毛利。
15. POC生成效果被人工确认可接受。
