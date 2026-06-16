const api = require("../../utils/api");

// 格式化日期为 YYYY-MM-DD
function formatDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

Page({
  data: {
    viewMode: "today", // today | history
    dateFrom: "",
    dateTo: "",
    todayLabel: "",
    status: "",
    orders: [],
    serviceItems: [],
    statuses: [
      { label: "全部", value: "" },
      { label: "待确认", value: "pending" },
      { label: "已确认", value: "confirmed" },
      { label: "已完成", value: "completed" }
    ],
    statusText: {
      pending: "待确认",
      confirmed: "已确认",
      arrived: "待结算",
      serving: "待结算",
      completed: "已完成",
      cancelled: "已取消"
    }
  },

  onShow() {
    if (!this.data.todayLabel) {
      const today = formatDate(new Date());
      const weekAgo = formatDate(new Date(Date.now() - 6 * 24 * 60 * 60 * 1000));
      this.setData({ todayLabel: today, dateFrom: weekAgo, dateTo: today });
    }
    this.loadPageData();
  },

  changeView(event) {
    const mode = event.currentTarget.dataset.mode;
    if (mode === this.data.viewMode) return;
    this.setData({ viewMode: mode });
    this.loadOrders();
  },

  onDateFromChange(event) {
    this.setData({ dateFrom: event.detail.value });
    this.loadOrders();
  },

  onDateToChange(event) {
    this.setData({ dateTo: event.detail.value });
    this.loadOrders();
  },

  changeStatus(event) {
    this.setData({ status: event.currentTarget.dataset.value });
    this.loadOrders();
  },

  async loadPageData() {
    await Promise.all([this.loadOrders(), this.loadServiceItems()]);
  },

  async loadOrders() {
    const s = api.session();
    const params = {
      tenant_id: s.tenantId,
      store_id: s.storeId,
      status: this.data.status
    };
    if (this.data.viewMode === "today") {
      params.date_from = this.data.todayLabel;
      params.date_to = this.data.todayLabel;
    } else {
      params.date_from = this.data.dateFrom;
      params.date_to = this.data.dateTo;
    }
    try {
      const orders = await api.get("/merchant/orders", params);
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
      serviceItemText: order.service_item_name || "到店沟通"
    };
  },

  async loadServiceItems() {
    const s = api.session();
    try {
      const serviceItems = await api.get("/merchant/service-items", {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      this.setData({
        serviceItems: serviceItems.map((item) => ({
          ...item,
          displayName: item.display_name || item.displayName || item.name
        }))
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async updateStatus(event) {
    const s = api.session();
    const orderId = event.currentTarget.dataset.id;
    const status = event.currentTarget.dataset.status;
    try {
      await api.put(`/merchant/orders/${orderId}/status`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        status
      });
      wx.showToast({ title: "已更新", icon: "success" });
      this.loadOrders();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  findOrder(orderId) {
    return this.data.orders.find((item) => String(item.id) === String(orderId));
  },

  showOrderDetail(event) {
    wx.navigateTo({ url: `/pages/merchant-order-detail/index?order_id=${event.currentTarget.dataset.id}` });
    return;
    const order = this.findOrder(event.currentTarget.dataset.id);
    if (!order) {
      wx.showToast({ title: "未找到订单", icon: "none" });
      return;
    }
    const lines = [
      `状态：${this.data.statusText[order.status] || order.status || "待确认"}`,
      `顾客：${order.customer_name || "顾客"} ${order.customer_phone || ""}`,
      `主理人：${order.stylist_name || "未分配"}`,
      `预约时间：${order.appointment_time || "到店沟通"}`,
      `发型：${order.hairstyleText || "未选择"}`,
      `发色：${order.hairColorText || "未选择"}`,
      `服务项目：${order.serviceItemText || "到店沟通"}`,
      `来源：${order.is_ai_converted ? "AI试发转化" : "普通预约"}`,
      order.notes ? `沟通重点：${order.notes}` : "",
      `订单号：${order.id}`
    ].filter(Boolean);
    wx.showModal({
      title: "订单详情",
      content: lines.join("\n"),
      confirmText: "知道了",
      showCancel: false
    });
  },

  async completeOrder(event) {
    const s = api.session();
    const orderId = event.currentTarget.dataset.id;
    const order = this.findOrder(orderId);
    const stylistId = event.currentTarget.dataset.stylistId || s.staffId;
    const serviceItem = await this.pickServiceItem();
    if (!serviceItem) return;
    const settlement = await this.pickSettlementMethod(order, serviceItem);
    if (!settlement) return;

    try {
      await api.put(`/merchant/orders/${orderId}/complete`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        stylist_id: Number(stylistId),
        service_item_id: serviceItem.id,
        actual_amount: settlement.amount,
        payment_method: settlement.paymentMethod,
        customer_package_id: settlement.customerPackageId || null
      });
      wx.showToast({ title: "???", icon: "success" });
      this.loadOrders();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  pickServiceItem() {
    return new Promise((resolve) => {
      const items = this.data.serviceItems || [];
      if (items.length === 0) {
        wx.showToast({ title: "请先维护服务项目", icon: "none" });
        resolve(null);
        return;
      }
      wx.showActionSheet({
        itemList: items.map((item) => `${item.displayName || item.display_name || item.name} ¥${item.base_price}`),
        success: (res) => resolve(items[res.tapIndex]),
        fail: () => resolve(null)
      });
    });
  },

  async getSettlementOptions(order, serviceItem) {
    const options = [{ label: "普通收款", value: "cash" }];
    const customerId = order && order.user_id;
    if (!customerId) return { options, packages: [] };

    const s = api.session();
    try {
      const membership = await api.get(`/merchant/customers/${customerId}/membership`, {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      const balance = Number(membership && membership.balance || 0);
      if (membership && membership.enabled !== false && balance > 0) {
        options.push({ label: `会员卡扣款（余额¥${balance}）`, value: "membership", balance });
      }
    } catch (err) {
      // 没开会员功能或未建会员卡时，不影响普通收款。
    }

    let packages = [];
    try {
      packages = await api.get(`/merchant/customers/${customerId}/packages`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        active_only: true,
        service_item_id: serviceItem.id
      });
      if (packages.length) {
        const remaining = packages.reduce((sum, item) => sum + Number(item.remaining_total || 0), 0);
        options.push({ label: `套餐扣次（可用${remaining || packages.length}次）`, value: "package" });
      }
    } catch (err) {
      packages = [];
    }

    return { options, packages };
  },

  pickSettlementOption(options) {
    return new Promise((resolve) => {
      wx.showActionSheet({
        itemList: options.map((item) => item.label),
        success: (res) => resolve(options[res.tapIndex] || null),
        fail: () => resolve(null)
      });
    });
  },

  async pickSettlementMethod(order, serviceItem) {
    const { options, packages } = await this.getSettlementOptions(order, serviceItem);
    const selected = await this.pickSettlementOption(options);
    if (!selected) return null;

    if (selected.value === "cash") {
      const amount = await this.inputActualAmount(serviceItem.base_price || 0, "普通收款金额");
      return amount === null ? null : { paymentMethod: "cash", amount };
    }

    if (selected.value === "membership") {
      const amount = await this.inputActualAmount(serviceItem.base_price || 0, "会员卡扣款金额");
      return amount === null ? null : { paymentMethod: "membership", amount };
    }

    const selectedPackage = await this.pickCustomerPackageFromList(packages, serviceItem);
    return selectedPackage ? {
      paymentMethod: "package",
      amount: 0,
      customerPackageId: selectedPackage.id
    } : null;
  },

  pickCustomerPackageFromList(packages, serviceItem) {
    if (!packages.length) {
      wx.showToast({ title: "该顾客没有可用套餐", icon: "none" });
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      wx.showActionSheet({
        itemList: packages.slice(0, 6).map((item) => {
          const packageItem = (item.items || []).find((child) => Number(child.service_item_id) === Number(serviceItem.id)) || {};
          return `${item.package_name || "顾客套餐"}，剩余${packageItem.remaining_count || item.remaining_total || 0} 次`;
        }),
        success: (res) => resolve(packages[res.tapIndex]),
        fail: () => resolve(null)
      });
    });
  },

  async pickCustomerPackage(order, serviceItem) {
    const customerId = order && order.user_id;
    if (!customerId) {
      wx.showToast({ title: "当前订单没有绑定顾客", icon: "none" });
      return null;
    }
    const s = api.session();
    try {
      const packages = await api.get(`/merchant/customers/${customerId}/packages`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        active_only: true,
        service_item_id: serviceItem.id
      });
      if (!packages.length) {
        wx.showToast({ title: "该顾客没有可用套餐", icon: "none" });
        return null;
      }
      return await new Promise((resolve) => {
        wx.showActionSheet({
          itemList: packages.slice(0, 6).map((item) => {
            const packageItem = (item.items || []).find((child) => Number(child.service_item_id) === Number(serviceItem.id)) || {};
            return `${item.package_name || "顾客套餐"}，剩余 ${packageItem.remaining_count || item.remaining_total || 0} 次`;
          }),
          success: (res) => resolve(packages[res.tapIndex]),
          fail: () => resolve(null)
        });
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
      return null;
    }
  },

  inputActualAmount(defaultAmount, title = "成交金额") {
    return new Promise((resolve) => {
      wx.showModal({
        title,
        placeholderText: "输入顾客到店支付金额",
        editable: true,
        content: String(defaultAmount || ""),
        success: (res) => {
          if (!res.confirm) {
            resolve(null);
            return;
          }
          const amount = Number(res.content);
          if (!Number.isFinite(amount) || amount <= 0) {
            wx.showToast({ title: "金额不正确", icon: "none" });
            resolve(null);
            return;
          }
          resolve(amount);
        },
        fail: () => resolve(null)
      });
    });
  },

  goWorkbench() {
    wx.navigateTo({ url: "/pages/merchant-workbench/index" });
  },

  goQuota() {
    wx.navigateTo({ url: "/pages/merchant-ai-quota/index" });
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
