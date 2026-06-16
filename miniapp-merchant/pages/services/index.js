const api = require("../../utils/api");

Page({
  data: {
    services: [],
    filteredServices: [],
    filterStatus: "all",
    categoryIndex: 0,
    currentCategoryLabel: "剪发",
    categoryOptions: [
      { label: "剪发", value: "haircut" },
      { label: "染发", value: "color" },
      { label: "烫发", value: "perm" },
      { label: "造型", value: "styling" },
      { label: "护理", value: "care" }
    ],
    statusTabs: [
      { label: "全部", value: "all" },
      { label: "启用", value: "enabled" },
      { label: "停用", value: "disabled" }
    ],
    categoryText: {
      haircut: "剪发",
      color: "染发",
      perm: "烫发",
      styling: "造型",
      care: "护理"
    },
    serviceNameText: {
      Haircut: "剪发",
      Color: "染发",
      Perm: "烫发",
      Styling: "造型",
      Care: "护理"
    },
    dialogVisible: false,
    dialogSubmitting: false,
    dialogMode: "create",
    editingServiceId: null,
    dialogForm: {
      name: "",
      price: ""
    }
  },

  onShow() {
    this.loadServices();
  },

  async loadServices() {
    const s = api.session();
    try {
      const services = await api.get("/merchant/service-items", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        include_disabled: true
      });
      const decorated = this.decorateServices(services);
      this.setData({ services: decorated });
      this.refreshFilteredServices();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  decorateServices(services) {
    return services.map((item) => ({
      ...item,
      displayName: this.data.serviceNameText[item.name] || item.name,
      categoryLabel: this.data.categoryText[item.category] || item.category,
      statusLabel: item.is_enabled ? "启用中" : "已停用"
    }));
  },

  changeStatus(event) {
    this.setData({ filterStatus: event.currentTarget.dataset.value });
    this.refreshFilteredServices();
  },

  changeCategory(event) {
    const categoryIndex = Number(event.detail.value || 0);
    this.setData({
      categoryIndex,
      currentCategoryLabel: this.data.categoryOptions[categoryIndex].label
    });
  },

  refreshFilteredServices() {
    const status = this.data.filterStatus;
    let filteredServices = this.data.services;
    if (status === "enabled") {
      filteredServices = this.data.services.filter((item) => item.is_enabled);
    }
    if (status === "disabled") {
      filteredServices = this.data.services.filter((item) => !item.is_enabled);
    }
    this.setData({ filteredServices });
  },

  addService() {
    this.setData({
      dialogVisible: true,
      dialogSubmitting: false,
      dialogMode: "create",
      editingServiceId: null,
      dialogForm: {
        name: "",
        price: ""
      }
    });
  },

  editService(event) {
    const serviceId = Number(event.currentTarget.dataset.id);
    const service = this.data.services.find((item) => item.id === serviceId);
    if (!service) return;
    const categoryIndex = Math.max(0, this.data.categoryOptions.findIndex((item) => item.value === service.category));
    this.setData({
      categoryIndex,
      currentCategoryLabel: this.data.categoryOptions[categoryIndex].label,
      dialogVisible: true,
      dialogSubmitting: false,
      dialogMode: "edit",
      editingServiceId: service.id,
      dialogForm: {
        name: service.displayName,
        price: String(service.base_price || 0)
      }
    });
  },

  closeDialog() {
    if (this.data.dialogSubmitting) return;
    this.setData({ dialogVisible: false });
  },

  noop() {},

  inputDialogName(event) {
    this.setData({ "dialogForm.name": event.detail.value });
  },

  inputDialogPrice(event) {
    this.setData({ "dialogForm.price": event.detail.value });
  },

  async saveServiceDialog() {
    if (this.data.dialogSubmitting) return;
    const name = this.data.dialogForm.name.trim();
    const price = Number(this.data.dialogForm.price);
    if (!name) {
      wx.showToast({ title: "请输入服务名称", icon: "none" });
      return;
    }
    if (!Number.isFinite(price) || price < 0) {
      wx.showToast({ title: "请输入正确价格", icon: "none" });
      return;
    }
    const category = this.data.categoryOptions[this.data.categoryIndex].value;
    const s = api.session();
    this.setData({ dialogSubmitting: true });
    try {
      if (this.data.dialogMode === "edit") {
        await api.put(`/merchant/service-items/${this.data.editingServiceId}`, {
          tenant_id: s.tenantId,
          store_id: s.storeId,
          name,
          category,
          base_price: price
        });
        wx.showToast({ title: "已保存", icon: "success" });
      } else {
        await api.post("/merchant/service-items", {
          tenant_id: s.tenantId,
          store_id: s.storeId,
          name,
          category,
          base_price: price,
          sort_order: 90
        });
        wx.showToast({ title: "已新增", icon: "success" });
      }
      this.setData({ dialogVisible: false });
      this.loadServices();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ dialogSubmitting: false });
    }
  },

  async toggleService(event) {
    const s = api.session();
    const serviceId = event.currentTarget.dataset.id;
    const isEnabled = Number(event.currentTarget.dataset.enabled) === 1;
    try {
      await api.put(`/merchant/service-items/${serviceId}`, {
        tenant_id: s.tenantId,
        is_enabled: !isEnabled
      });
      wx.showToast({ title: isEnabled ? "已停用" : "已启用", icon: "success" });
      this.loadServices();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  goWorkbench() {
    wx.navigateTo({ url: "/pages/workbench/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goQuota() {
    wx.navigateTo({ url: "/pages/ai-quota/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/performance/index" });
  },

  goStaff() {
    wx.navigateTo({ url: "/pages/staff/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/customers/index" });
  }
});
