const labels = {
  open: "开仓", close: "平仓", protect: "调整保护线", plan: "策略更新",
  observe: "观望", analysis: "看盘摘要", review: "看盘", end: "结束", margin_call: "保证金预警",
};
const states = {
  success: "完成", rejected: "操作失败", failed: "调用失败", pending: "排队",
  running: "进行中", interrupted: "已中断", cancelled: "已取消",
};
const stamp = (value, zone = "Asia/Shanghai") => new Date(value * 1000).toLocaleString("zh-CN", {timeZone: zone, hour12: false});
const number = (value, digits = 2) => Number(value).toLocaleString("zh-CN", {maximumFractionDigits: digits, minimumFractionDigits: digits});
const fill = (event) => event.price != null && event.status === "success";
const title = (event) => event.kind === "liquidation" ? "模拟强平" :
  event.action === "close" && ["触发止损", "触发止盈"].includes(event.reason) ? event.reason :
  event.action === "review" ? event.reason : labels[event.action] || event.action;
const el = (tag, text, cls) => {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (cls) item.className = cls;
  return item;
};

export class ReplayPanel {
  constructor(root, fetchReview) {
    this.root = root;
    this.fetchReview = fetchReview;
    this.version = 0;
    this.scope = "";
    root.innerHTML = `
      <div class="replay-heading"><div><h2>AI 复盘</h2><p>从行情回到她做决定的那一刻。</p></div>
      <form class="replay-filters"><label>货币对 <select name="pair"></select></label>
        <label>范围 <select name="days"><option value="1">最近 24 小时</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option></select></label>
        <label>截至 <input type="date" name="date" aria-label="复盘截至日期"></label>
        <button type="submit">查看</button></form></div>
      <p class="replay-status" role="status"></p>
      <div class="replay-layout">
        <div class="replay-main"><div class="replay-stats"></div>
          <div class="replay-chart-top"><span>成交与行情</span><label>账户曲线 <select class="replay-metric">
            <option value="drawdown">回撤</option><option value="return_rate">收益率</option><option value="equity">净值</option>
          </select></label></div>
          <p class="replay-legend" hidden></p>
          <div class="replay-chart" aria-label="K 线和账户曲线"></div>
          <div class="replay-timeline-top"><h3>决定与操作</h3>
            <select class="replay-event-filter" aria-label="记录筛选"><option value="all">全部记录</option>
              <option value="trade">成交</option><option value="review">看盘与观望</option><option value="plan">策略调整</option>
              <option value="failure">失败记录</option><option value="ai">仅 AI</option><option value="system">仅系统</option></select></div>
          <ol class="replay-timeline"></ol></div>
        <aside class="replay-detail" aria-live="polite"></aside>
      </div>`;
    this.form = root.querySelector("form");
    this.form.onsubmit = (event) => { event.preventDefault(); this.load(); };
    root.querySelector(".replay-metric").onchange = () => this.draw();
    root.querySelector(".replay-event-filter").onchange = () => this.timeline();
  }

  open(scope, pairs) {
    if (!scope || this.scope === scope) return;
    this.scope = scope;
    this.form.elements.date.value = "";
    this.form.elements.pair.replaceChildren(new Option("最近操作品种", ""), ...pairs.map(pair => new Option(pair, pair)));
    this.load();
  }

  close() {
    this.version++;
    this.scope = "";
    this.clearTradeLabels?.();
    this.chart?.remove();
    this.chart = null;
    this.root.querySelector(".replay-chart").classList.remove("is-drawn");
    this.data = null;
    this.selected = null;
    this.root.querySelector(".replay-timeline").replaceChildren();
    this.root.querySelector(".replay-detail").replaceChildren();
    this.root.querySelector(".replay-stats").replaceChildren();
  }

