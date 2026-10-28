"""Bounded, source-backed replenishment. No AI requests and no publishing API access.

Automatic admission is deliberately narrower than the manually reviewed catalogue:
an editorial content guide and an IMDb-bound Wikimedia identity are both required.
"""
import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

from .cinema_catalog import age_eligible, content_eligible, quality_eligible, used
from .cinema_media import artwork
from .config import load_config
from .http import HTTP

ROOT = Path(__file__).resolve().parents[1]
CSM = 'https://www.commonsensemedia.org'
INDEX = CSM + '/reviews/sitemap.xml'
UA = 'TKDaily/1.0 (https://github.com/Hero9994/tiktok-daily; source-backed catalogue renewal)'
NS = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
REVIEW_URL = re.compile(r'https://www\.commonsensemedia\.org/(movie|tv)-reviews/[a-z0-9-]+')


class Rejected(ValueError):
    pass


def fetch(url):
    """Only editorial pages; bounded reads and same-host redirects, no credentials."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.commonsensemedia.org' or parsed.username or parsed.port:
        raise Rejected('Unsupported editorial source')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target=urllib.parse.urlsplit(newurl)
            if target.scheme!='https' or target.netloc!='www.commonsensemedia.org':
                raise Rejected('Editorial redirect changed host')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    opener = urllib.request.build_opener(Redirect)
    for attempt in range(3):
        try:
            with opener.open(req, timeout=25) as response:
                data = response.read(8_000_001)
            if len(data)>8_000_000:
                raise Rejected('Editorial source too large')
            return data.decode('utf-8')
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==2:
                raise RuntimeError('Editorial source unavailable') from None
        except (OSError,TimeoutError):
            if attempt==2:raise RuntimeError('Editorial source unavailable') from None
        time.sleep(2**attempt)


def plain(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', value)).split())


class ReviewHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.graphs=[];self.script=None;self.container=None;self.sex=None;self.button=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='script' and a.get('type')=='application/ld+json':self.script=''
        if tag=='div' and 'content-grid-content' in a.get('class','').split():
            self.container=a.get('data-text','')
        if tag=='button' and a.get('id')=='content-grid-item-sex':
            self.sex={'guide':plain(self.container or ''),'score':0,'label':''};self.button=True
        if self.button and tag=='i' and {'icon-circle-solid','active'}<=set(a.get('class','').split()):
            self.sex['score']+=1
    def handle_data(self, data):
        if self.script is not None:self.script+=data
        if self.button:self.sex['label']+=data
    def handle_endtag(self, tag):
        if tag=='script' and self.script is not None:
            try:self.graphs.extend(json.loads(self.script).get('@graph',[]))
            except (ValueError,AttributeError):pass
            self.script=None
        if tag=='button':self.button=False


def parse_review(url, document, c):
    if not REVIEW_URL.fullmatch(url):raise Rejected('Invalid review URL')
    parsed=ReviewHTML();parsed.feed(document)
    media_type='Movie' if '/movie-reviews/' in url else 'TVSeries'
    media=next((x for x in parsed.graphs if x.get('@type')==media_type and x.get('@id')==url+('#movie' if media_type=='Movie' else '#series')),None)
    # The review must rate this exact item, not a parent/user review or related title.
    review=next((x for x in parsed.graphs if x.get('@type')=='CriticReview' and x.get('url')==url),None)
    if not media or not review or review.get('itemReviewed',{}).get('@id')!=media.get('@id'):
        raise Rejected('Missing title-bound editorial rating')
    rating=review.get('reviewRating',{})
    try:score=float(rating['ratingValue']);scale=float(rating['bestRating'])
    except (KeyError,ValueError,TypeError):raise Rejected('Missing editorial rating') from None
    if scale!=5 or not c.get('cinema_min_critic_rating',4)<=score<=5:
        raise Rejected('Below editorial quality threshold')
    same=media.get('sameAs',[])
    if isinstance(same,str):same=[same]
    ids=[re.fullmatch(r'https://www\.imdb\.com/title/(tt\d+)/?',x) for x in same if isinstance(x,str)]
    imdb=next((x[1] for x in ids if x),None)
    if not imdb:raise Rejected('Editorial source lacks canonical IMDb identity')
    sex=parsed.sex
    if sex is None:raise Rejected('Missing editorial content guide')
    guide=sex['guide'];level=sex['score']
    if 'Not present' in sex['label'] and not guide and level==0:
        category='none';guide='Sex, Romance & Nudity: Not present.'
    else:
        # Do not infer absence from a synopsis. Only a complete, mild editorial guide.
        if not guide or not 1<=level<=2:raise Rejected('Sexual-content guide needs manual review')
        if re.search(r'\b(explicit|graphic|nudity|nude|naked|intercourse|porn\w*|erotic|sex scenes?|sexual violence|rape|strip\w*)\b',guide,re.I):
            raise Rejected('Sexual-content guide needs manual review')
        category='brief_romance_only' if level==1 and re.search(r'\b(kiss\w*|crush\w*|romanc\w*)\b',guide,re.I) and not re.search(r'\bsex\w*\b',guide,re.I) else 'occasional_mature'
    return {'name':media['name'],'imdb_id':imdb,'kind':'film' if media_type=='Movie' else 'series',
            'review_url':url,'rating_source':'Common Sense Media','critic_rating':score,'rating_scale':5,
            'sex_nudity':category,'sexual_focus':False,'review_note':'Automatic admission from the full editorial sexual-content guide; not a guarantee about every scene.',
            'content_evidence':{'source_url':url,'text':guide,'level':level,'sha256':hashlib.sha256(document.encode()).hexdigest()}}


def claims(entity, property_id):
    return [x['mainsnak']['datavalue']['value'] for x in entity.get('claims',{}).get(property_id,[])
            if 'datavalue' in x.get('mainsnak',{}) and x.get('rank')!='deprecated']


def resolve(review, http, deadline=None):
    """Search results are candidates only; the IMDb property must match exactly."""
    def read(url):
        if deadline is not None and time.monotonic()>=deadline:raise RuntimeError('Source review time budget exhausted')
        return http.json(url,safe_retry=False,timeout=15)
    q=urllib.parse.urlencode({'action':'query','list':'search','srsearch':review['name'],'srlimit':5,'format':'json'})
    result=read('https://en.wikipedia.org/w/api.php?'+q)
    for item in result.get('query',{}).get('search',[]):
        title=item.get('title','')
        source=read('https://en.wikipedia.org/api/rest_v1/page/summary/'+urllib.parse.quote(title.replace(' ','_'),safe=''))
        qid=source.get('wikibase_item','')
        if source.get('type')!='standard' or not re.fullmatch(r'Q\d+',qid):continue
        entity=read(f'https://www.wikidata.org/wiki/Special:EntityData/{qid}.json').get('entities',{}).get(qid,{})
        if review['imdb_id'] not in claims(entity,'P345'):continue
        extract=source.get('extract','')
        pattern=r'\bfilm\b' if review['kind']=='film' else r'\b(television|TV|series|miniseries)\b'
        if not re.search(pattern,extract[:600],re.I):raise Rejected('Work type could not be verified')
        years=[]
        release_dates=claims(entity,'P577') or (claims(entity,'P580') if review['kind']=='series' else [])
        for stamp in release_dates:
            if stamp.get('precision',0)>=9:
                match=re.match(r'\+(\d{4})-',stamp.get('time',''))
                if match:years.append(int(match[1]))
        if not years:raise Rejected('Missing verified release year')
        countries={x.get('id') for x in claims(entity,'P495')}
        languages={x.get('id') for x in claims(entity,'P364')}
        country=next((code for q,code in [('Q79','EG'),('Q858','SY'),('Q822','LB'),('Q851','SA')] if q in countries),None)
        poster=(source.get('originalimage') or source.get('thumbnail') or {}).get('source')
        if not poster:raise Rejected('No verifiable artwork')
        return dict(review,wikipedia_title=source['title'],wikipedia_pageid=source['pageid'],wikidata_id=qid,
                    wiki_language='en',release_year=min(years),language='ar' if languages & {'Q13955','Q29919','Q56467'} else 'en',
                    production_country=country,poster_url=poster,
                    identity_evidence={'source_url':source.get('content_urls',{}).get('desktop',{}).get('page'),
                                       'wikidata_url':f'https://www.wikidata.org/wiki/Special:EntityData/{qid}.json'})
    raise Rejected('No matching Wikipedia/Wikidata/IMDb identity')


def inventory(works,c,day,previous):
    eligible=[w for w in works if age_eligible(w,c,day) and quality_eligible(w,c) and content_eligible(w,c) and not used(w,previous)]
    return {'total':len(eligible),'arabic':sum(w.get('language')=='ar' for w in eligible),
            'foreign':sum(w.get('language')!='ar' for w in eligible),
            'films':sum(w.get('kind')=='film' for w in eligible),'series':sum(w.get('kind')=='series' for w in eligible)}


def needs_renewal(counts,c):
    return any(counts[group]<c.get('cinema_renewal_targets',{}).get(group,default)
               for group,default in [('total',60),('arabic',24),('foreign',30),('films',20),('series',20)])


def discover(state,get=fetch):
    index=ET.fromstring(get(INDEX))
    pages=[n.text for n in index.findall('s:sitemap/s:loc',NS) if n.text and re.fullmatch(re.escape(INDEX)+r'\?page=\d+',n.text)]
    if not pages:raise RuntimeError('Editorial discovery index changed; no catalogue entries were altered')
    pages.reverse()  # Newer editorial entries first; still cycle through the whole index.
    page=state.get('next_page',0)%len(pages)
    document=ET.fromstring(get(pages[page]));state['next_page']=(page+1)%len(pages)
    urls=[]
    for item in document.findall('s:url',NS):
        url=item.findtext('s:loc',default='',namespaces=NS)
        if REVIEW_URL.fullmatch(url):urls.append(url)
    return sorted(set(urls))


def replenish(c,works,state,previous,day,*,get=fetch,http=None,image_check=artwork,force=False):
    counts=inventory(works,c,day,previous)
    if not c.get('cinema_auto_renewal',False):return {'status':'disabled','added':0,'inventory':counts}
    if state.get('last_run')==day:
        return {'status':'already_checked_today','added':0,'inventory':counts,
                'needs_attention':state.get('last_report',{}).get('needs_attention',False)}
    if not force and not needs_renewal(counts,c):return {'status':'stock_sufficient','added':0,'inventory':counts}
    candidates=discover(state,get)
    known={w.get('review_url') for w in works}
    attempted=state.setdefault('attempted',{})
    cutoff=(date.fromisoformat(day)-timedelta(days=30)).isoformat()
    candidates=[u for u in candidates if u not in known and attempted.get(u,{}).get('day','')<cutoff]
    # Prefer the underrepresented work type. Rotate fairly instead of rechecking A-Z daily.
    preferred='/tv-reviews/' if counts['series']<counts['films'] else '/movie-reviews/'
    arabic_needed=counts['arabic']<c.get('cinema_renewal_targets',{}).get('arabic',24)
    regional_hint=re.compile(r'(arab|egypt|syri|leban|beirut|cairo|finding-ola|alrawabi|al-rawabi|wajd|theeb|capernaum)')
    # Discovery hints only; language/country are subsequently verified from Wikidata.
    candidates.sort(key=lambda u:(arabic_needed and not bool(regional_hint.search(u)),preferred not in u,
                                  hashlib.sha256((day+u).encode()).hexdigest()))
    checked=added=errors=0;http=http or HTTP()
    deadline=time.monotonic()+8*60
    seen=[*previous,*({'subject_wikidata':w['wikidata_id'],'subject_imdb':w.get('imdb_id'),'subject_elcinema':w.get('elcinema_id'),
                      'subject_title':w['wikipedia_title']} for w in works)]
    for url in candidates[:min(c.get('cinema_renewal_max_checks',12),20)]:
        if time.monotonic()>=deadline:break
        checked+=1
        try:
            review=parse_review(url,get(url),c)
            work=resolve(review,http,deadline=deadline)
            if used(work,seen):raise Rejected('Already catalogued or previously recommended')
            if not age_eligible(work,c,day):raise Rejected('Older than age limit without verified Top 200 evidence')
            if not quality_eligible(work,c) or not content_eligible(work,c):raise Rejected('Outside current content policy')
            # Do not keep filling foreign stock to hide an Arabic shortage (or vice versa).
            current=inventory(works,c,day,previous)
            group='arabic' if work['language']=='ar' else 'foreign'
            target=c.get('cinema_renewal_targets',{}).get(group,24 if group=='arabic' else 30)
            if not force and current[group]>=target and current['total']>=c.get('cinema_renewal_targets',{}).get('total',60):
                continue
            if not image_check(work['poster_url']):raise Rejected('Artwork could not be verified')
            work.update(reviewed_at=day,automatic_review=True)
            works.append(work);seen.append({'subject_wikidata':work['wikidata_id'],'subject_imdb':work['imdb_id']})
            attempted[url]={'day':day,'result':'added','imdb_id':work['imdb_id']};added+=1
        except Rejected as exc:
            attempted[url]={'day':day,'result':'rejected','reason':str(exc)}
        except (RuntimeError,ValueError,OSError,KeyError,TypeError):
            # Incomplete/failed sources are not approvals; retry them on the next run.
            errors+=1
        time.sleep(0.25)
        if added>=min(c.get('cinema_renewal_max_additions',4),6):break
    if errors==checked and checked:raise RuntimeError('All renewal sources failed; existing catalogue preserved')
    state['last_run']=day
    state['no_addition_runs']=0 if added else state.get('no_addition_runs',0)+1
    state['attempted']={k:v for k,v in attempted.items() if v['day']>=cutoff}
    report={'status':'checked','day':day,'checked':checked,'added':added,'source_errors':errors,
            'inventory':inventory(works,c,day,previous),'extra_openai_requests':0,
            'needs_attention':state['no_addition_runs']>=3 and needs_renewal(inventory(works,c,day,previous),c)}
    state['last_report']=report
    return report


def atomic_json(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(path)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--force',action='store_true',help='Check even above inventory target; daily limits still apply')
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--journal',type=Path);args=parser.parse_args()
    c=load_config(ROOT/'config.json');path=ROOT/'assets/cinema-catalog.json';state_path=ROOT/'assets/cinema-renewal.json'
    payload=json.loads(path.read_text());state=json.loads(state_path.read_text()) if state_path.exists() else {}
    # Journal read is mandatory: fail before discovery if it cannot be loaded.
    if args.journal:
        journal=json.loads(args.journal.read_text())
    else:
        result=subprocess.run(['git','show',f"origin/{c['state_branch']}:state.json"],cwd=ROOT,text=True,capture_output=True,check=True)
        journal=json.loads(result.stdout)
    if journal.get('version')!=1 or not isinstance(journal.get('entries'),dict):
        raise RuntimeError('Publication journal is invalid; renewal was not attempted')
    previous=list(journal['entries'].values())
    from datetime import datetime
    from zoneinfo import ZoneInfo
    day=datetime.now(ZoneInfo(c['timezone'])).date().isoformat()
    report=replenish(c,payload['works'],state,previous,day,force=args.force)
    print(json.dumps(report,ensure_ascii=False))
    if not args.dry_run:
        atomic_json(path,payload);atomic_json(state_path,state)
    output=os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output,'a') as f:f.write(f"added={report['added']}\nstatus={report['status']}\nneeds_attention={str(report.get('needs_attention',False)).lower()}\n")


if __name__=='__main__':
    main()
