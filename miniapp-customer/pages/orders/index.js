const api = require("../../utils/api");

Page({
  data: {
    status: "",
    orders: [],
    statuses: [
      { label: "全部", value: "" },
      { label: "待确认", value: "pending" },
      { label: "已确认", value: "confirmed" },
      { label: "已到店", value: "arrived" },
      { label: "服务中", value: "serving" },
      { label: "已完成", value: "completed" }
    ],
    statusText: {
      pending: "待确认",
      confirmed: "已确认",
      arrived: "已到店",
      serving: "服务中",
      completed: "已完成",
      cancelled: "已取消"
    },
    directionText: {
      female: "女性",
      male: "男性",
      neutral: "中性"
    }
  },

  onShow() {
    this.loadOrders();
  },

  changeStatus(event) {
    this.setData({ status: event.currentTarget.dataset.value });
    this.loadOrders();
  },

  async loadOrders() {
    const session = api.getSession();
    try {
      const orders = await api.get("/orders", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId,
        status: this.data.status
      });
      this.setData({ orders: orders.map((item) => this.decorateOrder(item)) });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  decorateOrder(order) {
    return {
      ...order,
      hairstyleText: order.hairstyle_name || (order.hairstyle_id ? "已选择方案" : "未选择"),
      hairColorText: order.hair_color_name || (order.hair_color_id ? "已选择发色" : "未选择"),
      serviceItemText: order.service_item_name || "到店沟通",
      appointmentText: order.appointment_time || "到店沟通",
      sourceText: order.is_ai_converted ? "AI试发预约" : "普通预约",
      statusLabel: this.data.statusText[order.status] || order.status || "待确认",
      directionLabel: this.data.directionText[order.direction] || order.direction || "未填"
    };
  },

  findOrder(orderId) {
    return this.data.orders.find((item) => String(item.id) === String(orderId));
  },

  showOrderDetail(event) {
    const order = this.findOrder(event.currentTarget.dataset.id);
    if (!order) {
      wx.showToast({ title: "未找到预约", icon: "none" });
      return;
    }
    const lines = [
      `状态：${order.statusLabel}`,
      `门店：${order.store_name || "门店"}`,
      `主理人：${order.stylist_name || "到店分配"}`,
      `预约时间：${order.appointmentText}`,
      `方向：${order.directionLabel}`,
      `发型：${order.hairstyleText}`,
      `发色：${order.hairColorText}`,
      order.notes ? `备注：${order.notes}` : "",
      `订单号：${order.id}`
    ].filter(Boolean);
    wx.showModal({
      title: "预约详情",
      content: lines.join("\n"),
      confirmText: "知道了",
      showCancel: false
    });
  },

  contactStore(event) {
    const order = this.findOrder(event.currentTarget.dataset.id);
    if (order) {
      wx.setStorageSync("pending_order_contact", {
        orderId: order.id,
        storeName: order.store_name || "门店",
        appointmentTime: order.appointmentText,
        stylistName: order.stylist_name || "到店分配",
        status: order.statusLabel
      });
    }
    this.goChat();
  },

  goHome() {
    wx.navigateTo({ url: "/pages/home/index" });
  },

  goStyle() {
    wx.navigateTo({ url: "/pages/style/index" });
  },

  goBooking() {
    wx.navigateTo({ url: "/pages/booking/index" });
  },

  goMember() {
    wx.navigateTo({ url: "/pages/member/index" });
  },

  goChat() {
    wx.navigateTo({ url: "/pages/ai-chat/index" });
  },

  goMe() {
    wx.navigateTo({ url: "/pages/me/index" });
  }
});
