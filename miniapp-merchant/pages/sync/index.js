const api = require("../../utils/api");

Page({
  data: {
    loading: false,
    syncing: false,
    status: {
      pending: 0,
      synced: 0,
      failed: 0
    },
    events: [],
    statusText: {
      pending: "待同步",
      synced: "已同步",
      failed: "同步失败"
    },
    eventTypeText: {
      order_created: "预约订单",
      order_completed: "完成服务",
      manual_service_recorded: "补录服务",
      ai_gift_granted: "AI赠送",
      ai_job_completed: "AI试发",
      ai_generation_job: "AI试发"
    }
  },

  onShow() {
    this.loadSync();
  },

  async loadSync() {
    const s = api.session();
    this.setData({ loading: true });
    try {
      const [status, events] = await Promise.all([
        api.get("/sync/feishu/status", { tenant_id: s.tenantId }),
        api.get("/sync/feishu/events", { tenant_id: s.tenantId, limit: 30 })
      ]);
      this.setData({
        status: {
          pending: status.counts.pending || 0,
          synced: status.counts.synced || 0,
          failed: status.counts.failed || 0
        },
        events: events.map((item) => this.decorateEvent(item))
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  decorateEvent(event) {
    return {
      ...event,
      typeLabel: this.data.eventTypeText[event.event_type] || event.event_type,
      statusLabel: this.data.statusText[event.status] || event.status,
      timeText: event.synced_at || event.created_at || "",
      errorText: event.last_error || ""
    };
  },

  async retrySync() {
    const s = api.session();
    this.setData({ syncing: true });
    try {
      const result = await api.post(`/sync/feishu/retry?tenant_id=${s.tenantId}`);
      wx.showToast({
        title: `同步${result.synced_count || 0}条`,
        icon: "none"
      });
      await this.loadSync();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ syncing: false });
    }
  },

  goWorkbench() {
    wx.navigateTo({ url: "/pages/workbench/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goAssets() {
    wx.navigateTo({ url: "/pages/assets/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/customers/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/performance/index" });
  }
});
