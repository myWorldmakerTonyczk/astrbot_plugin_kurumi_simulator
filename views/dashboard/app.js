import { refreshRequired } from "./required-fields.js";
import { UserManager } from "./user-manager.js";
import { ModelSettings } from "./model-settings.js";
import { InstanceNotices } from "./notification-form.js";
import { DiaryPanel } from "./diary-panel.js";
import { HistoryChart } from "./history-chart.js";
import { TradingNotices } from "./notifications.js";
import { instanceGroups, renderInstanceDirectory } from "./instance-catalog.js";
const bridge = window.AstrBotPluginView;
const tradingNotices = new TradingNotices(bridge);
const diaryPanel = new DiaryPanel(bridge);
const userManager = new UserManager(post, load, (user) => {
  rotatingUser = user;
  $("rotate-user-name").textContent = `为「${user.name}」生成新ID？`;
  $("rotate-user-dialog").showModal();
  tradingNotices.setScope("");
}, (user) => {
  deletingUser=user;
  $("delete-user-description").textContent=`删除「${user.name}」及其 ${user.instances?.length||0} 个交易实例？`;
  $("delete-user-dialog").showModal();tradingNotices.setScope("");
});
const modelSettings = new ModelSettings(post, load);
const instanceNotices = new InstanceNotices(post, load);
let settingsPage = "users";
function showSettings(page) {
  settingsPage = page;
  for (const section of document.querySelectorAll("[data-settings-page]")) section.hidden=section.dataset.settingsPage!==page;
  for (const button of document.querySelectorAll("[data-settings-tab],[data-settings-anchor]")) {
    const active=(button.dataset.settingsTab||button.dataset.settingsAnchor)===page;
    button.classList.toggle("selected",active);button.setAttribute("aria-pressed",String(active));
  }
}
for (const button of document.querySelectorAll("[data-settings-tab]")) button.onclick=()=>showSettings(button.dataset.settingsTab);
const requestId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
const $ = (id) => document.getElementById(id);
let state = null,
  gid = "",
  loading = false,
  posting = false;
let priceChart;
let workspaceMode = "instances",
  instancePage = "overview",
  selectedOwner = "";
