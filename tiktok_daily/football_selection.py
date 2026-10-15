"""Editorial priorities, not invented live follower/popularity statistics."""
import json
import re
import unicodedata
from pathlib import Path

TEAMS=Path(__file__).resolve().parents[1]/'assets/football-teams.json'


def normalize(value):
    value=unicodedata.normalize('NFKD',value or '').casefold()
    value=''.join(c for c in value if not unicodedata.combining(c))
    value=value.translate(str.maketrans({'أ':'ا','إ':'ا','آ':'ا','ى':'ي','ة':'ه'}))
    return re.sub(r'[^\w]+','',value)


def select(matches,c):
    if not c.get('football_featured_only',False):
        return matches,{}
    teams=json.loads(TEAMS.read_text())['teams']
    aliases={normalize(alias):team for team in teams for alias in team['aliases']+[team['name_ar']]}
    selected=[]
    for source in matches:
        match=dict(source)
        home=aliases.get(normalize(match['home']))
        away=aliases.get(normalize(match['away']))
        ranks=[t['priority'] if t else 0 for t in (home,away)]
        if max(ranks)<c.get('football_min_team_priority',3):
            continue
        for side,team in [('home',home),('away',away)]:
            if team:
                match[side+'_original']=match[side]
                match[side]=team['name_ar']
        score=max(ranks)*150+min(ranks)*20
        score+= {'CL':35,'WC':30,'EC':25,'EL':10}.get(match['competition_code'],0)
        match['editorial_priority']=score
        selected.append(match)
    selected.sort(key=lambda m:(-m['editorial_priority'],m.get('kickoff_utc',''),str(m['id'])))
    return selected,{'selection':'editorial_featured','total_available':len(matches),
                     'selected_count':len(selected),'excluded_count':len(matches)-len(selected)}
