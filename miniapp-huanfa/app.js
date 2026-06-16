App({
  globalData: {
    apiBaseUrl: "https://api.huanfaai.com",
    tenantId: 1,
    storeId: 1,
    staffId: 2,
    demoOpenid: "demo_customer_openid",
    merchantDemoOpenid: "demo_merchant_openid",
    useSyncGenerate: false,
    devAllowTrialWithoutScan: true,
    allowDemoLoginFallback: true,
    useDemoLogin: false,
    accessToken: ""
  },

  ensureLogin(force) {
    if (force) this._loginPromise = null;
    if (this._loginPromise) return this._loginPromise;

    const token = wx.getStorageSync("access_token");
    const userId = wx.getStorageSync("user_id");
    const loginMode = wx.getStorageSync("login_mode");
    const expectedMode = this.globalData.useDemoLogin ? "demo_openid" : "wechat_code";
    if (!force && token && userId && loginMode === expectedMode) {
      this._loginPromise = Promise.resolve();
      return this._loginPromise;
    }

    this._loginPromise = (this.globalData.useDemoLogin ? this.loginWithDemoOpenid() : this.loginWithWechat())
      .catch((err) => {
        if (!this.globalData.allowDemoLoginFallback) throw err;
        console.warn("wx login failed, fallback to demo login", err && err.message);
        return this.loginWithDemoOpenid();
      })
      .catch((err) => {
        this._loginPromise = null;
        throw err;
      });
    return this._loginPromise;
  },

  loginWithWechat() {
    return new Promise((resolve, reject) => {
      wx.login({
        success: (loginRes) => {
          if (!loginRes.code) {
            reject(new Error("微信登录失败，请重新打开小程序"));
            return;
          }
          this.requestLogin({
            tenant_id: this.globalData.tenantId,
            store_id: this.globalData.storeId,
            code: loginRes.code,
            nickname: "微信顾客"
          }).then(resolve).catch(reject);
        },
        fail: (err) => reject(new Error(err.errMsg || "微信登录失败"))
      });
    });
  },

  loginWithDemoOpenid() {
    return this.requestLogin({
      tenant_id: this.globalData.tenantId,
      store_id: this.globalData.storeId,
      openid: this.globalData.demoOpenid,
      phone: "13800000000",
      nickname: "演示顾客"
    });
  },

  requestLogin(payload) {
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${this.globalData.apiBaseUrl}/auth/wx-login`,
        method: "POST",
        header: { "content-type": "application/json" },
        data: payload,
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300 && res.data && res.data.access_token) {
            const u = res.data.user || {};
            wx.setStorageSync("tenant_id", u.tenant_id || this.globalData.tenantId);
            wx.setStorageSync("store_id", u.store_id || this.globalData.storeId);
            wx.setStorageSync("user_id", u.id);
            wx.setStorageSync("access_token", res.data.access_token);
            wx.setStorageSync("login_mode", payload.code ? "wechat_code" : "demo_openid");
            resolve();
          } else {
            reject(new Error((res.data && res.data.detail) || "登录失败"));
          }
        },
        fail: (err) => reject(new Error(err.errMsg || "网络不可用"))
      });
    });
  },

  ensureMerchantLogin(force) {
    if (force) this._merchantLoginPromise = null;
    if (this._merchantLoginPromise) return this._merchantLoginPromise;

    const cached = wx.getStorageSync("merchant_token");
    if (!force && cached) {
      this.globalData.accessToken = cached;
      this._merchantLoginPromise = Promise.resolve();
      return this._merchantLoginPromise;
    }

    this._merchantLoginPromise = new Promise((resolve, reject) => {
      wx.request({
        url: `${this.globalData.apiBaseUrl}/auth/merchant-login`,
        method: "POST",
        header: { "content-type": "application/json" },
        data: {
          tenant_id: this.globalData.tenantId,
          store_id: this.globalData.storeId,
          openid: this.globalData.merchantDemoOpenid,
          nickname: "演示商家"
        },
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300 && res.data && res.data.access_token) {
            this.globalData.accessToken = res.data.access_token;
            wx.setStorageSync("merchant_token", res.data.access_token);
            const u = res.data.user || {};
            if (u.tenant_id) this.globalData.tenantId = u.tenant_id;
            if (u.store_id) this.globalData.storeId = u.store_id;
            resolve();
          } else {
            reject(new Error((res.data && res.data.detail) || "商家登录失败"));
          }
        },
        fail: (err) => reject(new Error(err.errMsg || "网络不可用"))
      });
    }).catch((err) => {
      this._merchantLoginPromise = null;
      throw err;
    });
    return this._merchantLoginPromise;
  },

  onLaunch() {
    this.ensureLogin().catch((e) => console.warn("global login failed", e && e.message));
  }
});
