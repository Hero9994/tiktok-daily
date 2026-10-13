"""Deterministic TK layouts. Numbers/times are rendered from verified data."""
import io
import math
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageOps, features

GOLD, WHITE, PANEL = "#d9ac57", "#f8f5eb", "#0c1016"


def font(size):
    if not features.check_feature("raqm"):
        raise RuntimeError("Arabic card rendering requires Pillow RAQM")
    return ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts/NotoSansArabic.ttf"), size)


def text(draw, value, box, size=40, color=WHITE, max_lines=4):
    x, y, width, height = box
    for trial in range(size, 19, -2):
        face, lines, current = font(trial), [], ""
        for word in str(value).split():
            candidate = (current + " " + word).strip()
            if draw.textlength(candidate, font=face, direction="rtl", language="ar") > width and current:
                lines.append(current); current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        step = int(trial * 1.8)
        if len(lines) <= max_lines and len(lines) * step <= height and all(draw.textlength(line, font=face, direction="rtl", language="ar") <= width for line in lines):
            for i, line in enumerate(lines):
                draw.text((x + width, y + i * step), line, font=face, fill=color, anchor="ra", direction="rtl", language="ar")
            return
    raise ValueError("Card text does not fit; refusing to clip factual content")


def canvas():
    image = Image.new("RGB", (1080, 1920), "#04070b")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 20, 1060, 1900), radius=32, outline=GOLD, width=3)
    # Static TK wordmark, with decorative particles rather than an invented asset.
    for i in range(60):
        x, y = 40 + (i * 173) % 1000, 40 + (i * 107) % 1830
        draw.ellipse((x, y, x + 2, y + 2), fill="#8b6b34")
    draw.rounded_rectangle((460, 45, 620, 185), radius=25, outline=GOLD, width=4)
    draw.text((482, 55), "TK", font=font(72), fill=GOLD)
    return image, draw


def footer(draw, c, note):
    draw.line((55, 1665, 1025, 1665), fill=GOLD, width=2)
    text(draw, c.get("brand_name", "TK SERVERS"), (60, 1690, 960, 90), size=52, color=GOLD, max_lines=1)
    signature = c.get("caption_suffix", "شاهدها على سيرفراتنا").replace("⚡", "").replace("🏆", "").strip()
    text(draw, signature, (150, 1780, 860, 75), size=29, max_lines=1)
    # Draw the bolt rather than relying on an unavailable emoji glyph in the Arabic font.
    draw.polygon([(108, 1775), (77, 1811), (99, 1811), (87, 1844), (125, 1797), (105, 1797)], fill=GOLD)
    text(draw, note, (70, 1850, 940, 42), size=20, color="#a6a09a", max_lines=1)


def encode(image):
    out = io.BytesIO(); image.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()


def cinema(hero, entry, c):
    image, draw = canvas()
    with Image.open(io.BytesIO(hero)) as src:
        panel = ImageOps.fit(src.convert("RGB"), (960, 630), method=Image.Resampling.LANCZOS)
    image.paste(panel, (60, 215))
    draw.rounded_rectangle((58, 212, 1022, 850), radius=15, outline=GOLD, width=3)
    text(draw, entry["title"], (70, 865, 940, 155), size=64, color=GOLD, max_lines=2)
    draw.rounded_rectangle((55, 1040, 1025, 1460), radius=24, fill=PANEL, outline=GOLD, width=2)
    text(draw, "نبذة مختصرة", (80, 1058, 920, 90), size=38, color=GOLD, max_lines=1)
    text(draw, entry.get("summary") or entry.get("description", ""), (80, 1145, 920, 290), size=41, max_lines=4)
    draw.rounded_rectangle((55, 1490, 1025, 1628), radius=20, fill=PANEL, outline="#76613c", width=2)
    text(draw, "ترشيح اليوم • نبذة دون حرق الأحداث", (80, 1517, 920, 100), size=36, color=GOLD, max_lines=1)
    footer(draw, c, "المصدر: Wikipedia | الرسم الفني مولّد بالذكاء الاصطناعي")
    if entry.get("demo"):
        text(draw, "نموذج تصميم — صورة تجريبية", (65, 805, 950, 45), size=24, color=GOLD, max_lines=1)
    return [encode(image)]


def football(hero, entry, c):
    schedule = entry["fixture_schedule"]
    matches = schedule["matches"]
    pages = math.ceil(len(matches) / 6)
    if not 1 <= pages <= 10:
        raise RuntimeError("Fixture schedule exceeds Buffer's 10-photo carousel capacity; do not silently omit matches")
    result = []
    for index in range(pages):
        image, draw = canvas()
        # One AI-generated stadium background is reused across all factual pages.
        with Image.open(io.BytesIO(hero)) as src:
            banner = ImageOps.fit(src.convert("RGB"), (960, 230), method=Image.Resampling.LANCZOS)
        image.paste(banner, (60, 215))
        text(draw, "مباريات الغد", (75, 235, 930, 140), size=70, color=GOLD, max_lines=1)
        day = datetime.fromisoformat(schedule["date"]).strftime("%d/%m/%Y")
        text(draw, f"{day}  |  ألمانيا ومكة  |  {index + 1}/{pages}", (70, 378, 940, 68), size=30, max_lines=1)
        page_matches = matches[index * 6:(index + 1) * 6]
        row_height = 1180 // len(page_matches)
        for row, match in enumerate(page_matches):
            top = 470 + row * row_height
            draw.rounded_rectangle((55, top, 1025, top + row_height - 17), radius=20, fill=PANEL, outline=GOLD, width=2)
            text(draw, match["competition"], (75, top + int(row_height * .05), 930, int(row_height * .22)), size=33 if row_height > 300 else 25, color=GOLD, max_lines=1)
            text(draw, f"{match['home']}  ×  {match['away']}", (75, top + int(row_height * .30), 930, int(row_height * .29)), size=52 if row_height > 300 else 35, max_lines=1)
            germany = f"ألمانيا {match['germany_time']}"
            makkah = f"مكة {match['makkah_time']}"
            if match["makkah_date"] != match["germany_date"]:
                makkah += " (+1 يوم)"
            text(draw, germany, (80, top + int(row_height * .67), 430, int(row_height * .25)), size=36 if row_height > 300 else 27, color=GOLD, max_lines=1)
            text(draw, makkah, (560, top + int(row_height * .67), 440, int(row_height * .25)), size=36 if row_height > 300 else 27, color=GOLD, max_lines=1)
        footer(draw, c, "المواعيد: football-data.org | قابلة للتغيير | الرسم الفني مولّد بالذكاء الاصطناعي")
        if entry.get("demo"):
            text(draw, "نموذج تصميم — الفرق والمواعيد تجريبية", (70, 209, 940, 40), size=23, color=GOLD, max_lines=1)
        result.append(encode(image))
    return result


def render(hero, entry, c):
    if entry.get("post_kind") == "football":
        return football(hero, entry, c)
    return cinema(hero, entry, c)
