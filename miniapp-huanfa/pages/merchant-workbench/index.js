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
    wx.navigateTo({ url: "/pages/merchant-orders/index" });
  },

  goManualService() {
    wx.navigateTo({ url: "/pages/merchant-manual-service/index" });
  },

  goQuota() {
    wx.navigateTo({ url: "/pages/merchant-ai-quota/index" });
  },

  goMembership() {
    wx.navigateTo({ url: "/pages/merchant-membership/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/merchant-performance/index" });
  },

  goAssets() {
    wx.navigateTo({ url: "/pages/merchant-assets/index" });
  },

  goStaff() {
    wx.navigateTo({ url: "/pages/merchant-staff/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/merchant-customers/index" });
  },

  goServices() {
    wx.navigateTo({ url: "/pages/merchant-services/index" });
  },

  goMarketing() {
    wx.navigateTo({ url: "/pages/merchant-marketing/index" });
  },

  goSync() {
    wx.navigateTo({ url: "/pages/merchant-sync/index" });
  },

  goStoreSettings() {
    wx.navigateTo({ url: "/pages/merchant-store-settings/index" });
  },

  goKnowledge() {
    wx.navigateTo({ url: "/pages/merchant-knowledge/index" });
  }
});
