import { ReplayPanel } from "./replay-panel.js";

const byId = id => document.getElementById(id);
const status = byId("portal-status");
const share = new URLSearchParams(location.hash.slice(1)).get("share");
if (location.hash) history.replaceState(null, "", location.pathname);
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
  if (!response.ok) throw Error(result.error || "面板请求失败");
  return result;
}

const replay = new ReplayPanel(byId("portal-review"), (game, options) =>
  api("review?" + new URLSearchParams({game, ...options})));

async function start() {
  const session = await api("session");
  const game = session.games?.[0];
  byId("portal-welcome").hidden = !!game;
  byId("portal-logout").hidden = !game;
  byId("portal-review").hidden = !game;
  if (game) {
    byId("portal-title").textContent = game.name;
    setStatus(session.mode === "summary" ? "复盘摘要 · 模拟交易" : "本人只读面板 · 模拟交易");
    replay.open(game.id, game.pairs);
  } else {
    replay.close();
    byId("portal-title").textContent = "她的交易记录";
    setStatus("");
  }
}

byId("portal-logout").onclick = async () => {
  try { await api("logout", {}); location.reload(); }
  catch (error) { setStatus(error.message, true); }
};

if (share) {
  const button = byId("portal-exchange");
  byId("portal-welcome-copy").textContent = "这条链接只能兑换一次，点击后在此浏览器打开。";
  button.hidden = false;
  button.onclick = async () => {
    button.disabled = true;
    try { await api("exchange", {token: share}); await start(); }
    catch (error) { setStatus(error.message, true); }
    finally { button.disabled = false; }
  };
} else {
  start().catch(error => setStatus(error.message, true));
}
