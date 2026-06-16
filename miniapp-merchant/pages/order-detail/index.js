const api = require("../../utils/api");

Page({
  data: {
    orderId: 0,
    order: {},
    loading: false,
    statusText: {
      pending: "待确认",
      confirmed: "已确认",
      arrived: "已到店",
      serving: "服务中",
      completed: "已完成",
      cancelled: "已取消"
    }
  },

  onLoad(options = {}) {
    this.setData({ orderId: Number(options.order_id || 0) });
  },

  onShow() {
    this.loadOrder();
  },

  async loadOrder() {
    if (!this.data.orderId) return;
    const s = api.session();
    this.setData({ loading: true });
    try {
      const order = await api.get(`/merchant/orders/${this.data.orderId}`, {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      this.setData({ order: this.decorateOrder(order) });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  decorateOrder(order) {
    return {
      ...order,
      statusLabel: this.data.statusText[order.status] || order.status || "待确认",
      customerText: `${order.customer_name || "顾客"} ${order.customer_phone || ""}`,
      stylistText: order.stylist_name || "未分配",
      appointmentText: order.appointment_time || "到店沟通",
      hairstyleText: order.hairstyle_name || (order.hairstyle_id ? "已选择方案" : "未选择"),
      hairColorText: order.hair_color_name || (order.hair_color_id ? "已选择发色" : "未选择"),
      serviceItemText: order.service_item_name || "到店沟通",
      sourceText: order.is_ai_converted ? "AI试发转化" : "普通预约",
      notesText: order.notes || "暂无备注"
    };
  },

  async updateStatus(event) {
    const status = event.currentTarget.dataset.status;
    if (!status) return;
    const s = api.session();
    try {
      await api.put(`/merchant/orders/${this.data.orderId}/status`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        status
      });
      wx.showToast({ title: "已更新", icon: "success" });
      this.loadOrder();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  goBack() {
    wx.navigateBack();
  }
});
