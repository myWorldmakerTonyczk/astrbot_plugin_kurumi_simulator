export class PortalSettings {
  constructor(post, reload) {
    this.form = document.getElementById("portal-settings");
    this.status = document.getElementById("portal-settings-status");
    this.revoke = document.getElementById("portal-revoke");
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

  render(config, gid) {
    this.gid = gid;
    this.revoke.disabled = !gid;
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
