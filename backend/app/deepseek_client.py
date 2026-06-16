"""
DeepSeek V3 客户端 — 发型顾问专用
OpenAI 兼容协议，按 token 计费追踪，支持多轮对话
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 定价（元/token，汇率 7.2）
_PRICE_INPUT_YUAN   = 0.27 * 7.2 / 1_000_000   # ¥0.000001944
_PRICE_CACHE_YUAN   = 0.07 * 7.2 / 1_000_000   # ¥0.000000504（缓存命中）
_PRICE_OUTPUT_YUAN  = 1.10 * 7.2 / 1_000_000   # ¥0.00000792

# 系统提示词模板（静态部分尽量靠前，利于 prefix cache）
_SYSTEM_TEMPLATE = """\
你是「焕发AI」的专属发型顾问，名叫「小焕」，服务于一家专业美发门店。

## 专业知识
脸型适配：椭圆脸百搭；圆脸需纵向拉长感；方脸需柔化棱角；心形脸避免头顶过蓬；长脸需增加横向宽度。
发质影响：细软发适合轻盈款；粗硬发适合有层次款；自然卷可顺势而为；受损发优先修护。
场景匹配：职场偏利落；日常偏自然；约会偏精致；学生偏清爽。

## 问诊顺序（顾客问发型建议时主动引导）
脸型 → 发质 → 风格偏好（甜美/帅气/随性/时髦）→ 日常场景 → 打理时间

## 回复规范
1. 语气亲切自然，每条回复≤120字，一次只问一个问题
2. 推荐发型时末尾加标记：[推荐试穿:{{style_id}}]（用发型库中的真实id，如 [推荐试穿:1]）
3. 顾客有预约意向时末尾加：[引导预约]
4. 引导 AI 试发时末尾加：[引导试发]
5. 价格说"到店确认"，不承诺具体数字

## 门店信息
{store_info}

## 门店发型库
{hairstyle_list}

## 门店知识库（常见问答）
{knowledge_items}\
"""


def build_system_prompt(
    *,
    store_name: str = "",
    store_address: str = "",
    services: list[dict] | None = None,
    hairstyles: list[dict] | None = None,
    knowledge_items: list[dict] | None = None,
) -> str:
    store_lines = [f"门店名称：{store_name or '专业美发门店'}"]
    if store_address:
        store_lines.append(f"地址：{store_address}")
    if services:
        names = [s.get("name") or s.get("category") or "" for s in services[:6]]
        store_lines.append("服务项目：" + "、".join(n for n in names if n))

    style_lines = []
    for s in (hairstyles or [])[:15]:
        length_map = {"short": "短发", "medium": "中发", "long": "长发"}
        length = length_map.get(s.get("hair_length", ""), "")
        tags = "、".join((s.get("display_tags") or [])[:3])
        style_lines.append(f"· [{s['id']}] {s.get('style_name') or s.get('name')}（{length}，{tags}）")

    kn_lines = []
    for k in (knowledge_items or [])[:8]:
        kn_lines.append(f"Q：{k.get('question','')}\nA：{k.get('answer','')}")

    return _SYSTEM_TEMPLATE.format(
        store_info="\n".join(store_lines),
        hairstyle_list="\n".join(style_lines) if style_lines else "（暂无发型库数据）",
        knowledge_items="\n\n".join(kn_lines) if kn_lines else "（暂无知识库数据）",
    )


def parse_actions(text: str) -> list[dict]:
    """从 AI 回复中提取动作标记。"""
    actions: list[dict] = []
    for m in re.finditer(r"\[推荐试穿:(\d+)\]", text):
        actions.append({"type": "try_on", "style_id": int(m.group(1)), "label": "立即试穿"})
    if "[引导预约]" in text:
        actions.append({"type": "create_order", "label": "预约主理人"})
    if "[引导试发]" in text:
        actions.append({"type": "start_ai_style", "label": "开始AI试发"})
    return actions


def clean_reply(text: str) -> str:
    """去掉回复中的动作标记，只留可读文字。"""
    text = re.sub(r"\[推荐试穿:\d+\]", "", text)
    text = re.sub(r"\[引导预约\]", "", text)
    text = re.sub(r"\[引导试发\]", "", text)
    return text.strip()


def calc_cost_fen(
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
) -> int:
    """
    返回本次调用成本（分）。
    cached_tokens 是命中缓存的输入 token 数（从 usage.prompt_cache_hit_tokens 读）。
    """
    fresh_tokens = prompt_tokens - cached_tokens
    cost_yuan = (
        fresh_tokens * _PRICE_INPUT_YUAN
        + cached_tokens * _PRICE_CACHE_YUAN
        + completion_tokens * _PRICE_OUTPUT_YUAN
    )
    return max(1, round(cost_yuan * 100))  # 至少 1 分，避免记 0


class DeepSeekClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def chat(
        self,
        *,
        messages: list[dict],
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> dict:
        """
        调用 DeepSeek，返回：
        {
          "content": str,          # 完整回复原文（含标记）
          "reply": str,            # 去掉标记的干净文字
          "actions": list[dict],   # 解析出的动作
          "prompt_tokens": int,
          "cached_tokens": int,
          "completion_tokens": int,
          "cost_fen": int,         # 本次成本（分）
        }
        """
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API error {e.code}: {err[:200]}") from e

        choice = data["choices"][0]
        content = choice["message"]["content"]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        cached_tokens = usage.get("prompt_cache_hit_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        return {
            "content": content,
            "reply": clean_reply(content),
            "actions": parse_actions(content),
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "completion_tokens": completion_tokens,
            "cost_fen": calc_cost_fen(prompt_tokens, cached_tokens, completion_tokens),
        }


def build_deepseek_from_env() -> DeepSeekClient | None:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    return DeepSeekClient(api_key=key)

