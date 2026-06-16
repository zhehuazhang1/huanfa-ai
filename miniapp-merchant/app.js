App({
  globalData: {
    apiBaseUrl: "https://api.huanfaai.com",
    tenantId: 1,
    storeId: 1,
    staffId: 2,
    accessToken: ""
  },

  onLaunch() {
    // 把登录 Promise 存起来，页面可以 await this.loginReady
    this.loginReady = this._doLogin();
  },

  async _doLogin() {
    // 已有缓存 token，直接用
    const cached = wx.getStorageSync("merchant_token");
    if (cached) {
      this.globalData.accessToken = cached;
      return;
    }
    try {
      const res = await new Promise((resolve, reject) => {
        wx.request({
          url: `${this.globalData.apiBaseUrl}/auth/merchant-login`,
          method: "POST",
          data: {
            tenant_id: this.globalData.tenantId,
            store_id: this.globalData.storeId,
            openid: "manager_openid",
            phone: "13900000001",
            nickname: "演示店长"
          },
          header: { "content-type": "application/json" },
          timeout: 10000,
          success(r) {
            if (r.statusCode >= 200 && r.statusCode < 300) resolve(r.data);
            else reject(new Error((r.data && r.data.detail) || "登录失败"));
          },
          fail(err) { reject(new Error(err.errMsg || "网络不可用")); }
        });
      });
      wx.setStorageSync("merchant_token", res.access_token);
      wx.setStorageSync("merchant_user_id", res.user.id);
      this.globalData.accessToken = res.access_token;
      this.globalData.staffId = res.user.id;
    } catch (err) {
      console.error("商家端登录失败", err.message);
    }
  }
});
