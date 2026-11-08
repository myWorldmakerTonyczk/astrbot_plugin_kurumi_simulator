"""Render bounded, mobile-readable PNGs from the shared replay projection."""

from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

CHARTS = {
    "diary": ("交易日记", "Trading diary"),
    "text": ("文字记录", "Notes"),
    "overview": ("账户表现总览", "Account performance overview"),
    "candles": ("K 线与成交", "Candles and fills"),
    "equity": ("账户净值", "Account equity"),
    "return": ("资金调整后收益率", "Cash-flow-adjusted return"),
    "drawdown": ("回撤曲线", "Drawdown"),
    "activity": ("AI 看盘活动", "AI review activity"),
    "realized": ("累计平仓盈亏扣成交费", "Cumulative realized P/L less fill fees"),
    "trades": ("单笔平仓盈亏", "P/L per close, before fees"),
    "fees": ("累计成交手续费", "Cumulative fill fees"),
}

PAPER = "#f7faf6"
INK = "#243735"
MUTED = "#526b62"
GRID = "#d8e5da"
TEAL = "#167e73"
ROSE = "#ae4761"
GOLD = "#8a6027"
BLUE = "#315da4"
CURVES = {"equity", "return", "drawdown", "realized", "fees"}
ZONE = ZoneInfo("Asia/Shanghai")
OVERVIEW_PANELS = ("equity", "return", "drawdown")
WIDE_PANELS = {"candles", "activity", "diary", "text"}
CHART_SIZE = (1120, 645)


def fonts():
    for path in (
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ):
        if Path(path).is_file():
            try:
                return [ImageFont.truetype(path, size) for size in (38, 22, 17)], True
            except OSError:
                continue
    return [ImageFont.load_default(size=size) for size in (38, 22, 17)], False


