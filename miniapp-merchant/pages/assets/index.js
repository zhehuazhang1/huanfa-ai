const api = require("../../utils/api");

Page({
  data: {
    direction: "female",
    assetType: "styles",
    directions: [
      { label: "女性", value: "female" },
      { label: "男性", value: "male" },
      { label: "中性", value: "neutral" }
    ],
    styles: [],
    colors: [],
    hairLengthText: {
      short: "短发",
      medium: "中发",
      long: "长发"
    },
    directionText: {
      female: "女性",
      male: "男性",
      neutral: "中性"
    }
  },

  onShow() {
    this.loadAssets();
  },

  changeDirection(event) {
    this.setData({ direction: event.currentTarget.dataset.value });
    this.loadAssets();
  },

  changeAssetType(event) {
    this.setData({ assetType: event.currentTarget.dataset.type });
  },

  addCurrentAsset() {
    if (this.data.assetType === "colors") {
      this.addColor();
      return;
    }
    this.addStyle();
  },

  openAssetDetail(event) {
    const { type, id } = event.currentTarget.dataset;
    const source = type === "color" ? this.data.colors : this.data.styles;
    const asset = source.find((item) => {
      return type === "color" ? item.color_id === id : item.style_id === id;
    });
    if (!asset) return;
    wx.setStorageSync("asset_detail_payload", {
      type,
      asset,
      direction: this.data.direction
    });
    wx.navigateTo({ url: `/pages/asset-detail/index?type=${type}` });
  },

  async loadAssets() {
    const s = api.session();
    try {
      const [styles, colors] = await Promise.all([
        api.get("/hairstyles", {
          tenant_id: s.tenantId,
          store_id: s.storeId,
          direction: this.data.direction
        }),
        api.get("/hair-colors", {
          tenant_id: s.tenantId,
          store_id: s.storeId,
          direction: this.data.direction
        })
      ]);
      this.setData({
        styles: styles.map((item) => ({
          ...item,
          hairLengthLabel: this.data.hairLengthText[item.hair_length] || item.hair_length || "未设置",
          directionLabel: this.data.directionText[item.direction] || item.direction || "",
          tagText: (item.tags || []).join("、"),
          tagList: (item.tags || []).slice(0, 4)
        })),
        colors: colors.map((item) => ({
          ...item,
          directionLabel: this.data.directionText[item.direction] || item.direction || "",
          tagText: (item.tags || []).join("、"),
          tagList: (item.tags || []).slice(0, 4)
        }))
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async addStyle() {
    try {
      const image = await this.chooseCatalogImage();
      const s = api.session();
      wx.showLoading({ title: "上传图片中" });
      const upload = await api.post("/merchant/assets/upload-url", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        asset_type: "hairstyle",
        file_ext: image.fileExt
      });
      await api.uploadToPresignedPut(upload.upload_url, image.filePath);
      wx.hideLoading();
      wx.showModal({
        title: "填写发型名称",
        editable: true,
        placeholderText: "例如：纹理短发",
        success: async (res) => {
          if (!res.confirm || !res.content) return;
          const styleName = res.content;
          const styleMetadata = await this.askStyleMetadata(styleName);
          try {
            await api.post("/merchant/hairstyles", {
              tenant_id: s.tenantId,
              store_id: s.storeId,
              name: styleName,
              direction: this.data.direction,
              hair_length: "medium",
              thumbnail_url: upload.asset_url,
              display_tags: styleMetadata,
              need_perm: false,
              is_enabled: true,
              is_recommended: true,
              sort_order: 80
            });
            wx.showToast({ title: "已新增", icon: "success" });
            this.loadAssets();
          } catch (err) {
            wx.showToast({ title: err.message, icon: "none" });
          }
        }
      });
    } catch (err) {
      wx.hideLoading();
      if (err.errMsg && err.errMsg.includes("cancel")) return;
      wx.showToast({ title: err.message || err.errMsg || "上传失败", icon: "none" });
    }
  },

  async chooseCatalogImage() {
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
    if (!file || !file.tempFilePath) throw new Error("请选择一张发型图片");
    const matched = file.tempFilePath.match(/\.([a-zA-Z0-9]+)$/);
    const ext = matched ? matched[1].toLowerCase() : "jpg";
    return {
      filePath: file.tempFilePath,
      fileExt: ["jpg", "jpeg", "png", "webp"].includes(ext) ? ext : "jpg"
    };
  },

  manageStyle(event) {
    const style = this.data.styles.find((item) => item.style_id === event.currentTarget.dataset.id);
    if (!style) return;
    wx.showActionSheet({
      itemList: ["修改名称", "编辑客户描述", "编辑发型参数", "设置发长", "替换图片", "删除发型"],
      success: (res) => {
        if (res.tapIndex === 0) this.renameStyle(style);
        if (res.tapIndex === 1) this.editStyleDescription(style);
        if (res.tapIndex === 2) this.editStyleParameters(style);
        if (res.tapIndex === 3) this.editStyleLength(style);
        if (res.tapIndex === 4) this.replaceStyleImage(style);
        if (res.tapIndex === 5) this.removeStyle(style);
      }
    });
  },

  defaultStyleParameterLines() {
    return [
      "发长：中发",
      "刘海：八字刘海",
      "分缝：中分",
      "卷度：微卷",
      "层次：自然层次",
      "发量感：自然",
      "风格：自然"
    ];
  },

  normalizeStyleMetadata(input, styleName) {
    const parameterGroups = (input.parameterLines || this.defaultStyleParameterLines())
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const parts = line.split(/[:：]/);
        const name = (parts.shift() || "").trim();
        const values = parts.join("：").split(/[,，、/]/).map((item) => item.trim()).filter(Boolean);
        return { name, values };
      })
      .filter((item) => item.name && item.values.length);
    const selectedTags = parameterGroups.reduce((all, group) => all.concat(group.values), []);
    const aiReferenceTags = Array.from(new Set([
      ...selectedTags,
      "自然发际线",
      "真实发丝纹理",
      "贴合客户头型",
      "贴合客户脸型",
      "只修改头发区域"
    ]));
    return {
      customer_description: (input.customerDescription || "").trim(),
      parameter_groups: parameterGroups,
      ai_reference_tags: aiReferenceTags,
      style_name: styleName
    };
  },

  askStyleMetadata(styleName) {
    return new Promise((resolve) => {
      wx.showModal({
        title: "客户看到的描述",
        editable: true,
        placeholderText: "例如：发根自然蓬松，修饰脸型，整体自然减龄。",
        success: (descRes) => {
          wx.showModal({
            title: "发型参数",
            editable: true,
            placeholderText: this.defaultStyleParameterLines().join("\n"),
            success: (paramRes) => {
              resolve(this.normalizeStyleMetadata({
                customerDescription: descRes.confirm ? descRes.content : "",
                parameterLines: paramRes.confirm && paramRes.content ? paramRes.content.split("\n") : this.defaultStyleParameterLines()
              }, styleName));
            },
            fail: () => resolve(this.normalizeStyleMetadata({ customerDescription: descRes.content }, styleName))
          });
        },
        fail: () => resolve(this.normalizeStyleMetadata({}, styleName))
      });
    });
  },

  styleParameterText(style) {
    if (style.parameter_groups && style.parameter_groups.length) {
      return style.parameter_groups.map((group) => `${group.name}：${(group.values || []).join("、")}`).join("\n");
    }
    return (style.tags || []).join("\n") || this.defaultStyleParameterLines().join("\n");
  },

  editStyleDescription(style) {
    wx.showModal({
      title: "编辑客户描述",
      editable: true,
      placeholderText: style.customer_description || "例如：发根自然蓬松，修饰脸型，整体自然减龄。",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          const metadata = this.normalizeStyleMetadata({
            customerDescription: res.content || "",
            parameterLines: this.styleParameterText(style).split("\n")
          }, style.style_name);
          await api.put(`/merchant/hairstyles/${style.style_id}`, {
            tenant_id: api.session().tenantId,
            display_tags: metadata
          });
          wx.showToast({ title: "已保存", icon: "success" });
          this.loadAssets();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  editStyleParameters(style) {
    wx.showModal({
      title: "编辑发型参数",
      editable: true,
      placeholderText: this.styleParameterText(style),
      success: async (res) => {
        if (!res.confirm) return;
        try {
          const metadata = this.normalizeStyleMetadata({
            customerDescription: style.customer_description || "",
            parameterLines: res.content ? res.content.split("\n") : []
          }, style.style_name);
          await api.put(`/merchant/hairstyles/${style.style_id}`, {
            tenant_id: api.session().tenantId,
            display_tags: metadata
          });
          wx.showToast({ title: "已保存", icon: "success" });
          this.loadAssets();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  editStyleLength(style) {
    wx.showActionSheet({
      itemList: ["短发", "中发", "长发"],
      success: async (res) => {
        const values = ["short", "medium", "long"];
        try {
          await api.put(`/merchant/hairstyles/${style.style_id}`, {
            tenant_id: api.session().tenantId,
            hair_length: values[res.tapIndex]
          });
          wx.showToast({ title: "已保存", icon: "success" });
          this.loadAssets();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  renameStyle(style) {
    wx.showModal({
      title: "修改发型名称",
      editable: true,
      placeholderText: style.style_name,
      success: async (res) => {
        if (!res.confirm || !res.content) return;
        try {
          await api.put(`/merchant/hairstyles/${style.style_id}`, {
            tenant_id: api.session().tenantId,
            name: res.content
          });
          wx.showToast({ title: "已修改", icon: "success" });
          this.loadAssets();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  async replaceStyleImage(style) {
    try {
      const image = await this.chooseCatalogImage();
      const s = api.session();
      wx.showLoading({ title: "上传图片中" });
      const upload = await api.post("/merchant/assets/upload-url", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        asset_type: "hairstyle",
        file_ext: image.fileExt
      });
      await api.uploadToPresignedPut(upload.upload_url, image.filePath);
      await api.put(`/merchant/hairstyles/${style.style_id}`, {
        tenant_id: s.tenantId,
        thumbnail_url: upload.asset_url
      });
      wx.hideLoading();
      wx.showToast({ title: "图片已替换", icon: "success" });
      this.loadAssets();
    } catch (err) {
      wx.hideLoading();
      if (err.errMsg && err.errMsg.includes("cancel")) return;
      wx.showToast({ title: err.message || err.errMsg || "上传失败", icon: "none" });
    }
  },

  removeStyle(style) {
    wx.showModal({
      title: "删除发型",
      content: `确认删除“${style.style_name}”吗？历史订单不会受影响。`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await api.put(`/merchant/hairstyles/${style.style_id}`, {
            tenant_id: api.session().tenantId,
            is_enabled: false
          });
          wx.showToast({ title: "已删除", icon: "success" });
          this.loadAssets();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  addColor() {
    wx.showModal({
      title: "新增发色",
      editable: true,
      placeholderText: "例如：雾感棕",
      success: async (res) => {
        if (!res.confirm || !res.content) return;
        const s = api.session();
        try {
          await api.post("/merchant/hair-colors", {
            tenant_id: s.tenantId,
            store_id: s.storeId,
            name: res.content,
            direction: this.data.direction,
            color_swatch: "#6b4a38",
            display_tags: ["商家新增"],
            need_bleach: false,
            is_enabled: true,
            is_recommended: true,
            sort_order: 80
          });
          wx.showToast({ title: "已新增", icon: "success" });
          this.loadAssets();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  manageColor(event) {
    const color = this.data.colors.find((item) => item.color_id === event.currentTarget.dataset.id);
    if (!color) return;
    wx.showActionSheet({
      itemList: ["修改名称", "删除发色"],
      success: (res) => {
        if (res.tapIndex === 0) this.renameColor(color);
        if (res.tapIndex === 1) this.removeColor(color);
      }
    });
  },

  renameColor(color) {
    wx.showModal({
      title: "修改发色名称",
      editable: true,
      placeholderText: color.color_name,
      success: async (res) => {
        if (!res.confirm || !res.content) return;
        try {
          await api.put(`/merchant/hair-colors/${color.color_id}`, {
            tenant_id: api.session().tenantId,
            name: res.content
          });
          wx.showToast({ title: "已修改", icon: "success" });
          this.loadAssets();
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  removeColor(color) {
    wx.showModal({
      title: "删除发色",
      content: `确认删除“${color.color_name}”吗？历史订单不会受影响。`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await api.put(`/merchant/hair-colors/${color.color_id}`, {
            tenant_id: api.session().tenantId,
            is_enabled: false
          });
          wx.showToast({ title: "已删除", icon: "success" });
          this.loadAssets();
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

  goStaff() {
    wx.navigateTo({ url: "/pages/staff/index" });
  },

  goCustomers() {
    wx.navigateTo({ url: "/pages/customers/index" });
  }
});
