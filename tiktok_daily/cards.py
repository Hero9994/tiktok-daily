"""Deterministic TK layouts. Numbers/times are rendered from verified data."""
import io
import math
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageOps, features
from .cinema_media import artwork

GOLD, WHITE, PANEL = "#d9ac57", "#f8f5eb", "#0c1016"


def font(size, weight=400):
    if not features.check_feature("raqm"):
        raise RuntimeError("Arabic card rendering requires Pillow RAQM")
    face = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts/NotoSansArabic.ttf"), size)
    if weight != 400:
        try:
            axes = face.get_variation_axes()
            settings = [a['default'] for a in axes]
            for i, axis in enumerate(axes):
                if axis['name'] == b'Weight':
                    settings[i] = weight
            face.set_variation_by_axes(settings)
        except OSError:
            pass
    return face


def text(draw, value, box, size=40, color=WHITE, max_lines=4, weight=400, stroke=0):
    x, y, width, height = box
    direction = 'rtl' if re.search(r'[\u0600-\u06ff]', str(value)) else 'ltr'
    for trial in range(size, 19, -2):
        face, lines, current = font(trial, weight), [], ""
        for word in str(value).split():
            candidate = (current + " " + word).strip()
            if draw.textlength(candidate, font=face, direction=direction, language="ar") > width and current:
                lines.append(current); current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        step = int(trial * 1.8)
        if len(lines) <= max_lines and len(lines) * step <= height and all(draw.textlength(line, font=face, direction=direction, language="ar") <= width for line in lines):
            for i, line in enumerate(lines):
                draw.text((x + width, y + i * step), line, font=face, fill=color, anchor="ra", direction=direction, language="ar", stroke_width=stroke, stroke_fill='#080a0d')
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


@lru_cache(maxsize=128)
def crest(url):
    parsed = urllib.parse.urlsplit(url or '')
    if parsed.scheme != 'https' or parsed.hostname not in {'crests.football-data.org', 'upload.wikimedia.org'}:
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TKDaily/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            final = urllib.parse.urlsplit(response.url)
            if final.scheme != 'https' or final.hostname not in {'crests.football-data.org', 'upload.wikimedia.org'}:
                return None
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            return None
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 4_000_000:
                return None
            return im.convert('RGBA')
    except (OSError, ValueError):
        return None  # Missing/unsupported crests must not hide a verified fixture.


