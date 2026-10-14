import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

STYLES = {
    "paper_cut": "clearly stylized layered paper-cut illustration",
    "watercolor": "clearly painted imaginative watercolor illustration",
    "pixel_art": "clearly fictional pixel art",
    "flat_vector": "clearly stylized flat vector illustration",
    "oil_painting": "clearly painted imaginative oil painting",
    "cinematic_gold": "original cinematic illustration with black and gold lighting, dramatic atmosphere, no photorealistic people",
}
DISCLOSURE = "صورة فنية خيالية مولّدة بالذكاء الاصطناعي."


def load_config(path):
    c = json.loads(path.read_text(encoding="utf-8"))
    for flag in ("enabled", "allow_paid_openai"):
        if type(c.get(flag)) is not bool:
            raise ValueError(f"{flag} must be a boolean")
    if type(c.get("daily_enabled", True)) is not bool:
        raise ValueError("daily_enabled must be a boolean")
    if type(c.get("activate_after_first_success", False)) is not bool:
        raise ValueError("activate_after_first_success must be a boolean")
    if c.get("content_mode", "art") not in ("art", "cinema", "auto", "football"):
        raise ValueError("Invalid content_mode")
    if type(c.get('video_enabled',False)) is not bool:
        raise ValueError('video_enabled must be a boolean')
    if type(c.get('skip_empty_football',True)) is not bool:
        raise ValueError('skip_empty_football must be boolean')
    if c.get('fixture_day','tomorrow') not in ('today','tomorrow'):
        raise ValueError('fixture_day must be today or tomorrow')
    extra=c.get('uefa_competitions',[])
    if not isinstance(extra,list) or len(extra)!=len(set(extra)) or any(x not in ('CL','EL','ECL') for x in extra):
        raise ValueError('Invalid UEFA competitions')
    posts = c.get('daily_posts')
    if posts is not None:
        if not isinstance(posts,list) or len(posts)!=2 or {p.get('kind') for p in posts}!={'football','cinema'}:
            raise ValueError('Configure exactly one sports and one cinema post')
        for post in posts:
            if not re.fullmatch(r'(?:1[2-9]):[0-5]\d',post.get('time','')):
                raise ValueError('Daily post times must be between 12:00 and 20:00')
            if post.get('music_file') != f"assets/audio/{'sports' if post['kind']=='football' else 'cinema'}.m4a":
                raise ValueError('Invalid daily music assignment')
    caption = c.get("fixed_caption")
    if caption is not None and (not isinstance(caption, str) or len(caption) > 1500 or "#" in caption):
        raise ValueError("fixed_caption must be plain text under 1500 characters; configure hashtags separately")
    suffix = c.get("caption_suffix", "")
    if not isinstance(suffix, str) or len(suffix) > 500 or "#" in suffix:
        raise ValueError("caption_suffix must be text under 500 characters without hashtags")
    if c.get("football_background") not in (None, "assets/football-stadium.jpg"):
        raise ValueError("Choose the bundled football background or null")
    if c.get("card_style", "simple") not in ("simple", "black_gold"):
        raise ValueError("Invalid card_style")
    if not isinstance(c.get("brand_name", "TK SERVERS"), str) or len(c.get("brand_name", "")) > 60:
        raise ValueError("Invalid brand_name")
    if c.get("content_mode") in ("auto","football"):
        supported = {"CL", "PL", "PD", "BL1", "SA", "FL1", "WC", "EC"}
        competitions = c.get("football_competitions")
        if not isinstance(competitions, list) or not competitions or any(x not in supported for x in competitions):
            raise ValueError("Choose supported free football competitions")
        if type(c.get("fixture_max_age_minutes")) is not int or not 1 <= c["fixture_max_age_minutes"] <= 180:
            raise ValueError("Invalid fixture freshness limit")
    if c.get("style") not in STYLES:
        raise ValueError("Choose a supported illustration style; realistic impersonation is excluded")
    if not isinstance(c.get("theme"), str) or not 1 <= len(c["theme"].strip()) <= 500:
        raise ValueError("theme must contain 1–500 characters")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", c.get("publish_time", "")):
        raise ValueError("publish_time must be HH:MM")
    ZoneInfo(c["timezone"])
    for name, low, high in [
        ("prepare_lead_minutes", 15, 1440),
        ("verification_grace_minutes", 15, 1440),
        ("max_image_requests_per_month", 1, 62),
        ("max_text_requests_per_day", 1, 5),
    ]:
        if type(c.get(name)) is not int or not low <= c[name] <= high:
            raise ValueError(f"Invalid {name}")
    if c.get("image_quality") not in ("low", "medium"):
        raise ValueError("Only low or medium quality is permitted; review costs before changing")
    if c.get("image_model") != "gpt-image-2" or c.get("text_model") != "gpt-6-luna":
        raise ValueError("Model change requires updating documented pricing and code first")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", c.get("state_branch", "")):
        raise ValueError("Invalid state branch")
    pool, fixed = c.get("hashtag_pool"), c.get("fixed_hashtags")
    if not isinstance(pool, list) or not isinstance(fixed, list):
        raise ValueError("Hashtags must be lists")
    if len(fixed) > 5 or len(set(fixed)) != len(fixed) or len(set(pool + fixed)) < 5:
        raise ValueError("Provide at least five unique hashtags and at most five fixed hashtags")
    if any(not isinstance(t, str) or not re.fullmatch(r"#[\w]+", t) or len(t) > 50 for t in pool + fixed):
        raise ValueError("Use hashtags without spaces or punctuation")
    return c


def track_config(c, kind):
    post = next((p for p in c.get('daily_posts',[]) if p['kind']==kind),None)
    if not post:
        raise ValueError('This publishing track is not configured')
    return dict(c,post_kind=kind,content_mode=kind,publish_time=post['time'],music_file=post['music_file'])


def next_slot(c, now):
    local = now.astimezone(ZoneInfo(c["timezone"]))
    hour, minute = map(int, c["publish_time"].split(":"))
    for offset in range(3):
        day = local.date() + timedelta(days=offset)
        slot = datetime(day.year, day.month, day.day, hour, minute, tzinfo=local.tzinfo)
        # Reject nonexistent DST wall times instead of silently changing the time.
        if slot.astimezone(timezone.utc).astimezone(local.tzinfo).replace(tzinfo=None) != slot.replace(tzinfo=None):
            continue
        if slot.astimezone(timezone.utc) >= now + timedelta(minutes=c["prepare_lead_minutes"]):
            return slot
    raise ValueError("No valid publishing slot")
