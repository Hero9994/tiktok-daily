"""Reviewed recommendations: quality threshold, explicit-content exclusion, canonical dedup."""
import hashlib
import json
import re
from datetime import date
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / 'assets/cinema-catalog.json'


def age_eligible(work, c, day=None):
    today=date.fromisoformat(day) if day else date.today()
    year=work.get('release_year')
    if type(year) is not int or year>today.year:
        return False
    if today.year-year<=c.get('cinema_max_age_years',15):
        return True
    evidence=work.get('top200',{})
    url='https://www.imdb.com/chart/toptv/' if work.get('kind')=='series' else 'https://www.imdb.com/chart/top/'
    try:
        reviewed=date.fromisoformat(evidence.get('checked_at',''))
    except (ValueError,TypeError):
        return False
    rank=evidence.get('rank')
    return (type(rank) is int and 1<=rank<=200 and evidence.get('source_url')==url
            and evidence.get('imdb_id')==work.get('imdb_id')
            and 0<=(today-reviewed).days<=30)


CINEMA_WARNING='تنبيه: قد يتضمن العمل مشاهد غير مناسبة'
EXCLUDED_IMDB={'tt1442449','tt1758429'}  # Spartacus and Gods of the Arena, explicitly excluded by the owner.


def identity(work):
    language=work.get('wiki_language','en')
    if language not in ('en','ar'):raise ValueError('Unsupported reviewed Wikipedia language')
    return f"wikipedia-{language}:{work['wikipedia_pageid']}"


def warn_caption(value):
    return value if value.startswith(CINEMA_WARNING) else CINEMA_WARNING+'\n\n'+value


def quality_eligible(w,c):
    source=w.get('rating_source','Common Sense Media')
    if source=='Common Sense Media':
        return (w.get('rating_scale')==5 and w.get('critic_rating',0)>=c.get('cinema_min_critic_rating',4)
                and w.get('review_url','').startswith('https://www.commonsensemedia.org/'))
    if source=='IMDb':
        return (w.get('rating_scale')==10 and 7<=w.get('critic_rating',0)<=10
                and type(w.get('rating_votes_lower_bound')) is int and w['rating_votes_lower_bound']>=1000
                and w.get('rating_url')==f"https://www.imdb.com/title/{w.get('imdb_id')}/"
                and (re.fullmatch(r'https://www\.netflix\.com/title/\d+',w.get('review_url','')) is not None
                     or w.get('review_url')==f"https://www.imdb.com/title/{w.get('imdb_id')}/parentalguide/")
                and w.get('sexual_focus') is False and bool(w.get('review_note')))
    return False


def content_eligible(w,c):
    if w.get('imdb_id') in EXCLUDED_IMDB or w.get('sexual_focus',False):return False
    if w.get('sex_nudity') in ('none','brief_romance_only'):return True
    return (c.get('cinema_allow_occasional_mature',False) and w.get('sex_nudity')=='occasional_mature'
            and w.get('sexual_focus') is False and bool(w.get('review_note')))


def catalog(c, day=None):
    works = json.loads(CATALOG.read_text())['works']
    eligible = [w for w in works if quality_eligible(w,c) and age_eligible(w,c,day) and content_eligible(w,c)]
    if not eligible:
        raise RuntimeError('No reviewed high-quality cinema titles are configured')
    return eligible


def used(work, previous):
    return any(e.get('subject_id') == identity(work)
               or e.get('subject_wikidata') == work['wikidata_id']
               or e.get('subject_imdb') == work['imdb_id']
               or e.get('subject_title', '').casefold() == work['wikipedia_title'].casefold()
               for e in previous)


def availability(c,day,previous):
    works=catalog(c,day)
    remaining=[w for w in works if not used(w,previous)]
    return {'eligible':len(works),'remaining':len(remaining),'used':len(works)-len(remaining)}


def choose(c, day, previous, attempt):
    available = [w for w in catalog(c,day) if not used(w, previous)]
    if not available:
        raise RuntimeError('Reviewed cinema catalogue exhausted; add reviewed works instead of repeating recommendations')
    history=[e for e in previous if e.get('post_kind')=='cinema' and e.get('status') in ('accepted','sent')]
    arabic=[w for w in available if w.get('language')=='ar']
    foreign=[w for w in available if w.get('language')!='ar']
    if arabic and foreign:
        available=arabic if (len(history)+1)%3==0 else foreign
    preferred='series' if len(history)%2 else 'film'
    kinds=[w for w in available if w.get('kind')==preferred]
    if kinds:available=kinds
    # Stable across retries; no paid selection request. The publisher reserves the summary call.
    offset = int(hashlib.sha256(day.encode()).hexdigest()[:8], 16)
    return available[(offset + attempt - 1) % len(available)]


def verify_source(work, source):
    if source.get('pageid') != work['wikipedia_pageid'] or source.get('wikibase_item') != work['wikidata_id']:
        raise ValueError('Cinema source identity differs from the reviewed work')


def approve_entry(c, entry, previous):
    work = next((w for w in catalog(c,entry.get('day')) if entry.get('subject_id') == identity(w)), None)
    if not work or entry.get('subject_wikidata') != work['wikidata_id'] or entry.get('subject_imdb') != work['imdb_id']:
        raise ValueError('Unreviewed cinema recommendation blocked; choose a reviewed high-quality title')
    if used(work, previous):
        raise ValueError('This film or series has already been recommended')
    return work
