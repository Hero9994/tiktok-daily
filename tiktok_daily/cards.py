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
    if parsed.scheme != 'https' or parsed.hostname not in {'crests.football-data.org', 'upload.wikimedia.org','img.uefa.com'}:
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TKDaily/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            final = urllib.parse.urlsplit(response.url)
            if final.scheme != 'https' or final.hostname not in {'crests.football-data.org', 'upload.wikimedia.org','img.uefa.com'}:
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
    image = Image.new('RGB',(1080,1920),'#050a0d')
    details = entry.get('cinema_details',{})
    if details.get('poster_url'):
        poster = artwork(details['poster_url'])
    else:
        with Image.open(io.BytesIO(hero)) as src: poster = src.convert('RGB')
    # An enlarged reference poster anchors the composition; details remain sourced text.
    art = ImageOps.fit(poster,(745,1060),method=Image.Resampling.LANCZOS,centering=(0.5,0.35))
    image.paste(art,(0,180))
    wash = Image.new('RGBA',image.size)
    wd = ImageDraw.Draw(wash)
    for x in range(745):
        alpha = int(240*max(0,(x-480)/265))
        wd.line((x,180,x,1240),fill=(5,10,13,alpha))
    for y in range(1060,1240):
        wd.line((0,y,1080,y),fill=(5,10,13,int(255*(y-1060)/180)))
    image=Image.alpha_composite(image.convert('RGBA'),wash).convert('RGB')
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((978,30,1048,105),radius=12,outline=GOLD,width=3)
    draw.text((989,34),'TK',font=font(33,650),fill=GOLD)
    text(draw,entry['title'],(60,0,875,164),size=98,color='#f7d27e',max_lines=1,weight=800,stroke=2)
    original = entry.get('subject_title','')
    original = re.sub(r'\s*\([^)]*\)\s*$','',original)
    if original and original.casefold()!=entry['title'].casefold():
        text(draw,original,(60,152,870,70),size=31,color=GOLD,max_lines=1)
    draw.line((100,149,875,149),fill=GOLD,width=2)
    facts = list(details.get('facts',[]))
    genres = ' / '.join(details.get('genres',[])[:2])
    if genres: facts.append({'label':'التصنيف','value':genres})
    ordered=[]
    for names in [('سنة الإصدار',),('التصنيف',),('المدة','المواسم'),('تقييم Common Sense','تقييم TVmaze'),('بلد الإنتاج',),('اللغة الأصلية','الحلقات','نوع العمل')]:
        fact=next((f for name in names for f in facts if f['label']==name),None)
        if fact:ordered.append(fact)
    if not ordered:ordered=[{'label':'ترشيح اليوم','value':'فيلم أو مسلسل'}]
    for i,fact in enumerate(ordered[:6]):
        top=280+i*139
        draw.rounded_rectangle((715,top,1050,top+124),radius=19,fill='#070c0f',outline='#a58a52',width=2)
        # Small geometric gold emblems avoid missing icon glyphs in the Arabic font.
        icon_x,icon_y=738,top+34
        if 'تقييم' in fact['label']:
            points=[]
            for n in range(10):
                angle=-math.pi/2+n*math.pi/5;r=22 if n%2==0 else 10
                points.append((icon_x+22+math.cos(angle)*r,icon_y+22+math.sin(angle)*r))
            draw.polygon(points,outline=GOLD,width=3)
        elif fact['label']=='المدة':
            draw.ellipse((icon_x,icon_y,icon_x+44,icon_y+44),outline=GOLD,width=3)
            draw.line((icon_x+22,icon_y+8,icon_x+22,icon_y+23,icon_x+32,icon_y+29),fill=GOLD,width=3)
        else:
            draw.rounded_rectangle((icon_x,icon_y,icon_x+44,icon_y+44),radius=6,outline=GOLD,width=2)
            draw.line((icon_x+8,icon_y+13,icon_x+36,icon_y+13),fill=GOLD,width=2)
        text(draw,fact['label'],(797,top+6,235,43),size=24,color=GOLD,max_lines=1)
        text(draw,fact['value'],(795,top+44,239,76),size=32,max_lines=2,weight=600)
    text(draw,'القصة',(70,1122,940,70),size=43,color=GOLD,max_lines=1,weight=700)
    draw.line((50,1188,1030,1188),fill=GOLD,width=2)
    draw.rounded_rectangle((35,1208,1045,1425),radius=22,fill='#0b1014',outline='#a58a52',width=2)
    text(draw,entry.get('summary') or entry.get('description',''),(60,1223,960,190),size=36,max_lines=3)
    cast=details.get('cast',[])[:3]
    text(draw,'أبطال العمل' if cast else 'لماذا تشاهده؟',(65,1440,950,74),size=41,color=GOLD,max_lines=1,weight=700)
    draw.line((50,1511,1030,1511),fill=GOLD,width=2)
    for i,actor in enumerate(cast):
        left=43+i*335
        draw.rounded_rectangle((left,1534,left+320,1823),radius=21,fill='#0b1014',outline=GOLD,width=3)
        if actor.get('image_url'):
            try:
                portrait=artwork(actor['image_url'])
                photo=ImageOps.fit(portrait,(306,211),method=Image.Resampling.LANCZOS,centering=(0.5,0.20))
                image.paste(photo,(left+7,1541))
            except (OSError,ValueError): pass
        text(draw,actor['name'],(left+12,1755,296,64),size=29,max_lines=1,color='#f7d27e',weight=650)
    if not cast:
        text(draw,entry.get('watch_reason') or 'ترشيح جديد لمحبي السينما والمسلسلات',(70,1580,940,180),size=42,max_lines=2)
    note='TK SERVERS • Wikipedia / Wikidata'
    if details.get('tvmaze_url'):note+=' / TVmaze'
    if entry.get('cinema_review'):note+=' / Common Sense Media'
    text(draw,note,(50,1853,980,43),size=20,color='#b6ac97',max_lines=1)
    if entry.get('demo'):
        text(draw,'معاينة تصميم فقط',(50,1879,980,40),size=20,color=GOLD,max_lines=1)
    return [encode(image)]


