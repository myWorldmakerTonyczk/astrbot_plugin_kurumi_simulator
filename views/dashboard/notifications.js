/* Dashboard-only notices: persistent event cursor, no trading side effects. */
export class TradingNotices {
  constructor(bridge) {
    this.bridge = bridge;
    this.activeGame = "";
    this.scopeVersion = 0;
    this.needsBaseline = new Set();
    this.cursors = new Map();
    this.handledRequests = new Set();
    this.queue = [];
    this.syncing = false;
    const make = (tag, text) => {
      const n = document.createElement(tag);
      if (text) n.textContent = text;
      return n;
    };
    this.dialog = make("dialog");
    this.dialog.id = "trade-notice";
    this.dialog.setAttribute("aria-labelledby", "trade-notice-title");
    this.dialog.setAttribute("aria-describedby", "trade-notice-body");
    this.title = make("h3");
    this.title.id = "trade-notice-title";
    this.body = make("p");
    this.body.id = "trade-notice-body";
    const close = make("button", "知道了");
    close.type = "button";
    close.className = "primary";
    close.onclick = () => this.dialog.close();
    this.dialog.append(this.title, this.body, close);
    document.body.append(this.dialog);
    this.dialog.addEventListener("close", () => {
      queueMicrotask(() => this.next());
    });
  }
  setScope(game) {
    if (game === this.activeGame) return;
    this.activeGame = game || "";
    this.scopeVersion++;
    if (game) this.needsBaseline.add(game);
    this.queue = this.queue.filter(
      (item) => !item.scope || item.scope === this.activeGame,
    );
    if (
      this.dialog.open &&
      this.currentItem?.scope &&
      this.currentItem.scope !== this.activeGame
    )
      this.dialog.close();
  }
  show(title, body, level = "info", scope = null) {
    if (scope && scope !== this.activeGame) return;
    this.queue.push({ title, body, level, scope });
    this.next();
  }
  next() {
    if (this.dialog.open || !this.queue.length) return;
    const item = this.queue.shift();
    if (item.scope && item.scope !== this.activeGame) {
      this.next();
      return;
    }
    this.currentItem = item;
    this.title.textContent = item.title;
    this.body.textContent = item.body;
    this.dialog.dataset.level = item.level;
    this.dialog.showModal();
  }
  failed(text, requestId, scope = null) {
    if (requestId) {
      this.handledRequests.add(requestId);
      if (this.handledRequests.size > 256)
        this.handledRequests.delete(this.handledRequests.values().next().value);
    }
    this.show("操作未完成", text || "请求失败，请稍后重试。", "danger", scope);
  }
  forget(game) {
    this.cursors.delete(game);
    this.needsBaseline.delete(game);
    this.queue = this.queue.filter((item) => item.scope !== game);
    try {
      localStorage.removeItem(this.key(game));
    } catch {}
    if (this.activeGame === game) this.setScope("");
  }
  key(game) {
    return `kurumi-simulator:alert-cursor:${game}`;
  }
  cursor(game) {
    if (this.cursors.has(game)) return this.cursors.get(game);
    try {
      const value = localStorage.getItem(this.key(game));
      if (value !== null && /^\d+$/.test(value)) return Number(value);
    } catch {}
    return null;
  }
  save(game, cursor) {
    this.cursors.set(game, cursor);
    try {
      localStorage.setItem(this.key(game), String(cursor));
    } catch {}
  }
  async sync(game) {
    if (!game || game !== this.activeGame || this.syncing || !this.bridge)
      return;
    const scopeVersion = this.scopeVersion;
    this.syncing = true;
    const events = [];
    try {
      for (let page = 0; page < 5; page++) {
        const after = this.needsBaseline.has(game) ? null : this.cursor(game),
          params = { game };
        if (after !== null) params.after = after;
        const data = await this.bridge.apiGet("alerts", params);
        if (scopeVersion !== this.scopeVersion || game !== this.activeGame)
          return;
        if (!Number.isSafeInteger(data.cursor) || !Array.isArray(data.events))
          return;
        for (const event of data.events)
          if (!event.request_id || !this.handledRequests.has(event.request_id))
            events.push(event);
        this.save(game, data.cursor);
        this.needsBaseline.delete(game);
        if (!data.has_more) break;
      }
      if (events.length === 1)
        this.show(events[0].title, events[0].body, events[0].level, game);
      else if (events.length) {
        const level = events.some((e) => e.level === "danger")
          ? "danger"
          : events.some((e) => e.level === "warning")
            ? "warning"
            : "info";
        const body = events
          .slice(-20)
          .map((e) => `${e.title}\n${e.body}`)
          .join("\n\n");
        this.show(
          `有 ${events.length} 条交易提醒`,
          (events.length > 20
            ? "以下显示最近20条，其余可在交易日志查看。\n\n"
            : "") + body,
          level,
          game,
        );
      }
    } catch {
      /* A failed poll keeps its cursor for retry; do not flood the user on network loss. */
    } finally {
      this.syncing = false;
    }
  }
}
