const api = require("../../utils/api");

Page({
  data: {
    staff: [],
    statusOptions: [
      { label: "在店", value: "available" },
      { label: "忙碌", value: "busy" },
      { label: "离店", value: "off_duty" }
    ],
    statusText: {
      available: "在店",
      busy: "忙碌",
      off_duty: "离店"
    },
    tagText: {
      female: "女发",
      male: "男发",
      neutral: "中性",
      color: "染发",
      perm: "烫发",
      "short hair": "短发",
      "medium hair": "中发",
      "long hair": "长发",
      texture: "纹理",
      business: "商务",
      brightening: "显白"
    }
  },

  onShow() {
    this.loadStaff();
  },

  async loadStaff() {
    const s = api.session();
    try {
      const staff = await api.get("/merchant/staff", {
        tenant_id: s.tenantId,
        store_id: s.storeId
      });
      this.setData({ staff: staff.map((item) => this.decorateStaff(item)) });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  decorateStaff(item) {
    const directions = (item.directions || []).map((tag) => this.data.tagText[tag] || tag);
    const skills = (item.skill_tags || []).map((tag) => this.data.tagText[tag] || tag);
    const allTags = [...directions, ...skills].filter(Boolean);
    return {
      ...item,
      avatarText: item.display_name ? String(item.display_name).slice(0, 1) : "主",
      displayDirections: directions,
      displaySkills: skills,
      tagSummary: allTags.slice(0, 4).join(" · ") || "暂未设置擅长方向",
      extraTagCount: Math.max(allTags.length - 4, 0),
      statusLabel: this.data.statusText[item.availability_status] || "未设置"
    };
  },

  async changeStatus(event) {
    const s = api.session();
    const staffId = event.currentTarget.dataset.id;
    const status = event.currentTarget.dataset.status;
    try {
      await api.put(`/merchant/staff/${staffId}/status`, {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        availability_status: status
      });
      wx.showToast({ title: "已更新", icon: "success" });
      this.loadStaff();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  addStaff() {
    wx.showModal({
      title: "新增主理人",
      editable: true,
      placeholderText: "输入主理人姓名",
      success: async (res) => {
        if (!res.confirm || !res.content) return;
        const s = api.session();
        const seed = Date.now();
        try {
          await api.post("/merchant/staff", {
            tenant_id: s.tenantId,
            store_id: s.storeId,
            openid: `staff_${seed}`,
            phone: "",
            display_name: res.content,
            title: "主理人",
            directions: ["female", "male", "neutral"],
            skill_tags: ["剪发", "染发"],
            role: "staff",
            sort_order: 90
          });
          wx.showToast({ title: "已新增", icon: "success" });
          this.loadStaff();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
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

  goAssets() {
    wx.navigateTo({ url: "/pages/assets/index" });
  }
});
