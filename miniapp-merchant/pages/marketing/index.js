const api = require("../../utils/api");

Page({
  data: {
    packages: [],
    services: [],
    serviceNames: [],
    serviceIndex: 0,
    packageTypeIndex: 0,
    packageTypes: [
      { label: "次卡", value: "times_card" },
      { label: "组合套餐", value: "bundle" }
    ],
    form: {
      name: "",
      sale_price: "",
      validity_days: "180",
      included_count: "10"
    },
    rechargeForm: {
      customer_id: "",
      amount: "",
      note: ""
    },
    submitting: false,
    rechargeSubmitting: false,
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
    }
  },

  onShow() {
    this.loadData();
  },

  async loadData() {
    const s = api.session();
    try {
      const [packages, services] = await Promise.all([
        api.get("/merchant/marketing-packages", {
          tenant_id: s.tenantId,
          store_id: s.storeId,
          include_disabled: true
        }),
        api.get("/merchant/service-items", {
          tenant_id: s.tenantId,
          store_id: s.storeId
        })
      ]);
      const decoratedServices = services.map((item) => this.decorateService(item));
      this.setData({
        packages: packages.map((item) => this.decoratePackage(item)),
        services: decoratedServices,
        serviceNames: decoratedServices.map((item) => `${item.displayName} · ${item.categoryLabel} · ¥${item.base_price || 0}`)
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  decorateService(item) {
    return {
      ...item,
      displayName: this.data.serviceNameText[item.name] || item.name,
      categoryLabel: this.data.categoryText[item.category] || item.category
    };
  },

  decoratePackage(item) {
    const itemText = (item.items || [])
      .map((service) => `${service.service_name || service.name || "服务"} ${service.included_count}次`)
      .join(" / ");
    return {
      ...item,
      typeText: item.package_type === "bundle" ? "组合套餐" : "次卡",
      statusText: item.is_enabled ? "启用中" : "已停用",
      itemText: itemText || "未配置服务"
    };
  },

  changeService(event) {
    this.setData({ serviceIndex: Number(event.detail.value || 0) });
  },

  changePackageType(event) {
    this.setData({ packageTypeIndex: Number(event.detail.value || 0) });
  },

  inputName(event) {
    this.setData({ "form.name": event.detail.value });
  },

  inputPrice(event) {
    this.setData({ "form.sale_price": event.detail.value });
  },

  inputValidity(event) {
    this.setData({ "form.validity_days": event.detail.value });
  },

  inputCount(event) {
    this.setData({ "form.included_count": event.detail.value });
  },

  inputRechargeCustomer(event) {
    this.setData({ "rechargeForm.customer_id": event.detail.value });
  },

  inputRechargeAmount(event) {
    this.setData({ "rechargeForm.amount": event.detail.value });
  },

  inputRechargeNote(event) {
    this.setData({ "rechargeForm.note": event.detail.value });
  },

  parseCustomerId(value) {
    const text = String(value || "").trim();
    if (!text || /^1\d{10}$/.test(text)) return 0;
    const matched = text.match(/\d+/);
    return matched ? Number(matched[0]) : 0;
  },

  async resolveCustomerId(value) {
    const text = String(value || "").trim();
    const directId = this.parseCustomerId(text);
    if (directId) return directId;
    if (!text) return 0;
    const s = api.session();
    const customers = await api.get("/merchant/customers", {
      tenant_id: s.tenantId,
      store_id: s.storeId,
      keyword: text,
      limit: 5
    });
    if (!customers || customers.length === 0) {
      throw new Error("没有找到这个手机号对应的顾客");
    }
    if (/^1\d{10}$/.test(text)) {
      return customers[0].user_id;
    }
    if (customers.length > 1) {
      throw new Error("匹配到多个顾客，请补充完整手机号");
    }
    return customers[0].user_id;
  },

  async submitMembershipTransaction(event) {
    if (this.data.rechargeSubmitting) return;
    const type = event.currentTarget.dataset.type || "recharge";
    const amount = Number(this.data.rechargeForm.amount);
    if (!String(this.data.rechargeForm.customer_id || "").trim()) {
      wx.showToast({ title: "请输入顾客手机号", icon: "none" });
      return;
    }
    if (!Number.isFinite(amount) || amount <= 0) {
      wx.showToast({ title: "请输入正确金额", icon: "none" });
      return;
    }
    const s = api.session();
    this.setData({ rechargeSubmitting: true });
    try {
      const customerId = await this.resolveCustomerId(this.data.rechargeForm.customer_id);
      await api.post(`/merchant/customers/${customerId}/membership/transactions`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        transaction_type: type,
        amount,
        note: this.data.rechargeForm.note || (type === "recharge" ? "门店会员充值" : "会员余额扣减"),
        created_by_user_id: s.staffId
      });
      wx.showToast({ title: type === "recharge" ? "充值成功" : "扣款成功", icon: "success" });
      this.setData({
        rechargeForm: {
          customer_id: "",
          amount: "",
          note: ""
        }
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ rechargeSubmitting: false });
    }
  },

  async createPackage() {
    if (this.data.submitting) return;
    const selectedService = this.data.services[this.data.serviceIndex];
    const name = this.data.form.name.trim();
    const salePrice = Number(this.data.form.sale_price);
    const validityDays = Number(this.data.form.validity_days);
    const includedCount = Number(this.data.form.included_count);
    if (!selectedService) {
      wx.showToast({ title: "请先新增服务项目", icon: "none" });
      return;
    }
    if (!name) {
      wx.showToast({ title: "请输入套餐名称", icon: "none" });
      return;
    }
    if (!Number.isFinite(salePrice) || salePrice < 0) {
      wx.showToast({ title: "请输入正确价格", icon: "none" });
      return;
    }
    if (!Number.isInteger(validityDays) || validityDays <= 0) {
      wx.showToast({ title: "请输入有效期天数", icon: "none" });
      return;
    }
    if (!Number.isInteger(includedCount) || includedCount <= 0) {
      wx.showToast({ title: "请输入可用次数", icon: "none" });
      return;
    }
    const s = api.session();
    this.setData({ submitting: true });
    try {
      await api.post("/merchant/marketing-packages", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        name,
        package_type: this.data.packageTypes[this.data.packageTypeIndex].value,
        sale_price: salePrice,
        validity_days: validityDays,
        items: [
          {
            service_item_id: selectedService.id,
            included_count: includedCount
          }
        ],
        sort_order: 90
      });
      wx.showToast({ title: "已新增套餐", icon: "success" });
      this.setData({
        form: {
          name: "",
          sale_price: "",
          validity_days: "180",
          included_count: "10"
        }
      });
      this.loadData();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  },

  async togglePackage(event) {
    const s = api.session();
    const packageId = Number(event.currentTarget.dataset.id);
    const enabled = Number(event.currentTarget.dataset.enabled) === 1;
    try {
      await api.put(`/merchant/marketing-packages/${packageId}`, {
        tenant_id: s.tenantId,
        is_enabled: !enabled
      });
      wx.showToast({ title: enabled ? "已停用" : "已启用", icon: "success" });
      this.loadData();
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
