"""Official football-data.org v4 fixtures; no paid/livescore endpoints."""
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .content import finalize_content
from .uefa import fixtures, UEFA
from .football_selection import select

COMPETITIONS = {
    "CL": ("دوري أبطال أوروبا", "#دوري_أبطال_أوروبا"),
    "PL": ("الدوري الإنجليزي", "#الدوري_الإنجليزي"),
    "PD": ("الدوري الإسباني", "#الدوري_الإسباني"),
    "BL1": ("الدوري الألماني", "#الدوري_الألماني"),
    "SA": ("الدوري الإيطالي", "#الدوري_الإيطالي"),
    "FL1": ("الدوري الفرنسي", "#الدوري_الفرنسي"),
    "WC": ("كأس العالم", "#كأس_العالم"),
    "EC": ("كأس أوروبا", "#كأس_أوروبا"),
}
COMPETITIONS.update({code:(value[1],value[2]) for code,value in UEFA.items()})


class Football:
    def __init__(self, http, c, token=None, clock=None):
        self.http, self.c = http, c
        self.token = token or os.environ.get("FOOTBALL_DATA_API_KEY")
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def publication(self, post_day, previous=()):
        schedule=self.tomorrow(post_day)
        if not schedule['matches'] and self.c.get('football_standings_fallback',False):
            from .football_standings import standings
            cached=getattr(self,'_standings_cache',None)
            now=self.clock()
            if not cached or cached[0]!=post_day or (now-cached[1]).total_seconds()>300:
                self._standings_cache=(post_day,now,standings(self.http,self.c,self.token,post_day,now,previous))
            return self._standings_cache[2]
        if not schedule['matches'] and self.c.get('football_results_fallback',False):
            from .football_results import latest_results
            return latest_results(self.http,self.c,self.token,post_day,self.clock(),previous)
        return schedule

    def tomorrow(self, post_day):
        if not self.token:
            raise RuntimeError("Add the FREE football-data.org key as FOOTBALL_DATA_API_KEY; football lookup cannot be skipped")
        mode=self.c.get('fixture_day','tomorrow')
        day = datetime.fromisoformat(post_day).date() + timedelta(days=0 if mode=='today' else 1)
        local_start = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("Europe/Berlin"))
        local_end = local_start + timedelta(days=1)
        start, end = local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)
        # v4 dateTo is exclusive. Fetch whole UTC dates bracketing the Berlin day,
        # then apply the precise local interval, including late games across midnight.
        params = urllib.parse.urlencode({"dateFrom": start.date().isoformat(),
                                        "dateTo": (end.date() + timedelta(days=1)).isoformat()})
        data = self.http.json("https://api.football-data.org/v4/matches?" + params,
                              extra_headers={"X-Auth-Token": self.token}, safe_retry=True)
        if not isinstance(data.get("matches"), list) or "error" in data or data.get("errorCode"):
            raise RuntimeError("Football provider response is invalid; do not infer an empty schedule")
        allowed = self.c["football_competitions"]
        matches, seen = [], set()
        for source in data["matches"]:
            code = source.get("competition", {}).get("code")
            if code in self.c.get('uefa_competitions',[]):continue
            if code not in allowed:
                continue
            try:
                kickoff = datetime.fromisoformat(source["utcDate"].replace("Z", "+00:00"))
            except (KeyError, ValueError, TypeError):
                raise RuntimeError("A covered fixture has no valid kickoff; do not invent a time") from None
            if kickoff.tzinfo is None:
                raise RuntimeError("Fixture timestamp lacks a timezone")
            if not start <= kickoff < end:
                continue
            status = source.get("status")
            if status in ("POSTPONED", "CANCELLED", "SUSPENDED", "AWARDED", "FINISHED"):
                continue
            if status != "TIMED":
                raise RuntimeError("A fixture's precise kickoff is not confirmed (TIMED); review tomorrow's schedule")
            if source.get("id") in seen:
                continue
            seen.add(source.get("id"))
            home, away = source.get("homeTeam", {}), source.get("awayTeam", {})
            if not source.get("id") or not home.get("name") or not away.get("name"):
                raise RuntimeError("Incomplete fixture teams or ID")
            germany, makkah = kickoff.astimezone(ZoneInfo("Europe/Berlin")), kickoff.astimezone(ZoneInfo("Asia/Riyadh"))
            matches.append({"id": source["id"], "competition_code": code, "competition": COMPETITIONS[code][0],
                "home": home.get("shortName") or home["name"], "away": away.get("shortName") or away["name"],
                "home_crest": home.get("crest"), "away_crest": away.get("crest"),
                "kickoff_utc": kickoff.astimezone(timezone.utc).isoformat(),
                "germany_time": germany.strftime("%H:%M"), "germany_date": germany.date().isoformat(),
                "makkah_time": makkah.strftime("%H:%M"), "makkah_date": makkah.date().isoformat()})
        extra=self.c.get('uefa_competitions',[])
        matches.extend(fixtures(self.http,day,extra))
        order=list(dict.fromkeys(allowed+extra))
        unique={str(m['id']):m for m in matches}
        matches=sorted(unique.values(),key=lambda m:(order.index(m['competition_code']),m['kickoff_utc'],str(m['id'])))
        matches,selection = select(matches,self.c)
        return {**selection,"date": day.isoformat(), "matches": matches,
                "date_mode":mode,"checked_at": self.clock().isoformat(), "source_url": "https://www.football-data.org/",
                "sources":['football-data.org']+(['UEFA.com'] if extra else [])}


