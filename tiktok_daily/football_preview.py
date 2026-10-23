"""Read-only future-date preview; no Buffer/OpenAI connection or state mutations."""
import argparse
import json
from datetime import date
from pathlib import Path
from .cards import render
from .config import load_config
from .football import Football,football_content
from .http import HTTP
from .football_selection import select


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--post-day',required=True,type=date.fromisoformat)
    parser.add_argument('--standings',action='store_true',help='Preview verified current big-five standings only')
    parser.add_argument('--results',action='store_true',help='Preview verified recent final scores only')
    parser.add_argument('--output',type=Path,default=Path('preview-output'))
    args=parser.parse_args();c=load_config(Path('config.json'))
    provider=Football(HTTP(),c)
    if args.standings:
        from datetime import datetime,timezone
        from .football_standings import standings
        schedule=standings(provider.http,c,provider.token,args.post_day.isoformat(),datetime.now(timezone.utc))
    elif args.results:
        from datetime import datetime,timezone
        from .football_results import latest_results
        schedule=latest_results(provider.http,c,provider.token,args.post_day.isoformat(),datetime.now(timezone.utc))
    else:
        schedule=provider.publication(args.post_day.isoformat())
    print(json.dumps({'fixtures_day':schedule['date'],'mode':schedule.get('date_mode'),
                      'available':schedule.get('total_available'),'selected':len(schedule['matches']),
                      'preview_matches':schedule['matches']},ensure_ascii=False))
    args.output.mkdir(exist_ok=True,parents=True)
    (args.output/'fixtures.json').write_text(json.dumps(schedule,ensure_ascii=False,indent=2))
    if not schedule['matches']:
        print('No selected confirmed fixtures; no card was generated and no post will be fabricated');return
    entry=football_content(schedule,c);entry['preview']=True
    cards=render(Path(c['football_background']).read_bytes(),entry,c)
    for i,card in enumerate(cards): (args.output/f'card-{i+1}.jpg').write_bytes(card)
    print(json.dumps({'post_day':args.post_day.isoformat(),'fixtures_day':schedule['date'],
                      'selected':len(schedule['matches']),'available':schedule.get('total_available'),
                      'pages':len(cards),'published':False,'paid_api_requests':0}))


if __name__=='__main__':main()
