const api = require("../../utils/api");

Page({
  data: {
    loading: false,
    saving: false,
    form: {
      store_name: "",
      home_title: "",
      home_subtitle: "",
      store_photos: []
    }
  },

  onShow() {
    this.loadConfig();
  },

  async loadConfig() {
    const s = api.session();
    this.setData({ loading: true });
    try {
      const config = await api.get("/merchant/store-home-config", {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      this.setData({
        form: {
          store_name: config.store_name || "",
          home_title: config.home_title || "",
          home_subtitle: config.home_subtitle || "",
          store_photos: this.normalizePhotos(config.store_photos || [])
        }
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  normalizePhotos(photos) {
    const base = photos.slice(0, 3).map((item) => ({
      title: item.title || "",
      desc: item.desc || "",
      url: item.url || ""
    }));
    while (base.length < 3) {
      base.push({ title: "", desc: "", url: "" });
    }
    return base;
  },

  inputStoreName(event) {
    this.setData({ "form.store_name": event.detail.value });
  },

  inputHomeTitle(event) {
    this.setData({ "form.home_title": event.detail.value });
  },

  inputHomeSubtitle(event) {
    this.setData({ "form.home_subtitle": event.detail.value });
  },

  inputPhotoField(event) {
    const index = Number(event.currentTarget.dataset.index);
    const field = event.currentTarget.dataset.field;
    const photos = this.data.form.store_photos.slice();
    photos[index] = { ...photos[index], [field]: event.detail.value };
    this.setData({ "form.store_photos": photos });
  },

  async saveConfig() {
    const s = api.session();
    const form = this.data.form;
    this.setData({ saving: true });
    try {
      await api.put("/merchant/store-home-config", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        store_name: form.store_name,
        home_title: form.home_title,
        home_subtitle: form.home_subtitle,
        store_photos: form.store_photos
      });
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ saving: false });
    }
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

  goKnowledge() {
    wx.navigateTo({ url: "/pages/merchant-knowledge/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/merchant-customers/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/merchant-performance/index" });
  }
});
