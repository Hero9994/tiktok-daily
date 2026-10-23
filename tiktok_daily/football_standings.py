"""Current complete TOTAL league tables from football-data.org, never inferred from scores."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from .football_selection import TEAMS,normalize

CODES=('PL','PD','BL1','SA','FL1')
EXPECTED={'PL':20,'PD':20,'BL1':18,'SA':20,'FL1':18}


def standings(http,c,token,post_day,now,previous=()):
    if not token:raise RuntimeError('FOOTBALL_DATA_API_KEY is required for league standings')
    from .football import COMPETITIONS
    names={normalize(alias):t['name_ar'] for t in json.loads(TEAMS.read_text())['teams'] for alias in t['aliases']+[t['name_ar']]}
    leagues=[]
    for code in CODES:
        data=http.json(f'https://api.football-data.org/v4/competitions/{code}/standings',
                       extra_headers={'X-Auth-Token':token},safe_retry=True)
        if data.get('competition',{}).get('code')!=code or data.get('error') or data.get('errorCode'):
            raise RuntimeError('Standings provider returned a different competition or error')
        totals=[t for t in data.get('standings',[]) if t.get('type')=='TOTAL']
        season=data.get('season',{})
        stage='season dates'
        try:
            start=datetime.fromisoformat(season['startDate']).date()
            end=datetime.fromisoformat(season['endDate']).date()
            current=now.astimezone(ZoneInfo('Europe/Berlin')).date()
            if not start<=current<=end or not season['id']:
                raise ValueError(f'season {start} to {end} does not cover {current}')
            stage=f'TOTAL tables={len(totals)}'
            table=totals[0]['table']
            stage=f'team count={len(table)}, expected={EXPECTED[code]}'
            if len(totals)!=1 or len(table)!=EXPECTED[code]:raise ValueError()
            rows=[];ids=set();positions=set()
            for item in table:
                team=item['team'];rank=item['position']
                stage=f'statistics at position {rank}'
                stats={k:item[k] for k in ('playedGames','won','draw','lost','points','goalsFor','goalsAgainst','goalDifference')}
                if any(type(v) is not int for v in stats.values()) or type(rank) is not int:raise ValueError()
                if min(stats[k] for k in ('playedGames','won','draw','lost','goalsFor','goalsAgainst'))<0:raise ValueError()
                if stats['playedGames']!=stats['won']+stats['draw']+stats['lost']:raise ValueError()
                if stats['goalDifference']!=stats['goalsFor']-stats['goalsAgainst']:raise ValueError()
                if not team['id'] or not team['name'] or team['id'] in ids or rank in positions:raise ValueError()
                ids.add(team['id']);positions.add(rank)
                label=team.get('shortName') or team['name']
                rows.append({'position':rank,'team_id':team['id'],'name':names.get(normalize(label),names.get(normalize(team['name']),label)),
                             'original_name':label,'crest':team.get('crest'),**stats})
            stage='unique consecutive positions'
            if positions!=set(range(1,len(table)+1)):raise ValueError()
        except (KeyError,ValueError,TypeError,IndexError):
            raise RuntimeError(f"{code}: invalid standings ({stage}; season={season.get('startDate')} to {season.get('endDate')}); no table was invented") from None
        rows.sort(key=lambda r:r['position'])
        leagues.append({'id':f"standings:{code}:{season['id']}",'competition_code':code,'competition':COMPETITIONS[code][0],
                        'season':f'{start.year}/{end.year}','table':rows})
    # Exclude only unchanged whole posts; reused team names are expected in updated tables.
    canonical=[{**league,'table':[{k:v for k,v in row.items() if k not in ('crest','name','original_name')} for row in league['table']]} for league in leagues]
    fingerprint=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    repeated=any(e.get('status') in ('accepted','sent') and e.get('fixture_schedule',{}).get('standings_hash')==fingerprint for e in previous)
    return {'date':post_day,'date_mode':'standings','matches':[] if repeated else leagues,
            'standings_hash':fingerprint,'unchanged_since_last_post':repeated,
            'checked_at':now.isoformat(),'source_url':'https://www.football-data.org/',
            'sources':['football-data.org'],'total_available':5,'selected_count':0 if repeated else 5,'excluded_count':0}


def standings_content(schedule,c):
    from .content import finalize_content
    if not schedule['matches']:raise RuntimeError('Standings have not changed; do not repeat an identical post')
    stamp=datetime.fromisoformat(schedule['checked_at']).astimezone(ZoneInfo('Europe/Berlin')).strftime('%d/%m/%Y %H:%M')
    description=f'ترتيب الدوريات الخمسة الكبرى حسب أحدث جدول متاح من المصدر، تحديث {stamp} بتوقيت ألمانيا.\n'
    description+='\n'.join(f"{league['competition']}: {league['table'][0]['name']} في الصدارة بـ{league['table'][0]['points']} نقطة." for league in schedule['matches'])
    description+='\nالترتيب الكامل، عدد المباريات، فارق الأهداف والنقاط في البطاقات. المصدر: football-data.org. يتغير الترتيب بعد تحديث النتائج.'
    tags=['#ترتيب_الدوريات','#الدوريات_الخمس','#كرة_القدم','#ترتيب_الفرق','#TK_Servers']
    raw={'idea':'Verified current big-five standings '+schedule['standings_hash'][:16],
         'title':'ترتيب الدوريات الخمسة الكبرى','description':description,
         'prompt':'Bundled approved black and gold stadium','hashtags':tags,'safe_fictional_art':True}
    entry=finalize_content(raw,dict(c,fixed_hashtags=[],hashtag_pool=tags),[])
    entry.update(post_kind='football',subject_id='standings:'+schedule['standings_hash'],subject_title=raw['title'],
                 fixture_schedule=schedule,source_url=schedule['source_url'])
    return entry
