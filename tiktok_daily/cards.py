"""Deterministic TK layouts. Numbers/times are rendered from verified data."""
import io
import math
import re
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
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


def text(draw, value, box, size=40, color=WHITE, max_lines=4, weight=400, stroke=0, align="right"):
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
                draw.text((x + width if align == "right" else x + (width + draw.textlength(line,font=face,direction=direction,language="ar"))/2, y + i * step), line, font=face, fill=color, anchor="ra", direction=direction, language="ar", stroke_width=stroke, stroke_fill='#080a0d')
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


def _crest_once(url):
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


@lru_cache(maxsize=128)
def crest(url):
    if not url:return None
    for attempt in range(3):
        badge=_crest_once(url)
        if badge is not None:return badge
        if attempt<2:time.sleep(0.3*(attempt+1))
    return None


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
    schedule=entry['fixture_schedule'];matches=schedule['matches']
    is_results=schedule.get('date_mode')=='results'
    per_page=5;pages=max(1,math.ceil(len(matches)/per_page))
    if pages>10:raise RuntimeError('Selected fixtures exceed 50 matches; refusing to omit selected fixtures')
    result=[]
    for page in range(pages):
        with Image.open(io.BytesIO(hero)) as src:
            image=ImageOps.fit(src.convert('RGB'),(1080,1920),method=Image.Resampling.LANCZOS)
        overlay=Image.new('RGBA',image.size);pd=ImageDraw.Draw(overlay)
        pd.rounded_rectangle((290,347,790,420),radius=30,fill=(0,0,0,224),outline=GOLD,width=3)
        selected=matches[page*per_page:(page+1)*per_page]
        for row in range(len(selected)):
            top=478+row*233
            pd.rounded_rectangle((28,top-2,1052,top+221),radius=24,outline=(255,185,52,85),width=7)
            pd.rounded_rectangle((32,top,1048,top+217),radius=23,fill=(2,5,7,240),outline=(245,197,84,255),width=3)
            pd.rectangle((439,top+8,641,top+210),fill=(9,10,7,230))
            pd.line((439,top+30,439,top+207),fill=GOLD,width=2)
            pd.line((641,top+30,641,top+207),fill=GOLD,width=2)
            pd.line((451,top+116,629,top+116),fill=GOLD,width=1)
            pd.polygon([(350,top-15),(730,top-15),(747,top+6),(730,top+28),(350,top+28),(333,top+6)],fill=(3,6,8,255),outline=GOLD,width=2)
        image=Image.alpha_composite(image.convert('RGBA'),overlay).convert('RGB');draw=ImageDraw.Draw(image)
        draw.line([(38,35),(38,135),(169,85),(38,35)],fill=GOLD,width=4)
        draw.text((52,37),'TK',font=font(46,750),fill='#ffdd88')
        draw.polygon([(69,27),(61,13),(78,20),(88,8),(98,20),(115,13),(108,27)],fill=GOLD)
        heading='آخر النتائج' if is_results else ('مباريات اليوم' if schedule.get('date_mode')=='today' else 'مباريات الغد')
        text(draw,heading,(88,56,910,252),size=140,color='#5b3611',max_lines=1,weight=900,stroke=4,align="center")
        text(draw,heading,(85,50,910,252),size=140,color='#ffdb7d',max_lines=1,weight=900,stroke=2,align="center")
        text(draw,'الدوريات الخمس الكبرى • نتائج نهائية' if is_results else 'بتوقيت ألمانيا ومكة المكرمة',(160,277,760,68),size=37,max_lines=1,weight=650,stroke=2,align="center")
        day=datetime.fromisoformat(schedule['date']).strftime('%d / %m / %Y')
        if pages>1:day+=f'   |   {page+1}/{pages}'
        text(draw,day,(310,353,460,60),size=34,color='#ffe6a1',max_lines=1,weight=650,align="center")
        if entry.get('demo'):
            text(draw,'مثال تصميم تجريبي • المباريات غير مؤكدة',(90,425,900,45),size=23,color=GOLD,max_lines=1,align="center")
        elif c.get('correction_notice'):
            text(draw,'تصحيح جدول المباريات',(90,425,900,45),size=23,color=GOLD,max_lines=1,align="center")
        elif entry.get('preview'):
            text(draw,'معاينة أولية • تُحدَّث البيانات قبل الحجز',(90,425,900,45),size=23,color=GOLD,max_lines=1,align="center")
        if not selected:text(draw,'لا توجد مواجهات مختارة مؤكدة',(80,780,920,130),size=52,color=GOLD,max_lines=1,align="center")
        for row,match in enumerate(selected):
            top=478+row*233
            text(draw,match['competition'],(356,top-14,366,43),size=24,color=WHITE,max_lines=1,weight=600,align="center")
            for field,left in [('away_crest',65),('home_crest',895)]:
                badge=crest(match.get(field))
                if badge is not None:
                    badge=ImageOps.contain(badge,(120,138),method=Image.Resampling.LANCZOS)
                    image.paste(badge,(left+(120-badge.width)//2,top+45+(138-badge.height)//2),badge)
            text(draw,match['away'],(202,top+61,221,130),size=46,max_lines=2,weight=800,stroke=1,align="center")
            text(draw,match['home'],(661,top+61,221,130),size=46,max_lines=2,weight=800,stroke=1,align="center")
            if is_results:
                # Home team is on the right; place its score on the right too.
                text(draw,f"{match['away_score']} – {match['home_score']}",(451,top+26,177,92),size=58,color='#ffe388',max_lines=1,weight=850,align="center")
                text(draw,'نهائية',(451,top+116,177,43),size=27,color='#f8de97',max_lines=1,weight=650,align="center")
                text(draw,datetime.fromisoformat(match['result_date']).strftime('%d/%m/%Y'),(448,top+167,184,39),size=20,color=WHITE,max_lines=1,align="center")
            else:
                text(draw,match['germany_time'],(451,top+22,177,83),size=54,color='#ffe388',max_lines=1,weight=850,align="center")
                text(draw,'ألمانيا',(460,top+85,160,39),size=21,color='#f8de97',max_lines=1,weight=650,align="center")
                text(draw,match['makkah_time'],(451,top+117,177,77),size=51,color='#ffe388',max_lines=1,weight=850,align="center")
                label='مكة (+1)' if match['makkah_date']!=match['germany_date'] else 'مكة'
                text(draw,label,(451,top+175,177,39),size=21,color='#f8de97',max_lines=1,weight=650,align="center")
        text(draw,c.get('brand_name','TK SERVERS'),(475,1745,545,95),size=52,color='#ffdb7d',max_lines=1,weight=800,stroke=2)
        signature=c.get('caption_suffix','شاهدها على سيرفراتنا').replace('⚡','').replace('🏆','').strip()
        text(draw,signature,(390,1834,630,57),size=24,max_lines=1,weight=600,stroke=1)
        sources=' / '.join(schedule.get('sources',['football-data.org']))
        note=('آخر النتائج المتاحة • '+sources+' • التاريخ داخل كل مواجهة' if is_results else ('أبرز المباريات • ' if schedule.get('selection') else '')+sources+' • المواعيد قابلة للتغيير')
        text(draw,note,(55,1890,970,40),size=20,max_lines=1,color='#d6c492',stroke=1)
        result.append(encode(image))
    return result


def render(hero, entry, c):
    if entry.get("post_kind") == "football":
        if entry['fixture_schedule'].get('date_mode')=='standings':
            return football_standings(hero,entry,c)
        return football(hero, entry, c)
    return cinema(hero, entry, c)


def football_standings(hero,entry,c):
    """One full league per page, keeping the approved stadium/branding."""
    schedule=entry['fixture_schedule'];pages=[]
    for page,league in enumerate(schedule['matches'],1):
        with Image.open(io.BytesIO(hero)) as src:
            image=ImageOps.fit(src.convert('RGB'),(1080,1920),method=Image.Resampling.LANCZOS)
        layer=Image.new('RGBA',image.size);pd=ImageDraw.Draw(layer)
        pd.rounded_rectangle((30,450,1050,1658),radius=26,fill=(2,5,7,246),outline=GOLD,width=3)
        pd.rounded_rectangle((250,350,830,422),radius=26,fill=(0,0,0,225),outline=GOLD,width=3)
        image=Image.alpha_composite(image.convert('RGBA'),layer).convert('RGB');draw=ImageDraw.Draw(image)
        draw.line([(38,35),(38,135),(169,85),(38,35)],fill=GOLD,width=4)
        draw.text((52,37),'TK',font=font(46,750),fill='#ffdd88')
        draw.polygon([(69,27),(61,13),(78,20),(88,8),(98,20),(115,13),(108,27)],fill=GOLD)
        text(draw,'ترتيب الدوريات',(90,92,900,188),size=108,color='#ffdb7d',max_lines=1,weight=900,stroke=2,align='center')
        text(draw,league['competition'],(160,280,760,65),size=42,color=WHITE,max_lines=1,weight=750,align='center')
        day=datetime.fromisoformat(schedule['date']).strftime('%d / %m / %Y')
        text(draw,f'{day}   |   {page}/5',(270,356,540,58),size=31,color='#ffe6a1',max_lines=1,align='center')
        text(draw,'الموسم '+league['season'],(80,462,920,55),size=28,color=GOLD,max_lines=1,align='center')
        # Reading right to left: rank, crest/team, played, goal difference, points.
        for value,box in [('#',(965,523,65,45)),('الفريق',(450,523,460,45)),('لعب',(345,523,100,45)),('الفارق',(205,523,115,45)),('نقاط',(55,523,125,45))]:
            text(draw,value,box,size=25,color=GOLD,max_lines=1,weight=750,align='center')
        draw.line((50,576,1030,576),fill=GOLD,width=2)
        for index,row in enumerate(league['table']):
            top=584+index*51
            if index%2==0:draw.rounded_rectangle((45,top-1,1035,top+49),radius=7,fill='#14130e')
            if row['position']==1:draw.rounded_rectangle((45,top-1,1035,top+49),radius=7,outline=GOLD,width=2)
            text(draw,str(row['position']),(965,top,65,48),size=26,color=GOLD,max_lines=1,weight=700,align='center')
            badge=crest(row.get('crest'))
            if badge is not None:
                badge=ImageOps.contain(badge,(39,39),method=Image.Resampling.LANCZOS)
                image.paste(badge,(919+(39-badge.width)//2,top+5+(39-badge.height)//2),badge)
            text(draw,row['name'],(455,top,449,50),size=28,max_lines=1,weight=650)
            text(draw,str(row['playedGames']),(345,top,100,50),size=27,max_lines=1,align='center')
            gd=row['goalDifference'];label=f'+{gd}' if gd>0 else str(gd)
            text(draw,label,(205,top,115,50),size=27,max_lines=1,align='center')
            text(draw,str(row['points']),(55,top,125,50),size=29,color='#ffe388',max_lines=1,weight=850,align='center')
        if entry.get('preview'):
            text(draw,'معاينة • أحدث ترتيب متاح من المصدر',(85,1610,910,42),size=22,color=GOLD,max_lines=1,align='center')
        text(draw,c.get('brand_name','TK SERVERS'),(475,1745,545,95),size=52,color='#ffdb7d',max_lines=1,weight=800,stroke=2)
        signature=c.get('caption_suffix','شاهدها على سيرفراتنا').replace('⚡','').replace('🏆','').strip()
        text(draw,signature,(390,1834,630,57),size=24,max_lines=1,weight=600,stroke=1)
        stamp=datetime.fromisoformat(schedule['checked_at']).astimezone(ZoneInfo('Europe/Berlin')).strftime('%d/%m %H:%M')
        text(draw,'football-data.org • تحديث '+stamp+' ألمانيا',(55,1890,970,40),size=20,max_lines=1,color='#d6c492',stroke=1)
        pages.append(encode(image))
    return pages
