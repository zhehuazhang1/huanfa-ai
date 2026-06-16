# 如何查看 AI 图片生成成本数据

> 本文教你在自己的电脑上启动后端，并在屏幕上看到真实的成本/毛利数据。
> （AI 助手的运行环境是隔离、无法联网装依赖的，所以无法替你跑后端；必须在你本机操作。）

## 一、准备：确认装了 Python

打开「开始菜单」搜 PowerShell 打开，输入：

```
python --version
```

- 显示 `Python 3.11.x` 之类 → 已装好，继续。
- 提示找不到命令 → 去 https://www.python.org 下载 Python 3.11，安装时**务必勾选 "Add Python to PATH"**，装完重开 PowerShell。

## 二、装依赖（只需做一次）

```
cd C:\Users\73177\Documents\美发
pip install -r backend\requirements.txt
```

## 三、启动后端（用项目自带脚本）

```
cd C:\Users\73177\Documents\美发
powershell -ExecutionPolicy Bypass -File .\启动本地后端.ps1
```

看到 `Backend is already running` 或健康检查返回 ok 即成功。
（停止后端用：`.\停止本地后端.ps1`）

## 四、查看成本数据

### 方式 A：浏览器直接看接口（最快）

在浏览器地址栏输入：

```
http://127.0.0.1:8000/platform/costs?tenant_id=1
http://127.0.0.1:8000/platform/billing?tenant_id=1
```

`/platform/costs` 返回示例：

```json
{
  "total_calls": 12,                 // 总生成次数
  "success_calls": 10,               // 成功次数
  "failed_calls": 2,                 // 失败次数
  "internal_api_cost": 4.5,          // 总成本（元）
  "average_success_cost": 0.45,      // 平均每次成功的成本（元）
  "configured_image_unit_cost": 0.15 // 当前单张单价（本次新增字段）
}
```

`/platform/billing` 在成本基础上再给出「AI 服务收入 / 内部成本 / 平台毛利」。

### 方式 B：图形化后台页面

双击打开项目里的 `平台后台展示小样_v1.html`（用浏览器）。
它会自动读取上面的接口，把成本、毛利显示成卡片。
**前提**：后端已按第三步启动；否则页面只显示演示假数据。

## 五、成本数字怎么来的、怎么调

- 每次 AI 生成都会在 `ai_generation_jobs` 表里记一笔 `internal_api_cost`。
- 取值规则（本次改造后）：
  1. 如果 Dify / 通义万相工作流回填了真实成本 → 用真实值；
  2. 如果没回填 → 后端按 **图片张数 × 单价** 自算（不再记成 0）。
- 单价由环境变量 `AI_IMAGE_UNIT_COST` 控制，默认 `0.15` 元/张。
  一次生成 3 张图，则每次成本 ≈ 3 × 0.15 = 0.45 元。
- **接通真实通义万相后**：先跑一批真实样本，测出单张真实价，再把
  `AI_IMAGE_UNIT_COST` 改成真实值，所有报表会自动跟着变准。

## 六、看不到数据/报错怎么办

- 浏览器打不开 `127.0.0.1:8000` → 后端没起来，回到第三步；看 `backend\uvicorn.err.log` 里的报错。
- 成本全是 0 → 说明还没有成功的生成记录（demo 数据里可能没有），可在小程序端或用 README 里的 `curl` 跑一次生成再看。
- 想要真实成本而非自算估算 → 需要接通真实通义万相，并在 Dify 工作流里回填成本（见第五节）。
```
```
