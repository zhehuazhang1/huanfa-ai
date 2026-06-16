const api = require("../../utils/api");

Page({
  data: {
    scope: "store",
    scopeOptions: [
      { label: "全店", value: "store" },
      { label: "我的", value: "mine" }
    ],
    period: "day",
    periodIndex: 0,
    currentPeriodLabel: "今日",
    periodOptions: [
      { label: "今日", value: "day" },
      { label: "本周", value: "week" },
      { label: "本月", value: "month" }
    ],
    performance: {
      totals: {},
      ai_conversion: {},
      by_category: [],
      by_stylist: [],
      by_service: []
    },
    categoryText: {
      haircut: "剪发",
      color: "染发",
      perm: "烫发",
      styling: "造型",
      care: "护理"
    },
    serviceNameText: {
      Haircut: "剪发",
      Color: "染发",
      Perm: "烫发",
      Styling: "造型",
      Care: "护理",
      "ç¾å®¹": "美容"
    },
    serviceTypes: []
  },

  onShow() {
    this.loadPerformance();
  },

  async loadPerformance() {
    const s = api.session();
    try {
      const performance = await api.get("/merchant/performance", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        stylist_id: this.data.scope === "mine" ? s.staffId : "",
        period: this.data.period,
        offset: 0
      });
      const decorated = this.decoratePerformance(performance);
      this.setData({
        performance: decorated
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  changeScope(event) {
    const scope = event.currentTarget.dataset.scope;
    if (!scope || scope === this.data.scope) return;
    this.setData({ scope });
    this.loadPerformance();
  },

  changePeriod(event) {
    const periodIndex = Number(event.detail.value || 0);
    const selected = this.data.periodOptions[periodIndex] || this.data.periodOptions[0];
    const period = selected.value;
    if (!period || period === this.data.period) return;
    this.setData({
      period,
      periodIndex,
      currentPeriodLabel: selected.label
    });
    this.loadPerformance();
  },

  decoratePerformance(performance) {
    const conversion = performance.ai_conversion || {};
    const byCategory = (performance.by_category || []).map((item) => ({
      ...item,
      categoryLabel: this.data.categoryText[item.category] || item.category,
      aiRateText: `${Math.round(((item.ai_converted_services || 0) / Math.max(item.completed_services || 0, 1)) * 100)}%`
    }));
    const byService = (performance.by_service || []).map((item) => ({
      ...item,
      displayName: this.data.serviceNameText[item.service_name] || item.service_name,
      categoryLabel: this.data.categoryText[item.category] || item.category
    }));
    const byStylist = (performance.by_stylist || []).map((item) => ({
      ...item,
      performanceText: `预计绩效 ¥${item.estimated_performance || 0}`
    }));
    this.setData({
      serviceTypes: byService.map((item) => ({
        key: item.service_name,
        label: item.displayName,
        completed_services: item.completed_services,
        revenue: item.revenue,
        ai_converted_services: item.ai_converted_services
      }))
    });
    return {
      ...performance,
      ai_conversion: {
        ...conversion,
        orderRateText: `${Math.round((conversion.order_conversion_rate || 0) * 100)}%`,
        serviceRateText: `${Math.round((conversion.service_conversion_rate || 0) * 100)}%`
      },
      by_category: byCategory,
      by_stylist: byStylist,
      by_service: byService
    };
  },

  goWorkbench() {
    wx.navigateTo({ url: "/pages/merchant-workbench/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/merchant-orders/index" });
  },

  goQuota() {
    wx.navigateTo({ url: "/pages/merchant-ai-quota/index" });
  },

  goAssets() {
    wx.navigateTo({ url: "/pages/merchant-assets/index" });
  },

  goStaff() {
    wx.navigateTo({ url: "/pages/merchant-staff/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/merchant-customers/index" });
  }
});
