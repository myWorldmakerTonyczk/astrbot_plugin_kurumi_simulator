"""Browser smoke test with explicitly labelled test-only account fixtures."""

import json
import mimetypes
import os
import sys
import time
from io import BytesIO

from PIL import Image
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.engine import Engine, PAIRS
from src.market_data.settings import public_settings
from src.diary.settings import settings as diary_settings
from src.agent.llm import public as llm_public
from src.notifications.settings import validate as notice_defaults
from src.agent.decision_settings import settings as decision_limits
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
engine = Engine(":memory:")
game = engine.create({"name": "小澪的外汇日记（界面测试）"})
engine.quotes["EUR/USD"] = dict(
    bid="1.1000", ask="1.1002", timestamp=time.time(), tradeable=True, source="测试数据"
)
engine.action(
    game["id"],
    "open",
    dict(pair="EUR/USD", side="buy", units="1000", reason="界面自动化测试"),
)
for side in ["buy", "sell"]:
    engine.action(
        game["id"],
        "open",
        dict(pair="EUR/USD", side=side, units="500", reason="多持仓界面测试"),
    )
try:
    engine.action(
        game["id"],
        "open",
        dict(pair="EUR/USD", side="buy", units="-1", reason="验证拒绝状态"),
    )
except ValueError:
    pass
