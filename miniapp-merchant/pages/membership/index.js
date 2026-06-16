const api = require("../../utils/api");

const PLAN_ORDER = ["trial", "basic", "pro", "enterprise"];

function yuan(value) {
  const n = Number(value || 0);
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

function featureText(features = {}) {
  const rows = [
    { key: "feishu", label: "飞书推送" },
    { key: "weekly_report", label: "周报月报" },
    { key: "stylist_kpi", label: "主理人数据" },
    { key: "multi_store_report", label: "多门店汇总" },
    { key: "member_card", label: "储值会员" },
    { key: "export", label: "数据导出" },
    { key: "api", label: "API 接口" }
  ];
  return rows.map((item) => ({
    ...item,
    enabled: !!features[item.key]
  }));
}

Page({
  data: {
    loading: true,
    subscription: {},
    currentPlan: {},
    plans: [],
    featureRows: [],
    bills: []
  },

  onShow() {
    this.loadData();
  },

  async loadData() {
    const s = api.session();
    this.setData({ loading: true });
    try {
      const [subscription, plansMap, bills] = await Promise.all([
        api.get("/merchant/subscription", { tenant_id: s.tenantId }),
        api.get("/merchant/plans"),
        api.get("/merchant/monthly-bills", { tenant_id: s.tenantId })
      ]);
      const plans = PLAN_ORDER
        .map((key) => plansMap[key])
        .filter(Boolean)
        .map((plan) => ({
          ...plan,
          annualPriceText: yuan(plan.annual_price_yuan),
          overagePriceText: yuan(plan.overage_price_yuan),
          storeLimitText: plan.max_stores === -1 ? "不限门店" : `${plan.max_stores} 家门店`,
          active: plan.plan === subscription.subscription_plan
        }));
      const currentPlan = subscription.plan_info || {};
      this.setData({
        subscription: {
          ...subscription,
          remainingText: Math.max(0, Number(subscription.monthly_ai_remaining || 0)),
          usedText: Number(subscription.monthly_ai_used || 0),
          quotaText: Number(subscription.monthly_ai_quota || 0)
        },
        currentPlan: {
          ...currentPlan,
          annualPriceText: yuan(currentPlan.annual_price_yuan),
          overagePriceText: yuan(currentPlan.overage_price_yuan),
          storeLimitText: currentPlan.max_stores === -1 ? "不限门店" : `${currentPlan.max_stores || 0} 家门店`
        },
        plans,
        featureRows: featureText(currentPlan.features),
        bills: (bills || []).slice(0, 3),
        loading: false
      });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  contactPlatform() {
    wx.showModal({
      title: "联系平台",
      content: "需要升级套餐、购买次数或调整门店额度时，请联系焕发AI平台客服处理。",
      confirmText: "知道了",
      showCancel: false
    });
  },

  goQuota() {
    wx.navigateTo({ url: "/pages/ai-quota/index" });
  },

  goSync() {
    wx.navigateTo({ url: "/pages/sync/index" });
  },

  goWorkbench() {
    wx.navigateTo({ url: "/pages/workbench/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goAssets() {
    wx.navigateTo({ url: "/pages/assets/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/customers/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/performance/index" });
  }
});
