const app = getApp();

Page({
  enterCustomer() {
    wx.setStorageSync("app_mode", "customer");
    app.ensureLogin()
      .then(() => {
        wx.reLaunch({ url: "/pages/home/index" });
      })
      .catch((err) => {
        wx.showToast({ title: err.message || "顾客登录失败", icon: "none" });
      });
  },

  enterMerchant() {
    wx.setStorageSync("app_mode", "merchant");
    app.ensureMerchantLogin()
      .then(() => {
        wx.reLaunch({ url: "/pages/merchant-workbench/index" });
      })
      .catch((err) => {
        wx.showToast({ title: err.message || "商家登录失败", icon: "none" });
      });
  }
});
