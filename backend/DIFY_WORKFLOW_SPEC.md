# Dify 工作流接入规范

当前后端已经支持两种模式：

```text
未配置 DIFY_BASE_URL / DIFY_API_KEY -> 使用 MockDifyClient
已配置 DIFY_BASE_URL / DIFY_API_KEY -> 调用真实 Dify /v1/workflows/run
```

## WF-01 输入

后端调用 Dify 时，会发送：

```json
{
  "inputs": {
    "job_no": "AI202605260001",
    "direction": "female",
    "selected_style": {
      "style_id": "style_010",
      "style_name": "Korean Medium Hair",
      "tags": ["korean", "natural"]
    },
    "selected_color": {
      "color_id": "color_003",
      "color_name": "Cool Brown",
      "tags": ["natural", "brightening"]
    },
    "recommendations": [
      {
        "slot": "natural",
        "title": "Natural recommendation",
        "style_id": "style_011",
        "style_name": "Textured Short Hair",
        "color_id": "color_003",
        "color_name": "Cool Brown"
      },
      {
        "slot": "advanced",
        "title": "Advanced recommendation",
        "style_id": "style_010",
        "style_name": "Korean Medium Hair",
        "color_id": "color_004",
        "color_name": "Black Tea Brown"
      }
    ]
  },
  "response_mode": "blocking",
  "user": "hair-ai-AI202605260001"
}
```

正式 POC 增加自拍后，还需要追加：
当前后端已经支持此字段：

```json
{
  "photo_temp_url": "https://temporary-object-url"
}
```

`photo_temp_url` 不写入 `ai_generation_jobs`，只在本次调用 Dify 时传递。

## 临时图片存储约定

后端已经把自拍临时上传抽象为 `TempStorageProvider`：

```text
TEMP_STORAGE_PROVIDER=mock       -> 本地POC/客户展示
TEMP_STORAGE_PROVIDER=aliyun_oss -> 阿里OSS短期上传URL
```

规则：
1. 小程序端只拿 `upload_url` 上传自拍，再把 `photo_temp_url` 传给生成接口。
2. `photo_temp_url` 只用于本次 Dify 工作流调用，不写入 `ai_generation_jobs`。
3. `object_key` 必须包含 `tenant_id/store_id/user_id` 路径，便于隔离和排查。
4. 生产环境必须使用短 TTL，不长期保存顾客自拍和生成图。
5. Dify 不直接拿 OSS 密钥，只接收后端传入的临时图片 URL。

## WF-01 输出

Dify 工作流最终必须输出 `result`，结构如下：

```json
{
  "status": "success",
  "internal_api_cost": 0.88,
  "images": [
    {
      "slot": "main",
      "title": "Selected style",
      "direction": "female",
      "style_id": "style_010",
      "style_name": "Korean Medium Hair",
      "color_id": "color_003",
      "color_name": "Cool Brown",
      "temp_image_url": "https://temporary-result-url/main.jpg"
    },
    {
      "slot": "natural",
      "title": "Natural recommendation",
      "direction": "female",
      "style_id": "style_011",
      "style_name": "Textured Short Hair",
      "color_id": "color_003",
      "color_name": "Cool Brown",
      "temp_image_url": "https://temporary-result-url/natural.jpg"
    },
    {
      "slot": "advanced",
      "title": "Advanced recommendation",
      "direction": "female",
      "style_id": "style_010",
      "style_name": "Korean Medium Hair",
      "color_id": "color_004",
      "color_name": "Black Tea Brown",
      "temp_image_url": "https://temporary-result-url/advanced.jpg"
    }
  ]
}
```

失败时输出：

```json
{
  "status": "failed",
  "error_code": "IMAGE_GENERATION_FAILED",
  "error_message": "Image generation failed",
  "internal_api_cost": 0.12
}
```

## 强制规则

1. 成功时必须返回3张图。
2. 少于3张图，后端按失败处理，不扣客户AI次数。
3. `style_id`、`color_id` 必须来自后端传入的候选，不允许 Dify 编造。
4. 图片 URL 必须是临时 URL。
5. 工作流不得长期保存顾客自拍和生成图。
6. POC 阶段必须人工记录是否像本人、是否只改头发、生成耗时和单次成本。
7. 后端结果页接口只临时返回 `images`，当前骨架使用内存保存，生产环境替换为短TTL缓存。

## 本地校验 Dify 输出

真实 Dify 工作流调通后，先把一次工作流输出保存成 JSON 文件，再执行：

```powershell
python backend/scripts/validate_dify_result.py backend/fixtures/dify_success_result.json
```

成功时应输出：

```text
PASS Dify result contract
images=3
slots=main,natural,advanced
```

校验失败时，脚本会输出失败原因，例如：

```powershell
python backend/scripts/validate_dify_result.py backend/fixtures/dify_invalid_less_than_three_images.json
```

会提示 Dify 没有返回3张图。此类结果在业务生成中会被按失败处理，失败、超时、少图都不扣客户AI次数。
