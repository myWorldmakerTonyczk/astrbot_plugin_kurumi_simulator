import { ReplayPanel } from "./replay-panel.js";
import { PortalTrading } from "./portal-trading.js";

const byId = id => document.getElementById(id);
const status = byId("portal-status");
const setStatus = (message, error = false) => {
  status.textContent = message;
  status.dataset.error = String(error);
};

async function api(path, body) {
  const response = await fetch("/api/" + path, {
    credentials: "same-origin",
    ...(body === undefined ? {} : {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    }),
  });
  const result = await response.json();
  if (!response.ok) {
    const error = Error(result.error || "面板请求失败");
    error.http = response.status < 500;
    throw error;
  }
  return result;
}

const replay = new ReplayPanel(byId("portal-review"), (game, options) =>
  api("review?" + new URLSearchParams({game, ...options})));
const desk = new PortalTrading(byId("portal-trading"), api);
const records = byId("portal-records");
let recordRequest = 0;
const instanceSelect = byId("portal-instance");
let session = null;
let activePage = "review";

function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}

const actions = {open: "开仓", close: "平仓", protect: "调整保护线", plan: "更新计划",
  observe: "观望", analysis: "看盘", deposit: "追加本金", borrow: "借入资金",
  repay: "偿还借款", update_pairs: "调整货币对", margin_call: "保证金不足",
  end: "本局结束", start: "开始游戏", pause: "暂停", resume: "恢复"};
const actors = {ai: "AI", human: "人类", system: "系统"};
const dates = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium",
});

async function showRecords(page, game, options = {}) {
  const request = ++recordRequest;
  const journal = page === "journal";
  const title = element("h2", journal ? "交易日志" : "计划与经验");
  const controls = document.createElement("div");
  controls.className = "portal-record-controls";
  if (journal) {
    const filter = document.createElement("select");
    filter.setAttribute("aria-label", "筛选交易日志");
    filter.replaceChildren(...[["all", "全部记录"], ["operations", "实际操作"],
      ["fills", "仅成交"], ["rejected", "未执行"]].map(([value, label]) => new Option(label, value)));
    filter.value = options.filter || "all";
    filter.onchange = () => showRecords(page, game, {filter: filter.value});
    controls.append(filter);
  }
  const content = element("div", "正在读取…");
  content.className = "portal-record-body";
  records.dataset.page = page;
  records.replaceChildren(title, controls, content);
  try {
    const data = await api(page + "?" + new URLSearchParams({game, ...options}));
    if (request !== recordRequest) return;
    content.replaceChildren();
    if (journal) {
      for (const row of data.logs) {
        const item = document.createElement("article");
        item.append(element("small", dates.format(row.time * 1000) + " · " + (actors[row.source] || row.source)),
          element("h3", (actions[row.action] || row.action) + (row.status === "rejected" ? " · 未执行" : "")));
        if (row.reason) item.append(element("p", row.reason));
        content.append(item);
      }
      if (!data.logs.length) content.append(element("p", "没有符合条件的日志。"));
      for (const [label, next] of [["上一页", data.page > 1 ? data.page - 1 : null], ["下一页", data.next_page]]) {
        const button = element("button", label);
        button.disabled = !next;
        button.onclick = () => showRecords(page, game, {...options, before: data.before, page: next});
        controls.append(button);
      }
    } else {
      const plan = document.createElement("article");
      plan.append(element("h3", "当前交易计划"), element("p", data.plan || "她还没有写下交易计划。"));
      const diary = document.createElement("article");
      diary.append(element("h3", "交易日记"));
      for (const [index, entry] of data.diaries.entries()) {
        const details = document.createElement("details");
        details.open = index === 0;
        details.append(element("summary", entry.day), element("p", entry.content));
        diary.append(details);
      }
      if (!data.diaries.length) diary.append(element("p", "她还没有写好日记。"));
      content.append(plan, diary);
    }
  } catch (error) {
    if (request === recordRequest) content.textContent = error.message;
  }
}

function showPage(page) {
  recordRequest++;
  const game = session?.games?.find(item => item.id === instanceSelect.value);
  if (!game) return;
  if (session.mode === "summary" || (page === "trading" && session.mode !== "account")) page = "review";
  activePage = page;
  byId("portal-title").textContent = game.name;
  for (const button of document.querySelectorAll("[data-portal-page]")) {
    button.hidden = session.mode === "summary" && button.dataset.portalPage !== "review"
      || session.mode !== "account" && button.dataset.portalPage === "trading";
    button.setAttribute("aria-pressed", String(button.dataset.portalPage === page));
  }
  byId("portal-review").hidden = page !== "review";
  records.hidden = page !== "journal" && page !== "notebook";
  if (page === "review") replay.open(game.id, game.pairs);
  else replay.close();
  if (page === "trading") desk.open(game.id);
  else desk.close();
  if (!records.hidden) showRecords(page, game.id);
}

async function start() {
  session = await api("session");
  const games = session.games || [];
  byId("portal-welcome").hidden = session.authenticated;
  byId("portal-logout").hidden = !session.authenticated;
  byId("portal-tabs").hidden = session.mode !== "account" || !games.length;
  byId("portal-sidebar").hidden = !games.length;
  byId("portal-banner").hidden = !games.length;
  byId("portal-review").hidden = !games.length;
  records.hidden = true;
  instanceSelect.replaceChildren(...games.map(game => new Option(game.name, game.id)));
  if (games.length) {
    const modes = {summary: "复盘摘要", read: "本人只读面板", account: "已登录用户面板"};
    setStatus("账户已同步 · " + modes[session.mode] + " · 所有金额均为虚拟资金");
    showPage("review");
  } else {
    replay.close();
    desk.close();
    byId("portal-title").textContent = "她的交易记录";
    setStatus(session.authenticated ? "此账号没有可用实例。" : "");
  }
}

instanceSelect.onchange = () => showPage(activePage);
for (const button of document.querySelectorAll("[data-portal-page]")) {
  button.onclick = () => showPage(button.dataset.portalPage);
}

byId("portal-login").onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = event.submitter;
  button.disabled = true;
  try {
    const credentials = Object.fromEntries(new FormData(form));
    await api("login", credentials);
    form.reset();
    await start();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
};

byId("portal-logout").onclick = async () => {
  try { await api("logout", {}); location.reload(); }
  catch (error) { setStatus(error.message, true); }
};

function handleShare() {
  const share = new URLSearchParams(location.hash.slice(1)).get("share");
  if (location.hash) history.replaceState(null, "", location.pathname);
  if (!share) return false;
  replay.close();
  desk.close();
  recordRequest++;
  records.hidden = true;
  byId("portal-sidebar").hidden = true;
  byId("portal-banner").hidden = true;
  byId("portal-review").hidden = true;
  byId("portal-tabs").hidden = true;
  byId("portal-welcome").hidden = false;
  byId("portal-logout").hidden = true;
  const button = byId("portal-exchange");
  byId("portal-welcome-copy").textContent = "这条链接只能兑换一次，点击后在此浏览器打开。";
  byId("portal-login").hidden = true;
  button.hidden = false;
  button.onclick = async () => {
    button.disabled = true;
    try { await api("exchange", {token: share}); await start(); }
    catch (error) { setStatus(error.message, true); }
    finally { button.disabled = false; }
  };
  return true;
}

window.addEventListener("hashchange", handleShare);
if (!handleShare()) start().catch(error => setStatus(error.message, true));
