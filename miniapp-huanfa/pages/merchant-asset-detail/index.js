const api = require("../../utils/api");

Page({
  data: {
    type: "style",
    asset: {},
    displayName: "",
    parameterText: "",
    editingField: "",
    draftText: "",
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

  onLoad(options) {
    const payload = wx.getStorageSync("asset_detail_payload") || {};
    const type = options.type || payload.type || "style";
    const asset = payload.asset || {};
    this.setData({
      type,
      asset: this.decorateAsset(type, asset),
      displayName: type === "color" ? asset.color_name : asset.style_name,
      parameterText: this.styleParameterText(asset)
    });
  },

  decorateAsset(type, asset) {
    if (type === "color") {
      return {
        ...asset,
        directionLabel: this.data.directionText[asset.direction] || asset.direction || "",
        tagList: (asset.tags || []).slice(0, 8)
      };
    }
    return {
      ...asset,
      hairLengthLabel: this.data.hairLengthText[asset.hair_length] || asset.hair_length || "中发",
      directionLabel: this.data.directionText[asset.direction] || asset.direction || "",
      tagList: (asset.tags || []).slice(0, 8)
    };
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

  styleParameterText(style) {
    if (style.parameter_groups && style.parameter_groups.length) {
      return style.parameter_groups.map((group) => `${group.name}：${(group.values || []).join("、")}`).join("\n");
    }
    return (style.tags || []).join("\n") || this.defaultStyleParameterLines().join("\n");
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
    return {
      customer_description: (input.customerDescription || "").trim(),
      parameter_groups: parameterGroups,
      ai_reference_tags: Array.from(new Set([
        ...selectedTags,
        "自然发际线",
        "真实发丝纹理",
        "贴合客户头型",
        "贴合客户脸型",
        "只修改头发区域"
      ])),
      style_name: styleName
    };
  },

  refreshLocal(asset) {
    this.setData({
      asset: this.decorateAsset(this.data.type, asset),
      displayName: this.data.type === "color" ? asset.color_name : asset.style_name,
      parameterText: this.styleParameterText(asset)
    });
    wx.setStorageSync("asset_detail_payload", {
      type: this.data.type,
      asset,
      direction: asset.direction
    });
  },

  async updateStyle(payload) {
    const s = api.session();
    await api.put(`/merchant/hairstyles/${this.data.asset.style_id}`, {
      tenant_id: s.tenantId,
      ...payload
    });
  },

  async updateColor(payload) {
    const s = api.session();
    await api.put(`/merchant/hair-colors/${this.data.asset.color_id}`, {
      tenant_id: s.tenantId,
      ...payload
    });
  },

  startInlineEdit(event) {
    const field = event.currentTarget.dataset.field;
    let draftText = "";
    if (field === "name") {
      draftText = this.data.displayName || "";
    } else if (field === "description") {
      draftText = this.data.asset.customer_description || "";
    } else if (field === "parameters") {
      draftText = this.data.parameterText || "";
    } else if (field === "colorTags") {
      draftText = (this.data.asset.tags || []).join("、");
    }
    this.setData({ editingField: field, draftText });
  },

  onDraftInput(event) {
    this.setData({ draftText: event.detail.value });
  },

  cancelInlineEdit() {
    this.setData({ editingField: "", draftText: "" });
  },

  async saveInlineEdit() {
    const field = this.data.editingField;
    const text = (this.data.draftText || "").trim();
    const asset = this.data.asset;
    try {
      if (field === "name") {
        if (!text) {
          wx.showToast({ title: "名称不能为空", icon: "none" });
          return;
        }
        if (this.data.type === "style") {
          await this.updateStyle({ name: text });
          this.refreshLocal({ ...asset, style_name: text });
        } else {
          await this.updateColor({ name: text });
          this.refreshLocal({ ...asset, color_name: text });
        }
      } else if (field === "description") {
        const metadata = this.normalizeStyleMetadata({
          customerDescription: text,
          parameterLines: this.data.parameterText.split("\n")
        }, asset.style_name);
        await this.updateStyle({ display_tags: metadata });
        this.refreshLocal({ ...asset, ...metadata });
      } else if (field === "parameters") {
        const metadata = this.normalizeStyleMetadata({
          customerDescription: asset.customer_description || "",
          parameterLines: text ? text.split("\n") : []
        }, asset.style_name);
        await this.updateStyle({ display_tags: metadata });
        this.refreshLocal({ ...asset, ...metadata });
      } else if (field === "colorTags") {
        const tags = text.split(/[,，、/]/).map((item) => item.trim()).filter(Boolean);
        await this.updateColor({ display_tags: tags });
        this.refreshLocal({ ...asset, tags, tagList: tags.slice(0, 8) });
      }
      this.setData({ editingField: "", draftText: "" });
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  renameAsset() {
    wx.showModal({
      title: this.data.type === "style" ? "修改发型名称" : "修改发色名称",
      editable: true,
      placeholderText: this.data.displayName,
      success: async (res) => {
        if (!res.confirm || !res.content) return;
        try {
          if (this.data.type === "style") {
            await this.updateStyle({ name: res.content });
            this.refreshLocal({ ...this.data.asset, style_name: res.content });
          } else {
            await this.updateColor({ name: res.content });
            this.refreshLocal({ ...this.data.asset, color_name: res.content });
          }
          wx.showToast({ title: "已修改", icon: "success" });
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  editDescription() {
    const asset = this.data.asset;
    wx.showModal({
      title: "编辑客户描述",
      editable: true,
      placeholderText: asset.customer_description || "例如：修饰脸型，整体自然有质感。",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          const metadata = this.normalizeStyleMetadata({
            customerDescription: res.content || "",
            parameterLines: this.data.parameterText.split("\n")
          }, asset.style_name);
          await this.updateStyle({ display_tags: metadata });
          this.refreshLocal({ ...asset, ...metadata });
          wx.showToast({ title: "已保存", icon: "success" });
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  editParameters() {
    const asset = this.data.asset;
    wx.showModal({
      title: "编辑发型参数",
      editable: true,
      placeholderText: this.data.parameterText,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          const metadata = this.normalizeStyleMetadata({
            customerDescription: asset.customer_description || "",
            parameterLines: res.content ? res.content.split("\n") : []
          }, asset.style_name);
          await this.updateStyle({ display_tags: metadata });
          this.refreshLocal({ ...asset, ...metadata });
          wx.showToast({ title: "已保存", icon: "success" });
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  editLength() {
    wx.showActionSheet({
      itemList: ["短发", "中发", "长发"],
      success: async (res) => {
        const values = ["short", "medium", "long"];
        try {
          await this.updateStyle({ hair_length: values[res.tapIndex] });
          this.refreshLocal({ ...this.data.asset, hair_length: values[res.tapIndex] });
          wx.showToast({ title: "已保存", icon: "success" });
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  chooseCatalogImage() {
    return new Promise((resolve, reject) => {
      wx.chooseMedia({
        count: 1,
        mediaType: ["image"],
        sourceType: ["camera", "album"],
        sizeType: ["compressed"],
        success: (result) => {
          const file = result.tempFiles && result.tempFiles[0];
          if (!file || !file.tempFilePath) {
            reject(new Error("请选择一张图片"));
            return;
          }
          const matched = file.tempFilePath.match(/\.([a-zA-Z0-9]+)$/);
          const ext = matched ? matched[1].toLowerCase() : "jpg";
          resolve({
            filePath: file.tempFilePath,
            fileExt: ["jpg", "jpeg", "png", "webp"].includes(ext) ? ext : "jpg"
          });
        },
        fail: reject
      });
    });
  },

  async replaceImage() {
    try {
      const image = await this.chooseCatalogImage();
      const s = api.session();
      wx.showLoading({ title: "上传图片中" });
      const isColor = this.data.type === "color";
      const upload = await api.post("/merchant/assets/upload-url", {
        tenant_id: s.tenantId,
        store_id: s.storeId,
        asset_type: isColor ? "hair_color" : "hairstyle",
        file_ext: image.fileExt
      });
      await api.uploadToPresignedPut(upload.upload_url, image.filePath);
      if (isColor) {
        await this.updateColor({ thumbnail_url: upload.asset_url });
      } else {
        await this.updateStyle({ thumbnail_url: upload.asset_url });
      }
      wx.hideLoading();
      this.refreshLocal({ ...this.data.asset, thumbnail_url: upload.asset_url });
      wx.showToast({ title: "图片已替换", icon: "success" });
    } catch (err) {
      wx.hideLoading();
      if (err.errMsg && err.errMsg.includes("cancel")) return;
      wx.showToast({ title: err.message || err.errMsg || "上传失败", icon: "none" });
    }
  },

  editColorTags() {
    const asset = this.data.asset;
    wx.showModal({
      title: "编辑发色标签",
      editable: true,
      placeholderText: (asset.tags || []).join("、") || "冷棕、显白、无需漂发",
      success: async (res) => {
        if (!res.confirm) return;
        const tags = (res.content || "").split(/[,，、/]/).map((item) => item.trim()).filter(Boolean);
        try {
          await this.updateColor({ display_tags: tags });
          this.refreshLocal({ ...asset, tags, tagList: tags.slice(0, 8) });
          wx.showToast({ title: "已保存", icon: "success" });
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  },

  async toggleBleach() {
    const next = !this.data.asset.need_bleach;
    try {
      await this.updateColor({ need_bleach: next });
      this.refreshLocal({ ...this.data.asset, need_bleach: next });
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  removeAsset() {
    wx.showModal({
      title: this.data.type === "style" ? "删除发型" : "删除发色",
      content: `确认删除“${this.data.displayName}”吗？历史订单不会受影响。`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          if (this.data.type === "style") {
            await this.updateStyle({ is_enabled: false });
          } else {
            await this.updateColor({ is_enabled: false });
          }
          wx.showToast({ title: "已删除", icon: "success" });
          setTimeout(() => wx.navigateBack(), 500);
        } catch (err) {
          wx.showToast({ title: err.message, icon: "none" });
        }
      }
    });
  }
});
