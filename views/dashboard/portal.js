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
const instanceSelect = byId("portal-instance");
let session = null;
let activePage = "review";

function showPage(page) {
  activePage = page;
  const game = session?.games?.find(item => item.id === instanceSelect.value);
  if (!game) return;
  byId("portal-title").textContent = game.name;
  const operations = page === "trading" && session.mode === "account";
  byId("portal-review").hidden = operations;
  for (const button of document.querySelectorAll("[data-portal-page]")) {
    button.setAttribute("aria-pressed", String(button.dataset.portalPage === page));
  }
  if (operations) {
    replay.close();
    desk.open(game.id);
  } else {
    desk.close();
    replay.open(game.id, game.pairs);
  }
}

async function start() {
  session = await api("session");
  const games = session.games || [];
  byId("portal-welcome").hidden = session.authenticated;
  byId("portal-logout").hidden = !session.authenticated;
  byId("portal-tabs").hidden = session.mode !== "account" || !games.length;
  byId("portal-review").hidden = !games.length;
  instanceSelect.replaceChildren(...games.map(game => new Option(game.name, game.id)));
  if (games.length) {
    const modes = {summary: "复盘摘要", read: "本人只读面板", account: "已登录用户面板"};
    setStatus(modes[session.mode] + " · 模拟交易");
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
