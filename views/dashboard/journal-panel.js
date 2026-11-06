import { renderNotebookText } from "./notebook.js";

const sources = { ai: "AI", human: "人类", system: "系统" };
const dateFormat = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", dateStyle: "long"});
const timeFormat = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", timeStyle: "medium"});
function element(tag, text, css) {
  const result = document.createElement(tag);
  if (text != null) result.textContent = text;
  if (css) result.className = css;
  return result;
}

export class JournalPanel {
  constructor(bridge, labels, pairLabel) {
    this.bridge = bridge;
    this.labels = labels;
    this.pairLabel = pairLabel;
    this.form = document.getElementById("journal-filters");
    this.root = document.getElementById("logs");
    this.status = document.getElementById("journal-status");
    this.prev = document.getElementById("journal-prev");
    this.next = document.getElementById("journal-next");
    this.gid = "";
    this.version = 0;
    this.form.onchange = () => this.load(1, 0);
    this.form.onreset = () => queueMicrotask(() => this.load(1, 0));
    this.prev.onclick = () => this.load(this.page - 1, this.before);
    this.next.onclick = () => this.load(this.page + 1, this.before);
  }

  update(gid, pairs, logs) {
    if (gid !== this.gid) {
      this.gid = gid;
      this.version++;
      this.page = 1;
      this.before = 0;
      this.remote = false;
      const pair = this.form.elements.pair;
      pair.replaceChildren(new Option("所有品种", ""), ...pairs.map(value => new Option(this.pairLabel(value), value)));
      this.form.elements.filter.value = "all";
      this.form.elements.source.value = "all";
      this.form.elements.sort.value = "newest";
      this.cacheKey = "";
    }
    if (!this.remote) {
      const key = gid + ":" + logs.map(row => row.id).join(",");
      if (key === this.cacheKey) return;
      this.cacheKey = key;
      this.before = logs.length ? logs[0].id + 1 : 0;
      this.draw(logs.slice(0, 20), logs.length > 20);
    }
  }

  async load(page, before) {
    if (!this.gid) return;
    this.remote = true;
    const token = ++this.version;
    this.prev.disabled = this.next.disabled = true;
    this.root.replaceChildren();
    this.status.textContent = "正在读取交易日志…";
    try {
      const result = await this.bridge.apiGet("journal", {
        game: this.gid, page, before, ...Object.fromEntries(new FormData(this.form)),
      });
      if (token !== this.version) return;
      this.page = result.page;
      this.before = result.before;
      this.draw(result.logs, result.next_page != null);
    } catch (error) {
      if (token !== this.version) return;
      this.status.textContent = error.message || "读取失败，请重新选择筛选条件。";
      this.prev.disabled = this.page <= 1;
    }
  }

  draw(logs, hasMore) {
    const open = new Set([...this.root.querySelectorAll("details[open]")].map(item => item.dataset.id));
    this.root.replaceChildren();
    let day = "", group;
    for (const row of logs) {
      const time = new Date(row.created * 1000);
      const label = dateFormat.format(time);
      if (day !== label) {
        day = label;
        group = element("section", null, "journal-day");
        group.append(element("h4", day));
        this.root.append(group);
      }
      group.append(this.entry(row, time, open));
    }
    if (!logs.length) this.root.append(element("p", "没有符合当前条件的交易记录。", "caption"));
    this.prev.disabled = this.page <= 1;
    this.next.disabled = !hasMore;
    this.status.textContent = "第 " + (this.page || 1) + " 页 · 本页 " + logs.length + " 条";
  }

  entry(row, time, open) {
    const rejected = row.status === "rejected";
    const data = row.detail || {};
    const position = data.position;
    const fill = !rejected && ["open", "close"].includes(row.action);
    const card = element("article", null, "journal-event");
    card.dataset.kind = rejected ? "rejected" : fill ? "fill" : "note";
    const stamp = element("time", timeFormat.format(time));
    stamp.dateTime = time.toISOString();
    const body = element("div", null, "journal-event-body");
    const heading = element("div", null, "journal-event-heading");
    heading.append(element("strong", this.labels[row.action] || row.action),
      element("span", sources[row.source] || row.source, "journal-badge"),
      element("span", rejected ? "未执行" : fill ? "已成交" : "已记录", "journal-badge"));
    body.append(heading);
    if (position?.pair) {
      const fields = [position.pair, position.side === "sell" ? "空" : "多", position.units + " 单位"];
      if (position.entry != null) fields.push("入场 " + position.entry);
      if (position.pnl != null) fields.push("平仓毛盈亏 $" + Number(position.pnl).toFixed(2));
      body.append(element("p", fields.join(" · "), "journal-position"));
    }
    if (row.reason) body.append(element("p", row.reason));
    if (rejected && data.error) body.append(element("p", data.error, "negative"));
    if (Object.keys(data).length) {
      const details = element("details");
      details.dataset.id = row.id;
      details.open = open.has(String(row.id));
      details.append(element("summary", "查看操作详情"));
      const text = data.summary || data.text;
      if (text) {
        const prose = element("div", null, "notebook-prose");
        renderNotebookText(prose, text);
        details.append(prose);
      }
      const fields = Object.fromEntries(Object.entries(data).filter(([key]) => !["summary", "text"].includes(key)));
      if (Object.keys(fields).length) details.append(element("pre", JSON.stringify(fields, null, 2)));
      body.append(details);
    }
    card.append(stamp, body);
    return card;
  }
}
