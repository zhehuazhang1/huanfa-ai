const api = require("../../utils/api");

Page({
  data: {
    items: [],
    filteredItems: [],
    filterCategory: "all",
    dialogVisible: false,
    dialogSubmitting: false,
    dialogMode: "create",
    editingId: null,
    categoryIndex: 0,
    currentCategoryLabel: "活动套餐",
    categoryOptions: [
      { label: "活动套餐", value: "campaign" },
      { label: "价格说明", value: "price" },
      { label: "护理建议", value: "care" },
      { label: "预约到店", value: "booking" },
      { label: "AI试发", value: "tryon" },
      { label: "通用客服", value: "general" }
    ],
    categoryText: {
      campaign: "活动套餐",
      price: "价格说明",
      care: "护理建议",
      booking: "预约到店",
      tryon: "AI试发",
      general: "通用客服"
    },
    tabs: [
      { label: "全部", value: "all" },
      { label: "活动", value: "campaign" },
      { label: "价格", value: "price" },
      { label: "护理", value: "care" },
      { label: "预约", value: "booking" }
    ],
    dialogForm: {
      question: "",
      answer: "",
      keywordsText: ""
    }
  },

  onShow() {
    this.loadItems();
  },

  async loadItems() {
    const s = api.session();
    try {
      const items = await api.get("/merchant/ai-knowledge", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        include_disabled: true
      });
      this.setData({
        items: items.map((item) => this.decorateItem(item))
      });
      this.refreshFilteredItems();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  decorateItem(item) {
    return {
      ...item,
      categoryLabel: this.data.categoryText[item.category] || item.category,
      keywordsText: (item.keywords || []).join("、"),
      statusLabel: item.is_enabled ? "启用中" : "已停用"
    };
  },

  changeTab(event) {
    this.setData({ filterCategory: event.currentTarget.dataset.value });
    this.refreshFilteredItems();
  },

  refreshFilteredItems() {
    const category = this.data.filterCategory;
    const filteredItems = category === "all"
      ? this.data.items
      : this.data.items.filter((item) => item.category === category);
    this.setData({ filteredItems });
  },

  changeDialogCategory(event) {
    const categoryIndex = Number(event.detail.value || 0);
    this.setData({
      categoryIndex,
      currentCategoryLabel: this.data.categoryOptions[categoryIndex].label
    });
  },

  inputQuestion(event) {
    this.setData({ "dialogForm.question": event.detail.value });
  },

  inputAnswer(event) {
    this.setData({ "dialogForm.answer": event.detail.value });
  },

  inputKeywords(event) {
    this.setData({ "dialogForm.keywordsText": event.detail.value });
  },

  addItem() {
    this.setData({
      dialogVisible: true,
      dialogSubmitting: false,
      dialogMode: "create",
      editingId: null,
      categoryIndex: 0,
      currentCategoryLabel: this.data.categoryOptions[0].label,
      dialogForm: {
        question: "",
        answer: "",
        keywordsText: ""
      }
    });
  },

  editItem(event) {
    const itemId = Number(event.currentTarget.dataset.id);
    const item = this.data.items.find((row) => row.id === itemId);
    if (!item) return;
    const categoryIndex = Math.max(0, this.data.categoryOptions.findIndex((option) => option.value === item.category));
    this.setData({
      dialogVisible: true,
      dialogSubmitting: false,
      dialogMode: "edit",
      editingId: item.id,
      categoryIndex,
      currentCategoryLabel: this.data.categoryOptions[categoryIndex].label,
      dialogForm: {
        question: item.question,
        answer: item.answer,
        keywordsText: item.keywordsText
      }
    });
  },

  closeDialog() {
    if (this.data.dialogSubmitting) return;
    this.setData({ dialogVisible: false });
  },

  noop() {},

  parseKeywords(text) {
    return (text || "")
      .split(/[,，、\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  },

  async saveDialog() {
    const s = api.session();
    const form = this.data.dialogForm;
    const category = this.data.categoryOptions[this.data.categoryIndex].value;
    if (!form.question.trim() || !form.answer.trim()) {
      wx.showToast({ title: "请填写问题和回答", icon: "none" });
      return;
    }
    this.setData({ dialogSubmitting: true });
    try {
      const payload = {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        category,
        question: form.question.trim(),
        answer: form.answer.trim(),
        keywords: this.parseKeywords(form.keywordsText),
        is_enabled: true,
        sort_order: 100
      };
      if (this.data.dialogMode === "edit") {
        await api.put(`/merchant/ai-knowledge/${this.data.editingId}`, payload);
      } else {
        await api.post("/merchant/ai-knowledge", payload);
      }
      wx.showToast({ title: "已保存", icon: "success" });
      this.setData({ dialogVisible: false });
      this.loadItems();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    } finally {
      this.setData({ dialogSubmitting: false });
    }
  },

  async toggleItem(event) {
    const itemId = Number(event.currentTarget.dataset.id);
    const enabled = event.currentTarget.dataset.enabled === "true";
    const s = api.session();
    try {
      await api.put(`/merchant/ai-knowledge/${itemId}`, {
        tenant_id: s.tenantId,
        is_enabled: !enabled
      });
      wx.showToast({ title: enabled ? "已停用" : "已启用", icon: "success" });
      this.loadItems();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
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

  goCustomers() {
    wx.navigateTo({ url: "/pages/merchant-customers/index" });
  },

  goPerformance() {
    wx.navigateTo({ url: "/pages/merchant-performance/index" });
  }
});
