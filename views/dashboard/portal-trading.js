const el = (tag, text, cls) => {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (cls) item.className = cls;
  return item;
};
const number = value => Number(value).toLocaleString("zh-CN", {maximumFractionDigits: 2});
const key = () => [...crypto.getRandomValues(new Uint8Array(16))].map(x => x.toString(16).padStart(2, "0")).join("");

export class PortalTrading {
  constructor(root, api) {
    this.root = root;
    this.api = api;
    this.version = 0;
    this.chartVersion = 0;
    this.pending = new Map();
    this.busy = false;
    this.gid = "";
    root.innerHTML = `
      <div class="portal-desk-heading"><div><h2>交易工作台</h2><p>操作会写入这个实例的交易日志。</p></div>
      <button class="desk-refresh" type="button">刷新行情与持仓</button></div>
      <p class="desk-status" role="status"></p>
      <div class="desk-balances"></div>
      <div class="portal-desk-grid">
        <aside class="portal-card desk-pairs"><h3>货币对</h3><div></div></aside>
        <section class="portal-card desk-market">
          <h3>市场观察</h3><p class="desk-market-status" role="status"></p><div class="desk-chart"></div>
        </section>
        <form class="portal-card desk-order" hidden>
          <h3>开一笔模拟交易</h3>
          <fieldset>
          <div class="desk-fields">
            <label>货币对 <select name="pair" required></select></label>
            <label>方向 <select name="side"><option value="buy">做多</option><option value="sell">做空</option></select></label>
            <label>数量 <input name="units" type="number" min="0.00000001" step="any" required></label>
            <label>杠杆倍数 <input name="leverage" type="number" min="1" step="any" required></label>
            <label>止损价 <input name="sl" type="number" min="0.00000001" step="any"></label>
            <label>止盈价 <input name="tp" type="number" min="0.00000001" step="any"></label>
          </div>
          <p class="desk-quote"></p>
          <label>操作理由 <textarea name="reason" maxlength="500" rows="2" required></textarea></label>
          <button type="submit">提交模拟开仓</button>
          </fieldset>
        </form>
        <div class="desk-positions"></div>
      </div>`;
    this.order = root.querySelector(".desk-order");
    this.status = root.querySelector(".desk-status");
    root.querySelector(".desk-refresh").onclick = () => this.load();
    this.order.elements.pair.onchange = () => this.selectPair();
    this.order.onsubmit = event => {
      event.preventDefault();
      const params = Object.fromEntries(new FormData(this.order));
      this.submit("open", params, event.submitter);
    };
  }

  open(gid) {
    if (this.gid !== gid) {
      this.close();
      this.data = null;
      this.order.reset();
    }
    this.gid = gid;
    this.root.hidden = false;
    this.load();
  }

  close() {
    this.gid = "";
    this.version++;
    this.chartVersion++;
    this.chart?.remove();
    this.chart = null;
    this.root.querySelector(".desk-market-status").textContent = "";
    this.root.querySelector(".desk-pairs > div").replaceChildren();
    this.root.hidden = true;
    this.order.hidden = true;
    this.root.querySelector(".desk-positions").replaceChildren();
    this.root.querySelector(".desk-balances").replaceChildren();
  }

  message(text, error = false) {
    this.status.textContent = text;
    this.status.dataset.error = String(error);
  }

  async load() {
    const version = ++this.version;
    const gid = this.gid;
    if (!gid) return;
    this.message("正在读取持仓…");
    try {
      const data = await this.api("account?" + new URLSearchParams({game: gid}));
      if (version !== this.version) return;
      this.render(data);
    } catch (error) {
      if (version !== this.version) return;
      this.order.hidden = true;
      this.chartVersion++;
      this.chart?.remove();
      this.chart = null;
      this.root.querySelector(".desk-pairs > div").replaceChildren();
      this.root.querySelector(".desk-market-status").textContent = "";
      this.root.querySelector(".desk-positions").replaceChildren();
      this.root.querySelector(".desk-balances").replaceChildren();
      this.message(error.message, true);
    }
  }

  selectPair() {
    const pair = this.order.elements.pair.value;
    this.quote();
    const pairs = this.root.querySelector(".desk-pairs > div");
    pairs.replaceChildren(...this.data.game.pairs.map(symbol => {
      const button = el("button", null, "desk-pair");
      button.type = "button";
      button.setAttribute("aria-pressed", String(symbol === pair));
      button.append(el("strong", symbol), el("small", this.data.quotes[symbol]?.bid ?? "暂无报价"));
      button.onclick = () => {
        this.order.elements.pair.value = symbol;
        this.selectPair();
      };
      return button;
    }));
    this.loadChart(pair);
  }

  async loadChart(pair) {
    const version = ++this.chartVersion;
    const status = this.root.querySelector(".desk-market-status");
    this.chart?.remove();
    this.chart = null;
    status.textContent = pair + " · 正在读取行情…";
    try {
      const data = await this.api("review?" + new URLSearchParams({game: this.gid, pair, days: 1}));
      if (version !== this.chartVersion) return;
      if (!data.candles.length) {
        status.textContent = pair + " · 这段时间暂无 K 线";
        return;
      }
      const L = window.LightweightCharts;
      this.chart = L.createChart(this.root.querySelector(".desk-chart"), {
        autoSize: true, height: 320,
        layout: {background: {color: "#fcfafd"}, textColor: "#59495d"},
        grid: {vertLines: {color: "#eee6ee"}, horzLines: {color: "#eee6ee"}},
        timeScale: {timeVisible: true},
      });
      const precision = pair.endsWith("/JPY") ? 3 : 5;
      this.chart.addSeries(L.CandlestickSeries, {
        upColor: "#16786e", downColor: "#a84664", borderVisible: false,
        wickUpColor: "#16786e", wickDownColor: "#a84664",
        priceFormat: {type: "price", precision, minMove: 10 ** -precision},
      }).setData(data.candles);
      this.chart.timeScale().fitContent();
      status.textContent = pair + " · " + data.period + " K 线";
    } catch (error) {
      if (version === this.chartVersion) status.textContent = pair + " · " + error.message;
    }
  }

