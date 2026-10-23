"""Verified final scores from the free provider, used only after an empty featured schedule."""
import hashlib
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .football_selection import select

LEAGUES={'PL','PD','BL1','SA','FL1'}


def latest_results(http,c,token,post_day,now,previous=()):
    if not token:raise RuntimeError('FOOTBALL_DATA_API_KEY is required for final results')
    zone=ZoneInfo('Europe/Berlin')
    end=min(now,datetime.fromisoformat(post_day).replace(tzinfo=zone)+timedelta(days=1))
    start=end-timedelta(days=7)
    params=urllib.parse.urlencode({'dateFrom':start.date().isoformat(),
        'dateTo':(end.date()+timedelta(days=1)).isoformat(),'status':'FINISHED'})
    data=http.json('https://api.football-data.org/v4/matches?'+params,
                   extra_headers={'X-Auth-Token':token},safe_retry=True)
    if not isinstance(data.get('matches'),list) or data.get('error') or data.get('errorCode'):
        raise RuntimeError('Final-results response is invalid; do not invent a scoreboard')
    from .football import COMPETITIONS
    rows={}
    for m in data['matches']:
        code=m.get('competition',{}).get('code')
        if code not in LEAGUES or m.get('status')!='FINISHED':continue
        try:
            kickoff=datetime.fromisoformat(m['utcDate'].replace('Z','+00:00'))
            home,away=m['homeTeam'],m['awayTeam']
            score=m['score']['fullTime'];hs,aws=score['home'],score['away']
            valid=(kickoff.tzinfo is not None and m['id'] and home['name'] and away['name']
                   and type(hs) is int and type(aws) is int and hs>=0 and aws>=0)
            if not valid:raise ValueError()
        except (KeyError,ValueError,TypeError):
            raise RuntimeError('Completed match has missing identity or final score') from None
        if not start<=kickoff<=end:continue
        local=kickoff.astimezone(zone)
        rows[str(m['id'])]={'id':m['id'],'competition_code':code,'competition':COMPETITIONS[code][0],
            'home':home.get('shortName') or home['name'],'away':away.get('shortName') or away['name'],
            'home_crest':home.get('crest'),'away_crest':away.get('crest'),
            'home_score':hs,'away_score':aws,'result_date':local.date().isoformat(),
            'kickoff_utc':kickoff.astimezone(timezone.utc).isoformat()}
    # Latest completed matchday of each league only: never fill the card with older rounds.
    latest={code:max((r['result_date'] for r in rows.values() if r['competition_code']==code),default=None) for code in LEAGUES}
    used={str(m['id']) for e in previous if e.get('status') in ('accepted','sent')
          and e.get('fixture_schedule',{}).get('date_mode')=='results'
          for m in e['fixture_schedule']['matches']}
    candidates=[r for r in rows.values() if r['result_date']==latest[r['competition_code']] and str(r['id']) not in used]
    # Rank prominent clubs first, but results cover all five leagues without the fixture popularity cutoff.
    matches,_=select(candidates,dict(c,football_featured_only=True,football_min_team_priority=0))
    if len(matches)>50:raise RuntimeError('More than 50 final results; refusing to silently omit scores')
    return {'date':post_day,'date_mode':'results','matches':matches,'checked_at':now.isoformat(),
            'source_url':'https://www.football-data.org/','sources':['football-data.org'],
            'selection':'latest_big_five_results','selected_count':len(matches),
            'total_available':len(candidates),'excluded_count':0,'lookback_days':7,
            'missing_leagues':sorted(code for code in LEAGUES if not any(m['competition_code']==code for m in matches))}


def results_content(schedule,c):
    from .content import finalize_content
    matches=schedule['matches']
    if not matches:raise RuntimeError('No new verified recent final scores; never publish an empty results card')
    dates=sorted({m['result_date'] for m in matches})
    description=('آخر النتائج النهائية المتاحة للدوريات الخمسة الكبرى، حتى '+schedule['date']+
                 '. نتائج مباريات '+ '، '.join(dates)+'. ليست مباريات الغد.\n'+
                 '\n'.join(f"{m['home']} {m['home_score']} — {m['away_score']} {m['away']} ({m['result_date']})" for m in matches)+
                 '\nالمصدر: football-data.org. قد لا تتوفر نتائج حديثة لكل دوري.')
    # Keep captions within the configured platform limit; every score remains visible on the cards.
    if len(description)>1200:description=description.split('\n')[0]+'\nجميع النتائج وتواريخها موضّحة في البطاقات. المصدر: football-data.org.'
    tags=['#نتائج_المباريات','#الدوريات_الخمس','#كرة_القدم','#نتائج_كرة_القدم','#TK_Servers']
    raw={'idea':'Latest verified big-five final scores '+schedule['date'],
         'title':'آخر نتائج الدوريات الخمس','description':description,'prompt':'Bundled approved black and gold stadium',
         'hashtags':tags,'safe_fictional_art':True}
    content=finalize_content(raw,dict(c,fixed_hashtags=[],hashtag_pool=tags),[])
    fingerprint=hashlib.sha256('|'.join(sorted(str(m['id']) for m in matches)).encode()).hexdigest()[:16]
    content.update(post_kind='football',subject_id='results:'+fingerprint,subject_title=raw['title'],
                   fixture_schedule=schedule,source_url=schedule['source_url'])
    return content
