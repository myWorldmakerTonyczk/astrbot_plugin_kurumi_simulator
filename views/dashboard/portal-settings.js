export class PortalSettings {
  constructor(post, reload) {
    this.form = document.getElementById("portal-settings");
    this.status = document.getElementById("portal-settings-status");
    this.revoke = document.getElementById("portal-revoke");
    this.trade = document.getElementById("portal-trade");
    this.reset = document.getElementById("portal-reset");
    this.access = document.getElementById("portal-access");
    this.account = document.getElementById("portal-account-name");
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

  render(config, gid, instance) {
    this.gid = gid;
    this.access.hidden = !gid || !instance?.owned;
    this.revoke.disabled = !gid;
    this.reset.disabled = !instance?.username;
    if (!this.trade.disabled) this.trade.checked = !!instance?.trade;
    this.account.textContent = instance?.username ? "网页账号 " + instance.username : "用户尚未领取网页账号";
    if (!config) return;
    this.status.textContent = config.error || (config.active ? "独立面板服务已启动" : "独立面板服务未启用");
    if (this.dirty) return;
    const form = this.form.elements;
    form.enabled.checked = config.enabled;
    form.origin.value = config.origin;
    form.bind.value = config.bind;
    form.port.value = config.port;
  }
}
