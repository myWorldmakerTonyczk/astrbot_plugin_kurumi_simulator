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
const metrics = {
  equity: {name: "净值", hint: "此刻账户值多少美元", color: "#187d71", fill: "#dceee5", value: row => row.equity},
  drawdown: {name: "回撤", hint: "较历史峰值的跌幅", color: "#a44a65", fill: "#efdce2", value: row => -row.drawdown},
  return_rate: {name: "收益率", hint: "扣除资金流影响后的累计收益", color: "#315da4", value: row => row.return_rate},
};
const activityKinds = {
  fill: "已成交", observe: "观望", fail: "失败或未执行", idle: "未成交", other: "其他状态",
};
const toolNames = {
  state: "账户与报价", logs: "查交易日志", history: "查历史行情", open: "开仓",
  close: "平仓", protect: "调整保护线", observe: "记录观望", plan: "更新策略",
  diary: "查日记", notifications: "通知设置", borrow: "借款", repay: "还款",
};
const activityActions = new Set(["open", "close", "protect", "plan", "borrow", "repay"]);
const taskKind = event => event.outcome === "已成交" ? "fill"
  : event.outcome === "已记录观望" ? "observe"
  : event.status === "failed" || event.outcome === "操作未执行" ? "fail"
  : event.outcome === "已完成，未成交" ? "idle" : "other";
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
      <form class="replay-filters">
        <label>范围 <select name="days"><option value="1">最近 24 小时</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option></select></label>
        <label>截至 <input type="date" name="date" aria-label="复盘截至日期"></label>
        <button type="submit">查看</button></form></div>
      <p class="replay-status" role="status"></p>
      <div class="replay-layout">
        <nav class="replay-pairs" aria-label="复盘货币对" hidden>
          <details open><summary>货币对 <span class="replay-pair-count"></span><span class="replay-pair-selection"></span></summary>
            <div class="replay-pair-list"></div>
            <div class="replay-pair-mix" hidden></div>
          </details>
        </nav>
        <div class="replay-main"><div class="replay-stats"></div>
          <div class="replay-market-slot"><section class="replay-market" aria-label="行情与成交">
            <div class="replay-chart-top"><strong>行情与成交</strong><span class="replay-current-pair"></span><button type="button" class="replay-return-chart" hidden>回到图表</button></div>
            <p class="replay-legend" hidden></p>
            <div class="replay-chart" aria-label="品种 K 线和成交标记"></div>
          </section></div>
          <section class="replay-activity" aria-label="AI 决策活动" hidden></section>
          <section class="replay-performance" aria-label="账户表现"></section>
          <div class="replay-timeline-top"><h3>决定与操作</h3>
            <select class="replay-event-filter" aria-label="记录筛选"><option value="all">全部记录</option>
              <option value="trade">成交</option><option value="review">看盘与观望</option><option value="plan">策略调整</option>
              <option value="failure">失败记录</option><option value="ai">仅 AI</option><option value="system">仅系统</option></select></div>
          <ol class="replay-timeline"></ol></div>
        <aside class="replay-side"><section class="replay-fill-summary" hidden></section><div class="replay-detail" aria-live="polite"></div></aside>
      </div>`;
    this.form = root.querySelector("form");
    this.pairNav = root.querySelector(".replay-pairs");
    this.pairList = this.pairNav.querySelector(".replay-pair-list");
    this.pairCount = this.pairNav.querySelector(".replay-pair-count");
    this.pairSelection = this.pairNav.querySelector(".replay-pair-selection");
    this.market = root.querySelector(".replay-market");
    this.marketSlot = root.querySelector(".replay-market-slot");
    this.returnChart = root.querySelector(".replay-return-chart");
    this.workspaceHeader = root.closest(".workspace > main")?.querySelector(":scope > header");
    this.returnChart.onclick = () => this.marketSlot.scrollIntoView({block: "center"});
    this.installChartDrag();
    const trackScroll = () => {
      cancelAnimationFrame(this.floatFrame);
      this.floatFrame = requestAnimationFrame(() => this.updateFloatingChart());
    };
    window.addEventListener("scroll", trackScroll, {capture: true, passive: true});
    window.addEventListener("resize", trackScroll);
    this.form.onsubmit = (event) => { event.preventDefault(); this.load(); };
    root.querySelector(".replay-event-filter").onchange = () => this.timeline();
  }

  updateFloatingChart() {
    const boundary = Math.max(0, this.workspaceHeader?.getBoundingClientRect().bottom || 0);
    const floating = !!this.chart && !this.root.hidden && this.marketSlot.getBoundingClientRect().bottom <= boundary;
    const wasFloating = this.market.classList.contains("is-floating");
    if (floating === wasFloating) {
      if (floating && this.floatPosition) this.placeFloatingChart(this.floatPosition);
      return;
    }
    this.marketSlot.style.minHeight = floating ? this.market.offsetHeight + "px" : "";
    this.market.classList.toggle("is-floating", floating);
    this.returnChart.hidden = !floating;
    if (floating && this.floatPosition) this.placeFloatingChart(this.floatPosition);
  }

  placeFloatingChart({x, y}) {
    const xMax = Math.max(6, window.innerWidth - this.market.offsetWidth - 6);
    const yMax = Math.max(6, window.innerHeight - this.market.offsetHeight - 6);
    this.floatPosition = {x: Math.max(6, Math.min(x, xMax)), y: Math.max(6, Math.min(y, yMax))};
    this.market.style.setProperty("--float-left", this.floatPosition.x + "px");
    this.market.style.setProperty("--float-top", this.floatPosition.y + "px");
    this.market.classList.add("is-positioned");
  }

  installChartDrag() {
    const handle = this.market.querySelector(".replay-chart-top");
    let drag = null;
    handle.addEventListener("pointerdown", event => {
      if (!this.market.classList.contains("is-floating") || event.button !== 0 || event.target.closest("button")) return;
      const rect = this.market.getBoundingClientRect();
      drag = {pointer: event.pointerId, x: event.clientX - rect.left, y: event.clientY - rect.top};
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    handle.addEventListener("pointermove", event => {
      if (drag?.pointer !== event.pointerId || !this.market.classList.contains("is-floating")) return;
      this.placeFloatingChart({x: event.clientX - drag.x, y: event.clientY - drag.y});
    });
    handle.addEventListener("lostpointercapture", () => { drag = null; });
  }

  open(scope, pairs) {
    if (!scope) return;
    if (this.scope === scope && this.pairs.join() === pairs.join()) return;
    if (this.scope !== scope) {
      this.pairNav.querySelector("details").open = true;
      this.form.elements.date.value = "";
      this.requestedPair = "";
    } else if (!pairs.includes(this.requestedPair)) {
      this.requestedPair = "";
    }
    this.scope = scope;
    this.pairs = [...pairs];
    this.renderPairs(pairs);
    this.load();
  }

  renderPairs(pairs, stats = [], selected = "") {
    this.pairNav.hidden = !pairs.length;
    this.pairCount.textContent = String(pairs.length);
    this.pairList.replaceChildren();
    this.pairSelection.textContent = selected || (pairs.length === 1 ? pairs[0] : "");
    const ranked = new Map(stats.filter(row => pairs.includes(row.pair)).map(row => [row.pair, row]));
    const maxOperations = Math.max(1, ...Array.from(ranked.values(), row => row.operations ?? row.fills));
    const maxPnl = Math.max(.01, ...Array.from(ranked.values(), row => Math.abs(row.net)));
    for (const pair of [...new Set([...ranked.keys(), ...pairs])]) {
      const {fills = 0, operations = fills, net = 0} = ranked.get(pair) || {};
      const button = el("button", null, "replay-pair");
      button.type = "button";
      button.dataset.pair = pair;
      button.setAttribute("aria-pressed", String(pair === (selected || (pairs.length === 1 ? pairs[0] : ""))));
      const sign = Math.round(net * 100) === 0 ? "flat" : net > 0 ? "gain" : "loss";
      const pnl = el("span", fills ? (sign === "loss" ? "−" : sign === "gain" ? "+" : "") + "$" + number(Math.abs(net)) : "—", "replay-pair-pnl");
      pnl.dataset.sign = sign;
      button.dataset.sign = sign;
      button.style.setProperty("--pnl-strength", (8 + 24 * Math.abs(net) / maxPnl) + "%");
      const bar = el("span", null, "replay-pair-volume");
      bar.style.setProperty("--activity", (operations / maxOperations * 100) + "%");
      bar.setAttribute("aria-hidden", "true");
      button.append(el("strong", pair), el("small", operations + " 次操作"), pnl, bar);
      button.onclick = () => {
        this.requestedPair = pair;
        this.load();
      };
      this.pairList.append(button);
    }
    this.pairList.append(el("small", "所选时段平仓盈亏扣成交费", "replay-pair-note"));
  }

  close() {
    this.version++;
    this.clearPerformance();
    this.scope = "";
    cancelAnimationFrame(this.rangeFrame);
    this.clearTradeLabels?.();
    this.chart?.remove();
    this.chart = null;
    this.updateFloatingChart();
    this.root.querySelector(".replay-chart").classList.remove("is-drawn");
    this.data = null;
    this.drawSideSummary();
    this.drawActivity();
    this.selected = null;
    this.relatedFrom = null;
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
      const data = await this.fetchReview(this.scope, {pair: this.requestedPair, days: Number(form.days.value), end});
      if (request !== this.version) return;
      this.data = data;
      this.pairs = data.pairs;
      this.renderPairs(this.pairs, data.pair_stats, data.pair);
      this.root.querySelector(".replay-current-pair").textContent = data.pair;
      status.textContent = [
        stamp(data.start) + " — " + stamp(data.end) + "（北京时间）",
        data.warning, data.truncated ? "记录较多，可缩短范围查看。" : "",
        data.marks.length ? "" : "这个时段没有净值采样。新版本开始记录曲线。",
      ].filter(Boolean).join(" · ");
      this.stats();
      this.selected = null;
      this.relatedFrom = null;
      this.draw();
      this.updateFloatingChart();
      this.drawPerformance();
      this.drawSideSummary();
      this.drawActivity();
      this.timeline();
      const latest = data.events.findLast(event => fill(event) && event.actor === "ai") || data.events.findLast(fill) || data.events.at(-1);
      if (latest) this.select(latest, false);
      else this.detail();
    } catch (error) {
      if (request !== this.version) return;
      this.data = null;
      this.clearPerformance();
      this.drawSideSummary();
      this.drawActivity();
      cancelAnimationFrame(this.rangeFrame);
      this.clearTradeLabels?.();
      this.chart?.remove();
      this.chart = null;
      this.updateFloatingChart();
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
    cancelAnimationFrame(this.rangeFrame);
    this.clearTradeLabels?.();
    this.chart?.remove();
    this.chart = null;
    this.priceSeries = null;
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
    if (!data.candles.length) {
      root.append(el("p", "这个时段暂无 K 线，可从下方查看操作记录。", "replay-empty"));
      return;
    }
    const L = window.LightweightCharts;
    const ink = "#243735";
    const grid = "#e3eae4";
    // autoSize measures the host, so give it a height before creating the chart.
    root.classList.add("is-drawn");
    const chart = this.chart = L.createChart(root, {
      autoSize: true, layout: {background: {type: "solid", color: "rgba(247,250,246,0)"}, textColor: ink},
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
        + (trades.length ? " · 紫色弧线关联选中持仓的开平仓" : " · 可见 K 线内暂无成交标记");
    } else {
      legend.textContent = "该时段没有可用的 K 线，操作记录仍可在下方查看。";
    }
    L.createSeriesMarkers(candles, trades.map(e => ({
      time: e.bar, position: "atPriceMiddle", price: e.price,
      shape: e.action === "close" ? "circle" : e.position.side === "buy" ? "arrowUp" : "arrowDown",
      color: e.actor === "system" ? "#855a21" : e.actor === "human" ? "#636b83" : e.action === "close" ? "#b34a65" : "#168275",
      size: 1.25,
    })));
    chart.subscribeClick(param => {
      if (typeof param.time !== "number") return;
      const at = trades.filter(e => e.bar === param.time);
      if (at.length) {
        const price = param.point ? candles.coordinateToPrice(param.point.y) : at[0].price;
        const hit = at.reduce((a, b) => Math.abs(a.price - price) <= Math.abs(b.price - price) ? a : b);
        this.select(hit, false);
      }
    });
    chart.timeScale().fitContent();
    this.installTradeLabels(root, chart, candles, trades);
    this.highlight(this.selected);
  }

  clearPerformance() {
    for (const chart of this.performanceCharts || []) chart.remove();
    this.performanceCharts = [];
    this.root.querySelector(".replay-performance").replaceChildren();
  }

  drawPerformance() {
    this.clearPerformance();
    const data = this.data;
    const L = window.LightweightCharts;
    const section = this.root.querySelector(".replay-performance");
    const rows = data.marks;
    const latest = rows.at(-1);
    section.append(el("h3", "账户表现"), el("p", latest
      ? "实际采样 · " + stamp(rows[0].time) + " 至 " + stamp(latest.time)
      : "所选时段没有账户采样", "replay-muted"));
    if (!latest || !L) return;
    const grid = el("div", null, "replay-performance-grid");
    section.append(grid);
    for (const metric of ["equity", "return_rate", "drawdown"]) {
      const spec = metrics[metric];
      const signed = value => (metric === "return_rate" && value > 0 ? "+" : "") + number(value === 0 ? 0 : value) + "%";
      const format = metric === "equity" ? value => "$" + number(value) : signed;
      const card = el("article", null, "replay-performance-card");
      card.style.setProperty("--curve-color", spec.color);
      const current = el("strong", format(spec.value(latest)), "replay-performance-value");
      const host = el("div", null, "replay-performance-chart");
      const caption = metric === "drawdown"
        ? "时段最深 " + number(Math.max(...rows.map(row => row.drawdown))) + "%"
        : spec.hint;
      card.append(el("h4", spec.name), current, el("p", caption, "replay-muted"), host);
      grid.append(card);
      const chart = L.createChart(host, {
        autoSize: true, layout: {background: {type: "solid", color: "#f7faf6"}, textColor: "#53665c", attributionLogo: false},
        grid: {vertLines: {visible: false}, horzLines: {color: "#e3eae4"}},
        timeScale: {timeVisible: true, secondsVisible: false,
          tickMarkFormatter: time => new Date(time * 1000).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false})},
        localization: {timeFormatter: time => stamp(time)},
      });
      this.performanceCharts.push(chart);
      const types = {equity: L.AreaSeries, return_rate: L.BaselineSeries, drawdown: L.HistogramSeries};
      const series = chart.addSeries(types[metric], {
        color: spec.color, lineColor: spec.color, lineWidth: 2, topColor: spec.fill,
        bottomColor: "#f7faf6", base: 0, baseValue: {type: "price", price: 0},
        topLineColor: "#187d71", bottomLineColor: "#a44a65",
        pointMarkersVisible: rows.length < 3,
        priceFormat: {type: "custom", minMove: .01, formatter: format},
      });
      const byTime = new Map(rows.map(row => [row.time, row]));
      series.setData(rows.map(row => ({time: row.time, value: spec.value(row)})));
      chart.timeScale().fitContent();
      chart.subscribeCrosshairMove(({time}) => {
        current.textContent = format(spec.value(byTime.get(time) || latest));
      });
      chart.subscribeClick(({time}) => {
        const mark = byTime.get(time);
        if (mark) this.markDetail(mark, time, 60);
      });
    }
  }

  drawSideSummary() {
    const left = this.root.querySelector(".replay-pair-mix");
    const right = this.root.querySelector(".replay-fill-summary");
    left.replaceChildren();
    right.replaceChildren();
    left.hidden = right.hidden = !this.data;
    if (!this.data) return;
    const fills = this.data.events.filter(event => event.pair === this.data.pair && fill(event));
    const opens = fills.filter(event => event.action === "open");
    const closes = fills.filter(event => event.action === "close");
    const longs = opens.filter(event => event.position?.side === "buy").length;
    const mix = el("div", null, "replay-mix-track");
    if (opens.length) {
      const long = el("span");
      long.style.width = (100 * longs / opens.length) + "%";
      mix.append(long);
    }
    left.append(el("h3", "开仓方向"), opens.length ? mix : el("small", "时段内无开仓"));
    if (opens.length) left.append(el("small", "做多 " + longs + " / 做空 " + (opens.length - longs)));
    const sources = [["ai", "AI"], ["human", "人类"], ["system", "系统"]];
    right.append(el("h3", this.data.pair + " 成交构成"));
    for (const [actor, name] of sources) {
      const count = fills.filter(event => event.actor === actor).length;
      const row = el("div", null, "replay-fill-source");
      const meter = el("meter");
      meter.min = 0;
      meter.max = Math.max(1, fills.length);
      meter.value = count;
      meter.setAttribute("aria-label", name + "成交占比");
      row.append(el("span", name), meter, el("strong", String(count)));
      right.append(row);
    }
    right.append(el("small", "开仓 " + opens.length + " 笔 · 平仓 " + closes.length + " 笔"));
  }

  drawActivity() {
    const root = this.root.querySelector(".replay-activity");
    root.replaceChildren();
    const data = this.data;
    root.hidden = !data || data.private === false;
    if (root.hidden) return;
    const jobs = data.events.filter(event => event.action === "review");
    root.append(el("h3", "AI 决策活动"));
    if (!jobs.length) {
      root.append(el("p", "这个时段没有保存的看盘任务。", "replay-muted"));
      return;
    }
    const keys = Object.keys(activityKinds);
    const ledgerCounts = new Map();
    for (const event of data.events) {
      if (event.job && event.actor === "ai" && event.status === "success" && activityActions.has(event.action)) {
        ledgerCounts.set(event.job, (ledgerCounts.get(event.job) || 0) + 1);
      }
    }
    const operations = new Map(jobs.map(event => [
      event.id,
      Math.max((event.tools || []).filter(tool => activityActions.has(tool)).length, ledgerCounts.get(event.job) || 0),
    ]));
    const countOperations = events => events.reduce((total, event) => total + operations.get(event.id), 0);
    const duration = data.end - data.start;
    const step = duration <= 2 * 86400 ? 3600 : duration <= 8 * 86400 ? 21600 : 86400;
    const bins = Array.from({length: Math.max(1, Math.ceil(duration / step))}, () => []);
    const totals = Object.fromEntries(keys.map(key => [key, 0]));
    for (const event of jobs) {
      const bin = Math.min(bins.length - 1, Math.max(0, Math.floor((event.time - data.start) / step)));
      bins[bin].push(event);
      totals[taskKind(event)]++;
    }
    const legend = el("div", null, "replay-activity-legend");
    for (const key of keys) {
      const badge = el("span", activityKinds[key] + " " + totals[key]);
      badge.dataset.kind = key;
      legend.append(badge);
    }
    const intro = el("p", "每格 " + (step === 86400 ? "1 天" : step / 3600 + " 小时") + " · 柱高为实际操作数，圆点表示有任务但没有操作", "replay-muted");
    const strip = el("div", null, "replay-activity-strip");
    const list = el("div", null, "replay-activity-runs");
    const max = Math.max(1, ...bins.map(countOperations));
    const labels = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai",
      ...(step === 86400 ? {month: "numeric", day: "numeric"} : {hour: "2-digit", minute: "2-digit", hour12: false})});
    const buttons = [];
    const show = index => {
      for (const [i, button] of buttons.entries()) button.setAttribute("aria-pressed", String(i === index));
      const start = data.start + index * step, end = Math.min(start + step, data.end);
      list.replaceChildren(el("strong", stamp(start) + " — " + stamp(end) + " · " + countOperations(bins[index]) + " 次操作"));
      if (!bins[index].length) list.append(el("p", "这段时间没有保存的看盘任务。", "replay-muted"));
      for (const event of bins[index]) {
        const button = el("button", null, "replay-run");
        button.type = "button";
        const result = event.outcome || states[event.status] || event.status;
        button.append(el("time", stamp(event.time)), el("strong", event.reason === "定时看盘" ? result : title(event)));
        const status = el("span", operations.get(event.id) + " 次操作");
        status.dataset.kind = taskKind(event);
        button.append(status);
        button.onclick = () => this.select(event);
        list.append(button);
      }
    };
    bins.forEach((events, index) => {
      const button = el("button", null, "replay-activity-bin");
      button.type = "button";
      const start = data.start + index * step;
      const count = countOperations(events);
      button.setAttribute("aria-label", stamp(start) + " 起，" + count + " 次操作，" + events.length + " 个任务");
      const stack = el("span", null, "replay-activity-stack");
      const dots = el("span", null, "replay-activity-dots");
      for (const key of keys) {
        const matching = events.filter(event => taskKind(event) === key);
        if (!matching.length) continue;
        const actions = countOperations(matching);
        if (actions) {
          const bar = el("span");
          bar.dataset.kind = key;
          bar.style.height = (actions / max * 100) + "%";
          stack.append(bar);
        }
        if (matching.some(event => operations.get(event.id) === 0)) {
          const dot = el("span");
          dot.dataset.kind = key;
          dots.append(dot);
        }
      }
      if (count) stack.append(el("b", count, "replay-activity-count"));
      button.append(stack, dots, el("small", index % 4 === 0 ? labels.format(start * 1000) : ""));
      button.onclick = () => show(index);
      strip.append(button);
      buttons.push(button);
    });
    root.append(legend, intro, strip, list);
    show(bins.findLastIndex(events => events.length));
  }

  installTradeLabels(root, chart, candles, trades) {
    const overlay = el("div", null, "replay-trade-labels");
    root.append(overlay);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("replay-position-arc");
    svg.setAttribute("aria-hidden", "true");
    const paths = ["halo", "ink"].map(kind => {
      const path = document.createElementNS(svg.namespaceURI, "path");
      path.classList.add("replay-arc-" + kind);
      svg.append(path);
      return path;
    });
    overlay.append(svg);
    const guides = ["上一条", "当前"].map(label => {
      const guide = el("span", label, "replay-event-guide");
      guide.hidden = true;
      guide.setAttribute("aria-hidden", "true");
      overlay.append(guide);
      return guide;
    });
    const labels = trades.map(event => {
      const button = el("button", title(event), "replay-trade-label");
      button.type = "button";
      button.dataset.kind = event.actor === "system" ? "system" : event.action;
      button.dataset.event = event.id;
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
        svg.setAttribute("width", width);
        svg.setAttribute("height", height);
        const position = this.selected?.position?.id;
        const related = position ? trades.filter(event => event.position?.id === position) : [];
        const first = related.find(event => event.action === "open");
        const last = related.findLast(event => event.action === "close");
        let route = "";
        if (first && last) {
          const x1 = scale.timeToCoordinate(first.bar), x2 = scale.timeToCoordinate(last.bar);
          const y1 = candles.priceToCoordinate(first.price), y2 = candles.priceToCoordinate(last.price);
          if ([x1, x2, y1, y2].every(Number.isFinite)) {
            const bend = Math.min(45, Math.max(18, Math.abs(x2 - x1) * .2));
            const side = (y1 + y2) / 2 > height / 2 ? -1 : 1;
            route = "M " + x1 + " " + y1 + " C " + (x1 + bend) + " " + (y1 + side * bend)
              + ", " + (x2 + bend) + " " + (y2 + side * bend) + ", " + x2 + " " + y2;
          }
        }
        for (const path of paths) path.setAttribute("d", route);
        const pair = this.relatedFrom && this.selected ? [this.relatedFrom, this.selected] : [];
        const sameBar = pair.length === 2 && pair[0].bar === pair[1].bar;
        for (const [i, guide] of guides.entries()) {
          const x = pair[i] && this.candleTimes.has(pair[i].bar) ? scale.timeToCoordinate(pair[i].bar) : null;
          guide.hidden = x == null || x < 0 || x > width || (sameBar && i === 0);
          if (guide.hidden) continue;
          guide.textContent = sameBar ? "前后记录" : i === 0 ? "上一条" : "当前";
          guide.style.left = Math.max(0, Math.min(x, width - guide.offsetWidth)) + "px";
          guide.style.setProperty("--guide-height", Math.max(0, height - 20) + "px");
        }
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
    for (const line of this.protectionLines) this.priceSeries.removePriceLine(line);
    this.protectionLines = [];
    if (!event?.position?.id || !this.candleTimes.has(event.bar)) return;
    const L = window.LightweightCharts;
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

  select(event, move = true, keepOrigin = false) {
    const origin = keepOrigin ? this.selected : null;
    this.relatedFrom = origin && origin.id !== event.id ? origin : null;
    this.selected = event;
    this.highlight(event);
    for (const button of this.root.querySelectorAll(".replay-row")) {
      button.setAttribute("aria-current", button.dataset.event === event.id ? "true" : "false");
    }
    cancelAnimationFrame(this.rangeFrame);
    const flash = this.relatedFrom ? () => this.flashEvent(event) : undefined;
    if (move && this.chart) this.revealEvents(event, this.relatedFrom, flash);
    else flash?.();
    this.detail(event);
  }

  flashEvent(event) {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    requestAnimationFrame(() => {
      if (this.selected?.id !== event.id) return;
      const elements = this.root.querySelectorAll(
        ".replay-row[aria-current=true], .replay-trade-label[aria-pressed=true], .replay-event-guide:last-of-type:not([hidden])"
      );
      for (const node of elements) {
        node.animate([
          {boxShadow: "0 0 0 0 #a76bd000"},
          {boxShadow: "0 0 0 4px #914dc7"},
          {boxShadow: "0 0 0 0 #a76bd000"},
        ], {duration: 380, iterations: 2});
      }
    });
  }

  revealEvents(event, origin, after) {
    const scale = this.chart.timeScale();
    const current = scale.getVisibleLogicalRange();
    const bars = this.data.candles;
    const indices = [event, origin].filter(Boolean).map(item => bars.findIndex(bar => bar.time === item.bar)).filter(index => index >= 0);
    if (!current || !indices.length) { after?.(); return; }
    const left = Math.min(...indices), right = Math.max(...indices);
    if (left >= current.from && right <= current.to) { after?.(); return; }
    const span = Math.max(current.to - current.from, right - left + 4);
    const from = Math.min(left - 2, Math.max(current.from, right + 2 - span));
    const target = {from, to: from + span};
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      scale.setVisibleLogicalRange(target);
      after?.();
      return;
    }
    const started = performance.now();
    const move = now => {
      const progress = Math.min(1, (now - started) / 320);
      const eased = 1 - (1 - progress) ** 3;
      scale.setVisibleLogicalRange({
        from: current.from + (target.from - current.from) * eased,
        to: current.to + (target.to - current.to) * eased,
      });
      if (progress < 1) this.rangeFrame = requestAnimationFrame(move);
      else after?.();
    };
    this.rangeFrame = requestAnimationFrame(move);
  }

  textSection(label, text, grouped = false) {
    const body = el("div", null, "replay-copy");
    const pieces = grouped ? text.split(/(?:^|\n)[ \t]*【([^】\n]+)】/u) : [text];
    if (pieces[0].trim()) body.append(el("p", pieces[0].trim(), "replay-text"));
    for (let i = 1; i < pieces.length; i += 2) {
      const group = el("div", null, "replay-plan-group");
      group.append(el("strong", pieces[i]), el("p", pieces[i + 1].trim(), "replay-text"));
      body.append(group);
    }
    const fold = text.length > 180;
    const section = el(fold ? "details" : "section", null, "replay-inspector-section");
    const heading = el(fold ? "summary" : "h4", label);
    if (fold) heading.append(el("span", text.slice(0, 100).trimEnd() + "…", "replay-copy-preview"));
    section.append(heading, body);
    return section;
  }

  links(root, events) {
    for (const event of events) {
      const button = el("button", null, "replay-related");
      button.append(el("strong", title(event)), el("time", stamp(event.time)));
      button.type = "button";
      button.onclick = () => this.select(event, true, true);
      root.append(button);
    }
  }

  detail(event) {
    const root = this.root.querySelector(".replay-detail");
    root.replaceChildren();
    root.scrollTop = 0;
    if (!event) {
      root.append(el("h3", "这一刻发生了什么"), el("p", "点击图上的成交点，或从时间线选择一条记录。"));
      return;
    }
    const heading = el("div", null, "replay-inspector-heading");
    const badges = el("div", null, "replay-inspector-badges");
    const actor = event.actor === "ai" ? "AI" : event.actor === "system" ? "系统" : "用户";
    badges.append(el("span", actor), el("span", event.outcome || states[event.status] || event.status));
    heading.append(el("h3", title(event)), badges, el("time", stamp(event.time), "replay-muted"));
    root.append(heading);
    if (event.action === "review") {
      const section = el("section", null, "replay-inspector-section");
      section.append(el("h4", "任务轨迹"));
      if (event.elapsed != null) section.append(el("p", "从入队到结束 " + event.elapsed + " 秒", "replay-muted"));
      const counts = new Map();
      for (const tool of event.tools || []) {
        if (!Object.hasOwn(toolNames, tool)) continue;
        counts.set(tool, (counts.get(tool) || 0) + 1);
      }
      const tools = el("div", null, "replay-inspector-badges");
      for (const [tool, count] of counts) tools.append(el("span", toolNames[tool] + " × " + count));
      section.append(counts.size ? tools : el("p", "没有保存的工具调用明细。", "replay-muted"));
      root.append(section);
    }

    const position = event.position;
    if (position?.pair) {
      const fields = [["品种", position.pair], ["方向", position.side === "buy" ? "做多" : "做空"], ["数量", position.units + " 单位"]];
      if (event.price != null) fields.push(["成交价", event.price], ["手续费", "$" + number(event.fee)]);
      if (position.sl) fields.push(["止损", position.sl]);
      if (position.tp) fields.push(["止盈", position.tp]);
      if (event.action === "close" && position.pnl != null) {
        const entry = this.data.events.find(e => e.action === "open" && fill(e) && e.position.id === position.id);
        const pnl = Number(position.pnl) - (entry ? event.fee + entry.fee : 0);
        fields.push([entry ? "扣双边费后" : "平仓毛盈亏", (pnl < 0 ? "−" : pnl > 0 ? "+" : "") + "$" + number(Math.abs(pnl))]);
        if (position.created) fields.push(["持仓时间", Math.max(0, Math.round((event.time - position.created) / 60)) + " 分钟"]);
      }
      const facts = el("dl", null, "replay-inspector-facts");
      for (const [label, value] of fields) {
        const field = el("div");
        field.append(el("dt", label), el("dd", value));
        facts.append(field);
      }
      root.append(facts);
    }
    if (event.reason && event.reason !== title(event)) root.append(this.textSection(event.actor === "ai" ? "操作理由" : "触发原因", event.reason));
    if (event.text) root.append(this.textSection(event.action === "plan" ? "策略内容" : event.status === "failed" ? "失败详情" : "任务记录", event.text, true));
    const mark = this.data.marks.findLast(m => m.time < Math.floor(event.time));
    if (mark) root.append(el("p", "此前最近采样 · 回撤 " + number(mark.drawdown) + "% · 净值 $" + number(mark.equity), "replay-muted replay-inspector-sample"));
    const related = this.data.events.filter(e => e !== event && (
      (position?.id && e.position?.id === position.id) || (event.job && e.job === event.job) ||
      event.related?.includes(e.id) || e.related?.includes(event.id)));
    if (related.length) {
      const section = el("section", null, "replay-inspector-section");
      section.append(el("h4", "关联记录"));
      this.links(section, related.slice(0, 20));
      root.append(section);
    }
    const plan = this.data.events.findLast(e => e.action === "plan" && e.status === "success" && e.time < event.time);
    if (this.data.private !== false) {
      root.append(this.textSection("当时策略", plan?.text || this.data.baseline || "未记录", true));
      for (const diary of this.data.diaries) {
        const date = new Intl.DateTimeFormat("sv-SE", {timeZone: diary.zone, dateStyle: "short"}).format(new Date(event.time * 1000));
        if (date !== diary.day) continue;
        const block = el("details", null, "replay-inspector-section replay-diary-entry");
        block.append(el("summary", date + " · 日记回顾"), el("p", diary.content, "replay-text"));
        root.append(block);
      }
    }
  }

  markDetail(mark, time, seconds) {
    this.relatedFrom = null;
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
