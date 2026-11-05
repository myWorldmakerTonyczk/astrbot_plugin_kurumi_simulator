"""Exercise the real standalone portal over local TLS with a disposable ledger."""

import asyncio
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.decisions import DecisionService  # noqa: E402
from src.core.engine import Engine  # noqa: E402
from src.diary.store import DiaryStore  # noqa: E402
from src.portal.server import Portal  # noqa: E402


async def smoke():
    engine = Engine(":memory:")
    game = engine.create({"user_binding": {"type": "umo", "values": ["test:FriendMessage:12345"]}})
    gid, owner = game["id"], game["owner_id"]
    engine.quotes["EUR/USD"] = dict(bid="1.1", ask="1.1002", timestamp=time.time() + 600, tradeable=True)

    async def candles(*args):
        stamp = int(time.time() // 900) * 900
        return {"bars": [{"time": stamp, "open": 1.1, "low": 1.099, "high": 1.102, "close": 1.101}]}

    plugin = SimpleNamespace(engine=engine, settings=lambda: {}, history=SimpleNamespace(page=candles), instance_locks={})
    DecisionService(plugin)
    DiaryStore(engine)
    portal = Portal(plugin)
    portal.accounts.allow_trade(gid, True)
    username, password = await portal.accounts.issue(owner)
    token = portal.access.issue(owner, gid, "summary")
    with TemporaryDirectory() as temp:
        cert, key = Path(temp) / "cert.pem", Path(temp) / "key.pem"
        secret = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(secret.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]), critical=False)
            .sign(secret, hashes.SHA256())
        )
        cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(secret.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        ))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        runner = web.AppRunner(portal.app(), access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls).start()
            origin = "https://127.0.0.1:" + str(runner.addresses[0][1])
            portal.config.update(enabled=True, origin=origin)
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True, channel="msedge")
                context = await browser.new_context(ignore_https_errors=True)
                page = await context.new_page()
                page.set_default_timeout(10000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(origin)
                await page.locator("#portal-login [name=username]").fill(username)
                await page.locator("#portal-login [name=password]").fill(password)
                await page.get_by_role("button", name="登录模拟交易面板").click()
                await page.locator("#portal-tabs:not([hidden])").wait_for()
                await page.locator(".replay-chart canvas").first.wait_for()
                await page.get_by_role("button", name="模拟操作", exact=True).click()
                await page.locator(".desk-order:not([hidden])").wait_for()
                await page.locator(".desk-order [name=units]").fill("1000")
                await page.locator(".desk-order [name=reason]").fill("验证浏览器模拟开仓")
                await page.get_by_role("button", name="提交模拟开仓").click()
                await page.get_by_role("heading", name="当前持仓 · 1 笔").wait_for()
                assert len(engine.get(gid)["positions"]) == 1
                await page.locator(".desk-positions summary").click()
                await page.locator(".desk-positions [name=sl]").fill("1.09")
                await page.locator(".desk-positions [name=reason]").fill("验证网页止损")
                await page.get_by_role("button", name="保存保护线").click()
                await page.get_by_text("止损 1.09 ·", exact=False).wait_for()
                await page.locator(".desk-positions summary").click()
                await page.locator(".desk-positions [name=reason]").fill("验证网页平仓")
                page.once("dialog", lambda dialog: dialog.accept())
                await page.get_by_role("button", name="平仓", exact=True).click()
                await page.get_by_role("heading", name="当前持仓 · 0 笔").wait_for()
                assert not engine.get(gid)["positions"]
                await page.get_by_role("button", name="退出面板").click()
                await page.locator("#portal-login").wait_for()
                await page.goto(origin + "/#share=" + token)
                await page.get_by_role("button", name="打开只读面板").click()
                await page.get_by_text("复盘摘要 · 模拟交易").wait_for()
                await page.locator(".replay-row").first.wait_for()
                assert not await page.locator("#portal-tabs").is_visible()
                assert "share=" not in page.url
                assert not errors, errors
                await browser.close()
        finally:
            await runner.cleanup()
            engine.db.close()


if __name__ == "__main__":
    asyncio.run(smoke())
    print("Portal browser check passed: HTTPS cookies, login, open, protect, close, logout and read-only exchange.")
