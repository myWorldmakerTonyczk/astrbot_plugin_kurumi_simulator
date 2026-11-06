export class PortalSettings {
  constructor(post, reload) {
    this.form = document.getElementById("portal-settings");
    this.status = document.getElementById("portal-settings-status");
    this.check = document.getElementById("portal-check-link");
    this.openLink = document.getElementById("portal-open-link");
    this.linkStatus = document.getElementById("portal-link-status");
    this.check.onclick = () => this.checkLink();
    this.revoke = document.getElementById("portal-revoke");
    this.trade = document.getElementById("portal-trade");
    this.reset = document.getElementById("portal-reset");
    this.access = document.getElementById("portal-access");
    this.account = document.getElementById("portal-account-name");
    this.umos = document.getElementById("portal-umos");
    this.umoForm = document.getElementById("portal-umo-form");
    this.umos.oninput = () => { this.bindingDirty = true; };
    this.umoForm.onsubmit = async event => {
      event.preventDefault();
      const gid = this.gid;
      if (!gid || !window.confirm("更改领取私聊会撤销该用户已发的面板链接并重置网页账号。确认保存？")) return;
      const umos = this.umos.value.split("\n").map(line => line.trim()).filter(Boolean);
      const button = event.submitter;
      button.disabled = true;
      try {
        await post("portal-settings", {binding_game: gid, umos});
        if (this.gid === gid) this.bindingDirty = false;
        await reload();
      } catch {}
      finally { button.disabled = false; }
    };
    this.trade.onchange = async () => {
      const gid = this.gid, allowed = this.trade.checked;
      this.trade.disabled = true;
      try { await post("portal-settings", {trade_game: gid, allowed}); await reload(); }
      catch { if (this.gid === gid) this.trade.checked = !allowed; }
      finally { this.trade.disabled = false; }
    };
    this.reset.onclick = async () => {
      const gid = this.gid;
      if (!gid || !window.confirm("重置后，这位用户原来的网页账号和登录会话会立即失效。确认重置？")) return;
      try { await post("portal-settings", {reset_account: gid}); await reload(); }
      catch {}
    };
    this.dirty = false;
    this.form.oninput = () => { this.dirty = true; };
    this.form.onsubmit = async event => {
      event.preventDefault();
      const form = this.form.elements;
      const button = this.form.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        await post("portal-settings", {
          enabled: form.enabled.checked, origin: form.origin.value.trim(),
          bind: form.bind.value, port: Number(form.port.value),
        });
        this.dirty = false;
        await reload();
      } catch {}
      finally { button.disabled = false; }
    };
    this.revoke.onclick = async () => {
      const gid = this.gid;
      if (!gid || !window.confirm("撤销此实例所有临时链接和只读浏览器会话？")) return;
      try { await post("portal-settings", {revoke_game: gid}); await reload(); }
      catch {}
    };
  }

  async checkLink() {
    const origin = this.origin;
    if (!origin || this.checking) return;
    this.checking = true;
    this.check.disabled = true;
    this.linkStatus.textContent = "正在检查 " + origin + "…";
    try {
      const response = await fetch(new URL("/api/health", origin), {
        credentials: "omit", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
      });
      if (!response.ok) throw Error("HTTP " + response.status);
      const result = await response.json();
      if (result.service !== "kurumi-user-portal" || result.ok !== true) throw Error("返回的不是久留美面板");
      if (this.origin === origin) this.linkStatus.textContent = "连接成功，当前浏览器已通过 HTTPS 访问到久留美面板。";
    } catch {
      if (this.origin === origin) this.linkStatus.textContent =
        "未能确认连接。请点「打开远程面板」查看浏览器提示，并检查 HTTPS 证书、反代和面板服务。";
    } finally {
      this.checking = false;
      this.check.disabled = !this.origin;
    }
  }

  render(config, gid, instance) {
    if (this.gid !== gid) this.bindingDirty = false;
    this.gid = gid;
    if (!this.bindingDirty) this.umos.value = (instance?.chat_umos || []).join("\n");
    this.access.hidden = !gid || !instance?.owned;
    this.revoke.disabled = !gid;
    this.reset.disabled = !instance?.username;
    if (!this.trade.disabled) this.trade.checked = !!instance?.trade;
    this.account.textContent = instance?.username ? "网页账号 " + instance.username : "用户尚未领取网页账号";
    if (!config) return;
    const origin = config.origin?.startsWith("https://") ? config.origin : "";
    if (this.origin !== origin) {
      this.origin = origin;
      this.linkStatus.textContent = origin ? "检查的是已保存的 HTTPS 地址。" : "保存 HTTPS 地址后可检查连接。";
      if (origin) this.openLink.href = origin;
      else this.openLink.removeAttribute("href");
    }
    this.openLink.hidden = !origin;
    this.check.disabled = !origin || !!this.checking;
    this.status.textContent = config.error || (config.active ? "独立面板服务已启动" : "独立面板服务未启用");
    if (this.dirty) return;
    const form = this.form.elements;
    form.enabled.checked = config.enabled;
    form.origin.value = config.origin;
    form.bind.value = config.bind;
    form.port.value = config.port;
  }
}
