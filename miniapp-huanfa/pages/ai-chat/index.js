const api = require("../../utils/api");

Page({
  data: {
    message: "",
    sending: false,
    scrollInto: "",
    quickPrompts: ["我适合什么发型？", "这个发色需要漂吗？", "大概多少钱？", "怎么预约主理人？"],
    messages: [
      { id: 1, role: "assistant", text: "你好，我可以帮你了解适合的发型发色、价格参考和预约建议。" }
    ]
  },

  onShow() {
    const pendingOrder = wx.getStorageSync("pending_order_contact");
    if (!pendingOrder || !pendingOrder.orderId) return;
    wx.removeStorageSync("pending_order_contact");
    const text = [
      "我想咨询这笔预约：",
      `订单号 ${pendingOrder.orderId}`,
      `预约时间 ${pendingOrder.appointmentTime || "到店沟通"}`,
      `主理人 ${pendingOrder.stylistName || "到店分配"}`,
      `当前状态 ${pendingOrder.status || "待确认"}`
    ].join("\n");
    const userMsg = { id: Date.now(), role: "user", text };
    const assistantMsg = {
      id: Date.now() + 1,
      role: "assistant",
      text: "收到，我会结合这笔预约帮你沟通。你可以问到店时间、服务项目、价格范围或想调整的发型发色。"
    };
    this.setData({
      messages: [...this.data.messages, userMsg, assistantMsg],
      scrollInto: `msg-${assistantMsg.id}`
    });
  },

  onInput(event) {
    this.setData({ message: event.detail.value });
  },

  sendQuick(event) {
    this.setData({ message: event.currentTarget.dataset.text || "" });
    this.sendMessage();
  },

  async sendMessage() {
    if (this.data.sending) return;
    const text = this.data.message.trim();
    if (!text) return;
    const session = api.getSession();
    const userMsg = { id: Date.now(), role: "user", text };
    this.setData({
      message: "",
      sending: true,
      messages: [...this.data.messages, userMsg]
    });
    try {
      const answer = await api.post("/ai/chat", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId,
        message: text
      });
      const assistantMsg = {
        id: Date.now() + 1,
        role: "assistant",
        text: answer.answer,
        actions: this.decorateActions(answer.actions || [])
      };
      this.setData({
        messages: [...this.data.messages, assistantMsg],
        scrollInto: `msg-${assistantMsg.id}`
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ sending: false });
    }
  },

  decorateActions(actions) {
    return actions
      .map((item) => {
        const type = item.type || "";
        const actionMap = {
          create_order: { label: item.label || "去预约", target: "booking" },
          start_ai_style: { label: item.label || "开始AI试发", target: "style" },
          view_services: { label: item.label || "查看预约", target: "orders" },
          contact_store: { label: item.label || "联系门店", target: "orders" },
          view_hairstyles: { label: item.label || "查看发型", target: "style" },
          view_hair_colors: { label: item.label || "查看发色", target: "style_colors" }
        };
        const mapped = actionMap[type];
        return mapped ? { ...mapped, type } : null;
      })
      .filter(Boolean);
  },

  handleAction(event) {
    const target = event.currentTarget.dataset.target;
    if (target === "booking") {
      wx.navigateTo({ url: "/pages/booking/index" });
      return;
    }
    if (target === "style_colors") {
      wx.navigateTo({ url: "/pages/style/index?category=colors" });
      return;
    }
    if (target === "style") {
      wx.navigateTo({ url: "/pages/style/index" });
      return;
    }
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goHome() {
    wx.navigateTo({ url: "/pages/home/index" });
  },

  goStyle() {
    wx.navigateTo({ url: "/pages/style/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goMember() {
    wx.navigateTo({ url: "/pages/member/index" });
  },

  goMe() {
    wx.navigateTo({ url: "/pages/me/index" });
  }
});
