/* Local Lightweight Charts renderer. History and all-six sampling are independent of selection. */
const L = window.LightweightCharts;
const intervals = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
  "1w": 604800,
  "1M": 2592000,
};
const el = (id) => document.getElementById(id);

export class HistoryChart {
  constructor(container, bridge) {
    this.bridge = bridge;
    this.feed = "";
    this.pair = "";
    this.period = "5m";
    this.series = null;
    this.cache = new Map();
    this.generation = 0;
    this.quotes = {};
    this.programmatic = false;
    this.pageSize = 200;
    this.follow = true;
    this.chart = L.createChart(container, {
      autoSize: true,
      height: 340,
      layout: {
        background: { type: "solid", color: "#fcfafd" },
        textColor: "#76637a",
        attributionLogo: true,
        fontFamily: "Segoe UI, Microsoft YaHei, sans-serif",
      },
      grid: {
        vertLines: { color: "#eee6ee" },
        horzLines: { color: "#eee6ee" },
      },
      rightPriceScale: {
        visible: true,
        borderColor: "#ded0df",
        autoScale: true,
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#ded0df",
        rightOffset: 4,
        barSpacing: 7,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: { time: true, price: true },
        axisDoubleClickReset: { time: true, price: true },
      },
      crosshair: { mode: L.CrosshairMode.Normal },
    });
    this.type = "candles";
    this.makeSeries();
    this.applyZone();
    this.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range || this.programmatic) return;
      const entry = this.entry();
      if (entry?.bars.length) this.follow = range.to >= entry.bars.length - 2;
      if (entry?.bars.length && range.from < 15 && entry.more && !entry.loading)
        this.older();
    });
    this.chart.subscribeCrosshairMove((param) => {
      const bar = param.seriesData.get(this.series);
      if (this.reference && bar?.value !== undefined) {
        el("chart-ohlc").textContent = `每日参考汇率 ${this.fmt(bar.value)}`;
        return;
      }
      if (bar?.open !== undefined)
        el("chart-ohlc").textContent =
          `开 ${this.fmt(bar.open)}　高 ${this.fmt(bar.high)}　低 ${this.fmt(bar.low)}　收 ${this.fmt(bar.close)}`;
    });
    el("chart-type").onchange = () => {
      this.type = el("chart-type").value;
      this.makeSeries();
      this.refreshContext();
    };
    el("chart-period").onchange = () => {
      this.period = el("chart-period").value;
      this.refreshContext();
    };
    el("history-more").onclick = () => this.older();
    el("chart-reset").onclick = () => {
      this.chart.priceScale("right").setAutoScale(true);
      this.fit();
    };
    el("chart-latest").onclick = () => {
      this.chart.timeScale().scrollToRealTime();
      this.chart.priceScale("right").setAutoScale(true);
    };
    el("chart-zoom-in").onclick = () => this.zoom(0.75);
    el("chart-zoom-out").onclick = () => this.zoom(1.35);
    el("axis-interactive").onchange = () => {
      const on = el("axis-interactive").checked;
      this.chart.applyOptions({ handleScroll: on, handleScale: on });
    };
    el("axis-mode").onchange = () =>
      this.chart
        .priceScale("right")
        .applyOptions({ mode: Number(el("axis-mode").value), autoScale: true });
    el("axis-zone").onchange = () => this.applyZone();
    el("axis-apply-y").onclick = () => {
      const from = Number(el("axis-min").value),
        to = Number(el("axis-max").value);
      if (
        !Number.isFinite(from) ||
        !Number.isFinite(to) ||
        from <= 0 ||
        to <= from
      ) {
        this.status("价格范围应为正数，且最高价大于最低价。", true);
        return;
      }
      this.chart.priceScale("right").setVisibleRange({ from, to });
    };
    el("axis-auto-y").onclick = () =>
      this.chart.priceScale("right").setAutoScale(true);
    el("axis-apply-x").onclick = () => this.applyX();
  }
  fmt(value) {
    return Number(value).toFixed(this.pair.endsWith("/JPY") ? 3 : 5);
  }
  status(text, error = false) {
    el("chart-status").textContent = text;
    el("chart-status").classList.toggle("error", error);
  }
  key(pair = this.pair) {
    return `${this.feed}:${pair}:${this.period}`;
  }
  entry(pair = this.pair) {
    return this.cache.get(this.key(pair));
  }
  ensure(pair) {
    const key = this.key(pair);
    if (!this.cache.has(key))
      this.cache.set(key, {
        bars: [],
        more: true,
        loading: false,
        request: null,
        loaded: false,
        warning: "",
      });
    return this.cache.get(key);
  }
  makeSeries() {
    const range = this.chart.timeScale().getVisibleLogicalRange();
    if (this.series) this.chart.removeSeries(this.series);
    const common = {
      priceFormat: {
        type: "price",
        precision: this.pair.endsWith("/JPY") ? 3 : 5,
        minMove: this.pair.endsWith("/JPY") ? 0.001 : 0.00001,
      },
    };
    if (this.type === "line")
      this.series = this.chart.addSeries(L.LineSeries, {
        ...common,
        color: "#9b4c7c",
        lineWidth: 2,
      });
    else if (this.type === "area")
      this.series = this.chart.addSeries(L.AreaSeries, {
        ...common,
        lineColor: "#9b4c7c",
        topColor: "#d69cbe70",
        bottomColor: "#fdf6fb00",
        lineWidth: 2,
      });
    else if (this.type === "bars")
      this.series = this.chart.addSeries(L.BarSeries, {
        ...common,
        upColor: "#c25575",
        downColor: "#278976",
      });
    else
      this.series = this.chart.addSeries(L.CandlestickSeries, {
        ...common,
        upColor: "#c25575",
        downColor: "#278976",
        wickUpColor: "#c25575",
        wickDownColor: "#278976",
        borderVisible: false,
      });
    if (range) this.chart.timeScale().setVisibleLogicalRange(range);
  }
  applyZone() {
    const zone = el("axis-zone").value;
    const full = new Intl.DateTimeFormat("zh-CN", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    const short = new Intl.DateTimeFormat("zh-CN", {
      timeZone: zone,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    const date = new Intl.DateTimeFormat("zh-CN", {
      timeZone: zone,
      month: "2-digit",
      day: "2-digit",
    });
    this.chart.applyOptions({
      localization: {
        timeFormatter: (t) => full.format(new Date(Number(t) * 1000)),
      },
      timeScale: {
        tickMarkFormatter: (t, type) =>
          (type <= 2 ? date : short).format(new Date(Number(t) * 1000)),
      },
    });
  }
  refreshContext() {
    if (!this.contextArgs) return;
    this.setContext(...this.contextArgs);
  }
  setContext(
    feed,
    pair,
    quotes,
    allPairs,
    historySource = "market",
    feeds = {},
  ) {
    this.contextArgs = [feed, pair, quotes, allPairs, historySource, feeds];
    const reference =
      historySource === "frankfurter" &&
      ["line", "area"].includes(this.type) &&
      ["1d", "1w", "1M"].includes(this.period);
    this.reference = reference;
    feed = feeds[reference ? "frankfurter" : "market"] || feed;
    for (const option of el("chart-period").options) option.disabled = false;
    for (const option of el("chart-type").options) option.disabled = false;
    el("history-kind").textContent = reference
      ? "Frankfurter 每日参考汇率；周/月显示末次参考价，不参与成交。"
      : "真实行情源历史 K 线；所有周期可选。Frankfurter 仅用于日/周/月折线或面积图。";
    const changed = this.feed !== feed;
    if (changed) {
      this.feed = feed;
      this.generation++;
      // Entries are keyed by feed/pair/period and shared by every instance.
    }
    this.allPairs = allPairs;
    this.quotes = quotes || {};
    // Capture every pair in memory too, regardless of visible symbol.
    for (const p of allPairs) this.ingest(p, this.quotes[p]);
    if (changed || this.pair !== pair || !this.entry(pair)?.loaded) {
      this.select(pair, true);
      this.primeAll();
    } else this.draw(false);
  }
  ingest(pair, q) {
    if (this.reference) return;
    if (!q || !q.tradeable || Date.now() / 1000 - q.timestamp > 30) return;
    const entry = this.ensure(pair),
      step = intervals[this.period];
    let t = Math.floor(q.timestamp / step) * step;
    if (["1d", "1w", "1M"].includes(this.period)) {
      const offset = q.source === "新浪外汇" ? 28800 : 0,
        d = new Date((q.timestamp + offset) * 1000);
      d.setUTCHours(0, 0, 0, 0);
      if (this.period === "1w")
        d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
      if (this.period === "1M") d.setUTCDate(1);
      t = d.getTime() / 1000 - offset;
    }
    const p = (Number(q.bid) + Number(q.ask)) / 2,
      last = entry.bars.at(-1);
    if (last && t < last.time) return;
    if (last?.time === t) {
      last.high = Math.max(last.high, p);
      last.low = Math.min(last.low, p);
      last.close = p;
    } else entry.bars.push({ time: t, open: p, high: p, low: p, close: p });
  }
  async select(pair, fit) {
    this.pair = pair;
    this.makeSeries();
    const entry = this.ensure(pair);
    if (entry.loaded) {
      this.draw(fit);
      return;
    }
    this.series.setData([]);
    this.status("正在加载历史 K 线…");
    try {
      await this.fetch(pair, 0);
      if (this.pair === pair) this.draw(fit);
    } catch (e) {
      if (this.pair === pair)
        this.status(e.message || "历史加载失败，点击“加载更早”重试。", true);
    }
  }
  primeAll() {
    for (const pair of this.allPairs || [])
      if (!this.ensure(pair).loaded) this.fetch(pair, 0).catch(() => {});
  }
  async fetch(pair, before) {
    const entry = this.ensure(pair);
    if (entry.request) return entry.request;
    const feed = this.feed,
      period = this.period;
    entry.loading = true;
    entry.request = (async () => {
      try {
        const data = await this.bridge.apiGet("history", {
          pair,
          period,
          before,
          limit: this.pageSize,
          history_source: this.reference ? "frankfurter" : "market",
        });
        if (feed !== this.feed || period !== this.period || data.feed !== feed)
          return;
        const merged = new Map(entry.bars.map((b) => [b.time, b]));
        for (const bar of data.bars) merged.set(bar.time, bar);
        entry.bars = [...merged.values()].sort((a, b) => a.time - b.time);
        entry.more = data.has_more;
        entry.warning = data.warning || "";
        entry.loaded = true;
        this.ingest(pair, this.quotes[pair]);
        if (pair === this.pair) this.draw(false);
      } finally {
        entry.loading = false;
        entry.request = null;
        this.controls();
      }
    })();
    return entry.request;
  }
  async older() {
    const entry = this.ensure(this.pair);
    if (entry.loading) return;
    if (!entry.loaded) {
      await this.select(this.pair, true);
      return;
    }
    if (!entry.more) return;
    const pair = this.pair,
      feed = this.feed,
      old = entry.bars.length,
      range = this.chart.timeScale().getVisibleLogicalRange();
    this.status("正在加载更早的 K 线…");
    try {
      await this.fetch(pair, entry.bars[0]?.time || 0);
      if (pair !== this.pair || feed !== this.feed) return;
      const added = entry.bars.length - old;
      if (!added) entry.more = false;
      this.programmatic = true;
      if (range)
        this.chart.timeScale().setVisibleLogicalRange({
          from: range.from + added,
          to: range.to + added,
        });
      this.programmatic = false;
      this.controls();
    } catch (e) {
      this.status(e.message || "历史加载失败，可重试。", true);
    }
  }
  draw(fit = false) {
    const entry = this.entry();
    if (!entry || !this.series) return;
    const range = this.chart.timeScale().getVisibleLogicalRange();
    this.programmatic = true;
    this.series.setData(
      this.type === "line" || this.type === "area"
        ? entry.bars.map((b) => ({ time: b.time, value: b.close }))
        : entry.bars,
    );
    if (fit) this.fit();
    else if (this.follow) this.chart.timeScale().scrollToRealTime();
    else if (range) this.chart.timeScale().setVisibleLogicalRange(range);
    this.programmatic = false;
    const bar = entry.bars.at(-1);
    if (bar && this.reference)
      el("chart-ohlc").textContent =
        `每日参考汇率 ${this.fmt(bar.close)} · ${new Date(bar.time * 1000).toISOString().slice(0, 10)}`;
    else if (bar)
      el("chart-ohlc").textContent =
        `开 ${this.fmt(bar.open)}　高 ${this.fmt(bar.high)}　低 ${this.fmt(bar.low)}　收 ${this.fmt(bar.close)}`;
    this.controls();
  }
  controls() {
    const entry = this.entry();
    if (!entry) return;
    el("history-more").disabled =
      entry.loading || (entry.loaded && !entry.more);
    if (!entry.loading)
      this.status(
        entry.warning ||
          `已加载 ${entry.bars.length} ${this.reference ? "条参考价" : "根"} · ${this.period} · ${entry.more ? "左拖或点击加载更早" : "已到当前数据源可提供的最早记录"}`,
      );
  }
  fit() {
    const n = this.entry()?.bars.length || 0;
    if (n)
      this.chart
        .timeScale()
        .setVisibleLogicalRange({ from: Math.max(0, n - 100), to: n + 4 });
  }
  zoom(factor) {
    const range = this.chart.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const mid = (range.from + range.to) / 2,
      half = ((range.to - range.from) * factor) / 2;
    this.chart
      .timeScale()
      .setVisibleLogicalRange({ from: mid - half, to: mid + half });
  }
  async applyX() {
    const from = Date.parse(el("axis-from").value) / 1000,
      to = Date.parse(el("axis-to").value) / 1000;
    if (!Number.isFinite(from) || !Number.isFinite(to) || from >= to) {
      this.status("请填写有效起止时间，结束须晚于开始。", true);
      return;
    }
    try {
      await this.fetch(
        this.pair,
        Math.floor(Math.min(Date.now() / 1000, to + 1)),
      );
      this.draw(false);
      this.chart.timeScale().setVisibleRange({ from, to });
    } catch (e) {
      this.status(e.message || "时间范围加载失败", true);
    }
  }
}
