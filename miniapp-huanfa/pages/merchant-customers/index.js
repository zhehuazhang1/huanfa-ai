const api = require("../../utils/api");

Page({
  data: {
    viewMode: "today_active", // today_active | all
    keyword: "",
    status: "all",
    customers: [],
    statusOptions: [
      { label: "全部", value: "all" },
      { label: "到店", value: "in_store" },
      { label: "已试发", value: "trialed" },
      { label: "已预约", value: "booked" },
      { label: "有赠送", value: "gifted" }
    ],
    statusText: {
      pending: "待确认",
      confirmed: "已确认",
      arrived: "已到店",
      serving: "服务中",
      completed: "已完成",
      cancelled: "已取消"
    }
  },

  onShow() {
    this.loadCustomers();
  },

  onKeywordInput(event) {
    this.setData({ keyword: event.detail.value });
  },

  changeView(event) {
    const mode = event.currentTarget.dataset.mode;
    if (mode === this.data.viewMode) return;
    this.setData({
      viewMode: mode,
      status: mode === "today_active" ? "today_active" : "all"
    });
    this.loadCustomers();
  },

  changeStatus(event) {
    this.setData({ status: event.currentTarget.dataset.status });
    this.loadCustomers();
  },

  async loadCustomers() {
    const s = api.session();
    try {
      const customers = await api.get("/merchant/customers", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        status: this.data.viewMode === "today_active" ? "today_active" : this.data.status,
        keyword: this.data.keyword
      });
      this.setData({
        customers: customers.map((item) => ({
          ...item,
          avatarText: (item.display_name || "顾").slice(0, 1)
        }))
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async giftAi(event) {
    const s = api.session();
    const customerId = Number(event.currentTarget.dataset.id);
    try {
      await api.post("/merchant/ai/gift", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        customer_id: customerId,
        staff_id: s.staffId
      });
      wx.showToast({ title: "已赠送", icon: "success" });
      this.loadCustomers();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  // 停用 / 恢复
  async toggleDisable(event) {
    const s = api.session();
    const customerId = Number(event.currentTarget.dataset.id);
    const isDisabled = event.currentTarget.dataset.disabled === true ||
                       event.currentTarget.dataset.disabled === "true";
    const newStatus = isDisabled ? "active" : "disabled";
    const label = isDisabled ? "恢复" : "停用";

    wx.showModal({
      title: `${label}顾客`,
      content: isDisabled
        ? "确定要恢复该顾客账号吗？恢复后顾客可正常使用。"
        : "确定要停用该顾客账号吗？停用后顾客将无法登录。",
      confirmText: label,
      confirmColor: isDisabled ? "#01261f" : "#d14343",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await api.put(`/merchant/customers/${customerId}/status`, {
            tenant_id: s.tenantId,
            store_id: s.storeId,
            status: newStatus
          });
          wx.showToast({ title: `已${label}`, icon: "success" });
          this.loadCustomers();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  // 删除顾客
  async deleteCustomer(event) {
    const s = api.session();
    const customerId = Number(event.currentTarget.dataset.id);

    wx.showModal({
      title: "删除顾客",
      content: "删除后顾客将无法登录，历史数据（试发记录、订单）仍保留。此操作不可撤销。",
      confirmText: "删除",
      confirmColor: "#d14343",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await api.delete(`/merchant/customers/${customerId}`, {
            tenant_id: s.tenantId,
            store_id: s.storeId
          });
          wx.showToast({ title: "已删除", icon: "success" });
          this.loadCustomers();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  goDetail(event) {
    wx.navigateTo({ url: `/pages/merchant-customer-detail/index?customer_id=${event.currentTarget.dataset.id}` });
  },

  goWorkbench() {
    wx.navigateTo({ url: "/pages/merchant-workbench/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/merchant-orders/index" });
  },

  goAssets() {
    wx.navigateTo({ url: "/pages/merchant-assets/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/merchant-performance/index" });
  }
});