def football(hero, entry, c):
    schedule = entry['fixture_schedule']
    matches = schedule['matches']
    pages = max(1, math.ceil(len(matches) / 6))
    if pages > 10:
        raise RuntimeError('Fixture schedule exceeds 60 matches; refusing to omit fixtures')
    result = []
    for index in range(pages):
        with Image.open(io.BytesIO(hero)) as src:
            image = ImageOps.fit(src.convert('RGB'), (1080,1920), method=Image.Resampling.LANCZOS)
        # Data remains separate from the artwork: never bake teams or times into AI art.
        overlay = Image.new('RGBA', image.size)
        pd = ImageDraw.Draw(overlay)
        pd.rounded_rectangle((275,465,805,542), radius=38, fill=(0,0,0,222), outline=GOLD, width=3)
        page_matches = matches[index*6:(index+1)*6]
        for row in range(len(page_matches)):
            top = 588 + row*160
            # Concentric outlines create a fine gold rim around an opaque readable panel.
            pd.rounded_rectangle((38,top-3,1042,top+147),radius=23,outline=(255,190,65,65),width=7)
            pd.rounded_rectangle((42,top,1038,top+144),radius=21,fill=(2,5,7,239),outline=(242,196,99,255),width=3)
            pd.line((474,top+132,520,top+14),fill=(168,111,36,160),width=2)
        pd.rounded_rectangle((390,1610,1038,1815),radius=24,fill=(0,0,0,215),outline=GOLD,width=3)
        image = Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB')
        draw = ImageDraw.Draw(image)
        draw.line([(45,35),(45,145),(169,90),(45,35)],fill=GOLD,width=5)
        draw.text((60,42),'TK',font=font(49,650),fill=WHITE)
        heading = 'مباريات اليوم' if schedule.get('date_mode')=='today' else 'مباريات الغد'
        # A darker offset gives the title the embossed metallic look of the approved reference.
        text(draw,heading,(83,238,917,175),size=115,color='#603e16',max_lines=1,weight=900,stroke=4)
        text(draw,heading,(80,232,917,175),size=115,color='#ffdc85',max_lines=1,weight=900,stroke=2)
        text(draw,'بتوقيت ألمانيا ومكة المكرمة',(130,397,820,74),size=40,max_lines=1,weight=600,stroke=2)
        day = datetime.fromisoformat(schedule['date']).strftime('%d / %m / %Y')
        text(draw,f'{day}   |   {index+1}/{pages}',(294,471,490,65),size=35,max_lines=1)
        if entry.get('demo') or c.get('correction_notice'):
            label = 'معاينة فقط • المباريات والمواعيد تجريبية' if entry.get('demo') else 'تصحيح جدول المباريات'
            text(draw,label,(90,161,900,65),size=28,max_lines=1,color=GOLD,stroke=2)
        if not page_matches:
            text(draw,'لا مباريات مؤكدة',(80,760,920,120),size=60,color=GOLD,max_lines=1)
        for row, match in enumerate(page_matches):
            top = 588 + row*160
            text(draw,match['competition'],(550,top+1,355,40),size=21,color=GOLD,max_lines=1)
            for field, left in [('away_crest',70),('home_crest',920)]:
                badge = crest(match.get(field))
                if badge is not None:
                    badge = ImageOps.contain(badge,(94,100),method=Image.Resampling.LANCZOS)
                    image.paste(badge,(left+(94-badge.width)//2,top+26+(100-badge.height)//2),badge)
            text(draw,match['away'],(177,top+25,266,91),size=36,max_lines=2,weight=700)
            text(draw,match['home'],(580,top+25,325,91),size=34,max_lines=2,weight=700)
            text(draw,'VS',(453,top+39,80,65),size=34,color='#ffdc85',max_lines=1,weight=700)
            germany = f"ألمانيا {match['germany_time']}"
            makkah = f"مكة {match['makkah_time']}"
            if match['makkah_date'] != match['germany_date']:
                makkah += ' (+1 يوم)'
            text(draw,germany,(175,top+102,268,40),size=25,color=WHITE,max_lines=1)
            text(draw,makkah,(550,top+102,355,40),size=25,color=WHITE,max_lines=1)
        text(draw,c.get('brand_name','TK SERVERS'),(410,1643,600,106),size=67,color='#ffdc85',max_lines=1,weight=850,stroke=2)
        signature = c.get('caption_suffix','شاهدها على سيرفراتنا').replace('⚡','').replace('🏆','').strip()
        text(draw,signature,(402,1753,610,59),size=25,max_lines=1,weight=600)
        sources = ' / '.join(schedule.get('sources',['football-data.org']))
        text(draw,f'المواعيد: {sources} • قابلة للتغيير',(70,1848,940,42),size=21,max_lines=1)
        result.append(encode(image))
    return result


def render(hero, entry, c):
    if entry.get("post_kind") == "football":
        return football(hero, entry, c)
    return cinema(hero, entry, c)
