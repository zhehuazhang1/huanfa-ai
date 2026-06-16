const api = require("../../utils/api");

Page({
  data: {
    staff: [],
    services: [],
    staffNames: [],
    serviceNames: [],
    customerPackages: [],
    customerPackageNames: ["不核销套餐"],
    customerPackageIndex: 0,
    staffIndex: 0,
    serviceIndex: 0,
    paymentMethodIndex: 0,
    sourceIndex: 0,
    paymentMethodNames: ["普通收款", "会员卡扣款", "套餐扣次"],
    paymentMethodValues: ["cash", "membership", "package"],
    sourceNames: ["到店散客", "老客到店", "电话预约", "其他"],
    sourceValues: ["walk_in", "old_customer", "phone", "other"],
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
      Care: "护理",
      "ç¾å®¹": "美容"
    },
    selectedStaffName: "",
    selectedServiceName: "",
    submitting: false,
    form: {
      service_date: "",
      stylist_id: null,
      service_item_id: null,
      actual_amount: "",
      customer_id: "",
      customer_package_id: null,
      payment_method: "cash",
      source: "walk_in",
      notes: ""
    }
  },

  onLoad() {
    this.setData({
      "form.service_date": this.today()
    });
  },

  onShow() {
    this.loadOptions();
  },

  today() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  },

  async loadOptions() {
    const s = api.session();
    try {
      const [staff, services] = await Promise.all([
        api.get("/merchant/staff", {
          tenant_id: s.tenantId,
          store_id: s.storeId
        }),
        api.get("/merchant/service-items", {
          tenant_id: s.tenantId,
          store_id: s.storeId
        })
      ]);
      const decoratedServices = services.map((item) => this.decorateService(item));
      const staffIndex = Math.max(0, staff.findIndex((item) => item.staff_id === s.staffId));
      const serviceIndex = 0;
      const selectedStaff = staff[staffIndex];
      const selectedService = decoratedServices[serviceIndex];
      this.setData({
        staff,
        services: decoratedServices,
        staffIndex,
        serviceIndex,
        staffNames: staff.map((item) => item.display_name || "未命名主理人"),
        serviceNames: decoratedServices.map((item) => `${item.displayName} · ${item.categoryLabel} · ¥${item.base_price || 0}`),
        selectedStaffName: selectedStaff ? selectedStaff.display_name : "",
        selectedServiceName: selectedService ? selectedService.displayName : "",
        "form.stylist_id": selectedStaff ? selectedStaff.staff_id : null,
        "form.service_item_id": selectedService ? selectedService.id : null,
        "form.actual_amount": selectedService && selectedService.base_price ? String(selectedService.base_price) : ""
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

  changeDate(event) {
    this.setData({ "form.service_date": event.detail.value });
  },

  changeStaff(event) {
    const staffIndex = Number(event.detail.value);
    const selected = this.data.staff[staffIndex];
    this.setData({
      staffIndex,
      selectedStaffName: selected ? selected.display_name : "",
      "form.stylist_id": selected ? selected.staff_id : null
    });
  },

  changeService(event) {
    const serviceIndex = Number(event.detail.value);
    const selected = this.data.services[serviceIndex];
    this.setData({
      serviceIndex,
      selectedServiceName: selected ? selected.displayName : "",
      "form.service_item_id": selected ? selected.id : null,
      "form.actual_amount": selected && selected.base_price ? String(selected.base_price) : this.data.form.actual_amount,
      "form.customer_package_id": null,
      customerPackageIndex: 0,
      customerPackages: [],
      customerPackageNames: ["不核销套餐"]
    });
    this.loadCustomerPackages();
  },

  changeSource(event) {
    const sourceIndex = Number(event.detail.value);
    this.setData({
      sourceIndex,
      "form.source": this.data.sourceValues[sourceIndex] || "walk_in"
    });
  },

  inputAmount(event) {
    this.setData({ "form.actual_amount": event.detail.value });
  },

  changePaymentMethod(event) {
    const paymentMethodIndex = Number(event.detail.value || 0);
    const paymentMethod = this.data.paymentMethodValues[paymentMethodIndex] || "cash";
    const selectedPackage = paymentMethod === "package"
      ? this.data.customerPackages[this.data.customerPackageIndex - 1]
      : null;
    this.setData({
      paymentMethodIndex,
      "form.payment_method": paymentMethod,
      "form.customer_package_id": selectedPackage ? selectedPackage.id : null,
      "form.actual_amount": paymentMethod === "package" ? "0" : this.data.form.actual_amount
    });
    if (paymentMethod === "package") this.loadCustomerPackages();
  },

  inputCustomerId(event) {
    this.setData({
      "form.customer_id": event.detail.value,
      "form.customer_package_id": null,
      customerPackageIndex: 0,
      customerPackages: [],
      customerPackageNames: ["不核销套餐"]
    });
  },

  async loadCustomerPackages() {
    const customerId = Number(this.data.form.customer_id);
    const serviceItemId = this.data.form.service_item_id;
    if (!customerId || !serviceItemId) return;
    const s = api.session();
    try {
      const packages = await api.get(`/merchant/customers/${customerId}/packages`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        active_only: true,
        service_item_id: serviceItemId
      });
      const names = ["不核销套餐"].concat(
        packages.map((item) => {
          const first = (item.items || [])[0] || {};
          return `${item.package_name || "套餐"} · 剩余${first.remaining_count || item.remaining_total || 0}次`;
        })
      );
      this.setData({
        customerPackages: packages,
        customerPackageNames: names,
        customerPackageIndex: 0,
        "form.customer_package_id": null
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  changeCustomerPackage(event) {
    const index = Number(event.detail.value || 0);
    const selected = index > 0 ? this.data.customerPackages[index - 1] : null;
    this.setData({
      customerPackageIndex: index,
      "form.customer_package_id": selected ? selected.id : null,
      "form.actual_amount": selected && this.data.form.payment_method === "package" ? "0" : this.data.form.actual_amount
    });
  },

  inputNotes(event) {
    this.setData({ "form.notes": event.detail.value });
  },

  async submitRecord() {
    if (this.data.submitting) return;
    const s = api.session();
    const amount = Number(this.data.form.actual_amount);
    if (!this.data.form.stylist_id) {
      wx.showToast({ title: "请选择主理人", icon: "none" });
      return;
    }
    if (!this.data.form.service_item_id) {
      wx.showToast({ title: "请选择服务项目", icon: "none" });
      return;
    }
    if (!Number.isFinite(amount) || amount < 0) {
      wx.showToast({ title: "请输入正确金额", icon: "none" });
      return;
    }
    if ((this.data.form.payment_method === "membership" || this.data.form.payment_method === "package") && !this.data.form.customer_id) {
      wx.showToast({ title: "请填写顾客ID", icon: "none" });
      return;
    }
    if (this.data.form.payment_method === "package" && !this.data.form.customer_package_id) {
      wx.showToast({ title: "请选择要核销的套餐", icon: "none" });
      return;
    }
    this.setData({ submitting: true });
    try {
      await api.post("/merchant/service-records/manual", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        stylist_id: this.data.form.stylist_id,
        service_item_id: this.data.form.service_item_id,
        actual_amount: amount,
        customer_id: this.data.form.customer_id ? Number(this.data.form.customer_id) : null,
        customer_package_id: this.data.form.customer_package_id,
        payment_method: this.data.form.payment_method,
        source: this.data.form.source,
        service_date: this.data.form.service_date,
        notes: this.data.form.notes
      });
      wx.showToast({ title: "已计入看板", icon: "success" });
      setTimeout(() => {
        wx.navigateBack();
      }, 500);
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  }
});
