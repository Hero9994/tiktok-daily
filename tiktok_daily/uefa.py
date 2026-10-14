"""Public fixtures from UEFA's own website feed. No paid provider/key."""
import urllib.parse
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo

UEFA = {'CL':('1','دوري أبطال أوروبا','#دوري_أبطال_أوروبا'),
        'EL':('14','الدوري الأوروبي','#الدوري_الأوروبي'),
        'ECL':('2019','دوري المؤتمر الأوروبي','#دوري_المؤتمر_الأوروبي')}


def fixtures(http,day,codes):
    start=datetime(day.year,day.month,day.day,tzinfo=ZoneInfo('Europe/Berlin')).astimezone(timezone.utc)
    end=(datetime(day.year,day.month,day.day,tzinfo=ZoneInfo('Europe/Berlin'))+timedelta(days=1)).astimezone(timezone.utc)
    season=day.year+1 if day.month>=7 else day.year
    matches=[]
    for code in codes:
        comp,label,_=UEFA[code]
        after=0
        while True:
            params=urllib.parse.urlencode({'competitionId':comp,'seasonYear':season,
                    'fromDate':start.date().isoformat(),'toDate':(end.date()+timedelta(days=1)).isoformat(),
                    'offset':after,'limit':100})
            data=http.json('https://match.uefa.com/v5/matches?'+params,safe_retry=True)
            if not isinstance(data,list):raise RuntimeError('UEFA fixture response invalid; do not infer an empty day')
            for item in data:
                if str(item.get('competition',{}).get('id'))!=comp or str(item.get('seasonYear'))!=str(season):
                    raise RuntimeError('UEFA returned a different competition or season')
                if item.get('status') in ('CANCELLED','POSTPONED','FINISHED','ENDED','ABANDONED','FORFEITED'):continue
                try:
                    kickoff=datetime.fromisoformat(item['kickOffTime']['dateTime'].replace('Z','+00:00'))
                except (KeyError,AttributeError,TypeError,ValueError):
                    raise RuntimeError('UEFA match has no confirmed kickoff time') from None
                if kickoff.tzinfo is None:raise RuntimeError('UEFA kickoff lacks timezone')
                if not start<=kickoff<end:continue
                if item.get('status')!='UPCOMING':raise RuntimeError('UEFA match status needs review')
                home,away=item.get('homeTeam',{}),item.get('awayTeam',{})
                def name(team):
                    return team.get('translations',{}).get('displayName',{}).get('AR') or team.get('internationalName')
                if not item.get('id') or not name(home) or not name(away) or home.get('isPlaceHolder') or away.get('isPlaceHolder'):
                    raise RuntimeError('Incomplete UEFA teams; do not invent a fixture')
                germany=kickoff.astimezone(ZoneInfo('Europe/Berlin'));makkah=kickoff.astimezone(ZoneInfo('Asia/Riyadh'))
                matches.append({'id':'uefa:'+str(item['id']),'competition_code':code,'competition':label,
                     'home':name(home),'away':name(away),'home_crest':home.get('mediumLogoUrl') or home.get('logoUrl'),
                     'away_crest':away.get('mediumLogoUrl') or away.get('logoUrl'),
                     'kickoff_utc':kickoff.astimezone(timezone.utc).isoformat(),
                     'germany_time':germany.strftime('%H:%M'),'germany_date':germany.date().isoformat(),
                     'makkah_time':makkah.strftime('%H:%M'),'makkah_date':makkah.date().isoformat(),
                     'source_url':'https://www.uefa.com/'})
            if len(data)<100:break
            after+=100
            if after>=1000:raise RuntimeError('UEFA pagination cap exceeded; refusing incomplete schedule')
    return sorted(matches,key=lambda m:(codes.index(m['competition_code']),m['kickoff_utc'],m['id']))
