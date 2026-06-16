# 美发AI小程序 AI执行落地计划 15店版

版本：v4.0  
日期：2026-05-25  
适用对象：15家门店连锁美发，每店每月约1000名顾客，总量约15000人/月  
执行方式：由AI主导开发、验证、修复和交付，用户无需懂技术  
文档目标：让AI能看懂、能执行、能自检，保障项目可上线、可运营、可扩展

---

## 0. 给老板看的简单说明

这个项目不是一次性做一个展示页面，而是要做一个可以支撑15家门店实际使用的小程序系统。

### 0.1 客户确认后的核心主流程

本项目第一优先级不是单纯“问答式AI推荐”，而是“顾客自选目标造型 + 拍照AI同步生成 + 同步推荐备选发型和发型师”。

顾客端主流程必须按以下顺序设计：

1. 顾客选择自己想要的发型性别：男性、女性、中性。
2. 顾客选择目标发色。
3. 顾客选择目标发型。
4. 系统弹出隐私授权说明。
5. 顾客拍照或上传照片。
6. AI同步生成顾客本人换发效果图。
7. 同一页面同时推荐2个备选发型。
8. 同一页面同时推荐3位擅长该风格、该发色、该服务类型的主理人，第一位为默认最匹配。
9. 顾客选择满意方案后进入预约。

这里的“男性、女性、中性”指顾客想要的目标发型风格，不一定等同于顾客身份证性别。系统可以允许顾客选择中性风格，但发型库、发色库、发型师技能仍必须用结构化标签约束。

AI执行时必须注意：

1. 顾客主动选择的目标发型、目标发色优先级高于系统猜测。
2. 拍照前必须先弹隐私授权。
3. 顾客照片只用于本次AI生成，不得保存到数据库。
4. 生成结果页面必须同时展示：AI换发预览、2个备选发型、3位推荐主理人。
5. 如果AI生成失败，必须保留顾客已选发型发色，并给出备选推荐和可预约发型师。

第一版不要贪多，必须先把核心业务跑通：

1. 顾客登录、选门店、看发型、看套餐、预约。
2. 顾客选择目标发型性别、发色、发型后，拍照生成AI预览。
3. 系统同步推荐2个备选发型和擅长该风格的发型师。
4. 发型和发色必须区分男性、女性、中性/通用，避免推荐和顾客选择不匹配。
5. 发型师按门店、技能、服务风格、可预约时间匹配。
6. 老板能看15家门店的基础数据，店长只能看自己门店。
7. 全系统必须保护顾客照片和个人信息。

虚拟换发、库存、作品集、飞书后台、抖音/美团/点评接口可以做，但建议分阶段，避免第一版过重导致上线拖延。

---

## 1. AI执行总规则

后续任何AI开始写代码前，必须先阅读本文件，并遵守以下规则。

### 1.1 不允许跳过的五个问题

每次开发、改代码、部署、修复问题前，AI必须自问：

1. 我是否读完了相关模块已有代码、接口、数据库表结构？
2. 本次修改是否会破坏已有接口、数据表或线上数据？
3. 是否涉及顾客照片、人脸、手机号、openid、生日等敏感信息？
4. 是否已经按角色和门店做权限隔离？
5. 是否有本地验证、接口验证、数据库验证、异常场景验证？

如果任何一个答案是“不确定”，必须停止编码，先补充读取和验证。

### 1.2 AI开发工作流

每个功能都按以下顺序执行：

1. 读代码：先搜索项目目录，确认已有框架、命名、接口风格。
2. 写计划：列出要改哪些文件、增加哪些表、影响哪些接口。
3. 小步修改：每次只完成一个明确功能。
4. 自主验证：运行测试、启动服务、请求接口、检查数据库。
5. 修复错误：发现报错必须继续修，不把半成品交给用户。
6. 总结交付：说明完成了什么、怎么验证、还有什么风险。

### 1.3 AI禁止事项

AI不得做以下事情：

1. 不得在小程序前端写入 Dify、Face++、OSS、微信支付等长期密钥。
2. 不得把顾客上传的照片、人脸图、虚拟换发原图保存到数据库。
3. 不得只依赖前端传入的 `store_id` 判断权限。
4. 不得让普通顾客访问其他顾客预约、会员、消费记录。
5. 不得让店长看到其他门店数据。
6. 不得在没有测试的情况下宣布功能完成。
7. 不得为了赶进度直接做充值储值功能，储值卡涉及预付款合规风险。

---

## 2. 项目范围和阶段

### 2.1 第一阶段：必须上线的MVP

第一阶段目标：15家门店能真实接待顾客，顾客能先自选目标性别风格、发色、发型，再拍照生成AI换发效果，同时获得2个备选推荐和擅长发型师，并最终完成预约。

必须完成：