  async load() {
    const request = ++this.version;
    const form = this.form.elements;
    const end = form.date.value ? Math.min(Math.floor(Date.now() / 1000), Date.parse(form.date.value + "T23:59:59+08:00") / 1000) : 0;
    const status = this.root.querySelector(".replay-status");
    status.textContent = "正在读取复盘记录…";
    try {
      const data = await this.fetchReview(this.scope, {pair: form.pair.value, days: Number(form.days.value), end});
      if (request !== this.version) return;
      this.data = data;
      form.pair.value = data.pair;
      status.textContent = [
        stamp(data.start) + " — " + stamp(data.end) + "（北京时间）",
        data.warning, data.truncated ? "记录较多，可缩短范围查看。" : "",
        data.marks.length ? "" : "这个时段没有净值采样。新版本开始记录曲线。",
      ].filter(Boolean).join(" · ");
      this.stats();
      this.selected = null;
      this.draw();
      this.timeline();
      const latest = data.events.findLast(event => fill(event) && event.actor === "ai") || data.events.findLast(fill) || data.events.at(-1);
      if (latest) this.select(latest, false);
      else this.detail();
    } catch (error) {
      if (request !== this.version) return;
      this.data = null;
      this.clearTradeLabels?.();
      this.chart?.remove();
      this.chart = null;
      this.root.querySelector(".replay-chart").classList.remove("is-drawn");
      this.stats();
      this.timeline();
      this.detail();
      status.textContent = error.message || "复盘加载失败";
    }
  }

  stats() {
    const root = this.root.querySelector(".replay-stats");
    const data = this.data;
    root.replaceChildren();
    if (!data) return;
    const marks = data.marks;
    const trades = data.events.filter(fill);
    const jobs = data.events.filter(e => e.action === "review");
    const latest = marks.at(-1);
    for (const [key, value] of [
      ["成交次数", trades.length + (data.truncated ? "+" : "")],
      ["看盘任务", jobs.length + (data.truncated ? "+" : "")],
      ["期末净值", latest ? "$" + number(latest.equity) : "—"],
      ["时段最深回撤", marks.length ? number(Math.max(...marks.map(m => m.drawdown))) + "%" : "—"],
    ]) {
      const box = el("div");
      box.append(el("span", key), el("strong", value));
      root.append(box);
    }
  }

