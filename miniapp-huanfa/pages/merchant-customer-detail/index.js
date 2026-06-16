const api = require("../../utils/api");

Page({
  data: {
    customerId: 0,
    customer: {},
    quota: {},
    activeVisit: null,
    recentJobs: [],
    recentOrders: [],
    giftRecords: [],
    giftRemaining: 0,
    membership: {},
    membershipTransactions: [],
    customerPackages: [],
    marketingPackages: [],
    directionText: {
      female: "女性",
      male: "男性",
      neutral: "中性"
    },
    jobStatusText: {
      queued: "排队中",
      running: "生成中",
      success: "已完成",
      failed: "失败",
      timeout: "超时",
      cancelled: "已取消"
    },
    orderStatusText: {
      pending: "待确认",
      confirmed: "已确认",
      arrived: "已到店",
      serving: "服务中",
      completed: "已完成",
      cancelled: "已取消"
    },
    giftStatusText: {
      unused: "未使用",
      used: "已使用",
      expired: "已过期"
    },
    transactionTypeText: {
      recharge: "充值",
      consume: "消费",
      adjust: "调整"
    }
  },

  onLoad(options = {}) {
    this.setData({ customerId: Number(options.customer_id || 0) });
  },

  onShow() {
    this.loadDetail();
  },

  async loadDetail() {
    if (!this.data.customerId) return;
    const s = api.session();
    try {
      const detail = await api.get(`/merchant/customers/${this.data.customerId}`, {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      const membership = detail.membership || {};
      this.setData({
        customer: {
          ...detail.customer,
          avatarText: (detail.customer.display_name || "顾").slice(0, 1)
        },
        quota: detail.quota || {},
        activeVisit: detail.active_visit,
        recentJobs: detail.recent_jobs || [],
        recentOrders: detail.recent_orders || [],
        giftRecords: detail.gift_records || [],
        giftRemaining: detail.gift_remaining || 0,
        membership,
        membershipTransactions: membership.transactions || [],
        customerPackages: (detail.customer_packages || []).map((item) => this.decorateCustomerPackage(item))
      });
      this.loadMarketingPackages();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  decorateCustomerPackage(item) {
    const itemText = (item.items || [])
      .map((service) => `${service.service_name || service.name || "服务"} 剩余${service.remaining_count || 0}/${service.total_count || 0}`)
      .join(" / ");
    return {
      ...item,
      itemText: itemText || "暂无服务明细",
      statusText: item.status === "active" ? "可用" : item.status === "used_up" ? "已用完" : item.status || "未知"
    };
  },

  decorateMarketingPackage(item) {
    const itemText = (item.items || [])
      .map((service) => `${service.service_name || service.name || "服务"} ${service.included_count}次`)
      .join(" / ");
    return {
      ...item,
      itemText: itemText || "未配置服务",
      actionText: `${item.name} · ¥${item.sale_price || 0}`
    };
  },

  async loadMarketingPackages() {
    const s = api.session();
    try {
      const packages = await api.get("/merchant/marketing-packages", {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      this.setData({ marketingPackages: packages.map((item) => this.decorateMarketingPackage(item)) });
    } catch (err) {
      // Customer details should remain usable even when package loading fails.
    }
  },

  async giftAi() {
    const s = api.session();
    try {
      await api.post("/merchant/ai/gift", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        customer_id: this.data.customerId,
        staff_id: s.staffId
      });
      wx.showToast({ title: "已赠送", icon: "success" });
      this.loadDetail();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  addMembershipTransaction(event) {
    const type = event.currentTarget.dataset.type;
    const title = type === "recharge" ? "会员充值" : "会员消费";
    const placeholder = type === "recharge" ? "输入线下实收金额" : "输入本次扣减金额";
    wx.showModal({
      title,
      editable: true,
      placeholderText: placeholder,
      confirmText: "确定",
      confirmColor: "#01261f",
      success: async (res) => {
        if (!res.confirm) return;
        const amount = Number(res.content || 0);
        if (!amount || amount <= 0) {
          wx.showToast({ title: "请输入正确金额", icon: "none" });
          return;
        }
        const s = api.session();
        try {
          await api.post(`/merchant/customers/${this.data.customerId}/membership/transactions`, {
            tenant_id: s.tenantId,
            store_id: s.storeId,
            transaction_type: type,
            amount,
            note: title,
            created_by_user_id: s.staffId
          });
          wx.showToast({ title: type === "recharge" ? "已充值" : "已扣减", icon: "success" });
          this.loadDetail();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  openPackage() {
    const packages = this.data.marketingPackages || [];
    if (!packages.length) {
      wx.showToast({ title: "请先在营销套餐里新增套餐", icon: "none" });
      return;
    }
    wx.showActionSheet({
      itemList: packages.map((item) => item.actionText).slice(0, 6),
      success: async (res) => {
        const selected = packages[res.tapIndex];
        if (!selected) return;
        const s = api.session();
        try {
          await api.post(`/merchant/customers/${this.data.customerId}/packages`, {
            tenant_id: s.tenantId,
            store_id: s.storeId,
            package_id: selected.id,
            paid_amount: selected.sale_price,
            notes: "门店开通营销套餐"
          });
          wx.showToast({ title: "已开通套餐", icon: "success" });
          this.loadDetail();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  async toggleDisable() {
    const s = api.session();
    const isDisabled = this.data.customer.is_disabled;
    const newStatus = isDisabled ? "active" : "disabled";
    const label = isDisabled ? "恢复" : "停用";

    wx.showModal({
      title: `${label}顾客账号`,
      content: isDisabled
        ? "确定要恢复该顾客账号吗？恢复后顾客可正常使用。"
        : "确定要停用该顾客账号吗？停用后顾客将无法登录，历史记录保留。",
      confirmText: label,
      confirmColor: isDisabled ? "#01261f" : "#d14343",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await api.put(`/merchant/customers/${this.data.customerId}/status`, {
            tenant_id: s.tenantId,
            store_id: s.storeId,
            status: newStatus
          });
          wx.showToast({ title: `已${label}`, icon: "success" });
          this.loadDetail();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  async deleteCustomer() {
    const s = api.session();
    wx.showModal({
      title: "删除顾客",
      content: "删除后顾客将无法登录，历史数据仍保留。此操作不可撤销。",
      confirmText: "删除",
      confirmColor: "#d14343",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await api.delete(`/merchant/customers/${this.data.customerId}`, {
            tenant_id: s.tenantId,
            store_id: s.storeId
          });
          wx.showToast({ title: "已删除", icon: "success" });
          setTimeout(() => wx.navigateBack(), 1200);
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/merchant-orders/index" });
  }
});