def football_content(schedule, c):
    """Copy every factual field from provider data. AI only draws the background."""
    if schedule.get('date_mode')=='standings':
        from .football_standings import standings_content
        return standings_content(schedule,c)
    if schedule.get('date_mode')=='results':
        from .football_results import results_content
        return results_content(schedule,c)
    matches = schedule["matches"]
    date = schedule["date"]
    day_label='اليوم' if schedule.get('date_mode')=='today' else 'الغد'
    sources=' و '.join(schedule.get('sources',['football-data.org']))
    codes = list(dict.fromkeys(m["competition_code"] for m in matches))
    leagues = "، ".join(COMPETITIONS[x][0] for x in codes)
    headline="أبرز مباريات" if schedule.get("selection") else "مباريات"
    description = (f"{headline} {day_label} {date}: {len(matches)} مواجهة ضمن {leagues}. عرض المواعيد بتوقيت ألمانيا ومكة المكرمة. المواعيد بحسب {sources} وقابلة للتغيير."
                   if matches else f"تحديث رياضي لغد {date}: لا يعرض football-data.org مباريات مؤكدة ضمن البطولات الثماني المتابعة حاليًا. هذا لا يعني عدم وجود مباريات في بطولات أخرى. تابعنا لتحديث الغد.")
    tags = ['#مباريات_'+day_label, "#كرة_القدم"] + [COMPETITIONS[x][1] for x in codes] + ["#TK_Servers"]
    if c.get('correction_notice'):
        description=c['correction_notice']+'\n\n'+description
    sports_c = dict(c, hashtag_pool=list(dict.fromkeys(tags)), fixed_hashtags=[])
    # Ensure a sports-only pool of at least five relevant tags.
    sports_c["hashtag_pool"] = list(dict.fromkeys(tags + ["#مباريات", "#كرة_قدم", "#رياضة"]))
    raw = {"idea": f"Official tomorrow football fixtures {date}",
        "title": f"مباريات {day_label} | {date}",
        "description": description,
        "prompt": "An original black and gold football stadium illustration, illuminated field, gold particles, dramatic night atmosphere, empty space for schedule cards. No people, team badges, trophies, text or logos.",
        "hashtags": tags, "safe_fictional_art": True}
    content = finalize_content(raw, sports_c, [])
    content.update(post_kind="football", subject_id=f"fixtures:{date}", subject_title=raw["title"],
                   fixture_schedule=schedule, source_url=schedule["source_url"])
    return content
