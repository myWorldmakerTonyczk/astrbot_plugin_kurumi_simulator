import { renderNotebookText } from "./notebook.js";
// Per-instance diary reader and global daily-writing controls.
export class DiaryPanel {
  constructor(bridge) {
    this.bridge = bridge;
    this.gid = "";
    this.before = "";
    this.entries = [];
    this.selectedDay = "";
    this.dirty = false;
    this.generation = 0;
    this.loading = false;
    const form = document.getElementById("diary-settings");
    form.addEventListener("input", () => { this.dirty = true; });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = document.getElementById("diary-settings-status");
      const button = form.querySelector("button");
      button.disabled = true;
      try {
        await bridge.apiPost("diary-settings", {
          enabled: form.elements.enabled.checked,
          chat_only: form.elements.chat_only.checked,
          time: form.elements.time.value,
          timezone: form.elements.timezone.value,
          min_logs: Number(form.elements.min_logs.value),
          history_count: Number(form.elements.history_count.value),
        });
        this.dirty = false;
        status.textContent = "日记设置已保存，遗漏日期将自动检查并排队。";
      } catch (error) { status.textContent = error.message || "保存失败"; }
      finally { button.disabled = false; }
    });
    document.getElementById("diary-refresh").onclick = () => this.load(false);
    document.getElementById("diary-older").onclick = () => this.load(true);
  }
  render(config, gid) {
    const form = document.getElementById("diary-settings");
    if (config && !this.dirty && !form.contains(document.activeElement)) {
      for (const key of ["enabled", "chat_only"]) form.elements[key].checked = config[key];
      for (const key of ["time", "timezone", "min_logs", "history_count"]) form.elements[key].value = config[key];
    }
    if (gid !== this.gid) {
      this.gid = gid;
      this.before = "";
    this.entries = [];
    this.selectedDay = "";
      this.generation++;
      this.loading = false;
      document.getElementById("diary-entries").replaceChildren();
      document.getElementById("diary-status").textContent = gid ? "点击刷新查看日记与排队状态。" : "请选择交易实例。";
      document.getElementById("diary-older").hidden = true;
      if (gid) this.load(false);
    }
  }
  async load(older) {
    if (!this.gid || this.loading) return;
    this.loading = true;
    const generation = this.generation, gid = this.gid;
    const status = document.getElementById("diary-status");
    status.textContent = "正在读取…";
    try {
      const result = await this.bridge.apiGet("diaries", {game: gid, before: older ? this.before : "", limit: 10});
      if (generation !== this.generation) return;
      const entries = result.entries || [];
      this.entries = older ? [...this.entries, ...entries] : entries;
      if (!this.entries.some(entry => entry.day === this.selectedDay)) this.selectedDay = this.entries[0]?.day || "";
      this.renderEntries();
      this.before = result.next_before || "";
      document.getElementById("diary-older").hidden = entries.length < 10;
      status.textContent = this.entries.length ? "选择日期阅读。生成失败后会自动重试。" : "暂无日记。达到条件的日期会在固定时间排队生成。";
    } catch (error) {
      if (generation === this.generation) status.textContent = error.message || "日记读取失败";
    } finally {
      if (generation === this.generation) this.loading = false;
    }
  }
  renderEntries() {
    const container = document.getElementById("diary-entries");
    container.replaceChildren();
    if (!this.entries.length) return;
    const states = {pending: "排队中", running: "正在写", failed: "待重试", success: "已写好", skipped: "未达到阈值"};
    const directory = document.createElement("nav");
    directory.setAttribute("aria-label", "日记日期");
    const reader = document.createElement("article");
    reader.className = "notebook-reader";
    const title = document.createElement("h4");
    const body = document.createElement("div");
    body.className = "notebook-prose";
    const select = entry => {
      this.selectedDay = entry.day;
      for (const button of directory.querySelectorAll("button")) {
        button.setAttribute("aria-pressed", String(button.dataset.day === entry.day));
      }
      title.textContent = entry.day + " · " + (states[entry.status] || entry.status);
      renderNotebookText(body, entry.content || entry.error || "后台会按排队顺序生成这篇日记。");
    };
    let month = "";
    for (const entry of this.entries) {
      if (entry.day.slice(0, 7) !== month) {
        month = entry.day.slice(0, 7);
        const label = document.createElement("small");
        label.textContent = month;
        directory.append(label);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.day = entry.day;
      button.textContent = entry.day.slice(5) + " " + (states[entry.status] || entry.status);
      button.onclick = () => select(entry);
      directory.append(button);
    }
    reader.append(title, body);
    container.append(directory, reader);
    select(this.entries.find(entry => entry.day === this.selectedDay));
  }

}
