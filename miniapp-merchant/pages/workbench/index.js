const api = require("../../utils/api");

Page({
  data: {
    workbench: {}
  },

  onShow() {
    this.loadWorkbench();
  },

  async loadWorkbench() {
    const s = api.session();
    try {
      const workbench = await api.get("/merchant/workbench", {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      this.setData({ workbench });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goManualService() {
    wx.navigateTo({ url: "/pages/manual-service/index" });
  },

  goQuota() {
    wx.navigateTo({ url: "/pages/ai-quota/index" });
  },

  goMembership() {
    wx.navigateTo({ url: "/pages/membership/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/performance/index" });
  },

  goAssets() {
    wx.navigateTo({ url: "/pages/assets/index" });
  },

  goStaff() {
    wx.navigateTo({ url: "/pages/staff/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/customers/index" });
  },

  goServices() {
    wx.navigateTo({ url: "/pages/services/index" });
  },

  goMarketing() {
    wx.navigateTo({ url: "/pages/marketing/index" });
  },

  goSync() {
    wx.navigateTo({ url: "/pages/sync/index" });
  },

  goStoreSettings() {
    wx.navigateTo({ url: "/pages/store-settings/index" });
  },

  goKnowledge() {
    wx.navigateTo({ url: "/pages/knowledge/index" });
  }
});
