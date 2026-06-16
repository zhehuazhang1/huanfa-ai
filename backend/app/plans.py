"""
订阅计划定义
每个计划的功能限制和配额，改这里即可全局生效。
"""
from __future__ import annotations
from typing import TypedDict


class PlanLimits(TypedDict):
    # 基础配额
    monthly_ai_quota: int       # 兼容旧字段：当前系统仍按月度额度检查
    annual_included_ai_quota: int  # 对外展示：年使用费赠送次数
    overage_price_fen: int      # 超出后每次价格（分）
    max_stores: int             # 门店数量上限
    max_hairstyles: int         # 发型款式上限（-1=无限）
    # 功能开关
    feature_full_history: bool      # 顾客完整历史（False=仅30天）
    feature_feishu: bool            # 飞书日报/周报推送
    feature_weekly_report: bool     # 周报/月报
    feature_stylist_kpi: bool       # 主理人绩效统计
    feature_multi_store_report: bool # 多门店汇总报表
    feature_member_card: bool       # 顾客储值/会员卡
    feature_export: bool            # 数据导出 Excel
    feature_api: bool               # API 开放接口
    # 支持
    support_level: str          # group / 1on1 / dedicated
    sla_hours: int              # 响应时间（小时）
    # 展示
    display_name: str
    monthly_price_fen: int      # 兼容旧字段
    annual_price_fen: int       # 对外展示：年使用费（分）


PLANS: dict[str, PlanLimits] = {
    "trial": {
        "monthly_ai_quota": 30,
        "annual_included_ai_quota": 30,
        "overage_price_fen": 0,
        "max_stores": 1,
        "max_hairstyles": 10,
        "feature_full_history": False,
        "feature_feishu": False,
        "feature_weekly_report": False,
        "feature_stylist_kpi": False,
        "feature_multi_store_report": False,
        "feature_member_card": False,
        "feature_export": False,
        "feature_api": False,
        "support_level": "group",
        "sla_hours": 72,
        "display_name": "免费试用",
        "monthly_price_fen": 0,
        "annual_price_fen": 0,
    },
    "basic": {
        "monthly_ai_quota": 30,
        "annual_included_ai_quota": 30,
        "overage_price_fen": 250,       # ¥2.5/次
        "max_stores": 1,
        "max_hairstyles": 20,
        "feature_full_history": False,  # 仅30天
        "feature_feishu": False,
        "feature_weekly_report": False,
        "feature_stylist_kpi": False,
        "feature_multi_store_report": False,
        "feature_member_card": True,
        "feature_export": False,
        "feature_api": False,
        "support_level": "group",
        "sla_hours": 48,
        "display_name": "基础版",
        "monthly_price_fen": 2500,      # 兼容旧字段：¥300/年折算
        "annual_price_fen": 30000,      # ¥300/年
    },
    "pro": {
        "monthly_ai_quota": 80,
        "annual_included_ai_quota": 80,
        "overage_price_fen": 200,       # ¥2/次
        "max_stores": 3,
        "max_hairstyles": 100,
        "feature_full_history": True,
        "feature_feishu": True,
        "feature_weekly_report": True,
        "feature_stylist_kpi": True,
        "feature_multi_store_report": False,
        "feature_member_card": True,
        "feature_export": True,
        "feature_api": False,
        "support_level": "1on1",
        "sla_hours": 24,
        "display_name": "专业版",
        "monthly_price_fen": 4167,      # 兼容旧字段：¥500/年折算
        "annual_price_fen": 50000,      # ¥500/年
    },
    "enterprise": {
        "monthly_ai_quota": 200,
        "annual_included_ai_quota": 200,
        "overage_price_fen": 150,       # ¥1.5/次
        "max_stores": -1,               # 不限
        "max_hairstyles": -1,
        "feature_full_history": True,
        "feature_feishu": True,
        "feature_weekly_report": True,
        "feature_stylist_kpi": True,
        "feature_multi_store_report": True,
        "feature_member_card": True,
        "feature_export": True,
        "feature_api": True,
        "support_level": "dedicated",
        "sla_hours": 4,
        "display_name": "连锁版",
        "monthly_price_fen": 8334,      # 兼容旧字段：¥1000/年折算
        "annual_price_fen": 100000,     # ¥1,000/年
    },
}

DEFAULT_PLAN = "trial"


def get_plan(plan_key: str | None) -> PlanLimits:
    """安全获取计划配置，未知计划降级为 trial。"""
    return PLANS.get(plan_key or DEFAULT_PLAN, PLANS[DEFAULT_PLAN])


def check_feature(plan_key: str | None, feature: str) -> bool:
    """检查指定计划是否开启某功能。feature 对应 PlanLimits 中 feature_* 的字段名。"""
    plan = get_plan(plan_key)
    return bool(plan.get(f"feature_{feature}", False))


def plan_summary(plan_key: str | None) -> dict:
    """返回可以直接序列化给前端的计划摘要。"""
    p = get_plan(plan_key)
    return {
        "plan": plan_key or DEFAULT_PLAN,
        "display_name": p["display_name"],
        "billing_model": "annual_fee_plus_included_quota_plus_topup",
        "annual_price_yuan": p["annual_price_fen"] / 100,
        "annual_included_ai_quota": p["annual_included_ai_quota"],
        "overage_price_yuan": p["overage_price_fen"] / 100,
        "monthly_price_yuan": p["monthly_price_fen"] / 100,
        "monthly_ai_quota": p["monthly_ai_quota"],
        "max_stores": p["max_stores"],
        "features": {
            "full_history": p["feature_full_history"],
            "feishu": p["feature_feishu"],
            "weekly_report": p["feature_weekly_report"],
            "stylist_kpi": p["feature_stylist_kpi"],
            "multi_store_report": p["feature_multi_store_report"],
            "member_card": p["feature_member_card"],
            "export": p["feature_export"],
            "api": p["feature_api"],
        },
        "support_level": p["support_level"],
        "sla_hours": p["sla_hours"],
    }
