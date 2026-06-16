const api = require("../../utils/api");

Page({
  data: {
    loading: false,
    customer: {},
    quota: {},
    membership: {},
    packages: [],
    genderText: {
      female: "女性",
      male: "男性",
      neutral: "中性",
      unknown: "未填写"
    }
  },

  onShow() {
    this.loadProfile();
  },

  async loadProfile() {
    const session = api.getSession();
    this.setData({ loading: true });
    try {
      const data = await api.get("/me/profile", {
        tenant_id: session.tenantId,
        store_id: session.storeId
      });
      this.setData({
        customer: data.customer || {},
        quota: data.quota || {},
        membership: data.membership || {},
        packages: data.packages || []
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  editName() {
    wx.showModal({
      title: "修改昵称",
      editable: true,
      placeholderText: this.data.customer.display_name || "请输入昵称",
      success: (res) => {
        if (!res.confirm) return;
        this.saveProfile({ nickname: res.content || "" });
      }
    });
  },

  editBirthday() {
    wx.showModal({
      title: "出生日期",
      editable: true,
      placeholderText: this.data.customer.birthday || "例如 1998-06-15",
      success: (res) => {
        if (!res.confirm) return;
        this.saveProfile({ birthday: res.content || "" });
      }
    });
  },

  changeGender() {
    wx.showActionSheet({
      itemList: ["女性", "男性", "中性", "不填写"],
      success: (res) => {
        const values = ["female", "male", "neutral", "unknown"];
        this.saveProfile({ gender: values[res.tapIndex] || "unknown" });
      }
    });
  },

  async saveProfile(patch) {
    const session = api.getSession();
    try {
      await api.put("/me/profile", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        nickname: patch.nickname !== undefined ? patch.nickname : this.data.customer.nickname,
        birthday: patch.birthday !== undefined ? patch.birthday : this.data.customer.birthday,
        gender: patch.gender !== undefined ? patch.gender : this.data.customer.gender,
        profile_note: this.data.customer.profile_note || ""
      });
      wx.showToast({ title: "已保存", icon: "success" });
      this.loadProfile();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  goHome() {
    wx.navigateTo({ url: "/pages/home/index" });
  },

  goStyle() {
    wx.navigateTo({ url: "/pages/style/index" });
  },

  goOrders() {
    wx.navigateTo({ url: "/pages/orders/index" });
  },

  goMember() {
    wx.navigateTo({ url: "/pages/member/index" });
  },

  goChat() {
    wx.navigateTo({ url: "/pages/ai-chat/index" });
  }
});