  draw() {
    this.clearTradeLabels?.();
    this.chart?.remove();
    this.chart = null;
    this.priceSeries = null;
    this.positionLine = null;
    this.protectionLines = [];
    const root = this.root.querySelector(".replay-chart");
    root.replaceChildren();
    root.classList.remove("is-drawn");
    const legend = this.root.querySelector(".replay-legend");
    legend.hidden = true;
    const data = this.data;
    if (!data) return;
    if (!window.LightweightCharts) {
      root.append(el("p", "图表组件加载失败，请刷新页面。", "replay-empty"));
      return;
    }
    if (!data.candles.length && !data.marks.length) {
      root.append(el("p", "这个时段暂无行情或净值采样。", "replay-empty"));
      return;
    }
    const L = window.LightweightCharts;
    const ink = "#243735";
    const grid = "#e3eae4";
    // autoSize measures the host, so give it a height before creating the chart.
    root.classList.add("is-drawn");
    const chart = this.chart = L.createChart(root, {
      autoSize: true, layout: {background: {type: "solid", color: "#f7faf6"}, textColor: ink},
      grid: {vertLines: {color: grid}, horzLines: {color: grid}},
      rightPriceScale: {borderColor: "#d3ded4"},
      timeScale: {timeVisible: true, secondsVisible: false, borderColor: "#d3ded4",
        tickMarkFormatter: time => new Date(time * 1000).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false})},
      localization: {timeFormatter: time => stamp(time)}, crosshair: {mode: L.CrosshairMode.Normal},
    });
    const currency = data.pair.endsWith("JPY") ? 3 : 5;
    const candles = this.priceSeries = chart.addSeries(L.CandlestickSeries, {
      upColor: "#168275", downColor: "#b34a65", borderVisible: false,
      wickUpColor: "#168275", wickDownColor: "#b34a65",
      priceFormat: {type: "price", precision: currency, minMove: 10 ** -currency},
    });
    candles.setData(data.candles);
    const times = this.candleTimes = new Set(data.candles.map(b => b.time));
    const trades = data.events.filter(e => fill(e) && times.has(e.bar));
    legend.hidden = false;
    if (data.candles.length) {
      legend.textContent = data.pair + " · " + data.period
        + " · ▲ 多头开仓 / ▼ 空头开仓 / ● 平仓 · 金色为系统退出"
        + (trades.length ? " · 点击标记查看操作" : " · 可见 K 线内暂无成交标记");
    } else {
      legend.textContent = "该时段没有可用的 K 线，操作记录仍可在下方查看。";
    }
    L.createSeriesMarkers(candles, trades.map(e => ({
      time: e.bar, position: "atPriceMiddle", price: e.price,
      shape: e.action === "close" ? "circle" : e.position.side === "buy" ? "arrowUp" : "arrowDown",
      color: e.actor === "system" ? "#855a21" : e.actor === "human" ? "#636b83" : e.action === "close" ? "#b34a65" : "#168275",
      size: 1.25,
    })));
    const metric = this.root.querySelector(".replay-metric").value;
    const seconds = {"15m": 900, "1h": 3600, "4h": 14400}[data.period];
    const marks = new Map();
    for (const row of data.marks) {
      const time = Math.floor(row.time / seconds) * seconds;
      const previous = marks.get(time);
      if (metric !== "drawdown" || !previous || row.drawdown >= previous.drawdown) marks.set(time, row);
    }
    if (marks.size) {
      const curve = chart.addSeries(L.AreaSeries, {
        lineColor: metric === "drawdown" ? "#a44a65" : "#187d71", lineWidth: 2,
        topColor: "#dceee5", bottomColor: "#f7faf6",
        priceFormat: {type: "custom", minMove: 0.01, formatter: value => metric === "equity" ? "$" + number(value) : number(value) + "%"},
      }, data.candles.length ? 1 : 0);
      curve.setData([...marks].map(([time, row]) => ({time, value: metric === "drawdown" ? -row.drawdown : row[metric]})));
      if (data.candles.length) chart.panes()[1]?.setHeight(140);
    }
    chart.subscribeClick(param => {
      if (typeof param.time !== "number") return;
      const at = trades.filter(e => e.bar === param.time);
      if (param.paneIndex === 1 || !at.length) this.markDetail(marks.get(param.time), param.time, seconds);
      else {
        const price = param.point ? candles.coordinateToPrice(param.point.y) : at[0].price;
        const hit = at.reduce((a, b) => Math.abs(a.price - price) <= Math.abs(b.price - price) ? a : b);
        this.select(hit, false);
      }
    });
    chart.timeScale().fitContent();
    this.installTradeLabels(root, chart, candles, trades);
    this.highlight(this.selected);
  }

  installTradeLabels(root, chart, candles, trades) {
    if (!trades.length) return;
    const overlay = el("div", null, "replay-trade-labels");
    root.append(overlay);
    const labels = trades.map(event => {
      const button = el("button", title(event), "replay-trade-label");
      button.type = "button";
      button.dataset.kind = event.actor === "system" ? "system" : event.action;
      button.title = stamp(event.time) + " · " + event.price;
      button.onclick = () => this.select(event, false);
      overlay.append(button);
      return {event, button};
    });
    const scale = chart.timeScale();
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const width = scale.width(), height = chart.panes()[0].getHeight();
        const occupied = [];
        for (const {event, button} of labels) {
          const x = scale.timeToCoordinate(event.bar);
          const y = candles.priceToCoordinate(event.price);
          const selected = this.selected?.id === event.id;
          button.setAttribute("aria-pressed", String(selected));
          if (x == null || y == null || x < 0 || x > width || y < 0 || y > height) {
            button.hidden = true;
            continue;
          }
          button.hidden = false;
          const w = button.offsetWidth, h = button.offsetHeight;
          const left = Math.min(Math.max(2, x - w / 2), Math.max(2, width - w - 2));
          const candidates = [y + 11, y - h - 11, y + h + 15, y - 2 * h - 15];
          const top = candidates.find(t => t >= 2 && t + h <= height - 2 &&
            !occupied.some(r => left < r.right + 4 && left + w + 4 > r.left && t < r.bottom + 3 && t + h + 3 > r.top));
          button.hidden = top == null;
          if (top == null) continue;
          button.style.left = left + "px";
          button.style.top = top + "px";
          occupied.push({left, right: left + w, top, bottom: top + h});
        }
      });
    };
    const observer = new ResizeObserver(update);
    observer.observe(root);
    scale.subscribeVisibleLogicalRangeChange(update);
    root.addEventListener("pointermove", update);
    root.addEventListener("wheel", update, {passive: true});
    this.updateTradeLabels = update;
    this.clearTradeLabels = () => {
      observer.disconnect();
      scale.unsubscribeVisibleLogicalRangeChange(update);
      root.removeEventListener("pointermove", update);
      root.removeEventListener("wheel", update);
      cancelAnimationFrame(frame);
      overlay.remove();
      this.updateTradeLabels = null;
      this.clearTradeLabels = null;
    };
    update();
  }

  highlight(event) {
    this.updateTradeLabels?.();
    if (!this.chart || !this.priceSeries) return;
    if (this.positionLine) {
      this.chart.removeSeries(this.positionLine);
      this.positionLine = null;
    }
    for (const line of this.protectionLines) this.priceSeries.removePriceLine(line);
    this.protectionLines = [];
    if (!event?.position?.id || !this.candleTimes.has(event.bar)) return;
    const L = window.LightweightCharts;
    const related = this.data.events.filter(e => e.position?.id === event.position.id && fill(e) && this.candleTimes.has(e.bar));
    const points = [...new Map(related.map(e => [e.bar, {time: e.bar, value: e.price}])).values()];
    if (points.length > 1) {
      this.positionLine = this.chart.addSeries(L.LineSeries, {
        color: "#9a7337", lineWidth: 2, lineStyle: L.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      });
      this.positionLine.setData(points);
    }
    for (const [field, title, color] of [["sl", "当时止损", "#ae4761"], ["tp", "当时止盈", "#168275"]]) {
      const value = Number(event.position[field]);
      if (value > 0) this.protectionLines.push(this.priceSeries.createPriceLine({
        price: value, title, color, lineWidth: 1, lineStyle: L.LineStyle.Dotted, axisLabelVisible: true,
      }));
    }
  }

  timeline() {
    const list = this.root.querySelector(".replay-timeline");
    list.replaceChildren();
    if (!this.data) return;
    const filter = this.root.querySelector(".replay-event-filter").value;
    const events = [...this.data.events].reverse().filter(e =>
      filter === "all" || (filter === "trade" && fill(e)) ||
      (filter === "review" && ["review", "observe", "analysis"].includes(e.action)) ||
      (filter === "plan" && e.action === "plan") || (filter === "ai" && e.actor === "ai") ||
      (filter === "system" && e.actor === "system") ||
      (filter === "failure" && ["failed", "rejected"].includes(e.status)));
    for (const event of events) {
      const row = el("li");
      const button = el("button", null, "replay-row");
      button.type = "button";
      button.dataset.event = event.id;
      button.append(el("time", stamp(event.time)), el("strong", title(event)),
        el("span", event.outcome || states[event.status] || event.status, "replay-tag"),
        el("span", event.actor === "system" ? "系统" : event.actor === "human" ? "用户" : "AI", "replay-actor"));
      button.onclick = () => this.select(event);
      row.append(button);
      list.append(row);
    }
    if (!events.length) list.append(el("li", "这个时段没有匹配的记录。", "replay-empty"));
  }

  select(event, move = true) {
    this.selected = event;
    this.highlight(event);
    for (const button of this.root.querySelectorAll(".replay-row")) {
      button.setAttribute("aria-current", button.dataset.event === event.id ? "true" : "false");
    }
    if (move && this.chart) {
      const half = {"15m": 900, "1h": 3600, "4h": 14400}[this.data.period] * 12;
      this.chart.timeScale().setVisibleRange({from: event.bar - half, to: event.bar + half});
    }
    this.detail(event);
  }

  links(root, events) {
    for (const event of events) {
      const button = el("button", stamp(event.time) + " · " + title(event), "replay-related");
      button.type = "button";
      button.onclick = () => this.select(event);
      root.append(button);
    }
  }

  detail(event) {
    const root = this.root.querySelector(".replay-detail");
    root.replaceChildren(el("h3", event ? title(event) : "这一刻发生了什么"));
    if (!event) { root.append(el("p", "点击图上的成交点，或从时间线选择一条记录。")); return; }
    root.append(el("p", stamp(event.time) + " · " + (event.outcome || states[event.status] || event.status), "replay-muted"));
    const position = event.position;
    if (position?.pair) {
      const parts = [position.pair, position.side === "buy" ? "做多" : "做空", position.units + " 单位"];
      if (event.price != null) parts.push("成交价 " + event.price, "手续费 $" + number(event.fee));
      if (position.sl) parts.push("止损 " + position.sl);
      if (position.tp) parts.push("止盈 " + position.tp);
      if (event.action === "close" && position.pnl != null) {
        const entry = this.data.events.find(e => e.action === "open" && fill(e) && e.position.id === position.id);
        if (entry) parts.push("扣双边手续费 $" + number(Number(position.pnl) - event.fee - entry.fee));
        else parts.push("平仓毛盈亏 $" + number(position.pnl));
        if (position.created) parts.push("持仓 " + Math.max(0, Math.round((event.time - position.created) / 60)) + " 分钟");
      }
      root.append(el("p", parts.join(" · ")));
    }
    if (event.reason && event.reason !== title(event)) root.append(el("p", event.reason, "replay-text"));
    if (event.text) root.append(el("p", event.text, "replay-text"));
    const mark = this.data.marks.findLast(m => m.time < Math.floor(event.time));
    if (mark) root.append(el("p", "此前最近采样 · 回撤 " + number(mark.drawdown) + "% · 净值 $" + number(mark.equity), "replay-muted"));
    const related = this.data.events.filter(e => e !== event && (
      (position?.id && e.position?.id === position.id) || (event.job && e.job === event.job) ||
      event.related?.includes(e.id) || e.related?.includes(event.id)));
    if (related.length) { root.append(el("h4", "关联记录")); this.links(root, related.slice(0, 20)); }
    const plan = this.data.events.findLast(e => e.action === "plan" && e.status === "success" && e.time < event.time);
    if (this.data.private !== false) {
      root.append(el("h4", "当时策略"), el("p", plan?.text || this.data.baseline || "未记录", "replay-text"));
      for (const diary of this.data.diaries) {
        const date = new Intl.DateTimeFormat("sv-SE", {timeZone: diary.zone, dateStyle: "short"}).format(new Date(event.time * 1000));
        if (date !== diary.day) continue;
        const block = el("details");
        block.append(el("summary", date + " · 日记回顾"), el("p", diary.content, "replay-text"));
        root.append(block);
      }
    }
  }

  markDetail(mark, time, seconds) {
    this.selected = null;
    this.highlight();
    const root = this.root.querySelector(".replay-detail");
    root.replaceChildren(el("h3", "这一段账户变化"));
    if (!mark) { root.append(el("p", "这根 K 线范围内没有净值采样。")); return; }
    root.append(el("p", stamp(mark.time)), el("p", "净值 $" + number(mark.equity) + " · 回撤 " + number(mark.drawdown) + "%"));
    const marks = this.data.marks;
    const index = marks.indexOf(mark);
    let first = time;
    let last = time + seconds;
    if (mark.drawdown > 0) {
      const high = marks.slice(0, index).findLast(m => m.drawdown <= 0);
      const recovery = marks.slice(index + 1).find(m => m.drawdown <= 0);
      const start = high?.time ?? marks[0].time;
      const end = recovery?.time ?? marks.at(-1).time;
      first = start;
      last = end + 1;
      const worst = Math.max(...marks.filter(m => m.time >= start && m.time <= end).map(m => m.drawdown));
      root.append(el("p", (high ? "起点 " : "可见起点 ") + stamp(start) + " · 最深回撤 " + number(worst) + "%"));
      root.append(el("p", (recovery ? "恢复于 " + stamp(end) : "可见范围内尚未恢复") + " · 可见时长 " + Math.round((end - start) / 60) + " 分钟"));
    }
    const nearby = this.data.events.filter(e => e.time >= first && e.time < last);
    if (nearby.length) { root.append(el("h4", "此区间的决定与操作")); this.links(root, nearby.slice(0, 20)); }
  }
}