1. 微信小程序登录。
2. 门店选择。
3. 顾客端首页。
4. 目标发型性别选择：男性、女性、中性。
5. 发色库选择。
6. 发型库选择。
7. 拍照或上传照片。
8. AI同步生成换发效果。
9. 同步推荐2个备选发型。
10. 同步推荐3位擅长该风格的主理人，默认第一位最匹配。
11. 套餐浏览。
12. 预约创建、查询、取消、确认、完成。
13. 会员积分基础能力。
14. 老板、店长、发型师、顾客四类角色权限。
15. 15家门店数据隔离。
16. 老板总览看板。
17. 店长门店看板。

### 2.2 第二阶段：增强运营

第二阶段目标：提高转化和复购。

建议完成：

1. 发型师作品集。
2. 会员生日提醒。
3. 超60天未到店召回提醒。
4. 优惠券。
5. AI数据分析解读。
6. 飞书多维表格后台。
7. 门店经营日报。

### 2.3 第三阶段：高级能力

第三阶段目标：做差异化体验和外部平台整合。

建议完成：

1. 虚拟换发。
2. 产品零售和库存预警。
3. 抖音团购同步。
4. 美团订单同步。
5. 大众点评数据同步。
6. 微信支付。
7. 多门店营销活动。

---

## 3. 15店规模假设

### 3.1 业务体量

当前按以下规模设计：

1. 门店数量：15家。
2. 每店每月顾客：约1000人。
3. 总顾客量：约15000人/月。
4. 平均每日顾客：约500人/天。
5. 高峰：周末、节假日前、晚上下班后。

### 3.2 技术影响

15店规模下，系统不能只按平均流量设计，必须考虑高峰：

1. AI推荐结果需要缓存。
2. 数据库查询必须按 `store_id`、时间字段、用户字段建立索引。
3. 图片必须走 OSS，不要放在服务器本地。
4. 老板看板应使用汇总表，不要每次实时扫描所有预约明细。
5. 定时任务要有幂等设计，不能重复发生日消息、重复扣库存、重复发优惠券。

---

## 4. 推荐技术架构

### 4.1 第一阶段推荐架构

前端：

1. 微信小程序原生开发。

后端：

1. Python FastAPI。
2. MySQL 8.0。
3. Redis。
4. Dify自部署或云服务。
5. 阿里云OSS。
6. Nginx + HTTPS。

AI模型：

1. 通义千问 qwen-plus：复杂推荐、数据分析。
2. 通义千问 qwen-turbo：商家录入解析、轻量问答。
3. text-embedding-v2：知识库向量。

### 4.2 服务器建议

如果Dify、MySQL、Redis、FastAPI部署在同一台机器：

1. 最低配置：8核16GB，不建议长期生产使用。
2. 推荐配置：8核32GB，200GB SSD。
3. 带宽：10Mbps起。

更稳的生产方案：

1. 应用服务器：FastAPI + Nginx。
2. AI服务器：Dify。
3. 数据库：云MySQL或独立MySQL。
4. 文件：OSS + CDN。

### 4.3 第一阶段暂不做的事项

为了降低上线风险，第一阶段暂不做：

1. 充值储值。
2. 微信支付闭环。
3. 抖音/美团/点评真实接入。
4. 复杂库存。
5. 高级虚拟换发。

这些能力可以预留表和接口，但不要阻塞MVP上线。

---

## 5. 数据库设计原则

### 5.1 所有核心业务表必须有门店字段

以下表必须有 `store_id`：

1. users。
2. stylists。
3. appointments。
4. packages。
5. members。
6. service_records。
7. payments。
8. coupons。
9. stylist_portfolios。
10. products。
11. stock_logs。

发型库和发色库可以是全局，也可以后续支持门店定制。

### 5.2 必须建立的索引

```sql
CREATE INDEX idx_users_openid ON users(openid);
CREATE INDEX idx_users_store_role ON users(store_id, role);
CREATE INDEX idx_stylists_store_active ON stylists(store_id, is_active);
CREATE INDEX idx_appointments_store_time ON appointments(store_id, appt_time);
CREATE INDEX idx_appointments_customer ON appointments(customer_id);
CREATE INDEX idx_appointments_stylist_time ON appointments(stylist_id, appt_time);
CREATE INDEX idx_members_store_user ON members(store_id, user_id);
CREATE INDEX idx_service_records_store_time ON service_records(store_id, service_time);
CREATE INDEX idx_payments_store_time ON payments(store_id, paid_at);
```

### 5.3 性别字段统一规则

所有涉及发型、发色、顾客偏好、推荐的性别字段统一使用：

```text
male    男
female  女
unisex  通用
unknown 未知
```

注意：