def series(data, kind):
    """Return time, value, color; financial events are scoped to the selected pair."""
    if kind in {"equity", "return", "drawdown"}:
        field = {"equity": "equity", "return": "return_rate", "drawdown": "drawdown"}[kind]
        return [(row["time"], -row[field] if kind == "drawdown" else row[field],
                 {"equity": TEAL, "return": BLUE, "drawdown": ROSE}[kind]) for row in data["marks"]]
    if kind == "activity":
        buckets = defaultdict(lambda: [0, 0, 0])
        step = 3600 if data["days"] == 1 else 86400
        for row in data["events"]:
            if row["action"] != "review":
                continue
            index = {"success": 0, "failed": 1}.get(row["status"], 2)
            buckets[(int(row["time"]) - data["start"]) // step * step + data["start"]][index] += 1
        return [(stamp, values, TEAL) for stamp, values in sorted(buckets.items())]
    total, points = 0.0, []
    for row in data["events"]:
        if row.get("price") is None:
            continue
        pnl = float(row["position"].get("pnl", 0))
        if kind == "trades":
            if row["action"] == "close":
                points.append((row["time"], pnl, TEAL if pnl >= 0 else ROSE))
        else:
            total += row["fee"] if kind == "fees" else pnl - row["fee"]
            points.append((row["time"], total, GOLD if kind == "fees" else TEAL))
    return points


def render_png(data, kind):
    if kind not in CHARTS:
        raise ValueError("图表类型无效")
    if kind in {"diary", "text"}:
        return render_text_png(data["text_panels"][kind])
    if kind == "overview":
        width, height = CHART_SIZE
        image = Image.new("RGB", (width, height * len(OVERVIEW_PANELS)), PAPER)
        for index, panel in enumerate(OVERVIEW_PANELS):
            with Image.open(BytesIO(render_png(data, panel))) as chart:
                image.paste(chart, (0, height * index))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    image = Image.new("RGB", CHART_SIZE, PAPER)
    draw = ImageDraw.Draw(image)
    (heading, body, small), zh = fonts()

    def label(x, y, text, font=small, color=INK, anchor=None):
        draw.text((x, y), text, fill=color, font=font, anchor=anchor)

    def time_label(t, fmt):
        return datetime.fromtimestamp(t, ZONE).strftime(fmt)

    pair = data["pair"]
    points = series(data, kind) if kind != "candles" else []
    bars = data["candles"] if kind == "candles" else []
    start, end = data["start"], data["end"]
    if points and (kind in CURVES or kind == "trades"):
        start, end = points[0][0], points[-1][0]
    axis_start, axis_end = (start, end) if start < end else (start - 60, end + 60)
    label(38, 25, CHARTS[kind][0 if zh else 1], heading)
    scoped = kind in {"candles", "realized", "trades", "fees"}
    subtitle = (pair + "   |   " if scoped else "") + time_label(start, "%m-%d %H:%M")
    if end != start:
        subtitle += " - " + time_label(end, "%m-%d %H:%M")
    subtitle += "   UTC+8"
    label(40, 82, subtitle, body, MUTED)
    draw.line((40, 122, 1080, 122), fill=GRID, width=2)

    values = ([v for bar in bars for v in (bar["low"], bar["high"])] if bars else
              [sum(value) if kind == "activity" else value for _, value, _ in points])
    if not values:
        label(560, 318, "这个时段暂无可绘制的记录" if zh else "No records in this time range", body, MUTED, "mm")
    else:
        left, top, right, bottom = 122, 159, 1074, 532
        lo, hi = min(values), max(values)
        if kind in {"activity", "trades", "drawdown", "realized", "fees"}:
            lo, hi = min(0, lo), max(0, hi)
        pad = (hi - lo) * .08 or max(abs(lo) * .005, .0001)
        lo, hi = lo - pad, hi + pad

        def x(t):
            return left + (right - left) * (min(axis_end, max(t, axis_start)) - axis_start) / (axis_end - axis_start)

        def y(v):
            return bottom - (bottom - top) * (v - lo) / (hi - lo)

        for i in range(5):
            value = lo + (hi - lo) * i / 4
            yy = y(value)
            draw.line((left, yy, right, yy), fill=GRID)
            if kind == "candles":
                tick = f"{value:.{3 if pair.endswith('JPY') else 5}f}"
            elif kind in {"return", "drawdown"}:
                tick = f"{value:.2f}%"
            elif kind == "activity":
                tick = f"{value:.1f}"
            else:
                tick = f"{value:,.2f}"
            label(left - 8, yy, tick, small, MUTED, "rm")
        span = axis_end - axis_start
        tick_format = "%H:%M:%S" if span < 240 else "%H:%M" if span < 86400 else "%m-%d %H:%M" if span < 172800 else "%m-%d"
        for i in range(5):
            t = axis_start + span * i / 4
            xx = x(t)
            draw.line((xx, top, xx, bottom), fill=GRID)
            label(xx, bottom + 13, time_label(t, tick_format), small, MUTED, "mt")

        if bars:
            width = max(2, min(9, (right - left) / max(20, len(bars)) * .35))
            for bar in bars:
                xx = x(bar["time"])
                first, last = y(bar["open"]), y(bar["close"])
                color = TEAL if last <= first else ROSE
                draw.line((xx, y(bar["high"]), xx, y(bar["low"])), fill=color, width=2)
                draw.rectangle((xx - width, min(first, last), xx + width, max(first, last, min(first, last) + 1)), fill=color)
            for event in data["events"]:
                price = event.get("price")
                if price is None:
                    continue
                xx, yy = x(event["time"]), min(bottom, max(top, y(price)))
                color = GOLD if event["actor"] == "system" else INK
                if event["action"] == "close":
                    draw.ellipse((xx - 6, yy - 6, xx + 6, yy + 6), fill=color, outline=PAPER, width=2)
                else:
                    direction = -1 if event["position"]["side"] == "buy" else 1
                    draw.polygon([(xx, yy + direction * 8), (xx - 7, yy - direction * 5),
                                  (xx + 7, yy - direction * 5)], fill=color, outline=PAPER)
        elif kind in {"activity", "trades"}:
            width = min(14, (right - left) / max(20, len(points)) / 3)
            for t, value, color in points:
                xx = x(t)
                if kind == "activity":
                    base = 0
                    for count, tint in zip(value, (TEAL, ROSE, GOLD)):
                        if count:
                            draw.rectangle((xx - width, y(base + count), xx + width, y(base)), fill=tint)
                        base += count
                else:
                    draw.rectangle((xx - width, min(y(0), y(value)), xx + width, max(y(0), y(value))), fill=color)
        else:
            coords = [(x(t), y(value)) for t, value, _ in points]
            color = points[-1][2]
            if kind in {"fees", "realized"}:
                stepped = [coords[0]]
                for (_, previous_y), (xx, yy) in zip(coords, coords[1:]):
                    stepped.extend(((xx, previous_y), (xx, yy)))
                coords = stepped
            if len(coords) > 1:
                baseline = y(0) if lo <= 0 <= hi else bottom
                tint = Image.blend(Image.new("RGB", (1, 1), PAPER), Image.new("RGB", (1, 1), color), .14).getpixel((0, 0))
                for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                    draw.polygon([(x1, baseline), (x1, y1), (x2, y2), (x2, baseline)], fill=tint)
                if lo <= 0 <= hi:
                    draw.line((left, baseline, right, baseline), fill=MUTED)
                draw.line(coords, fill=color, width=4)
            xx, yy = coords[-1]
            draw.line((left, yy, right, yy), fill=color)
            draw.ellipse((xx - 6, yy - 6, xx + 6, yy + 6), fill=color, outline=PAPER, width=2)
            last = points[-1][1]
            unit = "%" if kind in {"return", "drawdown"} else " USD"
            label(1080, 30, f"{last:,.2f}" + unit, heading, color, "rt")
            caption = "最新采样" if zh else "Latest sample"
            if kind in {"fees", "realized"}:
                caption = "区间累计" if zh else "Period total"
            if kind == "drawdown":
                caption += ("   ·   区间最深 " if zh else "   |   Worst ") + f"{min(values):.2f}%"
            label(1080, 88, caption, small, MUTED, "rt")

    footer = ("虚拟交易 · 仅供复盘" if zh else "SIMULATED TRADES   /   REVIEW ONLY")
    legends = {
        "candles": ("三角：开仓  圆点：平仓  金色：系统退出", "Triangle: open   Dot: close   Gold: system exit"),
        "activity": ("绿：完成  红：失败  金：其他", "Green: completed   Rose: failed   Gold: other"),
        "trades": ("平仓毛盈亏，未扣手续费", "Gross P/L per close, before fees"),
        "realized": ("所选时段平仓毛盈亏减去该时段成交费", "Period gross realized P/L minus period fill fees"),
    }
    if kind in legends:
        footer += "   |   " + legends[kind][0 if zh else 1]
    if data.get("truncated"):
        footer += "   |   " + ("事件已截断" if zh else "Events truncated")
    label(40, 604, footer, small, MUTED)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_chart_sheet(data, kinds):
    """Compose one image, keeping wider charts on their own row."""
    if len(kinds) == 1:
        return render_png(data, kinds[0])

    panels = list(dict.fromkeys(
        panel for kind in kinds for panel in (OVERVIEW_PANELS if kind == "overview" else (kind,))
    ))
    rows = []
    for panel in panels:
        if rows and len(rows[-1]) == 1 and rows[-1][0] not in WIDE_PANELS and panel not in WIDE_PANELS:
            rows[-1].append(panel)
        else:
            rows.append([panel])

    chart_width, _ = CHART_SIZE
    gap = 24
    columns = max(map(len, rows))
    width = chart_width * columns + gap * (columns - 1)
    rendered = {panel: Image.open(BytesIO(render_png(data, panel))).convert("RGB") for panel in panels}
    try:
        heights = [max(rendered[panel].height for panel in row) for row in rows]
        sheet = Image.new("RGB", (width + 2 * gap, sum(heights) + gap * (len(rows) + 1)), GRID)
        top = gap
        for row, height in zip(rows, heights):
            for column, kind in enumerate(row):
                chart = rendered[kind]
                if len(row) == 1 and columns == 2:
                    ImageDraw.Draw(sheet).rectangle((gap, top, gap + width - 1, top + height - 1), fill=PAPER)
                    left = gap + (width - chart_width) // 2
                else:
                    left = gap + column * (chart_width + gap)
                sheet.paste(chart, (left, top))
            top += height + gap
        buffer = BytesIO()
        sheet.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        for image in rendered.values():
            image.close()


def render_text_png(panel):
    (heading, body, small), _ = fonts()
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = []
    for paragraph in panel["content"].splitlines():
        line = ""
        for char in paragraph:
            if measure.textlength(line + char, font=body) > 1024:
                lines.append(line)
                line = char
            else:
                line += char
        if line or (lines and lines[-1]):
            lines.append(line)
    if len(lines) > 240:
        lines = lines[:239] + ["……内容较长，请分段查看后续文字"]
    height = max(320, 150 + len(lines) * 36 + 48)
    image = Image.new("RGB", (1120, height), PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((48, 28), panel["title"], font=heading, fill=INK)
    draw.text((48, 82), panel.get("subtitle", ""), font=small, fill=MUTED)
    draw.line((48, 120, 1072, 120), fill=GRID, width=2)
    for index, line in enumerate(lines):
        draw.text((48, 150 + index * 36), line, font=body, fill=INK)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
