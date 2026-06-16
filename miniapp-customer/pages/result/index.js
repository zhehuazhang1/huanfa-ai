const api = require("../../utils/api");

Page({
  data: {
    jobNo: "",
    currentIndex: 0,
    images: [],
    stylists: [],
    selectedStylistId: null,
    resultTags: [],
    saveHint: "长按保存或截图，退出后不可找回",
    ordering: false,
    fallbackAvatar: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=200",
    selectedStyleId: "",
    selectedColorId: "",
    direction: "female",
    generating: true,
    generationFailed: false,
    recommendationsLoading: false,
    generationText: "正在生成造型，请稍候",
    currentPlanTitle: "当前方案",
    currentPlanDesc: "",
    currentPlanTags: []
  },

  onLoad(options) {
    this.setData({ jobNo: options.job_no || "" });
    wx.setNavigationBarTitle({ title: "生成中" });
    this.pollResult();
  },

  onUnload() {
    if (this.pollTimer) clearTimeout(this.pollTimer);
  },

  async pollResult() {
    const session = api.getSession();
    try {
      const job = await api.get(`/ai/style/jobs/${this.data.jobNo}`, {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId
      });
      if (job.status === "success") {
        await this.loadResult(false);
        return;
      }
      if (job.main_status === "success") {
        await this.loadResult(true);
        this.pollTimer = setTimeout(() => this.pollResult(), 3000);
        return;
      }
      if (["failed", "timeout", "cancelled"].includes(job.status)) {
        const message = job.error_code === "ALIYUN_HAIR_TRYON_FAILED"
          ? "AI 发型服务尚未开通，请联系门店工作人员"
          : (job.error_message || "生成失败，请返回后重试");
        this.setData({
          generating: false,
          generationFailed: true,
          generationText: message
        });
        wx.setNavigationBarTitle({ title: "生成失败" });
        return;
      }
      this.setData({
        generating: true,
        generationText: job.status === "queued" ? "正在排队，请稍候" : "正在生成造型，请稍候"
      });
      this.pollTimer = setTimeout(() => this.pollResult(), 3000);
    } catch (err) {
      this.setData({ generationText: "网络波动，正在重新连接" });
      this.pollTimer = setTimeout(() => this.pollResult(), 3000);
    }
  },

  async loadResult(recommendationsLoading = false) {
    const session = api.getSession();
    try {
      const detail = await api.get(`/ai/style/results/${this.data.jobNo}`, {
        tenant_id: session.tenantId,
        store_id: session.storeId,
        user_id: session.userId
      });
      this.setData({
        generating: false,
        generationFailed: false,
        recommendationsLoading,
        images: this.decorateImages(detail.carousel.images || []),
        stylists: detail.recommended_stylists || [],
        selectedStylistId: detail.default_stylist_id,
        resultTags: detail.result_tags || [],
        saveHint: detail.save_hint || this.data.saveHint,
        selectedStyleId: detail.selected_style_id,
        selectedColorId: detail.selected_color_id,
        direction: detail.direction
      });
      wx.setNavigationBarTitle({ title: "生成结果" });
      this.updateCurrentPlan(this.data.currentIndex);
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  decorateImages(images) {
    return images.map((image) => {
      const tags = [];
      if (image.style_name) tags.push(image.style_name);
      if (image.color_name) tags.push(image.color_name);
      const styleName = image.style_name || "当前发型";
      const colorName = image.color_name || "当前发色";
      const meta = {
        main: {
          title: "本次主推",
          desc: `本方案采用「${styleName}」和「${colorName}」，呈现你本次选择的整体试发效果。`
        },
        natural: {
          title: "灵感搭配",
          desc: `在保留你偏好方向的基础上，搭配「${styleName}」和「${colorName}」，方便主理人参考调整。`
        },
        advanced: {
          title: "门店精选",
          desc: `参考门店近期热门造型，使用「${styleName}」和「${colorName}」生成另一种可沟通方案。`
        }
      }[image.slot] || { title: "推荐方案", desc: "门店为你生成的试发参考方案。" };
      return { ...image, planTitle: meta.title, planDesc: meta.desc, planTags: tags };
    });
  },

  updateCurrentPlan(index) {
    const image = this.data.images[index] || this.data.images[0] || {};
    this.setData({
      currentIndex: index,
      currentPlanTitle: image.planTitle || "当前方案",
      currentPlanDesc: image.planDesc || "",
      currentPlanTags: image.planTags || []
    });
  },

  onSwipe(event) {
    this.updateCurrentPlan(event.detail.current);
  },

  previewImage(event) {
    wx.previewImage({
      urls: this.data.images.map((item) => item.temp_image_url),
      current: event.currentTarget.dataset.url
    });
  },

  selectStylist(event) {
    this.setData({ selectedStylistId: Number(event.currentTarget.dataset.id) });
  },

  async createOrder() {
    if (!this.data.selectedStylistId) {
      wx.showToast({ title: "请选择主理人", icon: "none" });
      return;
    }
    wx.navigateTo({
      url: `/pages/booking/index?job_no=${this.data.jobNo}&stylist_id=${this.data.selectedStylistId}`
    });
  }
});
