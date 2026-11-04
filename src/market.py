"""Read-only selectable quote adapters. Never submits broker orders."""

import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import aiohttp

from .engine import PAIRS, number

DEFAULT_URLS = {
    "biquote": "https://biquote.io/api/latest",
    "sina": "https://hq.sinajs.cn/list=",
}
LABELS = {
    "biquote": "biquote（免注册）",
    "sina": "新浪外汇（免注册）",
    "oanda": "OANDA Practice",
}


def source(settings):
    return settings.get("market_source") or (
        "oanda" if settings.get("market_key") else "biquote"
    )


def endpoint(settings, provider):
    return settings.get(provider + "_url") or DEFAULT_URLS[provider]


def signature(settings):
    provider = source(settings)
    return (
        (provider, settings.get("market_account", ""), settings.get("market_key", ""))
        if provider == "oanda"
        else (provider, endpoint(settings, provider))
    )


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2000 or any(c in url for c in "\r\n"):
        raise ValueError("行情地址格式无效")
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("行情地址须为无账号密码的公开 HTTPS 地址")
    try:
        address = ipaddress.ip_address(p.hostname)
    except ValueError:
        if p.hostname.lower() == "localhost":
            raise ValueError("行情地址不能为本机或内网地址")
    else:
        if not address.is_global:
            raise ValueError("行情地址不能为本机或内网地址")


class PublicResolver(aiohttp.abc.AbstractResolver):
    def __init__(self):
        self.delegate = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        addresses = await self.delegate.resolve(host, port, family)
        if not addresses or any(
            not ipaddress.ip_address(a["host"]).is_global for a in addresses
        ):
            raise OSError("非公网地址")
        return addresses

    async def close(self):
        await self.delegate.close()


def quote(pair, bid, ask, stamp, tradeable, label, now=None):
    now = time.time() if now is None else now
    bid, ask = number(bid), number(ask)
    if bid <= 0 or ask < bid or stamp > now + 5:
        raise ValueError("行情价格或时间无效")
    return dict(
        bid=str(bid),
        ask=str(ask),
        timestamp=stamp,
        received=now,
        tradeable=bool(tradeable and now - stamp <= 30),
        source=label,
    )