1. 顾客性别可允许 unknown。
2. 推荐时如果顾客性别是 unknown，必须让顾客先选择男/女/不限。
3. `unisex` 表示男客女客都可以推荐。
4. AI不得把 `unknown` 当成 `unisex`。

---

## 6. 核心表结构

### 6.1 门店表 stores

```sql
CREATE TABLE stores (
  id VARCHAR(20) PRIMARY KEY,
  name VARCHAR(50) NOT NULL,
  address TEXT,
  phone VARCHAR(20),
  manager_id INT,
  is_active TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.2 用户表 users

```sql
CREATE TABLE users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  openid VARCHAR(64) UNIQUE NOT NULL,
  nickname VARCHAR(50),
  phone VARCHAR(20),
  gender ENUM('male','female','unknown') DEFAULT 'unknown',
  role ENUM('boss','manager','stylist','customer') DEFAULT 'customer',
  store_id VARCHAR(20),
  birthday DATE,
  points INT DEFAULT 0,
  subscribe_msg TINYINT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.3 发型师表 stylists

```sql
CREATE TABLE stylists (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT,
  store_id VARCHAR(20) NOT NULL,
  name VARCHAR(30) NOT NULL,
  gender ENUM('male','female','unknown') DEFAULT 'unknown',
  skill_tags JSON,
  service_genders JSON,
  rating DECIMAL(2,1) DEFAULT 5.0,
  intro TEXT,
  avatar_url VARCHAR(255),
  is_active TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

`service_genders` 示例：

```json
["male", "female"]
```

含义：该发型师能服务男客和女客。

### 6.4 套餐表 packages

```sql
CREATE TABLE packages (
  id INT PRIMARY KEY AUTO_INCREMENT,
  store_id VARCHAR(20),
  name VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  description TEXT,
  service_type ENUM('cut','perm','color','care','style','combo') DEFAULT 'combo',
  gender ENUM('male','female','unisex') DEFAULT 'unisex',
  tags JSON,
  duration_minutes INT DEFAULT 60,
  is_active TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.5 发型表 hairstyles

```sql
CREATE TABLE hairstyles (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  gender ENUM('male','female','unisex') NOT NULL DEFAULT 'unisex',
  hair_length ENUM('short','medium','long','any') DEFAULT 'any',
  style_id VARCHAR(50),
  face_types JSON,
  style_tags JSON,
  service_type JSON,
  age_range JSON,
  thumbnail_url VARCHAR(255),
  is_active TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

`service_type` 示例：

```json
["cut", "perm", "color"]
```

### 6.6 发色表 hair_colors

```sql
CREATE TABLE hair_colors (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  color_id VARCHAR(50),
  gender ENUM('male','female','unisex') DEFAULT 'unisex',
  tone ENUM('natural','black','brown','ash','gold','red','fashion') DEFAULT 'natural',
  requires_bleach TINYINT DEFAULT 0,
  suitable_skin_tones JSON,
  workplace_friendly TINYINT DEFAULT 1,
  thumbnail_url VARCHAR(255),
  is_active TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.7 预约表 appointments

```sql
CREATE TABLE appointments (
  id INT PRIMARY KEY AUTO_INCREMENT,
  customer_id INT NOT NULL,
  stylist_id INT,
  store_id VARCHAR(20) NOT NULL,
  package_id INT,
  hairstyle_id INT,
  hair_color_id INT,
  appt_time DATETIME NOT NULL,
  status ENUM('pending','confirmed','done','cancelled') DEFAULT 'pending',
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.8 服务记录表 service_records

```sql
CREATE TABLE service_records (
  id INT PRIMARY KEY AUTO_INCREMENT,
  appointment_id INT,
  customer_id INT NOT NULL,
  stylist_id INT,
  store_id VARCHAR(20) NOT NULL,
  package_id INT,
  hairstyle_id INT,
  hair_color_id INT,
  service_time DATETIME NOT NULL,
  service_amount DECIMAL(10,2) DEFAULT 0,
  actual_duration_minutes INT,
  remark TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.9 支付记录表 payments

```sql
CREATE TABLE payments (
  id INT PRIMARY KEY AUTO_INCREMENT,
  store_id VARCHAR(20) NOT NULL,
  customer_id INT NOT NULL,
  appointment_id INT,
  service_record_id INT,
  amount DECIMAL(10,2) NOT NULL,
  discount_amount DECIMAL(10,2) DEFAULT 0,
  paid_amount DECIMAL(10,2) NOT NULL,
  pay_method ENUM('cash','wechat','alipay','meituan','douyin','other') DEFAULT 'other',
  paid_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.10 会员表 members

```sql
CREATE TABLE members (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT UNIQUE,
  store_id VARCHAR(20),
  total_spent DECIMAL(10,2) DEFAULT 0,
  visit_count INT DEFAULT 0,
  points INT DEFAULT 0,
  level ENUM('normal','silver','gold','diamond') DEFAULT 'normal',
  last_visit DATE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.11 优惠券表 coupons

```sql
CREATE TABLE coupons (
  id INT PRIMARY KEY AUTO_INCREMENT,
  store_id VARCHAR(20),
  user_id INT,
  name VARCHAR(100) NOT NULL,
  coupon_type ENUM('discount','amount','service') DEFAULT 'amount',
  value DECIMAL(10,2),
  status ENUM('unused','used','expired') DEFAULT 'unused',
  valid_from DATE,
  valid_to DATE,
  used_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.12 门店每日汇总表 store_daily_stats

```sql
CREATE TABLE store_daily_stats (
  id INT PRIMARY KEY AUTO_INCREMENT,
  store_id VARCHAR(20) NOT NULL,
  stat_date DATE NOT NULL,
  appointment_count INT DEFAULT 0,
  done_count INT DEFAULT 0,
  new_customer_count INT DEFAULT 0,
  revenue DECIMAL(10,2) DEFAULT 0,
  avg_order_amount DECIMAL(10,2) DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_store_date (store_id, stat_date)
);
```

---

## 7. AI同步换发与推荐规则

### 7.1 主流程输入

顾客点击“AI同步生成”前，至少收集以下信息：

```json
{
  "store_id": "store_001",
  "target_style_gender": "female",
  "selected_hairstyle_id": 12,
  "selected_hair_color_id": 3,
  "photo_temp_path": "wxfile://temp_xxx",
  "customer_face_type": "round",
  "customer_current_hair_length": "medium"
}
```

字段说明：

1. `target_style_gender`：顾客想要的发型风格，取值为 `male`、`female`、`neutral`。
2. `selected_hairstyle_id`：顾客主动选择的目标发型。
3. `selected_hair_color_id`：顾客主动选择的目标发色。
4. `photo_temp_path`：前端临时照片路径，只用于本次生成，不入库。

### 7.2 同步生成流程

必须按以下顺序执行：

1. 校验顾客选择的目标发型是否存在、启用。
2. 校验顾客选择的目标发色是否存在、启用。
3. 校验目标发型性别是否与顾客选择的 `target_style_gender` 匹配。
4. 校验目标发色是否适合该目标风格。
5. 弹出隐私授权。
6. 顾客同意后调用拍照或选图。
7. 调用AI换发服务生成预览图。
8. 同步查询2个备选发型。
9. 同步查询擅长该风格的发型师。
10. 在一个结果页展示：生成效果、2个备选发型、推荐发型师、预约入口。

### 7.3 备选推荐硬过滤

备选发型推荐必须先由后端做硬过滤，不能交给大模型自由决定。

顺序如下：

1. 过滤启用状态：`is_active = 1`。
2. 过滤目标风格性别：`hairstyles.gender IN (target_style_gender, 'neutral', 'unisex')`。
3. 排除顾客已经选择的目标发型。
4. 优先同发长、同风格、同服务类型。
5. 如果顾客选择的发色需要漂发，备选推荐要标记护理提醒。
6. 最终只返回2个备选发型。

### 7.4 大模型只做生成说明和排序

后端硬过滤后，将候选备选发型、目标发色、目标发型和发型师候选传给 Dify。

Dify只能做：

1. 生成预览结果说明。
2. 从候选中选择2个备选发型。
3. 解释备选发型为什么可作为替代方案。
4. 给出发色护理提醒。
5. 给推荐发型师生成介绍话术。

Dify不能做：

1. 编造数据库不存在的发型。
2. 推荐被硬过滤排除的发型。
3. 推荐与目标风格性别不匹配的发型。
4. 编造发型师。

### 7.5 同步生成输出格式

Dify必须返回结构化JSON：

```json
{
  "preview": {
    "selected_hairstyle_id": 12,
    "selected_hair_color_id": 3,
    "preview_url": "temporary_preview_url",
    "summary": "已生成女性风格黑茶色锁骨发预览"
  },
  "alternative_hairstyles": [
    {
      "hairstyle_id": 18,
      "hair_color_id": 3,
      "reason": "同样适合中发和黑茶色，比目标发型更好打理。"
    },
    {
      "hairstyle_id": 21,
      "hair_color_id": 3,
      "reason": "保留女性柔和轮廓，适合作为到店沟通备选。"
    }
  ],
  "recommended_stylists": [
    {
      "stylist_id": 5,
      "reason": "擅长锁骨发、韩系层次和黑茶色染发。"
    }
  ]
}
```

后端必须校验：

1. `hairstyle_id` 是否存在。
2. `hair_color_id` 是否存在。
3. 备选发型性别是否匹配目标风格。
4. 推荐发色是否匹配目标风格。
5. 发型师是否属于当前门店。
6. 发型师技能是否覆盖目标发型和发色。

校验不通过时，不允许直接返回给顾客，必须降级为规则推荐。

---

## 8. 发型师匹配规则

### 8.1 匹配输入

```json
{
  "store_id": "store_001",
  "customer_gender": "female",
  "service_type": ["cut", "perm"],
  "hairstyle_id": 12,
  "appt_time": "2026-06-01 14:00:00"
}
```

### 8.2 匹配顺序

1. 发型师必须属于当前门店。
2. 发型师必须启用。
3. 发型师 `service_genders` 必须包含顾客性别。
4. 发型师 `skill_tags` 必须覆盖服务类型。
5. 发型师在预约时间不能已有冲突预约。
6. 按评分、完成订单数、相关作品数量排序。

### 8.3 不能匹配时

如果没有发型师完全匹配：

1. 返回最近可预约时间。
2. 返回可做类似服务的发型师。
3. 明确提示“当前时间无完全匹配发型师”。

不得编造发型师。

---

## 9. 权限和数据隔离

### 9.1 角色

```text
boss      老板：可看所有门店
manager   店长：只看本门店
stylist   发型师：只看本人相关预约、作品、业绩
customer  顾客：只看本人数据
```

### 9.2 服务端权限规则

任何接口都不能只靠前端传参判断权限。

后端必须从 JWT 中读取：

1. `user_id`
2. `role`
3. `store_id`
4. `stylist_id`

### 9.3 数据过滤规则

老板：

```text
允许访问所有 store_id。
```

店长：

```text
强制 WHERE store_id = 当前用户 store_id。
```

发型师：

```text
强制 WHERE stylist_id = 当前发型师 id。
```

顾客：

```text
强制 WHERE customer_id = 当前用户 id。
```

### 9.4 权限测试必须覆盖

1. 店长A访问门店B预约，必须403。
2. 发型师A访问发型师B预约，必须403。
3. 顾客A访问顾客B会员信息，必须403。
4. 未登录访问预约接口，必须401。
5. 老板访问全部门店统计，必须200。

---

## 10. API接口计划

### 10.1 认证

```text
POST /auth/wx-login
GET  /auth/me
```

### 10.2 门店

```text
GET /stores
GET /stores/{id}
```

### 10.3 发型和发色

```text
GET /hairstyles
GET /hairstyles/{id}
GET /hair-colors
GET /hair-colors/{id}
```

筛选参数：

```text
gender
hair_length
face_type
style_tag
service_type
```

### 10.4 AI推荐

```text
POST /ai/recommend-hairstyles
POST /ai/recommend-stylists
GET  /ai/data-analysis
```

### 10.5 预约

```text
POST /appointments
GET  /appointments
GET  /appointments/{id}
PUT  /appointments/{id}/confirm
PUT  /appointments/{id}/cancel
PUT  /appointments/{id}/done
```

### 10.6 会员

```text
GET  /members/me
GET  /members/{id}
POST /members/points
```

### 10.7 商家后台

```text
GET  /merchant/dashboard
GET  /merchant/appointments
GET  /merchant/stylists
POST /merchant/stylists
PUT  /merchant/stylists/{id}
GET  /merchant/packages
POST /merchant/packages
PUT  /merchant/packages/{id}
```

### 10.8 老板看板

```text
GET /boss/overview
GET /boss/stores/{store_id}/stats
GET /boss/daily-stats
```

---

## 11. 小程序页面计划

### 11.1 顾客端

```text
pages/login/index                 微信手机号登录
pages/home/index                  AI造型首页，圆形开始按钮，商家照片滚动
pages/style-direction/index       女性/男性/中性
pages/style-select/index          左侧分类，右侧发型/发色图片
pages/photo/index                 自拍/上传
pages/generate-confirm/index      免费/付费确认
pages/generating/index            Dify+通义万相生成中
pages/result/index                结果页，三图横向滑动，3位主理人可选
pages/image-preview/index         大图预览，仅图片+右下角LOGO水印
pages/order/index                 下单到店支付
pages/orders/index                我的订单
pages/ai-chat/index               AI咨询
```

顾客端UI要求：

1. 首页核心入口为圆形“开始AI造型”按钮。
2. 首页中间展示商家上传照片，照片自动滚动更换。
3. `发型灵感`、`我的订单`、`AI咨询` 放在首页底部最下面。
4. 发型/发色选择页左侧为分类，右侧为内容。
5. 分类为：热门、发色、长发、中发、短发。
6. 热门为顾客上一级选择方向下的商家推荐内容。
7. 结果页3张图横向滑动查看，不使用上一张/下一张按钮。
8. 结果页推荐3位主理人，第一位默认最匹配，顾客可自主选择。
9. 结果页按钮统一命名为“下单”。

### 11.2 商家端

```text
pages/merchant/workbench          工作台
pages/merchant/orders             订单
pages/merchant/ai-quota           AI次数，赠送和追加额度
pages/merchant/performance        业绩
pages/merchant/gallery            图库
pages/merchant/hairstyles         发型库
pages/merchant/colors             发色库
pages/merchant/stylists           主理人管理
pages/merchant/services           服务项目
pages/merchant/settings           设置
```

商家端UI要求：

1. 商家端是小程序操作台，飞书是统计台。
2. 工作台展示今日预约、待确认、AI试发、AI转下单。
3. 订单支持确认预约、确认到店、开始服务、完成服务、取消、分配主理人。
4. AI次数支持给顾客赠送1次，给主理人追加当天赠送额度。
5. 业绩展示本店成交、AI转化率、客单价、AI转成交、主理人排行、服务项目统计。
6. 图库管理发型、发色、标签、作品和AI自动标签入口。
7. 主理人状态包括可预约、忙碌、不在店、暂停接单，并影响推荐。
8. 服务项目支持商家自定义，包括美发、染发、烫发、造型、护理等。

### 11.3 老板端

```text
pages/boss/index                  15店总览
pages/boss/store-detail           单店详情
pages/boss/ranking                门店排行、发型师排行
```

---

## 12. 隐私合规规则

### 12.1 顾客照片

第一阶段不保存顾客照片。

如果第三阶段做虚拟换发：

1. 拍照或选图前必须弹出隐私说明。
2. 顾客必须主动点击同意。
3. 长期API密钥不能放在小程序前端。
4. 后端只签发短时效临时凭证。
5. 后端不保存照片文件。
6. 数据库不保存顾客照片URL。
7. 日志中不得打印照片地址、base64、人脸数据。

### 12.2 手机号、openid、生日

1. 手机号仅用于预约联系和会员服务。
2. openid仅用于微信登录。
3. 生日仅用于会员生日提醒。
4. API返回用户信息时，默认隐藏手机号中间四位。

### 12.3 订阅消息

1. 微信订阅消息必须由用户主动授权。
2. 不得强制批量推送。
3. 发送前必须检查 `subscribe_msg = 1`。
4. 每次发送要写入日志，避免重复发送。

---

## 13. AI自验证清单

### 13.1 启动验证

```bash
curl http://localhost:8000/health
```

通过标准：

```json
{"status":"ok"}
```

### 13.2 数据库验证

```sql
SELECT 1;
SHOW TABLES;
SELECT COUNT(*) FROM stores;
SELECT COUNT(*) FROM hairstyles;
SELECT COUNT(*) FROM hair_colors;
```

通过标准：

1. 数据库连接正常。
2. 核心表存在。
3. 至少存在15家门店测试数据。
4. 发型库同时包含男、女、通用数据。
5. 发色库同时包含男、女、通用数据。

### 13.3 AI生成并发与排队验证

AI生成必须通过后端队列执行，不允许小程序直接调用Dify或通义万相。

默认并发限制建议：

```text
单个用户：同一时间最多1个生成任务
单个门店：同一时间最多5个生成任务
单个租户/客户：同一时间最多20个生成任务
全平台：同一时间最多50个生成任务
```

这些限制必须做成后台配置项，后续可根据服务器和模型额度调整。

任务状态必须包含：

```text
queued      排队中
running     生成中
success     成功
failed      失败
timeout     超时
cancelled   已取消
```

排队规则：

1. 超过并发限制时，任务进入排队。
2. 返回 `job_no`、`queue_position`、`estimated_wait_seconds`。
3. 小程序显示排队提示。
4. 前端每2-3秒轮询任务状态。
5. 同一用户已有排队中或生成中任务时，不创建新任务，直接返回已有任务号。

超时规则：

```text
排队最长等待：3分钟
生成最长执行：45秒
总任务最长生命周期：5分钟
```

扣次数规则：

1. 三张图全部成功才扣1次。
2. 任意失败或超时不扣次数。
3. 付费成功但生成失败，可免费重试一次。

飞书统计必须增加：

```text
排队时长
生成耗时
队列位置
是否排队
失败原因
是否重试
是否扣次数
```

### 13.4 性别推荐验证

测试用例1：男客推荐

输入：

```json
{
  "customer_gender": "male",
  "face_type": "round",
  "current_hair_length": "short",
  "style_preference": ["business"],
  "accept_color": false
}
```

通过标准：

1. 返回发型 `gender` 只能是 `male` 或 `unisex`。
2. 不返回 `female` 发型。
3. 不推荐染发方案。

测试用例2：女客推荐

输入：

```json
{
  "customer_gender": "female",
  "face_type": "oval",
  "current_hair_length": "medium",
  "style_preference": ["korean"],
  "accept_perm": true,
  "accept_color": true
}
```

通过标准：

1. 返回发型 `gender` 只能是 `female` 或 `unisex`。
2. 不返回 `male` 发型。
3. 推荐结果必须包含理由。

测试用例3：不接受漂发

输入：

```json
{
  "customer_gender": "female",
  "accept_color": true,
  "accept_bleach": false
}
```

通过标准：

1. 不返回 `requires_bleach = 1` 的发色。

### 13.5 权限验证

必须创建测试账号：

```text
boss_user
manager_store_001
manager_store_002
stylist_store_001
customer_a
customer_b
```

测试：

1. `manager_store_001` 查询 `store_002` 数据，返回403。
2. `customer_a` 查询 `customer_b` 预约，返回403。
3. `stylist_store_001` 查询其他发型师预约，返回403。
4. `boss_user` 查询全部门店概览，返回200。

### 13.6 预约验证

必须测试：

1. 顾客创建预约成功。
2. 同一发型师同一时间不能重复预约。
3. 取消预约后状态变为 `cancelled`。
4. 完成预约后生成 `service_records`。
5. 完成服务后更新会员 `visit_count`、`total_spent`、`last_visit`。

### 13.7 看板验证

必须测试：

1. 老板能看到15家门店汇总。
2. 店长只能看到本店。
3. 营收等于支付记录汇总。
4. 预约数量等于预约表统计。
5. 每日汇总任务重复执行不会重复累加。

---

## 14. 自动化测试要求

### 14.1 后端测试

必须至少覆盖：

1. 登录。
2. 权限中间件。
3. 发型性别过滤。
4. 发色漂发过滤。
5. AI推荐结果校验。
6. 预约冲突。
7. 会员积分更新。
8. 老板/店长看板权限。

### 14.2 接口测试

每个核心接口必须测试：

1. 正常请求。
2. 未登录请求。
3. 越权请求。
4. 参数缺失。
5. 参数非法。
6. 空数据情况。

### 14.3 前端测试

小程序必须人工或自动验证：

1. 首页能加载。
2. 门店能选择。
3. 男客筛选不出现女款发型。
4. 女客筛选不出现男款发型。
5. 推荐结果能进入预约。
6. 预约成功后能在我的预约看到。
7. 商家端非管理员不可进入。

---

## 15. 种子数据要求

为了让系统能测试，第一阶段必须准备种子数据。

### 15.1 门店

必须创建15家门店：

```text
store_001 到 store_015
```

### 15.2 发型

至少准备：

1. 男士发型20个。
2. 女士发型30个。
3. 通用发型10个。

每个发型必须包含：

1. 名称。
2. 性别。
3. 发长。
4. 适合脸型。
5. 风格标签。
6. 服务类型。
7. 缩略图。

### 15.3 发色

至少准备：

1. 男士发色10个。
2. 女士发色20个。
3. 通用自然发色10个。

每个发色必须包含：

1. 名称。
2. 性别。
3. 色系。
4. 是否需要漂发。
5. 是否职场友好。
6. 缩略图。

### 15.4 发型师

每家门店至少准备：

1. 3名发型师。
2. 每名发型师设置服务性别。
3. 每名发型师设置技能标签。

15家门店共至少45名发型师。

---

## 16. 部署和运维

### 16.1 环境变量

所有密钥必须放在服务器环境变量，不得写入代码。

```text
MYSQL_HOST
MYSQL_PORT
MYSQL_USER
MYSQL_PASSWORD
MYSQL_DATABASE
REDIS_URL
JWT_SECRET
DIFY_API_KEY
DIFY_BASE_URL
OSS_ACCESS_KEY_ID
OSS_ACCESS_KEY_SECRET
OSS_BUCKET
WECHAT_APP_ID
WECHAT_APP_SECRET
```

### 16.2 健康检查

必须提供：

```text
GET /health
```

返回：

```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok",
  "version": "x.x.x"
}
```

### 16.3 备份

必须配置：

1. MySQL每日自动备份。
2. 备份保留至少30天。
3. 备份文件上传OSS。
4. 每月至少做一次恢复演练。

### 16.4 日志

必须记录：

1. 登录失败。
2. 权限拒绝。
3. AI推荐失败。
4. Dify超时。
5. 预约创建、取消、完成。
6. 订阅消息发送。
7. 定时任务执行结果。

不得记录：

1. 顾客照片。
2. 人脸数据。
3. 完整手机号。
4. 明文密钥。

---

## 17. AI执行阶段计划

### 阶段1：项目初始化

AI要做：

1. 创建后端项目结构。
2. 创建小程序项目结构。
3. 配置环境变量模板。
4. 配置数据库迁移工具。
5. 创建 `/health` 接口。

完成标准：

1. 后端能启动。
2. `/health` 返回正常。
3. 数据库能连接。

### 阶段2：数据库和种子数据

AI要做：

1. 创建核心表。
2. 创建索引。
3. 写入15家门店测试数据。
4. 写入男/女/通用发型数据。
5. 写入男/女/通用发色数据。
6. 写入45名发型师测试数据。

完成标准：

1. 所有表存在。
2. 种子数据可查询。
3. 性别字段符合枚举规则。

### 阶段3：登录和权限

AI要做：

1. 实现微信登录。
2. 实现JWT。
3. 实现角色权限。
4. 实现门店数据隔离。

完成标准：

1. 未登录访问核心接口返回401。
2. 越权访问返回403。
3. 老板、店长、发型师、顾客权限测试通过。

### 阶段4：发型、发色、套餐

AI要做：

1. 实现发型列表接口。
2. 实现发色列表接口。
3. 实现套餐列表接口。
4. 实现性别、发长、脸型、风格筛选。

完成标准：

1. 男客不出现女款。
2. 女客不出现男款。
3. 通用款可出现在男客和女客结果中。

### 阶段5：AI推荐

AI要做：

1. 实现后端硬过滤。
2. 接入Dify。
3. 校验Dify输出。
4. 实现降级规则推荐。
5. 缓存推荐结果。

完成标准：

1. Dify正常时返回TOP3推荐。
2. Dify失败时仍有规则推荐。
3. 推荐结果不违反性别、漂发、烫染限制。

### 阶段6：预约

AI要做：

1. 创建预约。
2. 查询预约。
3. 取消预约。
4. 店长确认预约。
5. 完成预约。
6. 防止发型师时间冲突。

完成标准：

1. 顾客能创建预约。
2. 发型师同时间不能重复预约。
3. 权限隔离正常。
4. 完成预约后更新会员数据。

### 阶段7：看板

AI要做：

1. 老板15店总览。
2. 店长本店看板。
3. 发型师个人业绩。
4. 每日汇总任务。

完成标准：

1. 老板能看全部。
2. 店长只能看本店。
3. 汇总数据和明细数据一致。

### 阶段8：小程序

AI要做：

1. 顾客端页面。
2. 商家端页面。
3. 老板端页面。
4. 登录态管理。
5. 接口错误提示。

完成标准：

1. 顾客完整走通：登录、选门店、AI推荐、预约、查看预约。
2. 店长完整走通：查看本店预约、确认、完成。
3. 老板完整走通：查看15店总览。

### 阶段9：上线前验收

AI要做：

1. 运行全部测试。
2. 检查密钥泄露。
3. 检查数据库是否保存顾客照片。
4. 检查权限越权。
5. 检查HTTPS。
6. 检查日志。
7. 输出上线报告。

完成标准：

1. 核心测试通过。
2. 无密钥泄露。
3. 无顾客照片存储。
4. 权限隔离通过。
5. 可灰度给1家门店试用。

---

## 18. 上线策略

### 18.1 灰度上线

不要15家门店同时上线。

建议：

1. 第1周：1家门店试用。
2. 第2周：增加到3家门店。
3. 第3周：增加到8家门店。
4. 第4周：全部15家门店上线。

### 18.2 灰度期间重点看

1. 顾客是否能顺利预约。
2. 推荐结果是否合理。
3. 男女性别过滤是否准确。
4. 店长是否会用后台。
5. 发型师预约时间是否冲突。
6. 周末高峰是否卡顿。
7. AI接口是否超时。

### 18.3 回滚方案

上线前必须保留：

1. 数据库备份。
2. 上一版本后端镜像。
3. 上一版本小程序体验版。
4. 配置文件备份。

如果新版本出现严重问题：

1. 立即切回上一版本后端。
2. 暂停AI推荐，启用规则推荐。
3. 保留预约基础功能。

---

## 19. 后续扩展原则

新增任何模块时，必须遵守：

1. 不破坏已有预约流程。
2. 不破坏门店数据隔离。
3. 不破坏性别发型发色过滤。
4. 不保存顾客照片。
5. 不把密钥放到前端。
6. 新接口必须有测试。
7. 新表必须考虑 `store_id`。
8. 新功能必须有关闭开关。

---

## 20. AI最终交付标准

项目可以交付时，必须满足：

1. 顾客能完成完整预约闭环。
2. AI推荐能区分男、女、通用发型发色。
3. 15家门店数据隔离正确。
4. 老板、店长、发型师、顾客权限正确。
5. 后端服务可稳定启动。
6. 数据库有备份。
7. 小程序关键页面可正常使用。
8. 核心接口测试通过。
9. 不保存顾客照片。
10. 无前端密钥泄露。
11. 有上线检查报告。
12. 有后续运维说明。

只有以上全部满足，AI才可以声明“项目已完成第一阶段上线准备”。
