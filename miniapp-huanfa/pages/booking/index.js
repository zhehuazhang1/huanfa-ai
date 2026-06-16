const api = require("../../utils/api");

function pad(value) {
  return String(value).padStart(2, "0");
}

function formatDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function shortDate(date) {
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())}`;
}

function serviceDisplayName(name) {
  const map = {
    Haircut: "剪发",
    Color: "染发",
    Perm: "烫发",
    Styling: "造型",
    Care: "护理"
  };
  return map[name] || name;
}

Page({
  data: {
    jobNo: "",
    submitting: false,
    selectedStylistId: null,
    selectedStylist: {},
    stylists: [],
    serviceItems: [],
    selectedServiceIds: [],
    selectedServiceIdsMap: {},
    selectedDate: "",
    selectedTime: "15:30",
    note: "",
    direction: "",
    selectedStyleId: "",
    selectedColorId: "",
    styleName: "",
    colorName: "",
    planImage: "",
    talkTags: ["刘海长度", "两侧层次", "卷度", "发尾厚薄"],
    dateOptions: [],
    timeGroups: [
      { label: "上午", icon: "☼", slots: ["09:30", "10:30", "11:30"] },
      { label: "下午", icon: "☀", slots: ["14:00", "15:30", "17:00"] },
      { label: "晚上", icon: "☾", slots: ["19:00", "20:30"] }
    ],
    fallbackAvatar: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=200",
    fallbackPlanImage: "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=500"
  },

  onLoad(options = {}) {
    const today = new Date();
    const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
    this.setData({
      jobNo: options.job_no || "",
      selectedStylistId: options.stylist_id ? Number(options.stylist_id) : null,
      selectedDate: formatDate(today),
      dateOptions: [
        { label: "今天", value: formatDate(today), short: shortDate(today) },
        { label: "明天", value: formatDate(tomorrow), short: shortDate(tomorrow) }
      ]
    });
    this.loadPageData();
  },

  async loadPageData() {
    await Promise.all([this.loadResultDetail(), this.loadServiceItems()]);
  },

  async loadResultDetail() {
    if (!this.data.jobNo) return;
    const session = api.getSession();
    try {
      const detail = await api.get(`/ai/style/results/${this.data.jobNo}`, {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId
      });
      const images = detail.carousel && detail.carousel.images ? detail.carousel.images : [];
      const mainImage = images.find((item) => item.slot === "main") || images[0] || {};
      const stylists = (detail.recommended_stylists || []).map((item) => ({
        ...item,
        skillsText: (item.skill_tags || []).slice(0, 3).join("、") || "修剪、造型"
      }));
      const selectedStylist = stylists.find((item) => item.staff_id === this.data.selectedStylistId) || stylists[0] || {};
      const talkTags = (detail.result_tags || []).map((item) => item.label).slice(0, 4);
      this.setData({
        direction: detail.direction,
        selectedStyleId: detail.selected_style_id,
        selectedColorId: detail.selected_color_id,
        planImage: mainImage.temp_image_url || "",
        styleName: mainImage.style_name || "",
        colorName: mainImage.color_name || "",
        stylists,
        selectedStylist,
        selectedStylistId: selectedStylist.staff_id || null,
        talkTags: talkTags.length ? talkTags : this.data.talkTags
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async loadServiceItems() {
    const session = api.getSession();
    try {
      const serviceItems = await api.get("/service-items", {
        tenant_id: session.tenantId,
        store_id: session.storeId
      });
      this.setData({
        serviceItems: serviceItems
          .filter((item) => item.is_enabled !== 0)
          .map((item) => ({ ...item, display_name: item.display_name || serviceDisplayName(item.name), selected: false }))
      });
    } catch (err) {
      this.setData({
        serviceItems: [
          { id: "cut", name: "剪发", display_name: "剪发", selected: false },
          { id: "color", name: "染发", display_name: "染发", selected: false },
          { id: "perm", name: "烫发", display_name: "烫发", selected: false },
          { id: "care", name: "护理", display_name: "护理", selected: false },
          { id: "consult", name: "到店沟通", display_name: "到店沟通", selected: false }
        ]
      });
    }
  },

  chooseStylist() {
    const stylists = this.data.stylists || [];
    if (stylists.length <= 1) return;
    wx.showActionSheet({
      itemList: stylists.map((item) => item.display_name),
      success: (res) => {
        const selectedStylist = stylists[res.tapIndex];
        this.setData({
          selectedStylist,
          selectedStylistId: selectedStylist.staff_id
        });
      }
    });
  },

  toggleService(event) {
    const id = event.currentTarget.dataset.id;
    const selected = this.data.selectedServiceIds.slice();
    const index = selected.indexOf(id);
    if (index >= 0) {
      selected.splice(index, 1);
    } else {
      selected.push(id);
    }
    const map = {};
    selected.forEach((item) => { map[item] = true; });
    this.setData({
      selectedServiceIds: selected,
      selectedServiceIdsMap: map,
      serviceItems: this.data.serviceItems.map((item) => ({ ...item, selected: Boolean(map[item.id]) }))
    });
  },

  selectDate(event) {
    this.setData({ selectedDate: event.currentTarget.dataset.value });
  },

  pickMoreDate(event) {
    const selectedDate = event.detail.value;
    const exists = this.data.dateOptions.some((item) => item.value === selectedDate);
    const dateOptions = exists
      ? this.data.dateOptions
      : this.data.dateOptions.concat([{ label: "已选", value: selectedDate, short: selectedDate.slice(5).replace("-", "/") }]);
    this.setData({ selectedDate, dateOptions });
  },

  selectTime(event) {
    this.setData({ selectedTime: event.currentTarget.dataset.time });
  },

  onNoteInput(event) {
    this.setData({ note: event.detail.value });
  },

  submitBooking() {
    if (this.data.selectedServiceIds.length === 0) {
      wx.showToast({ title: "请选择服务项目", icon: "none" });
      return;
    }
    if (!this.data.selectedDate || !this.data.selectedTime) {
      wx.showToast({ title: "请选择预约时间", icon: "none" });
      return;
    }
    this.createBooking();
  },

  async createBooking() {
    const session = api.getSession();
    const serviceNames = this.data.serviceItems
      .filter((item) => this.data.selectedServiceIdsMap[item.id])
      .map((item) => item.display_name || item.name);
    const notes = [
      `预约服务：${serviceNames.join("、")}`,
      `沟通重点：${this.data.talkTags.join("、")}`,
      this.data.note ? `顾客备注：${this.data.note}` : ""
    ].filter(Boolean).join("；");

    this.setData({ submitting: true });
    try {
      await api.post("/orders", {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId,
        stylist_id: this.data.selectedStylistId || null,
        direction: this.data.direction,
        hairstyle_id: this.data.selectedStyleId,
        hair_color_id: this.data.selectedColorId,
        ai_job_no: this.data.jobNo || null,
        appointment_time: `${this.data.selectedDate} ${this.data.selectedTime}:00`,
        notes
      });
      wx.showToast({ title: "已提交预约", icon: "success" });
      setTimeout(() => wx.navigateTo({ url: "/pages/orders/index" }), 500);
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  },

  goBack() {
    wx.navigateBack();
  }
});
