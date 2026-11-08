export class PortalSettings {
  constructor(post, reload) {
    this.form = document.getElementById("portal-settings");
    this.status = document.getElementById("portal-settings-status");
    this.check = document.getElementById("portal-check-link");
    this.openLink = document.getElementById("portal-open-link");
    this.linkStatus = document.getElementById("portal-link-status");
    this.check.onclick = () => this.checkLink();
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

  render(config) {
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
