const api = require("../../utils/api");

Page({
  data: {
    loading: false,
    membership: {},
    packages: [],
    transactions: []
  },

  onShow() {
    this.loadMembership();
  },

  async loadMembership() {
    const session = api.getSession();
    this.setData({ loading: true });
    try {
      const data = await api.get("/me/membership", {
        tenant_id: session.tenantId,
        store_id: session.storeId
      });
      const membership = data.membership || {};
      this.setData({
        membership,
        transactions: membership.transactions || [],
        packages: (data.packages || []).map((item) => this.decoratePackage(item))
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  decoratePackage(item) {
    const itemText = (item.items || [])
      .map((service) => `${service.service_name || service.name || "服务"} 剩余 ${service.remaining_count || 0}/${service.total_count || 0} 次`)
      .join(" / ");
    return {
      ...item,
      itemText: itemText || "暂无服务明细",
      statusText: item.status === "active" ? "可用" : item.status === "used_up" ? "已用完" : item.status || "未知"
    };
  },

  goHome() {
    wx.navigateTo({ url: "/pages/home/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goStyle() {
    wx.navigateTo({ url: "/pages/style/index" });
  },

  goChat() {
    wx.navigateTo({ url: "/pages/ai-chat/index" });
  },

  goMe() {
    wx.navigateTo({ url: "/pages/me/index" });
  }
});
