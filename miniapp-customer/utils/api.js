const app = getApp();

function getSession() {
  return {
    tenantId: wx.getStorageSync("tenant_id") || app.globalData.tenantId,
    storeId: wx.getStorageSync("store_id") || app.globalData.storeId,
    userId: wx.getStorageSync("user_id"),
    staffId: app.globalData.staffId
  };
}

function isMerchantPath(path) {
  return path.indexOf("/merchant/") === 0 || path.indexOf("/sync/") === 0;
}

async function request(method, path, data = {}, _retried = false) {
  if (isMerchantPath(path) && app && typeof app.ensureMerchantLogin === "function") {
    await app.ensureMerchantLogin();
  } else if (app && typeof app.ensureLogin === "function") {
    await app.ensureLogin();
  }
  return new Promise((resolve, reject) => {
    const token = isMerchantPath(path)
      ? (app.globalData.accessToken || wx.getStorageSync("merchant_token"))
      : wx.getStorageSync("access_token");
    const header = { "content-type": "application/json" };
    if (token) header["Authorization"] = "Bearer " + token;
    wx.request({
      url: `${app.globalData.apiBaseUrl}${path}`,
      method,
      data,
      header,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        // token 缺失/失效 → 重新登录后自动重试一次（兜底，避免直接 401 报错）
        if (res.statusCode === 401 && !_retried && app && typeof app.ensureLogin === "function") {
          app.ensureLogin(true)
            .then(() => request(method, path, data, true))
            .then(resolve)
            .catch(reject);
          return;
        }
        const message = res.data && res.data.detail ? res.data.detail : "请求失败";
        reject(new Error(message));
      },
      fail(err) {
        reject(new Error(err.errMsg || "网络不可用"));
      }
    });
  });
}

function buildQuery(params) {
  return Object.keys(params)
    .filter((key) => params[key] !== undefined && params[key] !== null && params[key] !== "")
    .map((key) => `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`)
    .join("&");
}

function uploadToPresignedPut(uploadUrl, filePath) {
  return new Promise((resolve, reject) => {
    wx.getFileSystemManager().readFile({
      filePath,
      success(file) {
        wx.request({
          url: uploadUrl,
          method: "PUT",
          data: file.data,
          timeout: 120000,
          header: { "content-type": "application/octet-stream" },
          success(res) {
            if (res.statusCode >= 200 && res.statusCode < 300) {
              resolve();
              return;
            }
            reject(new Error("自拍上传失败"));
          },
          fail(err) {
            const message = err.errMsg && err.errMsg.includes("timeout")
              ? "自拍上传超时，请检查网络后重试"
              : (err.errMsg || "自拍上传失败");
            reject(new Error(message));
          }
        });
      },
      fail(err) {
        reject(new Error(err.errMsg || "无法读取自拍"));
      }
    });
  });
}

module.exports = {
  getSession,
  session: getSession,
  get: (path, params = {}) => request("GET", `${path}?${buildQuery(params)}`),
  post: (path, data = {}) => request("POST", path, data),
  put: (path, data = {}) => request("PUT", path, data),
  delete: (path, params = {}) => request("DELETE", `${path}?${buildQuery(params)}`),
  uploadToPresignedPut
};
