const api = require("../../utils/api");
const app = getApp();

Page({
  data: {
    loading: false,
    confirmSelfieVisible: false,
    pendingSelfie: null,
    selfiePreviewPath: "",
    remainingQuota: 0,
    customerReference: null,
    customerReferencePreviewPath: "",
    customerReferenceType: "",
    previewAssetVisible: false,
    previewAssetType: "",
    previewAsset: null,
    direction: "female",
    assetMode: "styles",
    category: "hot",
    directions: [
      { label: "女士", value: "female" },
      { label: "男士", value: "male" },
      { label: "中性", value: "neutral" }
    ],
    categories: [
      { label: "热门", value: "hot" },
      { label: "长发", value: "long" },
      { label: "中发", value: "medium" },
      { label: "短发", value: "short" }
    ],
    styles: [],
    colors: [],
    styleCache: {},
    colorsLoaded: false,
    visibleStyles: [],
    visibleColors: [],
    selectedStyleId: "",
    selectedStyleName: "",
    selectedColorId: "",
    selectedColorName: "",
    hairProfile: {
      strand_thickness: "",
      texture_hardness: "",
      damage_level: ""
    },
    hairProfileOptions: [
      {
        key: "strand_thickness",
        label: "发丝粗细",
        options: [
          { label: "细软", value: "fine" },
          { label: "中等", value: "medium" },
          { label: "粗硬", value: "coarse" }
        ]
      },
      {
        key: "texture_hardness",
        label: "发质软硬",
        options: [
          { label: "偏软", value: "soft" },
          { label: "中等", value: "medium" },
          { label: "偏硬", value: "hard" }
        ]
      },
      {
        key: "damage_level",
        label: "头发状态",
        options: [
          { label: "健康", value: "healthy" },
          { label: "轻度受损", value: "mild_damage" },
          { label: "中度受损", value: "damaged" },
          { label: "极度受损", value: "severe_damage" }
        ]
      }
    ],
    fallbackStyleImage: "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=500"
  },

  onLoad(options = {}) {
    if (options.category === "colors") {
      this.setData({ assetMode: "colors" });
    }
    const pendingReference = app.globalData.pendingCustomerReference;
    if (pendingReference) {
      this.setData({
        customerReference: pendingReference,
        customerReferencePreviewPath: pendingReference.filePath,
        customerReferenceType: pendingReference.referenceType || options.reference_type || "hairstyle",
        assetMode: pendingReference.referenceType === "hair_color" ? "colors" : this.data.assetMode
      });
      app.globalData.pendingCustomerReference = null;
    }
    this.loadAssets();
  },

  async loadAssets() {
    const session = api.getSession();
    this.setData({ loading: true });
    try {
      if (this.data.assetMode === "colors") {
        await this.loadColors();
      } else {
        await this.loadStylesByCategory(this.data.category);
      }
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  async loadStylesByCategory(category) {
    const cacheKey = `${this.data.direction}:${category}`;
    if (this.data.styleCache[cacheKey]) {
      this.setData({
        visibleStyles: this.data.styleCache[cacheKey],
        styles: this.mergeById(this.data.styles, this.data.styleCache[cacheKey], "style_id"),
        visibleColors: []
      });
      return;
    }
    const session = api.getSession();
    const params = {
      tenant_id: session.tenantId,
      store_id: session.storeId,
      direction: this.data.direction,
      limit: category === "hot" ? 12 : 18
    };
    if (category === "hot") {
      params.recommended_only = true;
    } else {
      params.hair_length = category;
    }
    const styles = await api.get("/hairstyles", params);
    const decorated = styles.map((item) => ({
      ...item,
      customerBadges: [
        item.need_perm ? "需要烫发" : "不需要烫发",
        "不需要染发"
      ]
    }));
    this.setData({
      [`styleCache.${cacheKey}`]: decorated,
      styles: this.mergeById(this.data.styles, decorated, "style_id"),
      visibleStyles: decorated,
      visibleColors: []
    });
  },

  async loadColors() {
    if (this.data.colorsLoaded) {
      this.setData({ visibleStyles: [], visibleColors: this.data.colors });
      return;
    }
    const session = api.getSession();
    const colors = await api.get("/hair-colors", {
      tenant_id: session.tenantId,
      store_id: session.storeId,
      direction: this.data.direction,
      limit: 24
    });
    const decorated = colors.map((item) => ({
      ...item,
      customerBadges: [
        item.need_bleach ? "需要漂发" : "不需要漂发",
        "需要染发"
      ]
    }));
    this.setData({
      colors: decorated,
      colorsLoaded: true,
      visibleStyles: [],
      visibleColors: decorated
    });
  },

  mergeById(current, incoming, key) {
    const map = {};
    current.forEach((item) => { map[item[key]] = item; });
    incoming.forEach((item) => { map[item[key]] = item; });
    return Object.keys(map).map((id) => map[id]);
  },

  changeDirection(event) {
    this.setData({
      direction: event.currentTarget.dataset.value,
      selectedStyleId: "",
      selectedStyleName: "",
      selectedColorId: "",
      selectedColorName: "",
      styles: [],
      colors: [],
      styleCache: {},
      colorsLoaded: false,
      visibleStyles: [],
      visibleColors: []
    });
    this.loadAssets();
  },

  changeCategory(event) {
    const category = event.currentTarget.dataset.value;
    this.setData({ category });
    this.loadStylesByCategory(category).catch((err) => {
      wx.showToast({ title: err.message, icon: "none" });
    });
  },

  changeAssetMode(event) {
    const assetMode = event.currentTarget.dataset.mode;
    this.setData({ assetMode });
    this.loadAssets();
  },

  refreshVisible() {
    const { assetMode, category, styles, colors } = this.data;
    let visibleStyles = styles;
    if (category === "hot") {
      visibleStyles = styles.filter((item) => item.is_recommended);
    } else {
      visibleStyles = styles.filter((item) => item.hair_length === category);
    }
    this.setData({
      visibleStyles: assetMode === "styles" ? visibleStyles : [],
      visibleColors: assetMode === "colors" ? colors : []
    });
  },

  selectStyle(event) {
    const style = this.data.styles.find((item) => item.style_id === event.currentTarget.dataset.id);
    if (!style) return;
    this.setData({
      previewAssetVisible: true,
      previewAssetType: "style",
      previewAsset: {
        ...style,
        previewImage: style.image_url || style.reference_image_url || style.thumbnail_url || this.data.fallbackStyleImage,
        previewTitle: style.style_name,
        previewDescription: style.customer_description || style.description || "门店造型参考图，确认后将作为本次 AI 试发方向。",
        selected: this.data.selectedStyleId === style.style_id
      }
    });
  },

  selectColor(event) {
    const color = this.data.colors.find((item) => item.color_id === event.currentTarget.dataset.id);
    if (!color) return;
    this.setData({
      previewAssetVisible: true,
      previewAssetType: "color",
      previewAsset: {
        ...color,
        previewImage: color.thumbnail_url || color.image_url || color.reference_image_url || "",
        previewTitle: color.color_name,
        previewDescription: color.customer_description || color.description || "门店发色参考，确认后将作为本次 AI 试发方向。",
        selected: this.data.selectedColorId === color.color_id
      }
    });
  },

  closeAssetPreview() {
    this.setData({
      previewAssetVisible: false,
      previewAssetType: "",
      previewAsset: null
    });
  },

  confirmPreviewAsset() {
    const { previewAssetType, previewAsset } = this.data;
    if (!previewAsset) return;
    if (previewAssetType === "style") {
      this.setData({
        selectedStyleId: previewAsset.style_id,
        selectedStyleName: previewAsset.style_name,
        previewAssetVisible: false,
        previewAssetType: "",
        previewAsset: null
      });
      this.trackAsset("hairstyle", previewAsset.style_id, "select");
      return;
    }
    if (previewAssetType === "color") {
      this.setData({
        selectedColorId: previewAsset.color_id,
        selectedColorName: previewAsset.color_name,
        previewAssetVisible: false,
        previewAssetType: "",
        previewAsset: null
      });
      this.trackAsset("hair_color", previewAsset.color_id, "select");
    }
  },

  previewAssetImage() {
    const asset = this.data.previewAsset;
    if (!asset || !asset.previewImage) return;
    wx.previewImage({
      current: asset.previewImage,
      urls: [asset.previewImage]
    });
  },

  noop() {},

  selectHairProfile(event) {
    const key = event.currentTarget.dataset.key;
    const value = event.currentTarget.dataset.value;
    if (!key || !value) return;
    const current = this.data.hairProfile[key];
    this.setData({
      [`hairProfile.${key}`]: current === value ? "" : value
    });
  },

  selectedHairProfile() {
    const profile = this.data.hairProfile || {};
    const cleaned = {};
    Object.keys(profile).forEach((key) => {
      if (profile[key]) cleaned[key] = profile[key];
    });
    return Object.keys(cleaned).length ? cleaned : null;
  },

  async trackAsset(assetType, assetId, eventType) {
    const session = api.getSession();
    try {
      await api.post("/analytics/asset-events", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId,
        asset_type: assetType,
        asset_id: assetId,
        event_type: eventType
      });
    } catch (err) {
      console.warn("asset event failed", err.message);
    }
  },

  async ensureConsent() {
    const session = api.getSession();
    const status = await api.get("/privacy/consent", {
      tenant_id: session.tenantId,
      user_id: session.userId
    });
    if (status.accepted) return true;
    const confirm = await new Promise((resolve) => {
      wx.showModal({
        title: "授权提示",
        content: "AI造型需要临时使用你的自拍生成预览图，平台不长期保存自拍和生成图。",
        confirmText: "同意",
        cancelText: "不同意",
        success: (res) => resolve(res.confirm)
      });
    });
    if (!confirm) return false;
    await api.post("/privacy/consent", {
      tenant_id: session.tenantId,
      user_id: session.userId,
      consent_scope: "photo_ai_generation",
      consent_version: "v1"
    });
    return true;
  },

  async chooseLocalImage(emptyMessage) {
    const result = await new Promise((resolve, reject) => {
      wx.chooseMedia({
        count: 1,
        mediaType: ["image"],
        sourceType: ["camera", "album"],
        sizeType: ["compressed"],
        success: resolve,
        fail: reject
      });
    });
    const file = result.tempFiles && result.tempFiles[0];
    if (!file || !file.tempFilePath) {
      throw new Error(emptyMessage);
    }
    const matched = file.tempFilePath.match(/\.([a-zA-Z0-9]+)$/);
    const ext = matched ? matched[1].toLowerCase() : "jpg";
    return {
      filePath: file.tempFilePath,
      fileExt: ["jpg", "jpeg", "png", "webp"].includes(ext) ? ext : "jpg"
    };
  },

  chooseSelfie() {
    return this.chooseLocalImage("请选择一张自拍");
  },

  async uploadTempImage(localImage) {
    const session = api.getSession();
    const upload = await api.post("/uploads/temp-url", {
      tenant_id: session.tenantId,
      store_id: session.storeId,
      user_id: session.userId,
      file_ext: localImage.fileExt
    });
    if (upload.provider !== "mock") {
      await api.uploadToPresignedPut(upload.upload_url, localImage.filePath);
    }
    return upload.photo_temp_url;
  },

  async startGenerate() {
    const { selectedStyleId, selectedColorId, customerReference } = this.data;
    if (!selectedStyleId && !selectedColorId && !customerReference) {
      wx.showToast({ title: "请选择发型、发色或上传参考图", icon: "none" });
      return;
    }
    const session = api.getSession();
    this.setData({ loading: true });
    try {
      const quota = await api.get("/ai/quota/today", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId
      });
      if (!quota.in_store && !app.globalData.devAllowTrialWithoutScan) {
        wx.showToast({ title: "请先返回首页点击到店扫码", icon: "none" });
        return;
      }
      if (quota.free_remaining <= 0 && (quota.gift_remaining || 0) <= 0) {
        wx.showToast({ title: "今日免费次数已用完", icon: "none" });
        return;
      }
      const consented = await this.ensureConsent();
      if (!consented) {
        wx.showToast({ title: "需要授权后继续", icon: "none" });
        return;
      }
      const selfie = await this.chooseSelfie();
      this.setData({
        confirmSelfieVisible: true,
        pendingSelfie: selfie,
        selfiePreviewPath: selfie.filePath,
        remainingQuota: quota.free_remaining > 0 ? quota.free_remaining : quota.gift_remaining
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  cancelSelfieConfirmation() {
    if (this.data.loading) return;
    this.setData({
      confirmSelfieVisible: false,
      pendingSelfie: null,
      selfiePreviewPath: ""
    });
  },

  async chooseSelfieAgain() {
    if (this.data.loading) return;
    try {
      const selfie = await this.chooseSelfie();
      this.setData({
        pendingSelfie: selfie,
        selfiePreviewPath: selfie.filePath
      });
    } catch (err) {
      if (err && err.errMsg && err.errMsg.includes("cancel")) return;
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async confirmSelfieGenerate() {
    const selfie = this.data.pendingSelfie;
    if (!selfie || this.data.loading) return;
    const { selectedStyleId, selectedColorId, customerReference } = this.data;
    const session = api.getSession();
    this.setData({ loading: true });
    try {
      const quota = await api.get("/ai/quota/today", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId
      });
      if (!quota.in_store && !app.globalData.devAllowTrialWithoutScan) {
        throw new Error("请先返回首页点击到店扫码");
      }
      if (quota.free_remaining <= 0 && (quota.gift_remaining || 0) <= 0) {
        throw new Error("今日免费次数已用完");
      }
      const billingType = quota.free_remaining > 0 ? "free" : "gift";
      this.setData({ remainingQuota: quota.free_remaining > 0 ? quota.free_remaining : quota.gift_remaining });
      const photoTempUrl = await this.uploadTempImage(selfie);
      const customerReferenceUrl = customerReference ? await this.uploadTempImage(customerReference) : null;
      const payload = {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId,
        direction: this.data.direction,
        billing_type: billingType,
        selected_style_id: selectedStyleId || null,
        selected_color_id: selectedColorId || null,
        photo_temp_url: photoTempUrl,
        customer_reference_url: customerReferenceUrl,
        customer_reference_type: customerReferenceUrl ? (this.data.customerReferenceType || "hairstyle") : null,
        hair_profile: this.selectedHairProfile()
      };
      const job = app.globalData.useSyncGenerate
        ? await api.post("/ai/style/generate", payload)
        : await api.post("/ai/style/enqueue", payload);
      this.setData({
        confirmSelfieVisible: false,
        pendingSelfie: null,
        selfiePreviewPath: "",
        customerReference: null,
        customerReferencePreviewPath: "",
        customerReferenceType: ""
      });
      wx.navigateTo({ url: `/pages/result/index?job_no=${job.job_no}` });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  goHome() {
    wx.navigateTo({ url: "/pages/home/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goMember() {
    wx.navigateTo({ url: "/pages/member/index" });
  },

  goChat() {
    wx.navigateTo({ url: "/pages/ai-chat/index" });
  },

  goMe() {
    wx.navigateTo({ url: "/pages/me/index" });
  }
});
