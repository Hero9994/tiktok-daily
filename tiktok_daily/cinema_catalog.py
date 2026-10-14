"""Reviewed recommendations: quality threshold, explicit-content exclusion, canonical dedup."""
import hashlib
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / 'assets/cinema-catalog.json'


def catalog(c):
    minimum = c.get('cinema_min_critic_rating', 4)
    works = json.loads(CATALOG.read_text())['works']
    eligible = [w for w in works if w['critic_rating'] >= minimum
                and w['rating_scale'] == 5
                and w['sex_nudity'] in ('none', 'brief_romance_only')
                and w.get('review_url', '').startswith('https://www.commonsensemedia.org/')]
    if not eligible:
        raise RuntimeError('No reviewed high-quality cinema titles are configured')
    return eligible


def used(work, previous):
    return any(e.get('subject_id') == f"wikipedia-en:{work['wikipedia_pageid']}"
               or e.get('subject_wikidata') == work['wikidata_id']
               or e.get('subject_imdb') == work['imdb_id']
               or e.get('subject_title', '').casefold() == work['wikipedia_title'].casefold()
               for e in previous)


def choose(c, day, previous, attempt):
    available = [w for w in catalog(c) if not used(w, previous)]
    if not available:
        raise RuntimeError('Reviewed cinema catalogue exhausted; add reviewed works instead of repeating recommendations')
    # Stable across retries; no paid selection request. The publisher reserves the summary call.
    offset = int(hashlib.sha256(day.encode()).hexdigest()[:8], 16)
    return available[(offset + attempt - 1) % len(available)]


def verify_source(work, source):
    if source.get('pageid') != work['wikipedia_pageid'] or source.get('wikibase_item') != work['wikidata_id']:
        raise ValueError('Cinema source identity differs from the reviewed work')


def approve_entry(c, entry, previous):
    work = next((w for w in catalog(c) if entry.get('subject_id') == f"wikipedia-en:{w['wikipedia_pageid']}"), None)
    if not work or entry.get('subject_wikidata') != work['wikidata_id'] or entry.get('subject_imdb') != work['imdb_id']:
        raise ValueError('Unreviewed cinema recommendation blocked; choose a reviewed high-quality title')
    if used(work, previous):
        raise ValueError('This film or series has already been recommended')
    return work