def parse_biquote(body, now=None):
    if not isinstance(body, dict):
        raise ValueError("biquote 返回格式无效，批量接口应返回对象")
    updates = {}
    for pair in PAIRS:
        item = body.get(pair.replace("/", ""))
        if not isinstance(item, dict):
            continue
        try:
            stamp = datetime.fromisoformat(
                item["timestamp"].replace("Z", "+00:00")
            ).timestamp()
            updates[pair] = quote(
                pair,
                item["bid"],
                item["ask"],
                stamp,
                item.get("marketState") == "open" and item.get("stale") is False,
                "biquote",
                now,
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return updates


def parse_sina(text, now=None):
    updates = {}
    # Parse data strings only. Never evaluate the provider's JavaScript.
    for name, content in re.findall(
        r'var\s+hq_str_fx_s([a-z]{6})\s*=\s*"([^"]*)"\s*;', text
    ):
        pair = name[:3].upper() + "/" + name[3:].upper()
        fields = content.split(",")
        if pair not in PAIRS or len(fields) < 18:
            continue
        try:
            stamp = (
                datetime.strptime(fields[17] + " " + fields[0], "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone(timedelta(hours=8)))
                .timestamp()
            )
            updates[pair] = quote(
                pair, fields[1], fields[2], stamp, True, "新浪外汇", now
            )
        except (ValueError, OverflowError):
            continue
    return updates


def market_error(exc):
    if isinstance(exc, ValueError):
        return str(exc)[:250]
    if isinstance(exc, TimeoutError):
        return "行情请求超时，请检查服务器到该数据源的网络；可测试另一行情源。"
    if isinstance(exc, aiohttp.ClientSSLError):
        return "行情 HTTPS 证书或TLS连接失败，请检查服务器时间与网络。"
    if isinstance(exc, aiohttp.ClientConnectorError):
        return "行情域名解析或网络连接失败，请检查服务器DNS及出口网络。"
    return "行情响应读取失败，请测试连接并检查接口返回格式。"


class Market:
    def __init__(self, engine):
        self.engine = engine
        self.error = "正在连接行情"
        self.last_success = 0

    async def fetch(self, url, params=None, headers=None):
        validate_url(url)
        connector = aiohttp.TCPConnector(resolver=PublicResolver())
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=15),
            trust_env=False,
        ) as session:
            async with session.get(
                url,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "*/*",
                    **(headers or {}),
                },
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise ValueError(
                        f"行情请求失败（HTTP {response.status}），请检查地址或权限"
                    )
                parts = []
                size = 0
                async for part in response.content.iter_chunked(65536):
                    size += len(part)
                    if size > 1024 * 1024:
                        raise ValueError("行情响应过大")
                    parts.append(part)
                return b"".join(parts)

    async def refresh(self, settings):
        provider = source(settings)
        if provider not in LABELS:
            raise ValueError("未知行情源")
        if provider == "biquote":
            raw = await self.fetch(
                endpoint(settings, provider),
                [("symbols", p.replace("/", "")) for p in PAIRS],
            )
            updates = parse_biquote(json.loads(raw))
        elif provider == "sina":
            url = endpoint(settings, provider)
            symbols = ",".join("fx_s" + p.replace("/", "").lower() for p in PAIRS)
            if url.endswith("list="):
                url += symbols
                params = None
            else:
                params = {"list": symbols}
            try:
                raw = await self.fetch(
                    url, params, {"Referer": "https://finance.sina.com.cn/"}
                )
            except Exception as first_error:
                if endpoint(settings, provider) != DEFAULT_URLS["sina"]:
                    raise
                try:
                    raw = await self.fetch(
                        "https://hq.sinajs.cn/",
                        {"list": symbols},
                        {"Referer": "https://finance.sina.com.cn/"},
                    )
                except ValueError as exc:
                    raise ValueError(
                        "新浪接口拒绝或返回异常："
                        + str(exc)
                        + "；若为HTTP403，可切换biquote。"
                    ) from first_error
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gb18030", errors="replace")
            updates = parse_sina(text)
        else:
            token, account = (
                settings.get("market_key", ""),
                settings.get("market_account", ""),
            )
            if not token or not account:
                raise ValueError("请填写 OANDA Practice 模拟账户和访问令牌")
            if not all(c.isdigit() or c == "-" for c in account):
                raise ValueError("模拟账户ID格式错误")
            raw = await self.fetch(
                f"https://api-fxpractice.oanda.com/v3/accounts/{account}/pricing",
                {"instruments": ",".join(p.replace("/", "_") for p in PAIRS)},
                {"Authorization": "Bearer " + token},
            )
            updates = {}
            for item in json.loads(raw).get("prices", []):
                pair = item["instrument"].replace("_", "/")
                if pair in PAIRS and item.get("bids") and item.get("asks"):
                    stamp = datetime.fromisoformat(
                        item["time"].replace("Z", "+00:00")
                    ).timestamp()
                    updates[pair] = quote(
                        pair,
                        item["bids"][0]["price"],
                        item["asks"][0]["price"],
                        stamp,
                        item.get("status") == "tradeable",
                        "OANDA Practice",
                    )
        if not updates:
            raise ValueError(
                "连接已返回响应，但未取得支持品种的有效行情；请核对接口格式"
            )
        self.engine.quotes.clear()
        self.engine.quotes.update(updates)
        self.error = ""
        self.last_success = time.time()
        return updates


async def probe(settings):
    from types import SimpleNamespace

    started = time.monotonic()
    market = Market(SimpleNamespace(quotes={}))
    updates = await market.refresh(settings)
    fresh = sum(q["tradeable"] for q in updates.values())
    return dict(
        ok=True,
        source=source(settings),
        latency_ms=round((time.monotonic() - started) * 1000),
        pairs=list(updates),
        fresh_count=fresh,
        message=f"连接成功，收到 {len(updates)} 个品种报价，其中 {fresh} 个可用于当前成交。"
        + ("其余可能休市或报价过期。" if fresh < len(updates) else ""),
    )