def cinema(hero, entry, c):
    image, draw = canvas()
    # Compact brand mark leaves the largest type for the actual work name.
    draw.rectangle((440, 35, 640, 200), fill="#04070b")
    draw.rounded_rectangle((55, 45, 174, 139), radius=18, outline=GOLD, width=3)
    draw.text((74, 47), "TK", font=font(48), fill=GOLD)
    text(draw, "ترشيح يستحق المشاهدة", (230, 57, 790, 75), size=38, color=GOLD, max_lines=1)
    text(draw, entry["title"], (55, 150, 970, 150), size=92, max_lines=1)
    details = entry.get("cinema_details", {})
    if details.get("poster_url"):
        poster = artwork(details['poster_url'])
    else:
        with Image.open(io.BytesIO(hero)) as src:
            poster = src.convert('RGB')
    panel = ImageOps.contain(poster, (398, 620), method=Image.Resampling.LANCZOS)
    image.paste(panel, (62 + (398 - panel.width)//2, 315 + (620 - panel.height)//2))
    draw.rounded_rectangle((55, 308, 467, 942), radius=14, outline=GOLD, width=3)
    facts = details.get('facts', [])[:6]
    if not facts:
        facts = [{'label': 'ترشيح اليوم', 'value': 'فيلم أو مسلسل'}, {'label': 'النبذة', 'value': 'دون حرق الأحداث'}]
    for index, fact in enumerate(facts):
        col, row = index % 2, index // 2
        left, top = 490 + col * 270, 310 + row * 148
        draw.rounded_rectangle((left, top, left + 255, top + 135), radius=15, fill=PANEL, outline="#76613c", width=2)
        text(draw, fact['label'], (left+12, top+8, 231, 54), size=27, color=GOLD, max_lines=1)
        text(draw, fact['value'], (left+12, top+61, 231, 65), size=38, max_lines=1)
    if len(facts) <= 4 and entry.get('watch_reason'):
        draw.rounded_rectangle((490, 616, 1018, 760), radius=15, fill=PANEL, outline='#76613c', width=2)
        text(draw, 'لماذا تشاهده؟', (509, 622, 490, 49), size=27, color=GOLD, max_lines=1)
        text(draw, entry['watch_reason'], (509, 673, 490, 83), size=28, max_lines=2)
    genres = ' • '.join(details.get('genres', []))
    if genres:
        draw.rounded_rectangle((490, 772, 1018, 939), radius=16, fill=PANEL, outline=GOLD, width=2)
        text(draw, 'التصنيف', (512, 781, 485, 55), size=29, color=GOLD, max_lines=1)
        text(draw, genres, (512, 836, 485, 95), size=30, max_lines=2)
    draw.rounded_rectangle((55, 965, 1025, 1248), radius=22, fill=PANEL, outline=GOLD, width=2)
    text(draw, "القصة باختصار • دون حرق", (80, 975, 920, 72), size=37, color=GOLD, max_lines=1)
    text(draw, entry.get("summary") or entry.get("description", ""), (80, 1048, 920, 190), size=39, max_lines=3)
    cast = details.get('cast', [])[:4]
    if cast:
        text(draw, 'من طاقم التمثيل', (75, 1265, 930, 64), size=37, color=GOLD, max_lines=1)
        width = 930 // len(cast)
        for index, actor in enumerate(cast):
            left = 75 + index * width
            draw.rounded_rectangle((left, 1330, left+width-12, 1638), radius=15, fill=PANEL, outline='#76613c', width=2)
            portrait = None
            if actor.get('image_url'):
                try:
                    portrait = artwork(actor['image_url'])
                except (OSError, ValueError):
                    pass  # Missing portraits never produce invented faces.
            if portrait is not None:
                photo = ImageOps.contain(portrait, (width-26, 217), method=Image.Resampling.LANCZOS)
                image.paste(photo, (left+7+(width-26-photo.width)//2, 1337+(217-photo.height)//2))
            else:
                text(draw, actor['name'].split()[0], (left+12, 1400, width-36, 90), size=35, color=GOLD, max_lines=1)
            text(draw, actor['name'], (left+10, 1553, width-32, 78), size=26, max_lines=2)
    else:
        text(draw, 'اختر مشاهدتك القادمة', (80, 1370, 920, 100), size=52, color=GOLD, max_lines=1)
        text(draw, 'ما رأيك بهذا الترشيح؟', (80, 1490, 920, 95), size=42, max_lines=1)
    footer(draw, c, "المصادر: Wikipedia / Wikidata / Wikimedia" + (" / TVmaze" if details.get('tvmaze_url') else ""))
    if entry.get("demo"):
        text(draw, "نموذج تصميم — صورة تجريبية", (70, 1875, 940, 40), size=23, color=GOLD, max_lines=1)
    return [encode(image)]


def football(hero, entry, c):
    schedule = entry["fixture_schedule"]
    matches = schedule["matches"]
    pages = math.ceil(len(matches) / 6)
    if not 1 <= pages <= 10:
        raise RuntimeError("Fixture schedule exceeds Buffer's 10-photo carousel capacity; do not silently omit matches")
    result = []
    for index in range(pages):
        with Image.open(io.BytesIO(hero)) as src:
            image = ImageOps.fit(src.convert('RGB'), (1080,1920), method=Image.Resampling.LANCZOS)
        overlay = Image.new('RGBA', image.size)
        panel_draw = ImageDraw.Draw(overlay)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((22,22,1058,1898), radius=24, outline=GOLD, width=2)
        # A compact play-shaped TK mark preserves the illuminated stadium artwork.
        draw.line([(444,58),(444,204),(621,130),(444,58)], fill=GOLD, width=6)
        draw.text((466,64),'TK',font=font(67),fill=GOLD)
        if entry.get('demo'):
            text(draw, 'معاينة فقط • المباريات والمواعيد تجريبية', (85,222,910,65),size=30,color=WHITE,max_lines=1)
        text(draw, 'مباريات الغد', (90,294,900,170),size=100,color=WHITE,max_lines=1,weight=850,stroke=3)
        text(draw, 'بتوقيت ألمانيا ومكة المكرمة', (100,450,880,90),size=39,max_lines=1)
        day = datetime.fromisoformat(schedule['date']).strftime('%d / %m / %Y')
        panel_draw.rounded_rectangle((185,550,895,634),radius=18,fill=(0,0,0,215),outline=GOLD,width=2)
        page_matches = matches[index * 6:(index + 1) * 6]
        row_height = min(265, 880 // len(page_matches))
        for row, match in enumerate(page_matches):
            top = 690 + row * row_height
            panel_draw.rounded_rectangle((55,top,1025,top+row_height-12),radius=17,fill=(4,9,13,218),outline=GOLD,width=2)
        panel_draw.rounded_rectangle((55,1600,1025,1763),radius=18,fill=(0,0,0,160),outline=GOLD,width=2)
        image = Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB')
        draw = ImageDraw.Draw(image)
        text(draw, f'{day}   |   {index+1}/{pages}', (205,562,670,68),size=36,max_lines=1)
        for row, match in enumerate(page_matches):
            top = 690 + row * row_height
            compact = row_height < 210
            text(draw, match['competition'], (80,top+5,920,44 if compact else 55),size=22 if compact else 29,color=GOLD,max_lines=1)
            name_top = top + (45 if compact else 70)
            name_height = 54 if compact else 92
            badge_size = 43 if compact else 69
            for field,left in [('away_crest',82),('home_crest',945)]:
                badge = crest(match.get(field))
                if badge is not None:
                    badge = ImageOps.contain(badge,(badge_size,badge_size),method=Image.Resampling.LANCZOS)
                    image.paste(badge,(left,name_top),badge)
            text(draw, match['away'], (140,name_top,340,name_height),size=28 if compact else 43,max_lines=1)
            text(draw, match['home'], (615,name_top,315,name_height),size=28 if compact else 43,max_lines=1)
            draw.text((515,name_top+5),'VS',font=font(25 if compact else 32),fill=GOLD)
            germany = f"ألمانيا {match['germany_time']}"
            makkah = f"مكة {match['makkah_time']}"
            if match['makkah_date'] != match['germany_date']:
                makkah += ' (+1 يوم)'
            time_top = top + (100 if compact else 174)
            text(draw,germany,(85,time_top,420,42 if compact else 73),size=22 if compact else 36,color=GOLD,max_lines=1)
            text(draw,makkah,(575,time_top,420,42 if compact else 73),size=22 if compact else 36,color=GOLD,max_lines=1)
        text(draw,c.get('brand_name','TK SERVERS'),(90,1614,900,80),size=45,color=GOLD,max_lines=1)
        signature = c.get('caption_suffix','شاهدها على سيرفراتنا').replace('⚡','').replace('🏆','').strip()
        text(draw,signature,(85,1698,915,63),size=28,max_lines=1)
        note = 'معاينة تصميم • ليست مباريات مؤكدة' if entry.get('demo') else 'المواعيد: football-data.org • قابلة للتغيير • الخلفية مولّدة بالذكاء الاصطناعي'
        text(draw,note,(70,1845,940,45),size=20,max_lines=1)
        result.append(encode(image))
    return result


def render(hero, entry, c):
    if entry.get("post_kind") == "football":
        return football(hero, entry, c)
    return cinema(hero, entry, c)
