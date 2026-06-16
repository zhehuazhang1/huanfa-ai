const api = require("../../utils/api");

Page({
  data: {
    customers: [],
    customerNames: [],
    selectedCustomerIndex: 0,
    selectedCustomer: null,
    giftCount: 1,
    freeLimit: 2,
    quota: {},
    conversion: { totals: {}, recent_records: [], by_staff: [] },
    gifting: false,
    savingLimit: false
  },

  onShow() {
    this.loadData();
  },

  async loadData() {
    const s = api.session();
    try {
      const [customers, conversion] = await Promise.all([
        api.get("/merchant/customers", {
          tenant_id: s.tenantId,
          store_id: s.storeId,
          status: "all",
          limit: 100
        }),
        api.get("/merchant/ai/gift-conversions", {
          tenant_id: s.tenantId,
          store_id: s.storeId
        })
      ]);
      const safeCustomers = customers || [];
      const selectedCustomer = safeCustomers[this.data.selectedCustomerIndex] || safeCustomers[0] || null;
      this.setData({
        customers: safeCustomers,
        customerNames: safeCustomers.map((item) => `${item.display_name || `顾客C${item.user_id}`} · 剩余${item.free_remaining || 0}次 · 赠送${item.gift_remaining || 0}次`),
        selectedCustomerIndex: selectedCustomer ? Math.max(0, safeCustomers.findIndex((item) => item.user_id === selectedCustomer.user_id)) : 0,
        selectedCustomer,
        conversion
      });
      await this.loadQuota();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async loadQuota() {
    const customer = this.data.selectedCustomer;
    if (!customer) return;
    const s = api.session();
    const quota = await api.get("/merchant/ai/quota/today", {
      tenant_id: s.tenantId,
      store_id: s.storeId,
      user_id: customer.user_id
    });
    this.setData({
      quota,
      freeLimit: quota.free_limit || 2
    });
  },

  async onCustomerChange(event) {
    const index = Number(event.detail.value || 0);
    this.setData({
      selectedCustomerIndex: index,
      selectedCustomer: this.data.customers[index] || null
    });
    await this.loadQuota();
  },

  onGiftCountInput(event) {
    this.setData({ giftCount: Number(event.detail.value || 1) });
  },

  onFreeLimitInput(event) {
    this.setData({ freeLimit: Number(event.detail.value || 0) });
  },

  async giftAi() {
    const s = api.session();
    const customer = this.data.selectedCustomer;
    if (!customer) {
      wx.showToast({ title: "请先选择顾客", icon: "none" });
      return;
    }
    const count = Math.max(1, Math.min(50, Number(this.data.giftCount || 1)));
    this.setData({ gifting: true });
    try {
      await api.post("/merchant/ai/gift", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        customer_id: customer.user_id,
        staff_id: s.staffId,
        count
      });
      wx.showToast({ title: `已赠送${count}次`, icon: "success" });
      this.loadData();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ gifting: false });
    }
  },

  async saveFreeLimit() {
    const s = api.session();
    const customer = this.data.selectedCustomer;
    if (!customer) {
      wx.showToast({ title: "请先选择顾客", icon: "none" });
      return;
    }
    const freeLimit = Math.max(0, Math.min(999, Number(this.data.freeLimit || 0)));
    this.setData({ savingLimit: true });
    try {
      const quota = await api.post("/merchant/ai/free-limit", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        customer_id: customer.user_id,
        free_limit: freeLimit
      });
      wx.showToast({ title: "已保存", icon: "success" });
      this.setData({ quota });
      this.loadData();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ savingLimit: false });
    }
  },

  async addQuota() {
    const s = api.session();
    try {
      await api.post(`/merchant/staff/${s.staffId}/gift-quota/add`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        extra_count: 3
      });
      wx.showToast({ title: "已给当前主理人加3次", icon: "success" });
      this.loadData();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  goWorkbench() {
    wx.navigateTo({ url: "/pages/merchant-workbench/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/merchant-orders/index" });
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
  }
});
