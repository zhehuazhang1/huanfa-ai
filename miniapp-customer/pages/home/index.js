const api = require("../../utils/api");
const app = getApp();

Page({
  data: {
    quotaText: "未登录",
    storeProfile: {},
    storePhotos: [
      { title: "专属试发方案", desc: "上传自拍，预览适合你的造型方向", url: "https://images.unsplash.com/photo-1562322140-8baeececf3df?w=900" },
      { title: "门店热门发色", desc: "从低调冷棕到高质感茶色", url: "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=900" },
      { title: "主理人推荐造型", desc: "带着参考图到店沟通更清楚", url: "https://images.unsplash.com/photo-1521590832167-7bcbfaa6381f?w=900" }
    ],
    popularStyles: [
      { title: "法式纹理卷", tags: ["中长发", "微卷"], url: "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=500" },
      { title: "冷棕层次发", tags: ["显白", "低调"], url: "https://images.unsplash.com/photo-1519699047748-de8e457a634e?w=500" },
      { title: "清爽短发", tags: ["短发", "自然"], url: "https://images.unsplash.com/photo-1562322140-8baeececf3df?w=500" }
    ]
  },

  onLoad() {
    this.ensureLogin();
    this.loadStoreProfile();
  },

  async loadStoreProfile() {
    const session = api.getSession();
    try {
      const profile = await api.get("/stores/public-profile", {
        tenant_id: session.tenantId,
        store_id: session.storeId
      });
      this.setData({
        storeProfile: profile,
        storePhotos: profile.store_photos && profile.store_photos.length ? profile.store_photos : this.data.storePhotos
      });
    } catch (err) {
      console.warn("load store profile failed", err.message || err);
    }
  },

  async ensureLogin() {
    try {
      const cachedUserId = wx.getStorageSync("user_id");
      if (!cachedUserId) {
        const res = await api.post("/auth/wx-login", {
          tenant_id: app.globalData.tenantId,
          store_id: app.globalData.storeId,
          openid: app.globalData.demoOpenid,
          phone: "13800000000",
          nickname: "演示顾客"
        });
        wx.setStorageSync("tenant_id", res.user.tenant_id);
        wx.setStorageSync("store_id", res.user.store_id || app.globalData.storeId);
        wx.setStorageSync("user_id", res.user.id);
        wx.setStorageSync("access_token", res.access_token);
      }
      await this.refreshQuota();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async refreshQuota() {
    const session = api.getSession();
    const quota = await api.get("/ai/quota/today", {
      tenant_id: session.tenantId,
      store_id: session.storeId,
      user_id: session.userId
    });
    this.setData({
      quotaText: quota.in_store || app.globalData.devAllowTrialWithoutScan
        ? `今日可试 ${quota.free_remaining} 次`
        : "未到店"
    });
  },

  async scanStore() {
    const session = api.getSession();
    try {
      await api.post("/stores/scan-qr", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId,
        qr_scene: `store:${session.tenantId}:${session.storeId}`
      });
      await this.refreshQuota();
      wx.showToast({ title: "已确认到店", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  startStyle() {
    wx.navigateTo({ url: "/pages/style/index" });
  },

  goStyle() {
    wx.navigateTo({ url: "/pages/style/index" });
  },

  async chooseReferenceImage() {
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
      throw new Error("请选择一张参考图");
    }
    const matched = file.tempFilePath.match(/\.([a-zA-Z0-9]+)$/);
    const ext = matched ? matched[1].toLowerCase() : "jpg";
    return {
      filePath: file.tempFilePath,
      fileExt: ["jpg", "jpeg", "png", "webp"].includes(ext) ? ext : "jpg"
    };
  },

  chooseReferenceType() {
    return new Promise((resolve, reject) => {
      wx.showActionSheet({
        itemList: ["参考发型", "参考发色"],
        success: (res) => {
          resolve(res.tapIndex === 1 ? "hair_color" : "hairstyle");
        },
        fail: reject
      });
    });
  },

  async startStyleWithReference() {
    try {
      const referenceType = await this.chooseReferenceType();
      const reference = await this.chooseReferenceImage();
      app.globalData.pendingCustomerReference = {
        ...reference,
        referenceType
      };
      wx.navigateTo({ url: `/pages/style/index?from_reference=1&reference_type=${referenceType}` });
    } catch (err) {
      if (err && err.errMsg && err.errMsg.includes("cancel")) return;
      wx.showToast({ title: err.message, icon: "none" });
    }
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