  quote() {
    const pair = this.order.elements.pair.value;
    const quote = this.data?.quotes[pair];
    this.root.querySelector(".desk-quote").textContent = quote ? `买入 ${quote.ask} · 卖出 ${quote.bid}` : "当前没有有效报价";
    this.order.querySelector("button[type=submit]").disabled = !quote || this.busy;
  }

  render(data) {
    this.data = data;
    const allowed = data.game.trade && data.status === "running";
    this.message(!data.game.trade ? "此实例为只读。网页交易权限由后台控制。" :
      data.status !== "running" ? "本局当前不可交易。" : data.market_error || "已同步当前持仓。");
    const totals = this.root.querySelector(".desk-balances");
    totals.replaceChildren();
    for (const [label, field] of [["净值", "equity"], ["可用保证金", "free"], ["浮动盈亏", "floating"]]) {
      const item = el("div");
      item.append(el("span", label), el("strong", data.valuation ? "$" + number(data.valuation[field]) : "—"));
      totals.append(item);
    }
    this.order.hidden = false;
    this.order.querySelector("fieldset").disabled = !allowed;
    const pair = this.order.elements.pair.value;
    this.order.elements.pair.replaceChildren(...data.game.pairs.map(p => new Option(p, p)));
    if (data.game.pairs.includes(pair)) this.order.elements.pair.value = pair;
    this.order.elements.leverage.max = data.leverage;
    if (!this.order.elements.leverage.value || Number(this.order.elements.leverage.value) > Number(data.leverage)) {
      this.order.elements.leverage.value = data.leverage;
    }
    this.selectPair();
    const list = this.root.querySelector(".desk-positions");
    list.replaceChildren(el("h3", `当前持仓 · ${data.positions.length} 笔`));
    if (!data.positions.length) list.append(el("p", "当前没有持仓。"));
    for (const position of data.positions) {
      const card = el("article", null, "portal-card");
      const direction = position.side === "buy" ? "多仓" : "空仓";
      card.append(el("h4", `${position.pair} · ${direction}`),
        el("p", `${number(position.units)} 单位 · 入场 ${position.entry} · 杠杆 ${position.leverage}×`),
        el("p", `止损 ${position.sl || "—"} · 止盈 ${position.tp || "—"} · 浮盈亏 ${position.pnl == null ? "—" : "$" + number(position.pnl)}`));
      if (allowed) this.positionForm(card, position);
      list.append(card);
    }
  }

  positionForm(card, position) {
    const details = el("details");
    const form = el("form");
    details.append(el("summary", "调整保护线或平仓"), form);
    const fields = el("div", null, "desk-fields");
    for (const [name, label] of [["sl", "止损价"], ["tp", "止盈价"]]) {
      const field = el("label", label);
      const input = el("input");
      Object.assign(input, {name, type: "number", min: "0", step: "any", placeholder: "留空保留，填 0 取消"});
      field.append(input);
      fields.append(field);
    }
    const reason = el("label", "操作理由");
    const text = el("textarea");
    Object.assign(text, {name: "reason", required: true, maxLength: 500, rows: 2});
    reason.append(text);
    const protect = el("button", "保存保护线");
    const close = el("button", "平仓");
    Object.assign(protect, {type: "submit", value: "protect"});
    Object.assign(close, {type: "submit", value: "close"});
    form.append(fields, reason, protect, close);
    form.onsubmit = event => {
      event.preventDefault();
      const action = event.submitter.value;
      const params = {position: position.id, reason: text.value};
      if (action === "protect") {
        for (const field of ["sl", "tp"]) if (form.elements[field].value !== "") params[field] = form.elements[field].value;
      } else if (!confirm(`确认按当前有效报价平掉这笔 ${position.pair} 持仓？`)) return;
      this.submit(action, params, event.submitter);
    };
    card.append(details);
  }

  async submit(action, params, button) {
    if (this.busy || !this.gid) return;
    const gid = this.gid;
    const tag = JSON.stringify([gid, action, params]);
    const requestId = this.pending.get(tag) || key();
    this.pending.set(tag, requestId);
    if (this.pending.size > 20) this.pending.delete(this.pending.keys().next().value);
    this.busy = true;
    button.disabled = true;
    this.message("正在提交模拟操作…");
    try {
      await this.api("action?" + new URLSearchParams({game: gid}), {action, params, request_id: requestId});
      this.pending.delete(tag);
      if (this.gid === gid) {
        await this.load();
        if (this.gid === gid) this.message("模拟操作已记入交易日志。");
      }
    } catch (error) {
      if (error.http) this.pending.delete(tag);
      if (this.gid === gid) this.message(error.message || "提交状态未知，可使用相同参数重试。", true);
    } finally {
      this.busy = false;
      button.disabled = false;
      if (this.gid) this.quote();
    }
  }
}
