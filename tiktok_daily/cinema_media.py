"""Work artwork and factual labels from Wikipedia/Wikidata; no invented ratings."""
import io
import re
import urllib.parse
import urllib.request
from PIL import Image
from .http import APIError


def values(entity, prop):
    return [s['mainsnak']['datavalue']['value'] for s in entity.get('claims', {}).get(prop, [])
            if s.get('rank') != 'deprecated' and 'datavalue' in s.get('mainsnak', {})]


def entity(http, qid):
    if not re.fullmatch(r'Q\d+', qid):
        raise ValueError('Invalid Wikidata identity')
    return http.json('https://www.wikidata.org/wiki/Special:EntityData/' + qid + '.json', safe_retry=True)['entities'][qid]


def label(item):
    labels = item.get('labels', {})
    return (labels.get('ar') or labels.get('en') or {}).get('value', '')


def enrich(http, source):
    qid = source.get('wikibase_item')
    if not qid:
        return {}  # Older saved entries/test sources remain renderable.
    work = entity(http, qid)
    art = (source.get('originalimage') or source.get('thumbnail') or {}).get('source')
    kind = 'مسلسل' if re.search(r'\b(?:television|documentary|animated) (?:\w+ ){0,3}series\b|\bminiseries\b', source.get('extract', ''), re.I) or 'مسلسل' in source.get('extract','') else 'فيلم'
    facts = [{'label': 'نوع العمل', 'value': kind}]
    imdb = values(work, 'P345')
    tvmaze_url = None
    tvmaze_cast = []
    if kind == 'مسلسل' and imdb and re.fullmatch(r'tt\d+', str(imdb[0])):
        try:
            show = http.json('https://api.tvmaze.com/lookup/shows?imdb=' + imdb[0], safe_retry=True)
            # Bind the show to its sourced external identifier, never a fuzzy title.
            if show.get('externals', {}).get('imdb') == imdb[0]:
                art = (show.get('image') or {}).get('original') or art
                rating = (show.get('rating') or {}).get('average')
                if type(rating) in (int, float) and 0 <= rating <= 10:
                    facts.append({'label': 'تقييم TVmaze', 'value': f'{rating:g} / 10'})
                tvmaze_url = show.get('url')
                if type(show.get('id')) is int:
                    members = http.json(f"https://api.tvmaze.com/shows/{show['id']}/cast", safe_retry=True)
                    for member in members[:4]:
                        person, character = member.get('person', {}), member.get('character', {})
                        picture = character.get('image') or person.get('image') or {}
                        if person.get('name'):
                            tvmaze_cast.append({'name': person['name'], 'image_url': picture.get('original') or picture.get('medium'),
                                                'source_url': person.get('url')})
        except APIError:
            pass  # Wikipedia remains the reference if the optional source fails.
    if not art:
        raise ValueError('This work has no reference artwork; choose another work')
    years = [v['time'][1:5] for v in values(work, 'P577') if isinstance(v, dict) and v.get('precision', 0) >= 9 and re.match(r'\+\d{4}', v.get('time', ''))]
    if years:
        facts.append({'label': 'سنة الإصدار', 'value': min(years)})
    for prop, heading in [('P2437', 'المواسم'), ('P1113', 'الحلقات'), ('P2047', 'المدة')]:
        v = values(work, prop)
        if v and isinstance(v[0], dict) and 'amount' in v[0]:
            if prop == 'P2047' and v[0].get('unit') != 'http://www.wikidata.org/entity/Q7727':
                continue
            facts.append({'label': heading, 'value': v[0]['amount'].lstrip('+') + (' دقيقة' if prop == 'P2047' else '')})
    genres = []
    for v in values(work, 'P136')[:3]:
        name = label(entity(http, v['id']))
        if name:
            genres.append(name)
    countries = values(work, 'P495')
    if countries:
        country = label(entity(http, countries[0]['id']))
        if country:
            facts.append({'label': 'بلد الإنتاج', 'value': country})
    languages = values(work, 'P364') or values(work, 'P407')
    if languages:
        language = label(entity(http, languages[0]['id']))
        if language:
            facts.append({'label': 'اللغة الأصلية', 'value': language})
    cast = []
    for v in ([] if tvmaze_cast else values(work, 'P161')[:4]):
        actor = entity(http, v['id'])
        pictures = values(actor, 'P18')
        name = label(actor)
        if name:
            cast.append({'name': name, 'image_url': ('https://commons.wikimedia.org/wiki/Special:FilePath/' + urllib.parse.quote(pictures[0], safe='') + '?width=300') if pictures else None,
                         'source_url': 'https://www.wikidata.org/wiki/' + v['id']})
    return {'cinema_details': {'poster_url': art, 'facts': facts[:6], 'genres': genres,
                               'cast': tvmaze_cast or cast, 'source_url': 'https://www.wikidata.org/wiki/' + qid,
                               'tvmaze_url': tvmaze_url}}


def artwork(url):
    """Bounded, HTTPS-only retrieval from the Wikimedia media hosts."""
    def allowed(value):
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme == 'https' and (parsed.hostname in {'upload.wikimedia.org', 'thumb.wikimedia.org', 'commons.wikimedia.org', 'static.tvmaze.com'} or re.fullmatch(r'media(?:[0-9]{4})?\.elcinema\.com',parsed.hostname or '') is not None)
    if not allowed(url):
        raise ValueError('Untrusted cinema media host')
    request = urllib.request.Request(url, headers={'User-Agent': 'TKDaily/1.0 (https://github.com/Hero9994/tiktok-daily; reference media)'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if not allowed(response.url):
            raise ValueError('Untrusted cinema media redirect')
        data = response.read(8_000_001)
    if len(data) > 8_000_000:
        raise ValueError('Cinema reference image too large')
    with Image.open(io.BytesIO(data)) as im:
        if im.width * im.height > 30_000_000:
            raise ValueError('Cinema reference dimensions too large')
        im.load()
        return im.convert('RGB')
