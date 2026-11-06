export function createPortalBridge() {
  async function request(path, params = {}, body) {
    const query = new URLSearchParams(params);
    const response = await fetch("/api/" + path + (query.size ? "?" + query : ""), {
      cache: "no-store",
      ...(body === undefined ? {} : {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
      }),
    });
    if (response.status === 401) location.replace("/");
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "面板请求失败");
    return result;
  }

  return {
    ready: () => request("session"),
    apiGet(route, params) {
      if (route === "alerts") return Promise.resolve({events: []});
      return request(route === "state" ? "workspace" : route, params);
    },
    apiPost(route, body) {
      if (route !== "command") throw Error("管理员已禁止此操作");
      const {game, ...payload} = body;
      return request("action", {game}, payload);
    },
    async logout() {
      await request("logout", {}, {});
      location.replace("/");
    },
  };
}
