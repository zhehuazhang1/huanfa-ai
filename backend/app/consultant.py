"""
AI 发型咨询师
结构化 5 步问诊 → 发型库智能匹配 → 个性化推荐卡片

流程：
  POST /ai/consultant/start          → 返回第一步问题
  POST /ai/consultant/reply          → 提交回答，返回下一步或最终推荐
  GET  /ai/consultant/session/{sid}  → 查询会话状态（可选）
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# ════════════════════════════════════════════════
#  问诊步骤配置
# ════════════════════════════════════════════════

STEPS: list[dict] = [
    {
        "step_id": "gender",
        "question": "你好！我是你的专属发型顾问 ✨\n先问你几个小问题，帮你找到最适合的发型～\n\n**你是？**",
        "choices": [
            {"label": "👩 女生", "value": "female"},
            {"label": "👨 男生", "value": "male"},
            {"label": "✨ 不限", "value": "neutral"},
        ],
    },
    {
        "step_id": "face_shape",
        "question": "你的**脸型**更像哪种？\n（不确定可以参考下巴和颧骨宽度）",
        "choices": [
            {"label": "椭圆脸 / 鹅蛋脸", "value": "oval"},
            {"label": "圆脸", "value": "round"},
            {"label": "方脸 / 颧骨宽", "value": "square"},
            {"label": "心形脸 / 额头宽", "value": "heart"},
            {"label": "长脸", "value": "long"},
        ],
    },
    {
        "step_id": "length",
        "question": "你想要**什么长度**的发型？",
        "choices": [
            {"label": "短发（耳上）", "value": "short"},
            {"label": "中短发（下颌～肩）", "value": "medium"},
            {"label": "中长发（锁骨以下）", "value": "long"},
            {"label": "都可以，帮我推荐", "value": "any"},
        ],
    },
    {
        "step_id": "style",
        "question": "你更偏向哪种**风格感觉**？",
        "choices": [
            {"label": "🌸 甜美可爱", "value": "sweet"},
            {"label": "🪐 干净帅气", "value": "cool"},
            {"label": "🌿 慵懒随性", "value": "casual"},
            {"label": "🔥 时髦个性", "value": "trendy"},
        ],
    },
    {
        "step_id": "maintenance",
        "question": "早上愿意花多少时间**打理头发**？",
        "choices": [
            {"label": "越省事越好", "value": "low"},
            {"label": "10～15 分钟都行", "value": "medium"},
            {"label": "为了好看不介意多整", "value": "high"},
        ],
    },
]

TOTAL_STEPS = len(STEPS)

# ════════════════════════════════════════════════
#  标签映射（决定发型匹配权重）
# ════════════════════════════════════════════════

_FACE_TAGS: dict[str, list[str]] = {
    "oval":   ["natural", "face shaping", "korean", "fresh"],
    "round":  ["slim face", "face shaping", "longer", "layered"],
    "square": ["soft", "sweet", "slim face", "layered"],
    "heart":  ["natural", "korean", "sweet", "bangs"],
    "long":   ["natural", "volume", "bangs", "soft"],
}

_STYLE_TAGS: dict[str, list[str]] = {
    "sweet":  ["sweet", "korean", "soft", "younger look"],
    "cool":   ["fresh", "clean", "business", "crisp"],
    "casual": ["natural", "casual", "japanese", "low maintenance"],
    "trendy": ["trendy", "bold", "younger look", "fresh"],
}

_MAINTENANCE_TAGS: dict[str, list[str]] = {
    "low":    ["low maintenance", "natural"],
    "medium": [],
    "high":   ["styled", "perm", "textured"],
}

# ════════════════════════════════════════════════
#  推荐理由模板（脸型 × 风格）
# ════════════════════════════════════════════════

_REASON_MATRIX: dict[tuple[str, str], str] = {
    ("oval",   "sweet"):  "椭圆脸天然百搭，甜美线条更突出你的柔和气质，减龄又显嫩 ✨",
    ("oval",   "cool"):   "鹅蛋脸配干净利落的线条，帅气感一分不损，早上五分钟出门",
    ("oval",   "casual"): "椭圆脸不挑发型，慵懒随性款自然大方，越随意越好看",
    ("oval",   "trendy"): "你的脸型驾驭个性款毫无压力，走哪都是回头率 🔥",
    ("round",  "sweet"):  "圆脸甜美感本来就强，纵向拉长发型叠加效果翻倍，精致可爱 💕",
    ("round",  "cool"):   "圆脸做干净帅气款有惊喜感，小脸错觉拉满",
    ("round",  "casual"): "圆脸做自然慵懒款，亲切感满分，没有距离感",
    ("round",  "trendy"): "圆脸做时髦款反差感超强，越个性越好看 ✨",
    ("square", "sweet"):  "方脸做甜美款能柔化棱角，增加女性气息，气质大变 🌸",
    ("square", "cool"):   "方脸和利落干净的线条是绝配，气场强到爆",
    ("square", "casual"): "方脸做自然随性款，不刻意反而更耐看，很有品位",
    ("square", "trendy"): "方脸时髦款视觉冲击力极强，个性十足，一眼难忘",
    ("heart",  "sweet"):  "心形脸做甜美款减龄感极强，像从漫画里走出来的 🌸",
    ("heart",  "cool"):   "心形脸配干净利落感，文艺清冷气息拉满",
    ("heart",  "casual"): "心形脸随性自然款，走路都带风，轻松又好看",
    ("heart",  "trendy"): "心形脸额头饱满，时髦款把优势发挥到极致 🔥",
    ("long",   "sweet"):  "长脸做甜美款横向蓬松感增加，脸感更精致，比例完美 ✨",
    ("long",   "cool"):   "长脸配干净帅气款，整体比例优雅，有一种高级感",
    ("long",   "casual"): "长脸慵懒款蓬松自然，显得很有生活感，非常耐看",
    ("long",   "trendy"): "长脸做个性款有独特高级感，时髦又不失辨识度",
}

_STYLE_LABEL: dict[str, str] = {
    "sweet": "甜美",
    "cool": "帅气",
    "casual": "随性",
    "trendy": "时髦",
}

_FACE_LABEL: dict[str, str] = {
    "oval": "椭圆脸",
    "round": "圆脸",
    "square": "方脸",
    "heart": "心形脸",
    "long": "长脸",
}


def _make_reason(face: str, style: str, style_name: str, maintenance: str) -> str:
    base = _REASON_MATRIX.get(
        (face, style),
        f"非常适合你的{_STYLE_LABEL.get(style, style_name)}风格，会让你焕然一新 ✨",
    )
    if maintenance == "low":
        base += "  日常打理也超省事。"
    return base


# ════════════════════════════════════════════════
#  会话数据结构
# ════════════════════════════════════════════════

@dataclass
class ConsultSession:
    session_id: str
    tenant_id: int
    store_id: int
    user_id: int
    current_step: int = 0          # 0..TOTAL_STEPS; TOTAL_STEPS 表示完成
    answers: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ConsultSession":
        return ConsultSession(**d)


# ════════════════════════════════════════════════
#  服务类
# ════════════════════════════════════════════════

class ConsultantService:
    """
    无状态服务——会话持久化在 Redis；如果 Redis 不可用则降级到进程内字典。
    """

    SESSION_TTL = 7200  # 2 小时
    MAX_RECOMMENDATIONS = 3

    def __init__(self, store: Any, redis_url: str | None = None) -> None:
        self._store = store          # AppStore，用于查询发型库
        self._redis: Any | None = None
        self._mem: dict[str, str] = {}   # 降级内存缓存

        if redis_url:
            try:
                import redis as redis_lib
                self._redis = redis_lib.Redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None

    # ── 会话存取 ──────────────────────────────

    def _save(self, session: ConsultSession) -> None:
        payload = json.dumps(session.to_dict(), ensure_ascii=False)
        key = f"consult:{session.session_id}"
        if self._redis:
            self._redis.setex(key, self.SESSION_TTL, payload)
        else:
            self._mem[key] = payload

    def _load(self, session_id: str) -> ConsultSession | None:
        key = f"consult:{session_id}"
        raw = self._redis.get(key) if self._redis else self._mem.get(key)
        if raw is None:
            return None
        return ConsultSession.from_dict(json.loads(raw))

    # ── 公开接口 ──────────────────────────────

    def start(self, *, tenant_id: int, store_id: int, user_id: int) -> dict:
        """新建会话，返回第一步问题。"""
        session = ConsultSession(
            session_id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
        )
        self._save(session)
        return self._step_response(session)

    def reply(self, *, session_id: str, choice: str) -> dict:
        """
        提交当前步骤的选择。
        返回下一步问题，或（最后一步后）发型推荐列表。
        """
        session = self._load(session_id)
        if session is None:
            raise ValueError("会话不存在或已过期，请重新开始")

        if session.current_step >= TOTAL_STEPS:
            # 已完成，直接返回推荐
            return self._recommend_response(session)

        step_def = STEPS[session.current_step]
        valid_values = {c["value"] for c in step_def["choices"]}
        if choice not in valid_values:
            raise ValueError(f"无效选项 '{choice}'，可选：{sorted(valid_values)}")

        session.answers[step_def["step_id"]] = choice
        session.current_step += 1

        if session.current_step >= TOTAL_STEPS:
            session.completed_at = datetime.utcnow().isoformat()
            self._save(session)
            return self._recommend_response(session)

        self._save(session)
        return self._step_response(session)

    def get_session(self, session_id: str) -> dict | None:
        s = self._load(session_id)
        return s.to_dict() if s else None

    # ── 内部：构建步骤响应 ─────────────────────

    def _step_response(self, session: ConsultSession) -> dict:
        step = STEPS[session.current_step]
        progress = session.current_step          # 0-based, 0..TOTAL_STEPS-1
        return {
            "session_id": session.session_id,
            "status": "in_progress",
            "progress": progress,
            "total_steps": TOTAL_STEPS,
            "step_id": step["step_id"],
            "message": step["question"],
            "choices": step["choices"],
            "recommendations": None,
        }

    # ── 内部：发型匹配与推荐 ──────────────────

    def _recommend_response(self, session: ConsultSession) -> dict:
        recs = self._match_styles(session)
        face = session.answers.get("face_shape", "oval")
        style = session.answers.get("style", "casual")
        maintenance = session.answers.get("maintenance", "medium")
        style_name = _STYLE_LABEL.get(style, style)
        face_name = _FACE_LABEL.get(face, face)

        opener = (
            f"根据你的情况（{face_name}、{style_name}风格），"
            f"我为你精选了 {len(recs)} 款最适合的发型 👇"
        )

        cards = []
        for i, rec in enumerate(recs):
            reason = _make_reason(face, style, style_name, maintenance)
            cards.append({
                "rank": i + 1,
                "style_id":      rec["id"],
                "style_name":    rec["name"],
                "hair_length":   rec["hair_length"],
                "direction":     rec["direction"],
                "thumbnail_url": rec.get("thumbnail_url"),
                "display_tags":  rec.get("display_tags_list", []),
                "reason":        reason,
                "match_score":   rec["_score"],
                "cta": {
                    "type":     "try_on",
                    "label":    "立即试穿 →",
                    "style_id": rec["id"],
                },
            })

        return {
            "session_id":    session.session_id,
            "status":        "completed",
            "progress":      TOTAL_STEPS,
            "total_steps":   TOTAL_STEPS,
            "step_id":       None,
            "message":       opener,
            "choices":       None,
            "recommendations": cards,
            "answers_summary": self._answers_summary(session.answers),
        }

    def _answers_summary(self, answers: dict) -> dict:
        return {
            "gender":     answers.get("gender"),
            "face_shape": _FACE_LABEL.get(answers.get("face_shape", ""), answers.get("face_shape")),
            "length":     answers.get("length"),
            "style":      _STYLE_LABEL.get(answers.get("style", ""), answers.get("style")),
            "maintenance": answers.get("maintenance"),
        }

    def _match_styles(self, session: ConsultSession) -> list[dict]:
        gender = session.answers.get("gender", "neutral")
        length_pref = session.answers.get("length", "any")
        face = session.answers.get("face_shape", "oval")
        style = session.answers.get("style", "casual")
        maintenance = session.answers.get("maintenance", "medium")

        # 构建目标标签集合（权重 = 出现次数）
        target_tags: list[str] = (
            _FACE_TAGS.get(face, [])
            + _STYLE_TAGS.get(style, [])
            + _MAINTENANCE_TAGS.get(maintenance, [])
        )

        # 查询发型库
        rows = self._store.rows(
            "SELECT * FROM hairstyles WHERE is_enabled = 1",
            (),
        )

        scored: list[dict] = []
        for row in rows:
            r = dict(row)

            # 方向过滤（宽松：neutral 款对所有人可见）
            direction = r.get("direction", "neutral")
            if gender != "neutral" and direction != "neutral" and direction != gender:
                continue

            # 长度过滤
            if length_pref != "any" and r.get("hair_length") != length_pref:
                continue

            # 标签评分
            try:
                style_tags: list[str] = json.loads(r.get("display_tags") or "[]")
            except (json.JSONDecodeError, TypeError):
                style_tags = []

            style_tags_lower = [t.lower() for t in style_tags]
            score = sum(
                style_tags_lower.count(t.lower())
                for t in target_tags
            )
            # 加权：推荐款 +2
            if r.get("is_recommended"):
                score += 2

            r["_score"] = score
            r["display_tags_list"] = style_tags
            scored.append(r)

        # 按得分降序，取前 N 款
        scored.sort(key=lambda x: x["_score"], reverse=True)

        # 如果不足 3 款（过滤太严），放宽长度限制补齐
        if len(scored) < self.MAX_RECOMMENDATIONS and length_pref != "any":
            extras = []
            existing_ids = {r["id"] for r in scored}
            for row in rows:
                r = dict(row)
                if r["id"] in existing_ids:
                    continue
                direction = r.get("direction", "neutral")
                if gender != "neutral" and direction != "neutral" and direction != gender:
                    continue
                try:
                    style_tags = json.loads(r.get("display_tags") or "[]")
                except (json.JSONDecodeError, TypeError):
                    style_tags = []
                style_tags_lower = [t.lower() for t in style_tags]
                score = sum(style_tags_lower.count(t.lower()) for t in target_tags)
                if r.get("is_recommended"):
                    score += 2
                r["_score"] = score
                r["display_tags_list"] = style_tags
                extras.append(r)
            extras.sort(key=lambda x: x["_score"], reverse=True)
            scored.extend(extras)

        return scored[: self.MAX_RECOMMENDATIONS]


# ════════════════════════════════════════════════
#  工厂函数
# ════════════════════════════════════════════════

def build_consultant_from_env(store: Any) -> ConsultantService:
    redis_url = os.getenv("REDIS_URL")
    return ConsultantService(store=store, redis_url=redis_url)
