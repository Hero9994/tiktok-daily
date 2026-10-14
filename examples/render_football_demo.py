"""Offline layout demo; fictional fixtures, no API keys or publication."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tiktok_daily.cards import render
from tiktok_daily.football import football_content

c = json.loads((ROOT / 'config.json').read_text())
games = [('ريال مدريد','بايرن ميونخ',86,5,'18:00','19:00'),
         ('مانشستر سيتي','إنتر ميلان',65,108,'20:00','21:00'),
         ('برشلونة','باريس سان جيرمان',81,524,'21:00','22:00')]
matches = [{'id':i+1,'competition_code':'CL','competition':'دوري أبطال أوروبا',
            'home':home,'away':away,'home_crest':f'https://crests.football-data.org/{hc}.png',
            'away_crest':f'https://crests.football-data.org/{ac}.png',
            'germany_time':germany,'makkah_time':makkah,
            'germany_date':'2026-10-15','makkah_date':'2026-10-15'}
           for i,(home,away,hc,ac,germany,makkah) in enumerate(games)]
entry = football_content({'date':'2026-10-15','matches':matches,
                         'checked_at':'2026-10-14T12:00:00Z','source_url':'https://www.football-data.org/'},c)
entry['demo'] = True
out = ROOT / 'output'
out.mkdir(exist_ok=True)
(out / 'football-premium-preview.jpg').write_bytes(render((ROOT / 'assets/football-stadium.jpg').read_bytes(),entry,c)[0])
print('Marked fictional preview saved; no publishing or paid image call.')
