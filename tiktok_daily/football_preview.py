"""Read-only future-date preview; no Buffer/OpenAI connection or state mutations."""
import argparse
import json
from datetime import date
from pathlib import Path
from .cards import render
from .config import load_config
from .football import Football,football_content
from .http import HTTP


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--post-day',required=True,type=date.fromisoformat)
    parser.add_argument('--output',type=Path,default=Path('preview-output'))
    args=parser.parse_args();c=load_config(Path('config.json'))
    schedule=Football(HTTP(),c).tomorrow(args.post_day.isoformat())
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