fixture = dict(
    diary_settings=diary_settings(),
    decision_limits=decision_limits(),
    decision=dict(state="idle",next_allowed=0,last_summary="",error=""),
    llm_settings=llm_public(None),
    instance_access=dict(allow_custom_interval=False,effective_interval=3600,allow_panel_notice=True,allow_tool_notice=True,notifications=notice_defaults()),
    games=engine.games(),
    workspace=dict(users=[], mode=dict(multiplayer=True, main_user_id="")),
    current=engine.snapshot(game["id"]),
    pairs=list(PAIRS),
    market_identity="referencefeed",
    history_feeds={"market": "testfeed", "frankfurter": "referencefeed"},
    providers=[dict(id="test", name="测试模型")],
    personas=[dict(id="test", name="测试人格")],
    market_error="",
    runtime_error="",
    connection=public_settings({"history_source": "frankfurter"}),
)
js = """window.fixture=FIXTURE;window.AstrBotPluginView={
 ready:async()=>{},
 apiGet:async(endpoint,params)=>{if(endpoint.includes('?'))throw Error('query in endpoint');
 if(endpoint==='alerts'){
   if(window.deferAlerts&&params.after!==undefined){window.deferAlerts=false;await new Promise(resolve=>window.releaseAlert=resolve);}
   window.alertEvents??=[];window.alertSeq??=100;
   if(params.after===undefined)return {cursor:window.alertSeq,events:[],has_more:false};
   return {cursor:window.alertSeq,events:window.alertEvents.filter(e=>e.id>params.after),has_more:false};
 }
 if(endpoint==='diaries')return {entries:[{day:'2026-11-03',status:'success',content:'今天认真观察了行情，也和你聊了天。'},{day:'2026-11-02',status:'success',content:'复盘上一笔交易。'}],next_before:'2026-11-03'};
 if(endpoint==='journal'){
  window.journalRequest=params;
  const logs=(window.instanceSnapshots?.[params.game]||window.fixture.current).logs;
  return {page:params.page,before:params.before||500,next_page:params.page===1?2:null,logs:logs.slice(0,1)};
 }
 if(endpoint==='review'){
  const t=Math.floor(Date.now()/900000)*900;
  return {pair:params.pair||'EUR/USD',pairs:window.fixture.current.game.pairs,
    pair_stats:window.fixture.current.game.pairs.map((pair,i)=>({pair,fills:i?2:7,net:i?3.5:-8.75})),period:'15m',start:t-86400,end:t+900,warning:'',candles:[
    {time:t-900,open:1.1,high:1.101,low:1.099,close:1.1005},{time:t,open:1.1005,high:1.102,low:1.1,close:1.101}],
    marks:[{time:t-900,equity:10000,return_rate:0,drawdown:0},{time:t,equity:9900,return_rate:-0.75,drawdown:1}],
    events:[
      {id:'job-1',job:1,time:t-1000,bar:t-1800,action:'review',status:'success',actor:'ai',reason:'定时看盘',outcome:'已记录观望',elapsed:6,tools:['state','observe']},
      {id:'log-1',time:t-900,bar:t-900,action:'open',status:'success',actor:'ai',reason:'观察到突破',price:1.1005,fee:.02,position:{id:'p',pair:'EUR/USD',side:'buy',units:1000,sl:'1.099',tp:'1.103'}},
      {id:'log-2',time:t,bar:t,action:'close',status:'success',actor:'system',reason:'触发止盈',price:1.101,fee:.02,position:{id:'p',pair:'EUR/USD',side:'buy',units:1000,pnl:0.5}}],

    diaries:[],baseline:'等待突破'};
 }
 if(endpoint==='history'){
  window.historyRequests??=[];window.historyRequests.push(params);
  const steps={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400,'1w':604800,'1M':2592000},step=steps[params.period];
  const end=params.before?params.before-step:Math.floor(Date.now()/1000/step)*step;
  const bars=Array.from({length:200},(_,i)=>{const value=1.10+Math.sin(i/9)*.001+i*.000003;return {time:end-(199-i)*step,open:value,high:value+.0003,low:value-.0002,close:value+.0001};});
  return {feed:params.history_source==='frankfurter'?'referencefeed':'testfeed',bars,has_more:true,warning:''};
 }const result=structuredClone(window.fixture);if(window.instanceSnapshots?.[params?.game])result.current=structuredClone(window.instanceSnapshots[params.game]);return result;},
 apiPost:async(endpoint,body)=>{window.lastRequest={endpoint,body};
 if(endpoint==='decision'){window.fixture.decision={state:'pending',next_allowed:Date.now()/1000,last_summary:'',error:''};return {ok:true,message:'看盘任务已排队'};}
 if(endpoint==='decision-settings'){window.fixture.decision_limits=body;return {ok:true};}
 if(endpoint==='llm-settings'){window.fixture.llm_settings={...body,key_configured:!!body.api_key,headers_configured:!!body.headers};delete window.fixture.llm_settings.api_key;delete window.fixture.llm_settings.headers;return {ok:true};}
 if(endpoint==='command'&&body.action==='workspace_mode'){window.fixture.workspace.mode={multiplayer:body.multiplayer,main_user_id:body.main_user_id};return {ok:true};}
 if(endpoint==='command'&&body.action==='delete_user'){window.fixture.workspace.users=window.fixture.workspace.users.filter(u=>u.id!==body.user_id);window.fixture.games=window.fixture.games.filter(g=>g.owner_id!==body.user_id);return {ok:true};}
 if(endpoint==='command'&&body.action==='update_user'){const u=window.fixture.workspace.users.find(u=>u.id===body.user_id);u.name=body.nickname;u.policy=body.policy;u.notifications=body.notifications;return {ok:true};}
 if(endpoint==='command'&&body.action==='notifications'){window.fixture.instance_access.notifications=body.settings;return {ok:true};}
 if(endpoint==='diary-settings'){window.fixture.diary_settings=body;return {ok:true};}
 if(endpoint==='command'&&body.action==='create_user'){window.fixture.workspace??={users:[]};const u={id:'managed-user',name:body.nickname||'用户1',public_id:'krm_11111111111111111111'};window.fixture.workspace.users.push(u);return u;}
 if(endpoint==='command'&&body.action==='rotate_user_id'){const u=window.fixture.workspace.users.find(u=>u.id===body.user_id);u.public_id='krm_22222222222222222222';return {ok:true,...u};}
 if(endpoint==='command'&&body.action==='delete'){window.fixture.games=window.fixture.games.filter(g=>g.id!==body.game);if(window.instanceSnapshots)delete window.instanceSnapshots[body.game];return {ok:true,deleted:body.game};}
 if(endpoint==='command'&&body.action==='create')return {id:window.fixture.games[0].id};
 if(endpoint==='command'&&window.failAction){window.failAction=false;const text='可用保证金不足，未成交';window.alertEvents.push({id:++window.alertSeq,title:'操作失败',body:text,level:'danger',request_id:body.request_id});throw Error(text);}
 if(endpoint==='command'&&['borrow','repay','deposit'].includes(body.action)){window.alertEvents.push({id:++window.alertSeq,title:body.action==='deposit'?'虚拟资金已追加':'借还款成功',body:'本次虚拟金额 $'+body.params.amount,level:'success'});}
 if(endpoint==="connection-test"){if(window.failTest)throw Error("测试连接失败");return {ok:true,message:"连接成功，收到6个报价。",latency_ms:123};}return {ok:true};}
};""".replace("FIXTURE", json.dumps(fixture, ensure_ascii=False))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="msedge")
    page = browser.new_page(
        viewport={"width": 1440, "height": 1000}, device_scale_factor=1
    )
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.add_init_script(js)

    def serve(route):
        name = route.request.url.split("kurumi.test/", 1)[1] or "index.html"
        path = root / "views/dashboard" / name
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.endswith(".js"):
            mime = "text/javascript"

        route.fulfill(body=path.read_bytes(), content_type=mime)

    page.route("http://kurumi.test/**", serve)
    page.goto("http://kurumi.test/index.html")
    page.wait_for_selector("#instance-catalog:not([hidden])")
    assert page.locator(".workspace>aside").is_hidden()
    assert page.locator("#instance-nav").is_hidden()
    assert page.locator("#instance-directory").is_visible()
    assert page.locator("#instance-directory .instance-card").count() == 1
    assert page.locator("[data-page=journal]").is_hidden()
    assert page.locator("[data-page=memory]").is_hidden()
    page.locator("#instance-directory .instance-card").first.click()
    page.wait_for_selector("#replay:not([hidden])")
    assert page.locator("#instance-nav button").first.inner_text() == "AI 复盘"
    page.wait_for_selector(".replay-row")
    assert "做多 1 / 做空 0" in page.locator(".replay-pair-mix").inner_text()
    assert "开仓 1 笔 · 平仓 1 笔" in page.locator(".replay-fill-summary").inner_text()
    single_pair = page.get_by_role("navigation", name="复盘货币对")
    assert single_pair.get_by_role("button", name="EUR/USD", pressed=True).is_visible()
    assert page.locator(".replay-current-pair").inner_text() == "EUR/USD"
    assert not page.locator(".replay-market").evaluate("node => node.classList.contains('is-floating')")

    chart_canvases = ".replay-chart canvas"
    page.wait_for_function(
        "(selector) => [...document.querySelectorAll(selector)].some(canvas => canvas.getBoundingClientRect().height >= 240)",
        arg=chart_canvases,
    )
    page.locator(".replay-trade-label").get_by_text("开仓", exact=True).wait_for()
    page.wait_for_function("document.querySelector('.replay-arc-ink')?.getAttribute('d')?.includes(' C ')")
    open_label = page.get_by_role("button", name="开仓", exact=True)
    before_jump = open_label.evaluate("node => node.offsetLeft")
    page.locator(".replay-related").get_by_text("触发止盈", exact=True).click()
    page.wait_for_selector(".replay-event-guide:not([hidden])")
    assert open_label.evaluate("node => node.offsetLeft") == before_jump
    assert "触发止盈" in page.locator(".replay-detail").inner_text()
    with Image.open(BytesIO(page.locator(".replay-chart").screenshot())) as image:
        colors = dict((color, count) for count, color in image.convert("RGB").getcolors(image.width * image.height))
        assert colors.get((22, 130, 117), 0) > 10, "K-line candles are not visible"
        assert colors.get((133, 90, 33), 0) > 4, "System exit marker is not visible"
    performance = page.locator(".replay-performance")
    assert performance.locator(".replay-performance-card").count() == 3
    for value in ("$9,900.00", "-0.75%", "-1.00%"):
        assert value in performance.inner_text()
    assert performance.locator(".replay-performance-chart canvas").count() >= 6
    page.wait_for_function(
        "(selector) => [...document.querySelectorAll(selector)].some(canvas => canvas.getBoundingClientRect().height >= 240)",
        arg=chart_canvases,
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function(
        "(selector) => [...document.querySelectorAll(selector)].some(canvas => canvas.getBoundingClientRect().height >= 200)",
        arg=chart_canvases,
    )
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.locator(".replay-row[data-event=log-1]").click()
    assert "观察到突破" in page.locator(".replay-detail").inner_text()
    assert "等待突破" in page.locator(".replay-detail").inner_text()
    activity = page.get_by_role("region", name="AI 决策活动")
    assert "观望 1" in activity.inner_text()
    activity.get_by_role("button", name="已记录观望", exact=False).click()
    assert "从入队到结束 6 秒" in page.locator(".replay-detail").inner_text()
    assert "记录观望 × 1" in page.locator(".replay-detail").inner_text()
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    floating = page.locator(".replay-market.is-floating")
    out = Path(os.environ.get("KURUMI_SCREENSHOT_DIR", root / "docs/screenshots"))
    out.mkdir(parents=True, exist_ok=True)
    floating.wait_for()
    assert page.locator(".replay-side").evaluate("element => getComputedStyle(element).position") == "sticky"
    page.screenshot(path=str(out / "replay-updated.png"))
    original = floating.bounding_box()
    handle = floating.locator(".replay-chart-top strong").bounding_box()
    page.mouse.move(handle["x"] + 10, handle["y"] + 5)
    page.mouse.down()
    page.mouse.move(handle["x"] - 70, handle["y"] - 45, steps=5)
    page.mouse.up()
    moved = floating.bounding_box()
    assert moved["x"] < original["x"] - 40 and moved["y"] < original["y"] - 25
    floating.get_by_role("button", name="回到图表").click()
    floating.wait_for(state="detached")


    page.get_by_role("button", name="交易工作台", exact=True).click()
    page.evaluate("window.fixture.current.game.pairs = ['EUR/USD', 'GBP/USD']")
    page.locator("#refresh").click()
    page.get_by_role("button", name="AI 复盘", exact=True).click()
    pairs = page.get_by_role("navigation", name="复盘货币对")
    assert "7 次操作" in pairs.get_by_role("button", name="EUR/USD").inner_text()
    assert pairs.locator(".replay-pair[data-sign=loss]").count() == 1
    assert pairs.locator(".replay-pair[data-sign=gain]").count() == 1
    pairs.locator("summary").click()
    assert pairs.get_by_role("button", name="EUR/USD").is_hidden()
    assert pairs.locator(".replay-pair-selection").inner_text() == "EUR/USD"
    pairs.locator("summary").click()
    pairs.get_by_role("button", name="GBP/USD").click()
    page.wait_for_function("document.querySelector('.replay-pair[data-pair=\"GBP/USD\"]').getAttribute('aria-pressed') === 'true'")

    page.get_by_role("button", name="交易工作台", exact=True).click()
    assert page.locator('#pause').count()==0
    page.locator('#decide').click()
    page.wait_for_function("window.lastRequest?.endpoint==='decision'")
    page.wait_for_function("document.querySelector('#decide').textContent.includes('已排队')")
    assert page.locator('#decide').is_disabled()
    page.evaluate("window.fixture.decision={state:'success',next_allowed:Date.now()/1000+600,last_summary:'看盘已完成，保持观望',error:''}")
    page.locator('#refresh').click()
    page.wait_for_function("document.querySelector('#decision-summary').textContent.includes('保持观望')")
    assert page.locator('#decide').is_disabled()
    assert page.locator("#metrics").inner_text().find("当前净值") >= 0
    assert page.locator("#positions").inner_text().find("EUR/USD") >= 0
    assert "当前持仓 · 3 笔" in page.locator("#positions").inner_text()
    assert page.locator(".position-card").count() == 3
    assert "未执行" in page.locator("#recent").inner_text()
    assert page.locator("#chart-type").input_value() == "candles"
    assert page.locator("#chart-period").input_value() == "5m"

    page.wait_for_function(
        "document.querySelector('#chart-status').textContent.includes('201') || document.querySelector('#chart-status').textContent.includes('200')"
    )
    assert page.evaluate("new Set(window.historyRequests.map(x=>x.pair)).size") == 6
    assert page.locator("#chart canvas").count() >= 2
    page.locator("#history-more").click()
    page.wait_for_function("window.historyRequests.some(r=>r.before>0)")
    page.wait_for_function(
        "/40[01]/.test(document.querySelector('#chart-status').textContent)"
    )
    for period in ["1d", "1w", "1M", "5m"]:
        page.locator("#chart-period").select_option(period)
        page.wait_for_function(
            "(period)=>window.historyRequests.some(r=>r.period===period)", arg=period
        )
    for chart_type in ["line", "area", "bars", "candles"]:
        page.locator("#chart-type").select_option(chart_type)
        page.wait_for_timeout(50)
    page.locator("summary").filter(has_text="坐标轴设置").click()
    page.locator("#axis-min").fill("1.098")
    page.locator("#axis-max").fill("1.103")
    page.locator("#axis-apply-y").click()
    page.locator("#axis-auto-y").click()
    page.locator("#axis-mode").select_option("1")
    page.locator("#axis-mode").select_option("0")
    page.locator("#axis-zone").select_option("UTC")
    page.locator("#axis-zone").select_option("Asia/Shanghai")
    page.locator("#axis-from").fill(
        time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() - 3600))
    )
    page.locator("#axis-to").fill(
        time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time()))
    )
    page.locator("#axis-apply-x").click()
    page.wait_for_timeout(100)
    page.locator("#chart-reset").click()
    page.locator("summary").filter(has_text="坐标轴设置").click()
    page.locator("#order-leverage").fill("3")
    page.locator("#order-leverage").dispatch_event("input")
    assert page.locator("#leverage-value").inner_text() == "3×"
    page.locator("#order-margin").fill("100")
    page.get_by_role("button", name="↗ 做多 / 买入", exact=True).click()
    page.wait_for_function('window.lastRequest?.body?.action==="open"')
    assert page.evaluate("window.lastRequest.body.params.side") == "buy"
    assert page.evaluate("window.lastRequest.body.params.margin") == "100"
    assert page.evaluate("window.lastRequest.body.params.leverage") == "3"
    page.evaluate("window.failAction=true")
    page.get_by_role("button", name="↗ 做多 / 买入", exact=True).click()
    page.wait_for_selector("#trade-notice[open]")
    assert "可用保证金不足" in page.locator("#trade-notice-body").inner_text()
    page.locator("#trade-notice button").click()
    page.wait_for_timeout(150)
    assert not page.locator("#trade-notice").is_visible()

    page.locator("#loan input[name=amount]").fill("1000")
    page.get_by_role("button", name="借入虚拟资金", exact=True).click()
    page.wait_for_function('window.lastRequest?.body?.action==="borrow"')
    page.wait_for_selector("#trade-notice[open]")
    assert "1000" in page.locator("#trade-notice-body").inner_text()
    page.locator("#trade-notice button").click()

    page.evaluate("delete window.lastRequest")

    page.get_by_role("button", name="追加本金", exact=True).click()
    assert page.evaluate("window.lastRequest===undefined")  # Native form validation.
    page.locator("#deposit input").fill("2000")
    page.get_by_role("button", name="追加本金", exact=True).click()
    page.wait_for_function('window.lastRequest?.body?.action==="deposit"')
    assert page.evaluate("window.lastRequest.body.params.amount") == "2000"
    page.wait_for_selector("#trade-notice[open]")
    assert "虚拟资金已追加" in page.locator("#trade-notice-title").inner_text()
    page.locator("#trade-notice button").click()

    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(path=str(out / "desktop.png"), full_page=True)
    page.evaluate("window.scrollTo(0,600)")
    assert page.locator("main>header").bounding_box()["y"] >= 0
    assert page.locator("main>header").bounding_box()["y"] < 50
    assert page.locator("header #back-to-catalog").is_visible()
    page.evaluate("window.scrollTo(0,0)")

    page.get_by_role("button", name="交易日志", exact=True).click()
    assert page.locator("#logs").is_visible()
    page.get_by_role("button", name="设置", exact=True).click()
    assert page.locator("#create").is_hidden()
    assert page.locator("#connection").is_hidden()
    assert page.locator("#access-scaffold").is_visible()
    page.locator("#new-user-nickname").fill("测试虚拟用户")
    page.locator("#generate-user-id").click()
    page.wait_for_selector("#managed-users .managed-user")
    assert not page.locator("#managed-users .managed-user").first.evaluate("el=>el.open")
    page.locator("#managed-users .managed-user > summary").first.click()
    old_id = page.locator("#managed-users code").first.inner_text()
    page.locator("#managed-users button").first.click()
    page.wait_for_selector("#rotate-user-dialog[open]")
    page.locator("#confirm-rotate-user").click()
    page.wait_for_function(
        "(old)=>document.querySelector(`#managed-users code`).textContent!==old",
        arg=old_id,
    )
    assert page.locator("#managed-users strong").first.inner_text() == "测试虚拟用户"
    manager=page.locator("#managed-users .managed-user").first
    manager.locator('input[name=nickname]').fill("")
    assert manager.locator('input[name=nickname]').locator('..').locator('.required-indicator').is_visible()
    manager.locator('input[name=nickname]').fill("改过的名字")
    assert manager.locator('input[name=nickname]').locator('..').locator('.required-indicator').is_hidden()
    manager.get_by_role("button",name="保存用户设置").click()
    page.wait_for_function("document.querySelector('#managed-users strong').textContent==='改过的名字'")
    assert page.locator("#managed-users code").first.inner_text() != old_id

    assert page.locator("#binding").is_hidden()
    assert page.locator("header #back-to-catalog").count() == 1
    assert (
        page.evaluate(
            "getComputedStyle(document.querySelector('main>header')).position"
        )
        == "sticky"
    )
    page.locator("#back-to-catalog").click()
    page.get_by_role("button", name="新建实例", exact=True).click()
    page.wait_for_selector("#create-instance-dialog[open]")
    assert page.locator("#create").is_visible()
    assert page.locator("#create-auto").is_checked()
    assert page.locator("#create-persona").input_value() == ""
    assert page.locator("#create-persona").get_attribute("required") is not None
    page.locator("#create-persona").select_option("test")
    assert page.locator("#bound-umos").get_attribute("required") is not None
    assert "/sid" in page.locator("#create-user-fields").inner_text()
    assert page.locator("#user-binding-type, #bound-qq, #bound-random-id").count() == 0
    page.locator("#bound-umos").fill("default:FriendMessage:123456789")
    page.screenshot(path=str(out / "new-instance-dialog.png"), full_page=True)
    assert page.locator("#create [name=leverage]").input_value() == "100"
    assert page.locator("#create #create-loan-enabled").is_checked()
    page.locator("#allow-deposit").uncheck()
    assert page.locator("#loan-limit").input_value() == "20000"
    assert page.locator(".loan-panel input[type=checkbox]").count() == 0

    assert page.locator("#pairs input[type=checkbox]").count() == 6
    page.locator("#pairs input").nth(1).check()
    assert page.locator("#pairs input:checked").count() == 2
    assert "英镑" in page.locator("#pairs").inner_text()
    page.locator("#pairs-all").click()
    assert page.locator("#pairs input:checked").count() == 6
    page.locator("#loan-limit").fill("4321")
    page.locator("#create-loan-enabled").uncheck()
    page.get_by_role("button", name="创建交易实例", exact=True).click()
    page.wait_for_function("window.lastRequest?.body?.action===`create`")
    assert len(page.evaluate("window.lastRequest.body.options.pairs")) == 6
    assert page.evaluate("window.lastRequest.body.options.loan_enabled") is False
    assert page.evaluate("window.lastRequest.body.options.allow_deposit") is False
    assert page.evaluate("window.lastRequest.body.options.loan_limit") == "4321"
    assert page.evaluate("window.lastRequest.body.options.leverage") == "100"
    assert page.evaluate("window.lastRequest.body.options.user_binding.type") == "umo"
    assert (
        page.evaluate("window.lastRequest.body.options.user_binding.values[0]")
        == "default:FriendMessage:123456789"
    )
    page.wait_for_selector("#replay:not([hidden])")
    assert page.locator("#create-instance-dialog").is_hidden()
    page.locator("#open-instance-settings").click()
    page.wait_for_selector("#instance-settings-dialog[open]")
    page.screenshot(path=str(out / "instance-settings-dialog.png"), full_page=True)
    notices=page.locator("#instance-notice-fields")
    assert notices.locator('[name=quiet_start]').input_value() == "00:00"
    assert notices.locator('[name=quiet_end]').input_value() == "07:00"
    assert notices.locator('[name=liquidation]').is_checked()
    assert notices.locator('[name=margin_call]').is_checked()
    assert not notices.locator('[name=use_window]').is_checked()
    notices.locator('[name=use_window]').check()
    page.locator('#instance-notifications button').click()
    page.wait_for_function("window.lastRequest?.body?.action==='notifications'")
    assert page.evaluate("window.lastRequest.body.settings.use_window") is True
    page.evaluate("window.fixture.instance_access.allow_panel_notice=false;document.activeElement.blur();document.querySelector('#refresh').click()")
    page.wait_for_function("document.querySelector('#instance-notifications button').disabled")
    assert notices.locator('[name=enabled]').is_disabled()
    assert page.locator("#binding input[name=interval]").is_disabled()
    assert page.locator("#binding input[name=interval]").input_value() == "1"
    page.evaluate("window.fixture.instance_access.allow_custom_interval=true;document.activeElement.blur();document.querySelector('#refresh').click()")
    page.wait_for_function("!document.querySelector('#binding input[name=interval]').disabled")
    page.locator("#interval-unit").select_option("3600")
    page.locator("#binding input[name=interval]").fill("2")
    page.locator("#binding select[name=provider]").select_option("test")
    page.locator("#binding select[name=persona]").select_option("test")
    page.locator("#binding button[type=submit]").click()
    page.wait_for_function('window.lastRequest?.body?.action==="bind"')
    assert page.evaluate("window.lastRequest.body.interval") == 7200
    page.wait_for_selector("#instance-settings-dialog:not([open])", state="attached")
    page.get_by_role("button", name="设置", exact=True).click()

    assert page.locator(".watch-column .loan-panel").count() == 1
    assert (
        page.evaluate(
            "getComputedStyle(document.querySelector('.workspace>aside')).position"
        )
        == "sticky"
    )

    page.locator('[data-settings-tab="api"]').click()
    assert page.locator("#access-scaffold").is_hidden()
    assert page.locator("#llm-settings").is_visible()
    page.locator('#decision-settings [name=cooldown]').fill('20')
    page.locator('#decision-settings [name=hourly_limit]').fill('3')
    page.locator('#decision-settings [name=stop_loss]').uncheck()
    page.locator('#decision-settings button').click()
    page.wait_for_function("window.lastRequest?.endpoint==='decision-settings'")
    assert page.evaluate("window.lastRequest.body.cooldown")==1200
    assert page.evaluate("window.lastRequest.body.stop_loss") is False
    assert not page.locator('#llm-settings [name=debug_prompt]').is_checked()
    page.locator('#llm-settings [name=debug_prompt]').check()
    page.locator('#llm-settings [name=mode]').select_option("custom")
    page.locator('#llm-settings [name=api_base]').fill("https://example.com/v1")
    page.locator('#llm-settings [name=model]').fill("offline-test")
    page.locator('#llm-settings [name=api_key]').fill("test-secret")
    page.locator('#llm-settings [name=headers]').fill('{"X-Test":"value"}')
    page.locator('#llm-settings button[type=submit]').click()
    page.wait_for_function("window.lastRequest?.endpoint==='llm-settings'")
    assert page.evaluate("window.lastRequest.body.headers['X-Test']") == "value"
    assert page.evaluate("window.lastRequest.body.debug_prompt") is True
    page.wait_for_function("document.querySelector('#llm-settings [name=api_key]').value===''")
    page.locator('#llm-settings [name=mode]').select_option("platform")
    assert page.locator('#llm-settings [name=provider_id]').input_value()==""
    assert page.locator('#llm-settings [data-llm-mode=platform] .required-indicator').is_visible()
    page.locator('#llm-settings [name=provider_id]').select_option("test")
    assert page.locator('#llm-settings [data-llm-mode=platform] .required-indicator').is_hidden()
    page.locator('#llm-settings button[type=submit]').click()
    page.wait_for_function("window.lastRequest?.body?.mode==='platform'")
    assert page.locator("#market-source").input_value() == "biquote"
    assert (
        page.locator("[name=biquote_url]").input_value()
        == "https://biquote.io/api/latest"
    )
    assert page.locator("[name=market_key]").is_hidden()
    page.locator("#market-source").select_option("sina")
    assert page.locator("[name=sina_url]").is_visible()
    assert page.locator("[name=biquote_url]").is_hidden()
    page.locator("[name=sina_url]").fill("https://example.com/list=")
    page.locator("#refresh").click()
    page.wait_for_timeout(150)
    assert page.locator("[name=sina_url]").input_value() == "https://example.com/list="
    page.locator("#reset-market-url").click()
    assert page.locator("[name=sina_url]").input_value() == "https://hq.sinajs.cn/list="
    page.locator("#test-connection").click()
    page.wait_for_function('window.lastRequest?.endpoint==="connection-test"')
    assert page.evaluate("window.lastRequest.body.market_source") == "sina"
    assert page.evaluate("window.lastRequest.body.market_key") is None
    assert "123 ms" in page.locator("#connection-status").inner_text()
    assert page.evaluate("window.fixture.connection.market_source") == "biquote"
    page.screenshot(path=str(out / "connection.png"), full_page=True)
    page.evaluate("window.failTest=true")
    page.locator("#test-connection").click()
    page.wait_for_selector("#connection-status.error")
    page.screenshot(path=str(out / "connection-error.png"), full_page=True)
    page.wait_for_selector("#trade-notice[open]")
    assert "测试连接失败" in page.locator("#trade-notice-body").inner_text()
    page.locator("#trade-notice button").click()

    page.locator("#market-source").select_option("oanda")
    assert page.locator("[name=market_key]").is_visible()
    assert page.locator("#reset-market-url").is_hidden()
    assert (
        page.evaluate(
            "Array.from(document.images).filter(i=>!i.complete||i.naturalWidth===0).length"
        )
        == 0
    )
    page.locator("#back-to-catalog").click()
    page.locator("#instance-directory .instance-card").first.click()
    page.wait_for_selector("#replay:not([hidden])")
    page.get_by_role("button", name="交易工作台", exact=True).click()
    page.wait_for_selector("#desk:not([hidden])")
    page.get_by_role("button", name="计划与经验", exact=True).click()
    page.locator("#diary-refresh").click()
    page.wait_for_function("document.querySelector('#diary-entries').textContent.includes('2026-11-03')")
    assert "今天认真观察" in page.locator("#diary-entries").inner_text()
    page.locator('#diary-entries [data-day="2026-11-02"]').click()
    assert "复盘上一笔交易" in page.locator(".notebook-reader").inner_text()
    page.evaluate("window.fixture.current.game.plan = '【当前状态】EUR/USD 持仓一笔\\n【下一步】等待确认\\n- 复核保护线\\n【风控】不加仓'")
    page.locator("#refresh").click()
    page.wait_for_selector("#plan h4")
    assert page.locator("#plan h4").all_inner_texts() == ["当前状态", "下一步", "风控"]
    assert page.locator("#plan li").inner_text() == "复核保护线"
    page.screenshot(path=str(out / "notebook-updated.png"), full_page=True)
    page.screenshot(path=str(out / "memory.png"), full_page=True)

    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="交易工作台", exact=True).click()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(out / "mobile.png"), full_page=True)
    page.evaluate(
        "window.alertEvents.push({id:++window.alertSeq,title:'模拟强平 / 爆仓提醒',body:'EUR/USD 持仓已强平',level:'danger'})"
    )
    page.locator("#refresh").click()
    page.wait_for_selector("#trade-notice[open]")
    assert "强平" in page.locator("#trade-notice-title").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(out / "notice-mobile.png"), full_page=True)
    page.locator("#trade-notice button").click()
    page.locator("#refresh").click()
    page.wait_for_timeout(100)
    assert not page.locator("#trade-notice").is_visible()
    page.evaluate(
        "for(let i=0;i<2;i++){const p=structuredClone(window.fixture.current.game.positions[0]);p.id='extra'+i;window.fixture.current.game.positions.push(p);const v=structuredClone(window.fixture.current.valuation.positions[0]);v.id=p.id;window.fixture.current.valuation.positions.push(v);}"
    )
    page.locator("#refresh").click()
    page.wait_for_function(
        "document.querySelector('#positions h3').textContent.includes('5 笔')"
    )
    assert page.locator(".position-card:visible").count() == 3
    assert page.locator(".position-controls button").count() == 5
    page.locator("#positions-toggle").click()
    assert page.locator(".position-card:visible").count() == 5
    page.locator("#refresh").click()
    page.wait_for_timeout(100)
    assert page.locator(".position-card:visible").count() == 5
    page.locator("#positions-toggle").click()
    assert page.locator(".position-card:visible").count() == 3
    page.locator("#chart-period").select_option("1d")
    page.locator("#chart-type").select_option("line")
    page.wait_for_function(
        "window.historyRequests.some(r=>r.period==='1d'&&r.history_source==='frankfurter')"
    )
    assert "Frankfurter" in page.locator("#history-kind").inner_text()
    assert not page.evaluate(
        "Array.from(document.getElementById(`chart-period`).options).some(o=>o.disabled)"
    )
    assert not page.evaluate(
        "Array.from(document.getElementById(`chart-type`).options).some(o=>o.disabled)"
    )
    page.locator("#chart-type").select_option("candles")
    page.locator("#chart-period").select_option("1m")
    page.wait_for_function(
        "window.historyRequests.some(r=>r.period==='1m'&&r.history_source==='market')"
    )
    assert "真实行情源" in page.locator("#history-kind").inner_text()
    page.locator("#chart-period").select_option("5m")
    page.evaluate(
        "window.fixture.current.valuation=null;window.fixture.current.market_error='行情过期'"
    )
    page.locator("#refresh").click()
    page.wait_for_function(
        "document.querySelector('#positions').textContent.includes('等待有效报价')"
    )
    assert "当前持仓 · 5 笔" in page.locator("#positions").inner_text()

    page.set_viewport_size({"width": 1440, "height": 1000})
    page.evaluate("""(()=>{
      const base=structuredClone(window.fixture.current), first=base.game.id;
      window.fixture.workspace={mode:{multiplayer:true,main_user_id:'alice'},users:[{id:'alice',name:'用户甲'},{id:'bob',name:'用户乙'}]};
      window.instanceSnapshots={};
      const scopes=[[first,'alice','甲的第一盘','第一盘独立经验'],['alice-two','alice','甲的第二盘','第二盘独立经验'],['bob-one','bob','乙的第一盘','乙的独立经验']];
      window.fixture.games=[];
      for(const [id,owner,name,notes]of scopes){const snap=structuredClone(base);Object.assign(snap.game,{id,owner_id:owner,name,notes,plan:name+'计划'});snap.logs=[{id:1,created:Date.now()/1000,source:'human',action:'observe',status:'success',reason:name+'专属日志',detail:{}}];window.instanceSnapshots[id]=snap;window.fixture.games.push(snap.game);}
    })()""")
    page.locator("#refresh").click()
    page.locator("#back-to-catalog").click()
    page.wait_for_selector("#instance-catalog:not([hidden])")
    assert page.locator(".workspace>aside").is_hidden()
    assert page.locator("#instance-nav").is_hidden()
    assert page.locator(".user-instance-group").count() == 2
    assert page.locator("#instance-directory .instance-card").count() == 3
    page.get_by_role("button", name="设置", exact=True).click()
    page.locator('[data-settings-tab="users"]').click()
    mode = page.locator("#workspace-mode-settings")
    mode.locator('[name="multiplayer"]').uncheck()
    mode.get_by_role("button", name="保存用户模式").click()
    page.wait_for_function("window.fixture.workspace.mode.multiplayer === false")
    assert page.locator("#multi-user-controls").is_hidden()
    assert "主用户" in page.locator("#managed-users").inner_text()
    assert page.locator("#managed-users .managed-user").count() == 1
    page.locator("#back-to-catalog").click()
    assert page.locator("#instance-directory .instance-card").count() == 2
    assert page.locator('.instance-card[data-instance-id="bob-one"]').count() == 0
    page.get_by_role("button", name="设置", exact=True).click()
    page.locator('[data-settings-tab="users"]').click()
    mode.locator('[name="multiplayer"]').check()
    mode.get_by_role("button", name="保存用户模式").click()
    page.wait_for_function("window.fixture.workspace.mode.multiplayer === true")
    page.locator("#back-to-catalog").click()
    assert page.locator("#instance-directory .instance-card").count() == 3
    alice = page.locator(".user-instance-group[data-owner-id=alice]")
    assert alice.locator(".instance-card").count() == 2
    alice.locator("summary").click()
    page.locator("#refresh").click()
    page.wait_for_timeout(100)
    assert not alice.evaluate("(el)=>el.open")
    alice.locator("summary").click()
    history_count_before=page.evaluate("window.historyRequests.length")
    page.locator('.instance-card[data-instance-id="alice-two"]').click()
    page.wait_for_function(
        "document.querySelector('#title').textContent==='甲的第二盘'"
    )
    assert page.locator("#instance-nav").is_visible()
    assert page.evaluate("window.historyRequests.length")==history_count_before
    page.get_by_role("button", name="计划与经验", exact=True).click()
    assert page.locator("#plan").inner_text() == "甲的第二盘计划"
    page.locator("#notes").locator("..").locator("summary").click()
    assert page.locator("#notes").inner_text() == "第二盘独立经验"
    assert page.locator(".global-experience-placeholder button").is_disabled()
    page.get_by_role("button", name="交易日志", exact=True).click()
    assert "甲的第二盘专属日志" in page.locator("#logs").inner_text()
    assert "乙的第一盘专属日志" not in page.locator("#logs").inner_text()
    page.locator('#journal-filters [name="source"]').select_option("human")
    page.wait_for_function("window.journalRequest?.source === 'human'")
    page.locator("#journal-next").click()
    page.wait_for_function("window.journalRequest?.page === 2 && window.journalRequest?.before === 500")
    assert "第 2 页" in page.locator("#journal-status").inner_text()
    page.screenshot(path=str(out / "journal-updated.png"), full_page=True)
    page.locator("#back-to-catalog").click()
    page.wait_for_selector("#instance-catalog:not([hidden])")
    assert page.locator("#instance-nav").is_hidden()
    page.locator('.instance-card[data-instance-id="bob-one"]').click()
    page.wait_for_function(
        "document.querySelector('#title').textContent==='乙的第一盘'"
    )
    assert page.locator("#replay").is_visible()
    page.get_by_role("button", name="交易日志", exact=True).click()
    assert "乙的第一盘专属日志" in page.locator("#logs").inner_text()
    page.get_by_role("button", name="设置", exact=True).click()
    assert page.locator("#instance-nav").is_hidden()
    assert page.locator("#settings-nav").is_visible()
    page.locator('[data-settings-tab="users"]').click()
    assert page.locator("#access-scaffold").is_visible()
    assert "聊天工具按用户归属隔离" in page.locator("#access-scaffold").inner_text()
    page.screenshot(path=str(out / "workspace-settings.png"), full_page=True)
    page.locator("#back-to-catalog").click()
    assert page.locator("#instance-nav").is_hidden()
    assert page.locator("#instance-catalog").is_visible()
    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(path=str(out / "workspace-catalog.png"), full_page=True)
    page.evaluate(
        "window.alertEvents.push({id:++window.alertSeq,title:'目录期间提醒',body:'不应在目录弹出',level:'danger'})"
    )
    page.locator("#refresh").click()
    page.wait_for_timeout(150)
    assert not page.locator("#trade-notice").is_visible()

    page.locator('.instance-card[data-instance-id="bob-one"]').click()
    page.wait_for_selector("#replay:not([hidden])")
    page.get_by_role("button", name="交易工作台", exact=True).click()
    page.wait_for_selector("#desk:not([hidden])")
    page.screenshot(path=str(out / "workspace-instances.png"), full_page=True)
    page.wait_for_timeout(100)
    assert not page.locator("#trade-notice").is_visible()
    page.evaluate("window.deferAlerts=true;delete window.releaseAlert")
    page.locator("#refresh").click()
    page.wait_for_function("typeof window.releaseAlert===`function`")
    page.locator("#back-to-catalog").click()
    page.evaluate(
        "window.alertEvents.push({id:++window.alertSeq,title:'旧实例延迟强平',body:'退出后不应显示',level:'danger'});window.releaseAlert()"
    )
    page.wait_for_timeout(150)
    assert page.locator("#instance-catalog").is_visible()
    assert not page.locator("#trade-notice").is_visible()

    page.locator("#back-to-catalog").click()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert page.locator(".workspace>aside").is_hidden()
    page.screenshot(path=str(out / "workspace-catalog-mobile.png"), full_page=True)
    page.locator('.delete-instance[data-instance-id="bob-one"]').click()
    page.wait_for_selector("#delete-instance-dialog[open]")
    assert "乙的第一盘" in page.locator("#delete-instance-name").inner_text()
    page.locator("[data-close-dialog=delete-instance-dialog]").click()
    assert page.locator(".instance-card").count() == 3
    page.locator('.delete-instance[data-instance-id="bob-one"]').click()
    page.locator("#confirm-delete-instance").click()
    page.wait_for_function("window.lastRequest?.body?.action===`delete`")
    page.wait_for_function("document.querySelectorAll(`.instance-card`).length===2")
    assert page.locator('.instance-card[data-instance-id="alice-two"]').count() == 1
    assert page.locator('.instance-card[data-instance-id="bob-one"]').count() == 0
    page.evaluate(
        "window.fixture.games=[];window.fixture.current=null;window.instanceSnapshots={};"
        "window.fixture.workspace={mode:{multiplayer:true,main_user_id:'managed-user'},users:[{id:'managed-user',name:'测试用户',public_id:'krm_11111111111111111111'}]}"
    )
    page.locator("#refresh").click()
    page.wait_for_selector("#empty:not([hidden])")
    assert "给她一笔资金，看看故事会怎样。" in page.locator("#empty").inner_text()
    user_create = page.locator("#instance-directory .user-create-instance").first
    user_create.click()
    assert page.locator("#create-owner").is_visible()
    assert page.locator("#create-user-fields").is_hidden()
    page.locator("[data-close-dialog=create-instance-dialog]").click()
    assert page.locator(".workspace>aside").is_hidden()
    page.screenshot(path=str(out / "workspace-welcome.png"), full_page=True)
    page.get_by_role("button", name="创建第一局", exact=True).click()
    assert page.locator("#create-instance-dialog").is_visible()
    assert page.locator("#create").is_visible()
    page.locator("[data-close-dialog=create-instance-dialog]").click()
    assert page.locator("#create-instance-dialog").is_hidden()
    assert page.locator("#binding").is_hidden()
    page.locator("#workspace-settings").click()
    page.locator('[data-settings-tab="diary"]').click()
    assert page.locator("#access-scaffold").is_hidden()
    assert page.locator("#connection").is_hidden()
    page.locator("#diary-settings [name=min_logs]").fill("4")
    page.locator("#diary-settings [name=chat_only]").check()
    page.locator("#diary-settings button[type=submit]").click()
    page.wait_for_function("window.lastRequest?.endpoint==='diary-settings'")
    assert page.evaluate("window.lastRequest.body.min_logs") == 4
    assert page.evaluate("window.lastRequest.body.chat_only") is True
    assert "已保存" in page.locator("#diary-settings-status").inner_text()
    page.locator('[data-settings-tab="users"]').click()
    managed=page.locator('#managed-users .managed-user').first
    if not managed.evaluate("el=>el.open"): managed.locator(':scope > summary').click()
    count_before=page.locator('#managed-users .managed-user').count()
    managed.get_by_role('button',name='删除用户',exact=True).click()
    assert page.locator('#delete-user-dialog').is_visible()
    page.locator('[data-close-dialog="delete-user-dialog"]').click()
    assert page.locator('#managed-users .managed-user').count()==count_before
    managed.get_by_role('button',name='删除用户',exact=True).click()
    page.locator('#confirm-delete-user').click()
    page.wait_for_function("window.lastRequest?.body?.action==='delete_user'")
    page.wait_for_function("(count)=>document.querySelectorAll('#managed-users .managed-user').length===count-1",arg=count_before)
    assert not errors, errors
    print(
        "Chart checks: initial 200, older paging, six pairs, daily/weekly/monthly, all chart types, leverage, margin order and virtual loan payloads."
    )
    browser.close()
engine.db.close()
print(
    "Browser smoke passed: desktop/mobile, tabs, form validation, deposit payload, three quote sources, custom URL preservation, defaults, isolated probe, artwork loading, no page errors."
)