const expandedPositions = new Set();
let connectionDirty = false;
let decisionSettingsDirty=false;
const money = (value) =>
  Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const pairNames = {
  "EUR/USD": "欧元 / 美元",
  "GBP/USD": "英镑 / 美元",
  "AUD/USD": "澳元 / 美元",
  "USD/JPY": "美元 / 日元",
  "USD/CHF": "美元 / 瑞士法郎",
  "USD/CAD": "美元 / 加元",
};
const pairLabel = (p) => (pairNames[p] ? `${p}（${pairNames[p]}）` : p);
const labels = {
  borrow: "借入虚拟资金",
  repay: "偿还贷款",
  loan_config: "贷款开关",
  loan_interest: "贷款计息",
  create: "创建游戏",
  open: "开仓",
  close: "平仓",
  deposit: "追加本金",
  pause: "暂停",
  resume: "继续",
  observe: "观望",
  plan: "更新计划",
  notes: "更新经验",
  bind: "绑定设置",
  end: "本局结束",
  protect: "修改止盈止损",
  margin_call: "保证金不足提醒",
};
function message(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function options(el, items, value) {
  el.replaceChildren(
    ...items.map((i) => {
      const o = node(
        "option",
        typeof i === "string" ? pairLabel(i) : i.name || i.id,
      );
      o.value = typeof i === "string" ? i : i.id;
      return o;
    }),
  );
  if (value !== undefined) el.value = value;
}
function workspace(mode) {
  workspaceMode = mode;
  const inInstance = mode === "instances" && !!gid,
    catalog = mode === "instances" && !gid;
  for (const button of document.querySelectorAll("[data-workspace]")) {
    const active = button.dataset.workspace === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  $("instance-nav").hidden = !inInstance;
  $("settings-nav").hidden = mode !== "settings";
  document.querySelector(".workspace>aside").hidden = catalog;
  document
    .querySelector(".workspace")
    .classList.toggle("catalog-mode", catalog);
  $("instance-context").hidden = !gid;
  document.querySelector(".character-banner").hidden = !inInstance;
  const page = mode === "settings" ? "setup" : gid ? instancePage : "catalog";
  for (const section of document.querySelectorAll("[data-page]"))
    section.hidden = section.dataset.page !== page;
  const current = state?.current?.game.id === gid ? state.current : null;
  $("title").textContent =
    mode === "settings"
      ? "久留美 · 设置"
      : catalog
        ? "交易实例"
        : current?.game.name || "正在打开交易实例…";
  $("instance-loading").hidden = !inInstance || !!current;
  for (const button of document.querySelectorAll("[data-tab]"))
    button.classList.toggle("selected", button.dataset.tab === instancePage);
  $("open-instance-settings").disabled = !gid;
  tradingNotices.setScope(
    inInstance &&
      !$("create-instance-dialog").open &&
      !$("instance-settings-dialog").open &&
      !$("delete-instance-dialog").open
      ? gid
      : "",
  );
  if (inInstance && instancePage === "overview")
    requestAnimationFrame(renderChart);
}
function tab(name) {
  if (name === "setup") workspace("settings");
  else if (gid) {
    instancePage = name;
    workspace("instances");
  }
}
function returnToCatalog() {
  gid = "";
  selectedOwner = "";
  if (state) state.current = null;
  workspace("instances");
  if (state) render();
  load();
}
for (const button of document.querySelectorAll("[data-workspace]"))
  button.onclick = () =>
    button.dataset.workspace === "instances"
      ? workspace("instances")
      : workspace("settings");
$("back-to-catalog").onclick = returnToCatalog;
for (const button of document.querySelectorAll("[data-settings-anchor]"))
  button.onclick = () => showSettings(button.dataset.settingsAnchor);
function selectInstance(instance) {
  selectedOwner = instance.ownerId;
  gid = instance.id;
  instancePage = "overview";
  if (state?.current?.game.id !== gid) state.current = null;
  workspace("instances");
  load();
}
function renderCatalog() {
  const groups = instanceGroups(state.games, state.workspace?.users || []),
    hasInstances = state.games.length > 0;
  $("empty").hidden = hasInstances;
  $("catalog-heading").hidden = !hasInstances;
  $("instance-directory").hidden = !hasInstances;
  renderInstanceDirectory(
    $("instance-directory"),
    groups,
    gid,
    selectInstance,
    openDeleteInstance,
  );
  const owner = groups.find((g) => g.instances.some((i) => i.id === gid));
  const instance = owner?.instances.find((i) => i.id === gid);
  $("instance-breadcrumb").textContent = instance
    ? `${owner.name} / ${instance.name}`
    : "";
}
for (const el of document.querySelectorAll("[data-tab],[data-go]"))
  el.onclick = () => tab(el.dataset.tab || el.dataset.go);
async function load() {
  if (loading) return;
  loading = true;
  try {
    if (!bridge) throw Error("请从 AstrBot 的插件视图打开面板。");
    const requestedId = gid;
    const nextState = await bridge.apiGet(
      "state",
      requestedId ? { game: requestedId } : {},
    );
    if (gid !== requestedId) {
      loading = false;
      return load();
    }
    state = nextState;
    if (state.missing_instance) {
      gid = "";
      state.current = null;
      workspace("instances");
    }
    render();
    await tradingNotices.sync(tradingNotices.activeGame);
    message(
      state.market_error ||
        state.runtime_error ||
        "账户已同步 · 所有金额均为虚拟资金",
      !!(state.market_error || state.runtime_error),
    );
  } catch (e) {
    message(e.message || "读取失败", true);
  } finally {
    loading = false;
  }
}
async function post(route, body) {
  if (posting) {
    tradingNotices.failed("上一项操作尚未完成，请稍候。");
    throw Error("上一项操作尚未完成");
  }
  posting = true;
  document
    .querySelectorAll("button[type=submit],#decide")
    .forEach((b) => (b.disabled = true));
  try {
    const r = await bridge.apiPost(route, body);
    message(r.message || "操作已完成");
    return r;
  } catch (e) {
    message(e.message || "操作失败", true);
    tradingNotices.failed(
      e.message || "操作失败",
      body.request_id,
      body.game && !["bind", "delete"].includes(body.action) ? body.game : null,
    );
    if (e && typeof e === "object") e.noticeShown = true;
    throw e;
  } finally {
    posting = false;
    document
      .querySelectorAll("button[type=submit],#decide")
      .forEach((b) => (b.disabled = b.dataset.permissionDisabled === "true"));
  }
}
async function action(name, params) {
  try {
    await post("command", {
      game: gid,
      action: name,
      params,
      request_id: requestId(),
    });
  } finally {
    await load();
  }
}
function journal(container, logs) {
  container.replaceChildren();
  if (!logs.length) {
    container.append(
      node("p", "还没有交易记录。创建游戏后的每次操作都会留在这里。"),
    );
    return;
  }
  for (const l of logs) {
    const row = node("article", undefined, "journal-row");
    row.append(
      node("small", new Date(l.created * 1000).toLocaleString("zh-CN")),
      node(
        "strong",
        { ai: "AI", human: "人类", system: "系统" }[l.source] || l.source,
      ),
    );
    const content = node("div");
    content.append(
      node(
        "strong",
        `${labels[l.action] || l.action} · ${l.status === "rejected" ? "未执行" : l.action === "open" ? "已成交" : "已执行"}`,
        l.status === "rejected" ? "negative" : "",
      ),
      node("p", l.reason),
      ...(l.status === "rejected"
        ? [node("p", l.detail?.error || "操作被拒绝", "negative")]
        : []),
    );
    const d = node("details");
    d.append(
      node("summary", "查看操作详情"),
      node("pre", JSON.stringify(l.detail, null, 2)),
    );
    content.append(d);
    row.append(content);
    container.append(row);
  }
}
function render() {
  renderCatalog();
  renderManagedUsers();
  diaryPanel.render(state.diary_settings, gid);
  modelSettings.render(state.llm_settings, state.providers);
  if(state.decision_limits&&!decisionSettingsDirty) {
    const form=$("decision-settings"),v=state.decision_limits;
    form.elements.cooldown.value=v.cooldown/60;form.elements.hourly_limit.value=v.hourly_limit;
    for(const key of ["stop_loss","take_profit","liquidation","margin_call","end"])form.elements[key].checked=v[key];
  }
  instanceNotices.render(state.instance_access, gid);
  showSettings(settingsPage);
  workspace(workspaceMode);
  if (!$("pairs").children.length) {
    for (const [index, pair] of state.pairs.entries()) {
      const label = node("label", undefined, "check"),
        input = node("input");
      input.type = "checkbox";
      input.name = "allowed-pair";
      input.value = pair;
      input.checked = index === 0;
      label.append(input, node("span", pairLabel(pair)));
      $("pairs").append(label);
    }
  }
  if (!connectionDirty && !$("connection").contains(document.activeElement)) {
    const connection = state.connection;
    const form = $("connection");
    form.elements.market_source.value = connection.market_source || "biquote";
    form.elements.history_source.value =
      connection.history_source || "frankfurter";
    form.elements.market_account.value = connection.market_account || "";
    for (const key of ["biquote", "sina"])
      form.elements[key + "_url"].value =
        connection[key + "_url"] || connection.defaults?.[key] || "";
    sourceFields();
  }
  const selected = gid && state.current?.game.id === gid ? state.current : null;
  $("desk").hidden = !selected;
  refreshRequired();
  if (!selected) {
    $("mood-scene").src = "./assets/neutral.png";
    journal($("logs"), []);
    return;
  }
  const g = selected.game,
    v = selected.valuation;
  const mood = v
    ? Number(v.profit) > 0
      ? "hero-red"
      : Number(v.profit) < 0
        ? "hero-green"
        : "neutral"
    : "neutral";
  $("mood-scene").src = "./assets/" + mood + ".png";
  $("mood-copy").textContent = v
    ? Number(v.profit) > 0
      ? "账面有了收获，也别忘记她当时的判断。"
      : Number(v.profit) < 0
        ? "行情不总是顺心，每一次经历都值得复盘。"
        : "还没分出胜负，先看看她怎样理解市场。"
    : "等行情连上，再一起看看她的选择。";
  $("title").textContent =
    workspaceMode === "settings" ? "久留美 · 设置" : g.name;
  $("game-status").textContent =
    ({ running: "运行中", paused: "自主操作已暂停", ended: "本局已结束" }[
      g.status
    ] || g.status) +
    " · 第 " +
    (Math.floor((Date.now() / 1000 - g.created) / 86400) + 1) +
    " 天";
  renderDecision();
  $("metrics").replaceChildren();
  for (const [label, value] of [
    ["当前净值", v ? "$" + money(v.equity) : "等待行情"],
    ["可用保证金", v ? "$" + money(v.free) : "—"],
    ["浮动盈亏", v ? "$" + money(v.floating) : "—"],
    ["已用保证金", v ? "$" + money(v.margin) : "—"],
    ["待还贷款（含息）", v ? "$" + money(v.debt || 0) : "—"],
    ["本局净收益", v ? "$" + money(v.profit) : "—"],
    ["收益率", v ? Number(v.return_rate).toFixed(2) + "%" : "—"],
    ["最大回撤", Number(g.drawdown).toFixed(2) + "%"],
  ]) {
    const box = node("div", undefined, "metric");
    box.append(node("small", label), node("strong", value));
    $("metrics").append(box);
  }
  const pair = $("pair").value;
  options(
    $("pair"),
    state.pairs,
    state.pairs.includes(pair) ? pair : g.pairs[0],
  );
  options($("trade-pair"), g.pairs, $("trade-pair").value || g.pairs[0]);
  journal($("logs"), selected.logs);
  journal($("recent"), selected.logs.slice(0, 4));
  $("plan").textContent = g.plan || "尚无计划";
  $("notes").textContent = g.notes || "尚无经验笔记";
  const bind = $("binding");
  if (!bind.contains(document.activeElement)) {
    options(
      $("provider"),
      [{ id: "", name: "请选择模型" }, ...state.providers],
      g.provider,
    );
    options(
      $("persona"),
      [{ id: "", name: "请选择人格" }, ...state.personas],
      g.persona,
    );
    const access = state.instance_access || {allow_custom_interval:false,effective_interval:3600};
    const actualInterval = access.effective_interval;
    const unit = actualInterval % 3600 === 0 ? 3600 : actualInterval % 60 === 0 ? 60 : 1;
    bind.elements.interval.disabled = !access.allow_custom_interval;
    $("interval-unit").disabled = !access.allow_custom_interval;
    $("interval-permission-note").textContent = access.allow_custom_interval
      ? "管理员已允许修改，范围10分钟～24小时；与管理员处同步。"
      : "管理员统一设置的间隔；请在设置的用户与权限中修改。";
    $("interval-unit").value = String(unit);
    bind.elements.interval.value = actualInterval / unit;
    bind.elements.interval.min=String(600/unit);
    bind.elements.umo.value = g.reference_umo || g.umo;
    bind.elements.history_count.value = g.history_count ?? 20;
    bind.elements.auto.checked = g.auto;
    const needsInstanceModel=state.llm_settings?.mode!=="custom"&&!state.llm_settings?.provider_id;
    bind.elements.provider.required=needsInstanceModel;
    bind.elements.persona.required=true;
  }
  renderPositions(g, v, selected.market_error);
  renderWatch();
  const lev = $("order-leverage");
  lev.max = g.leverage;
  if (Number(lev.value) > Number(g.leverage)) lev.value = g.leverage;
  $("leverage-hint").textContent =
    `本局上限 ${g.leverage}×；杠杆越高，同样价格波动带来的盈亏越大。`;
  $("deposit").hidden = !g.allow_deposit;
  $("deposit-disabled").hidden = !!g.allow_deposit;
  $("loan-permission").textContent = g.loan_enabled
    ? "本局允许借用虚拟资金"
    : "本局未开启虚拟借款";
  $("loan-info").textContent =
    `待还 $${money(v?.debt || 0)} · 本金上限 $${money(g.loan_limit || Number(g.initial) * 2)} · 日利率 ${(Number(g.loan_rate || 0.0001) * 100).toFixed(2)}%（真实时间）`;
  $("trade")
    .querySelectorAll("button[type=submit]")
    .forEach((b) => (b.disabled = g.status === "ended" || !v));
  $("loan")
    .querySelectorAll("button[type=submit]")
    .forEach(
      (b) =>
        (b.disabled =
          g.status === "ended" || (b.value === "borrow" && !g.loan_enabled)),
    );
  estimate();
  renderChart();
  refreshRequired();
}
function renderChart() {
  if ($("desk").hidden || document.querySelector("[data-page=overview]").hidden)
    return;
  if (!priceChart) priceChart = new HistoryChart($("chart"), bridge);
  const pair = $("pair").value,
    q = state?.current?.quotes[pair];
  if (q) {
    const valid = Date.now() / 1000 - q.timestamp <= 30 && q.tradeable;
    $("quote").replaceChildren(
      node("span", `${q.bid} / ${q.ask}`),
      node(
        "small",
        `${pair} · ${q.source} · ${new Date(q.timestamp * 1000).toLocaleTimeString()} · ${valid ? "有效报价" : "过期或休市"}`,
      ),
    );
  } else $("quote").textContent = "等待有效报价";
  priceChart.setContext(
    state.market_identity,
    pair,
    state.current.quotes,
    state.pairs,
    state.connection.history_source || "frankfurter",
    state.history_feeds || {},
  );
}
$("pair").onchange = () => {
  renderWatch();
  renderChart();
};
$("refresh").onclick = load;
$("decide").onclick = async () => {
  try {
    message("正在提交看盘任务…");
    await post("decision", { game: gid });
    await load();
  } catch {}
};
function renderDecision() {
  const d=state?.decision || {state:"idle",next_allowed:0};
  const active=["pending","running"].includes(d.state);
  const seconds=Math.max(0,Math.ceil(d.next_allowed-Date.now()/1000));
  $("decide").disabled=posting||active||seconds>0;
  $("decide").dataset.permissionDisabled=String(active||seconds>0);
  $("decide").textContent=d.state==="running"?"她正在看盘…":d.state==="pending"?"看盘已排队":seconds>0?`冷却中 ${Math.ceil(seconds/60)} 分钟`:"让她看一次盘";
  $("decision-progress").textContent=d.state==="running"?"正在读取账户、聊天和日志并调用模型。":d.state==="pending"?`等待队列与频率额度${seconds?`，约 ${Math.ceil(seconds/60)} 分钟后可开始`:""}。`:d.state==="failed"?`上次看盘失败：${d.error}`:d.state==="success"?"上次看盘已完成，结果与操作理由已保存。":"点击后异步排队，可在此查看进度和结果。";
  $("decision-result").hidden=!d.last_summary;
  $("decision-summary").textContent=d.last_summary||"";
}
setInterval(()=>{if(state?.current&&gid)renderDecision();},1000);
function submit(id, handler) {
  $(id).onsubmit = async (event) => {
    event.preventDefault();
    try {
      await handler(
        Object.fromEntries(new FormData(event.target)),
        event.submitter,
      );
    } catch (e) {
      if (!e?.noticeShown) tradingNotices.failed(e.message || "操作未完成");
    }
  };
}
submit("trade", async (p, button) => {
  p.side = button?.value || "buy";
  if (!p.reason) p.reason = "人类手动市价单";
  await action("open", p);
});
submit("deposit", async (p) => {
  await action("deposit", { ...p, reason: "人类追加虚拟本金" });
});

function renderWatch() {
  $("watchlist").replaceChildren();
  for (const pair of state.pairs) {
    const q = state.current.quotes[pair],
      b = node("button", undefined, "watch-item");
    b.type = "button";
    b.classList.toggle("active", pair === $("pair").value);
    const a = node("div"),
      right = node("div");
    a.append(
      node("strong", pair),
      node(
        "small",
        `${pairNames[pair]} · ${state.current.game.pairs.includes(pair) ? "可交易" : "仅观察"}`,
      ),
    );
    right.append(
      node(
        "strong",
        q
          ? Number((Number(q.bid) + Number(q.ask)) / 2).toFixed(
              pair.endsWith("/JPY") ? 3 : 5,
            )
          : "—",
      ),
      node("small", q?.tradeable ? "最新中间价" : "等待 / 休市"),
    );
    b.append(a, right);
    b.onclick = () => {
      $("pair").value = pair;
      if (state.current.game.pairs.includes(pair)) $("trade-pair").value = pair;
      renderWatch();
      renderChart();
      estimate();
    };
    $("watchlist").append(b);
  }
}
function renderPositions(g, v, error) {
  const target = $("positions"),
    positions = v?.positions || g.positions;
  if (positions.length <= 3) expandedPositions.delete(g.id);
  target.replaceChildren(
    node("span", "OPEN POSITIONS", "eyebrow"),
    node("h3", `当前持仓 · ${g.positions.length} 笔`),
  );
  target.append(
    node("p", "按未平仓笔数统计，已平仓和被拒绝的操作不计入。", "caption"),
  );
  if (!v)
    target.append(node("p", error || "行情暂不可用，持仓仍保留。", "negative"));
  if (!positions.length)
    target.append(
      node("p", "还没有持仓，选一个货币对开始观察吧。", "position-empty"),
    );
  const overflow = node("div");
  overflow.id = "position-overflow";
  overflow.hidden = !expandedPositions.has(g.id);
  for (const [index, p] of positions.entries()) {
    const card = node("article", undefined, "position-card"),
      head = node("div", undefined, "section-head");
    head.append(
      node(
        "strong",
        `${p.pair} · ${p.side === "buy" ? "做多" : "做空"} · ${p.leverage || g.leverage}×`,
      ),
      node(
        "strong",
        v ? `$${money(p.pnl)}` : "等待估值",
        v ? (Number(p.pnl) >= 0 ? "positive" : "negative") : "caption",
      ),
    );
    card.append(
      head,
      node(
        "p",
        `数量 ${Number(p.units).toLocaleString("en-US", { maximumFractionDigits: 2 })} · 开仓 ${p.entry} · ${v ? "当前 " + p.current : "等待有效报价估值"}`,
        "caption",
      ),
    );
    const row = node("div", undefined, "position-controls"),
      strip = node("div", undefined, "position-track");
    strip.setAttribute("aria-label", "持仓价格位置：开仓、当前与保护线");
    if (v) {
      const levels = [
          Number(p.entry),
          Number(p.current),
          ...["sl", "tp"].filter((k) => p[k]).map((k) => Number(p[k])),
        ],
        min = Math.min(...levels),
        max = Math.max(...levels),
        span = max - min || min * 0.001;
      for (const [label, value, cls] of [
        ["开", p.entry, "entry"],
        ["现", p.current, "current"],
        ["损", p.sl, "stop"],
        ["盈", p.tp, "take"],
      ])
        if (value) {
          const marker = node("span", label, `price-marker ${cls}`);
          marker.style.left = `${8 + ((Number(value) - min) / span) * 84}%`;
          marker.title = `${label} ${value}`;
          strip.append(marker);
        }
    }
    const close = node("button", "平仓");
    close.type = "button";
    close.onclick = () =>
      action("close", { position: p.id, reason: "人类手动平仓" }).catch(
        () => {},
      );
    close.disabled = g.status === "ended" || !v;
    row.append(strip, close);
    card.append(
      row,
      node(
        "p",
        `止损 ${p.sl || "未设置"} · 止盈 ${p.tp || "未设置"}${v ? " · 保证金 $" + money(p.margin) : ""}`,
        "caption",
      ),
    );
    (index < 3 ? target : overflow).append(card);
  }
  if (positions.length > 3) {
    const toggle = node("button", undefined, "positions-toggle");
    toggle.id = "positions-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-controls", overflow.id);
    const update = () => {
      const expanded = expandedPositions.has(g.id);
      overflow.hidden = !expanded;
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.textContent = expanded
        ? "收起其余持仓"
        : `展开其余 ${positions.length - 3} 笔持仓`;
    };
    toggle.onclick = () => {
      if (expandedPositions.has(g.id)) expandedPositions.delete(g.id);
      else expandedPositions.add(g.id);
      update();
    };
    update();
    target.append(overflow, toggle);
  }
  if (v)
    target.append(
      node(
        "p",
        `余额 $${money(g.balance)} · 净值已扣除债务 · 累计交易费 $${money(g.fees)}`,
        "caption",
      ),
    );
}
function estimate() {
  const g = state?.current?.game;
  if (!g) return;
  const form = $("trade"),
    lev = Number($("order-leverage").value),
    pair = $("trade-pair").value,
    q = state.current.quotes[pair];
  $("leverage-value").textContent = `${lev}×`;
  const marginMode = $("order-mode").value === "margin";
  $("margin-label").hidden = !marginMode;
  $("units-label").hidden = marginMode;
  form.elements.margin.disabled = !marginMode;
  form.elements.units.disabled = marginMode;
  let unitUSD = q ? (Number(q.bid) + Number(q.ask)) / 2 : NaN;
  if (pair.startsWith("USD/")) unitUSD = 1;
  const notional = marginMode
    ? Number(form.elements.margin.value) * lev
    : Number(form.elements.units.value) * unitUSD;
  $("order-estimate").replaceChildren(
    node("div", `名义仓位　$${money(notional)}`),
    node("div", `预计保证金　$${money(notional / lev)}`),
    node("div", `预计开仓手续费　$${money(notional * Number(g.fee_rate))}`),
  );
}
$("trade").addEventListener("input", estimate);
$("trade-pair").onchange = estimate;
$("order-mode").onchange = estimate;
$("order-max").onclick = () => {
  const v = state?.current?.valuation,
    g = state?.current?.game;
  if (!v) return;
  $("order-margin").value = Math.max(
    0,
    Math.floor(
      (Number(v.free) /
        (1 + Number($("order-leverage").value) * Number(g.fee_rate) + 0.01)) *
        100,
    ) / 100,
  );
  estimate();
};
submit("loan", async (p, button) =>
  action(button?.value || "borrow", {
    amount: p.amount,
    reason: "人类手动借还虚拟资金",
  }),
);
function sourceFields() {
  const selected = $("market-source").value;
  for (const row of document.querySelectorAll("[data-source]")) {
    row.hidden = row.dataset.source !== selected;
    for (const input of row.querySelectorAll("input"))
      input.disabled = row.hidden;
  }
  $("reset-market-url").hidden = selected === "oanda";
}
$("connection").addEventListener("input", () => {
  connectionDirty = true;
});
$("market-source").addEventListener("change", () => {
  connectionDirty = true;
  sourceFields();
});
$("reset-market-url").onclick = () => {
  const selected = $("market-source").value;
  $("connection").elements[selected + "_url"].value =
    state?.connection?.defaults?.[selected] || "";
  connectionDirty = true;
  $("connection-status").textContent = "已恢复默认地址，保存后生效。";
};
$("test-connection").onclick = async () => {
  const target = $("connection-status");
  target.classList.remove("error");
  target.textContent = "正在从服务器测试当前输入，请稍候…";
  $("test-connection").disabled = true;
  try {
    const result = await post(
      "connection-test",
      Object.fromEntries(new FormData($("connection"))),
    );
    target.textContent =
      result.message +
      " 耗时 " +
      result.latency_ms +
      " ms；本次测试未保存设置。";
  } catch (e) {
    target.textContent = e.message || "连接测试失败";
    target.classList.add("error");
  } finally {
    $("test-connection").disabled = false;
  }
};
$("decision-settings").addEventListener("input",()=>{decisionSettingsDirty=true;});
submit("decision-settings",async(p)=>{
  const form=$("decision-settings"),values={cooldown:Math.round(Number(p.cooldown)*60),hourly_limit:Number(p.hourly_limit)};
  for(const key of ["stop_loss","take_profit","liquidation","margin_call","end"])values[key]=form.elements[key].checked;
  await post("decision-settings",values);decisionSettingsDirty=false;await load();
  $("decision-settings-status").textContent="看盘限频和风险触发设置已保存。";
});
submit("connection", async (p) => {
  await post("settings", p);
  connectionDirty = false;
  $("connection").elements.market_key.value = "";
  $("connection-status").textContent =
    "设置已保存。连通性测试可以随时检查当前服务器的获取结果。";
  await load();
});
sourceFields();
submit("binding", async (p) => {
  if (!gid) throw Error("请先创建游戏");
  await post("command", {
    action: "bind",
    game: gid,
    ...p,
    interval: state.instance_access?.allow_custom_interval ? Math.round(Number(p.interval) * Number($("interval-unit").value)) : state.instance_access?.effective_interval ?? 3600,
    auto: $("binding").elements.auto.checked,
  });
  $("instance-settings-dialog").close();
  await load();
});
submit("create", async (p) => {
  const pairs = [...$("pairs").querySelectorAll("input:checked")].map(
    (o) => o.value,
  );
  if (!pairs.length) throw Error("请至少勾选一个货币对");
  const rules = {};
  for (const k of ["profit", "loss", "floor", "drawdown"])
    if (p[k]) rules[k] = p[k];
  if (p.deadline) rules.deadline = Date.parse(p.deadline) / 1000;
  const result = await post("command", {
    action: "create",
    options: {
      name: p.name,
      persona: p.persona,
      auto: $("create-auto").checked,
      user_binding: collectUserBinding(p),
      user_nickname: p.user_nickname || "",
      initial: p.initial,
      leverage: p.leverage,
      fee_rate: p.fee_rate,
      loan_enabled: $("create-loan-enabled").checked,
      allow_deposit: $("allow-deposit").checked,
      loan_limit: p.loan_limit,
      pairs,
      rules,
    },
  });
  gid = result.id;

  $("create-instance-dialog").close();
  instancePage = "overview";
  workspace("instances");
  await load();
});
let loanLimitEdited = false;
$("loan-limit").addEventListener("input", () => {
  loanLimitEdited = true;
});
$("create").elements.initial.addEventListener("input", () => {
  if (!loanLimitEdited) {
    const initial = Number($("create").elements.initial.value);
    if (initial > 0) $("loan-limit").value = (initial * 2).toFixed(2);
  }
});
$("pairs-all").onclick = () =>
  $("pairs")
    .querySelectorAll("input")
    .forEach((i) => (i.checked = true));
function userBindingFields() {
  const kind = $("user-binding-type").value;
  for (const row of document.querySelectorAll("[data-binding-kind]")) {
    row.hidden = row.dataset.bindingKind !== kind;
    for (const field of row.querySelectorAll("input,textarea")) {
      field.disabled = row.hidden;
      field.required = !row.hidden && kind !== "random";
    }
  }
}
function collectUserBinding(p) {
  const type = p.user_binding_type;
  if (type === "umo")
    return {
      type,
      values: (p.bound_umos || "")
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean),
    };
  if (type === "qq") return { type, values: [(p.bound_qq || "").trim()] };
  return {
    type: "random",
    values: p.bound_random_id?.trim() ? [p.bound_random_id.trim()] : [],
  };
}
$("user-binding-type").onchange = userBindingFields;
userBindingFields();
let pendingDeletion = null;
function openDeleteInstance(instance) {
  pendingDeletion = { id: instance.id, name: instance.name };
  if ($("instance-settings-dialog").open) $("instance-settings-dialog").close();
  $("delete-instance-name").textContent = `确认删除「${instance.name}」？`;
  $("delete-instance-dialog").showModal();
  tradingNotices.setScope("");
}
$("delete-current-instance").onclick = () => {
  if (state?.current?.game) openDeleteInstance(state.current.game);
};
$("confirm-delete-instance").onclick = async () => {
  if (!pendingDeletion) return;
  const target = pendingDeletion;
  $("confirm-delete-instance").disabled = true;
  try {
    await post("command", { action: "delete", game: target.id });
    expandedPositions.delete(target.id);
    tradingNotices.forget(target.id);
    if (gid === target.id) {
      gid = "";
      state.current = null;
    }
    pendingDeletion = null;
    $("delete-instance-dialog").close();
    workspace("instances");
    await load();
  } catch {
  } finally {
    $("confirm-delete-instance").disabled = false;
  }
};
let rotatingUser = null;
let deletingUser = null;
function renderManagedUsers() {
  userManager.render(state.workspace?.users || []);
}
$("generate-user-id").onclick = async () => {
  try {
    await post("command", {
      action: "create_user",
      nickname: $("new-user-nickname").value,
    });
    $("new-user-nickname").value = "";
    await load();
  } catch {}
};
$("confirm-rotate-user").onclick = async () => {
  if (!rotatingUser) return;
  try {
    await post("command", {
      action: "rotate_user_id",
      user_id: rotatingUser.id,
    });
    $("rotate-user-dialog").close();
    rotatingUser = null;
    await load();
  } catch {}
};
function openCreateInstance() {
  options($("create-persona"), [{ id: "", name: "请选择人格" }, ...(state?.personas || [])], "");
  $("create-auto").checked = true;
  $("create-instance-dialog").showModal();
  tradingNotices.setScope("");
}
for (const button of document.querySelectorAll("[data-new-instance]"))
  button.onclick = openCreateInstance;
for (const button of document.querySelectorAll("[data-close-dialog]"))
  button.onclick = () => $(button.dataset.closeDialog).close();
for (const id of [
  "create-instance-dialog",
  "instance-settings-dialog",
  "delete-instance-dialog",
  "rotate-user-dialog",
  "delete-user-dialog",
])
  $(id).addEventListener("close", () => workspace(workspaceMode));
$("open-instance-settings").onclick = () => {
  if (!gid) return;
  $("binding-instance-name").textContent =
    state?.current?.game.name || "当前实例";
  $("instance-settings-dialog").showModal();
  tradingNotices.setScope("");
};
$("interval-unit").addEventListener("change",()=>{
  $("binding").elements.interval.min=String(600/Number($("interval-unit").value));
});
$("confirm-delete-user").onclick=async()=>{
  if(!deletingUser)return;
  try {
    await post("command",{action:"delete_user",user_id:deletingUser.id});
    deletingUser=null;$("delete-user-dialog").close();
    document.activeElement?.blur();await load();
  }catch{}
};
if (bridge) await bridge.ready();
await load();
setInterval(() => {
  if (!document.hidden && !posting) load();
}, 10000);

window.addEventListener("resize", () => requestAnimationFrame(renderChart));

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !posting) load();
});
