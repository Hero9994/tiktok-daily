import copy
import json
import unittest
from unittest.mock import patch

from tiktok_daily.cinema_renewal import (CSM, INDEX, Rejected, discover, inventory,
                                       needs_renewal, parse_review, replenish, resolve)
from test_project import config

URL=CSM+'/movie-reviews/example'


def document(*,rating=5,sex='Not present',guide='',level=0,kind='Movie',bound=True):
    fragment='#movie' if kind=='Movie' else '#series'
    graph=[{'@type':kind,'@id':URL+fragment,'name':'Example','sameAs':'https://www.imdb.com/title/tt12345/'},
           {'@type':'CriticReview','url':URL,'itemReviewed':{'@id':URL+fragment if bound else 'other'},
            'reviewRating':{'ratingValue':str(rating),'bestRating':'5'}}]
    import html
    return ('<script type="application/ld+json">'+json.dumps({'@graph':graph})+'</script>'
            '<div class="content-grid-content" data-text="'+html.escape(guide,quote=True)+'">'
            '<button id="content-grid-item-sex">'+sex+'<i class="active"></i>'
            +'<i class="icon-circle-solid active"></i>'*level+'</button></div>')


def work():
    return dict(parse_review(URL,document(),config()),wikipedia_title='Example (film)',wikipedia_pageid=123,
                wikidata_id='Q123',release_year=2024,imdb_id='tt12345',kind='film',poster_url='https://upload.wikimedia.org/example.jpg',language='en')


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.c=dict(config(),cinema_auto_renewal=True,cinema_allow_occasional_mature=True,
                    cinema_renewal_max_checks=2,cinema_renewal_max_additions=1)

    def test_only_bound_editorial_scores_are_used(self):
        self.assertEqual(parse_review(URL,document(),self.c)['critic_rating'],5)
        for source in (document(rating=3),document(bound=False),document().replace('CriticReview','AggregateRating')):
            with self.assertRaises(Rejected):parse_review(URL,source,self.c)

    def test_full_content_guide_not_truncated_teaser(self):
        source=document(sex='Kissing',guide='Kissing initially; later graphic nudity.',level=1)
        with self.assertRaises(Rejected):parse_review(URL,source,self.c)
        with self.assertRaises(Rejected):parse_review(URL,document(sex='',guide='',level=1),self.c)
        with self.assertRaises(Rejected):parse_review(URL,document().replace('content-grid-item-sex','other'),self.c)

    def test_warning_category_requires_evidence_not_genre(self):
        self.assertEqual(parse_review(URL,document(),self.c)['sex_nudity'],'none')
        mild=parse_review(URL,document(sex='Kissing',guide='A couple kisses.',level=1),self.c)
        self.assertEqual(mild['sex_nudity'],'brief_romance_only')
        mature=parse_review(URL,document(sex='References',guide='Adults make suggestive jokes.',level=2),self.c)
        self.assertEqual(mature['sex_nudity'],'occasional_mature')
        with self.assertRaises(Rejected):parse_review(URL,document(sex='References',guide='Adults make jokes.',level=3),self.c)

    def test_sitemap_accepts_only_canonical_review_urls(self):
        index=f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>{INDEX}?page=1</loc></sitemap><sitemap><loc>https://evil.test/reviews/sitemap.xml?page=1</loc></sitemap></sitemapindex>'
        urls=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{URL}</loc></url><url><loc>{URL}/user-reviews/adult</loc></url></urlset>'
        state={};calls=[]
        def get(url):calls.append(url);return index if url==INDEX else urls
        self.assertEqual(discover(state,get),[URL]);self.assertEqual(calls,[INDEX,INDEX+'?page=1'])

    def test_sufficient_stock_does_not_fetch_sources(self):
        works=[dict(work(),wikidata_id=f'Q{x}',imdb_id=f'tt{x}') for x in range(70)]
        c=dict(self.c,cinema_renewal_targets={'total':20,'arabic':1,'foreign':20,'films':1,'series':1})
        works[0].update(language='ar',kind='series')
        report=replenish(c,works,{},[],'2026-10-29',get=lambda _:self.fail('No source read needed'))
        self.assertEqual(report['status'],'stock_sufficient')

    def test_limits_and_same_day_reruns_prevent_overfilling(self):
        state={};works=[]
        with patch('tiktok_daily.cinema_renewal.discover',return_value=[URL,URL+'2']),patch('tiktok_daily.cinema_renewal.resolve',return_value=work()),patch('tiktok_daily.cinema_renewal.time.sleep'):
            report=replenish(self.c,works,state,[],'2026-10-29',get=lambda _:document(),image_check=lambda _:True)
        self.assertEqual(report['added'],1);self.assertLessEqual(report['checked'],2)
        self.assertEqual(report['extra_openai_requests'],0)
        second=replenish(self.c,works,state,[],'2026-10-29',get=lambda _:self.fail('No repeated scan'),force=True)
        self.assertEqual(second['status'],'already_checked_today')

    def test_alias_of_previously_posted_work_is_rejected_before_artwork(self):
        previous=[{'subject_imdb':'tt12345','subject_title':'عنوان مختلف'}];works=[];state={}
        with patch('tiktok_daily.cinema_renewal.discover',return_value=[URL]),patch('tiktok_daily.cinema_renewal.resolve',return_value=work()),patch('tiktok_daily.cinema_renewal.time.sleep'):
            report=replenish(self.c,works,state,previous,'2026-10-29',get=lambda _:document(),image_check=lambda _:self.fail('Duplicate artwork not needed'))
        self.assertEqual(report['added'],0);self.assertEqual(works,[])
        self.assertIn('previously',state['attempted'][URL]['reason'])

    def test_old_or_unverified_artwork_never_enters_catalogue(self):
        for changes,check in [({'release_year':1980},lambda _:True),({},lambda _:False)]:
            works=[]
            with patch('tiktok_daily.cinema_renewal.discover',return_value=[URL]),patch('tiktok_daily.cinema_renewal.resolve',return_value=dict(work(),**changes)),patch('tiktok_daily.cinema_renewal.time.sleep'):
                report=replenish(self.c,works,{},[],'2026-10-29',get=lambda _:document(),image_check=check)
            self.assertEqual(report['added'],0);self.assertEqual(works,[])

    def test_total_source_outage_does_not_claim_success(self):
        works=[work()];before=copy.deepcopy(works)
        with patch('tiktok_daily.cinema_renewal.discover',return_value=[URL+'2']),patch('tiktok_daily.cinema_renewal.time.sleep'):
            with self.assertRaises(RuntimeError):replenish(self.c,works,{},[],'2026-10-29',get=lambda _:(_ for _ in ()).throw(OSError()))
        self.assertEqual(works,before)

    def test_stagnation_alerts_before_stock_runs_out(self):
        state={'no_addition_runs':2}
        with patch('tiktok_daily.cinema_renewal.discover',return_value=[]):
            report=replenish(self.c,[],state,[],'2026-10-29')
        self.assertTrue(report['needs_attention'])

    def test_identity_search_never_accepts_title_alone(self):
        class Fake:
            def json(self,url,**kwargs):
                if 'list=search' in url:return {'query':{'search':[{'title':'Example'}]}}
                if 'summary' in url:return {'type':'standard','wikibase_item':'Q1','pageid':1,'title':'Example','extract':'Example is a film.'}
                return {'entities':{'Q1':{'claims':{'P345':[{'mainsnak':{'datavalue':{'value':'tt999'}}}]}}}}
        with self.assertRaises(Rejected):resolve(work(),Fake())

    def test_matching_identity_uses_release_evidence_not_review_date(self):
        def claim(v):return {'mainsnak':{'datavalue':{'value':v}}}
        class Fake:
            def json(self,url,**kwargs):
                if 'list=search' in url:return {'query':{'search':[{'title':'Example'}]}}
                if 'summary' in url:return {'type':'standard','wikibase_item':'Q1','pageid':1,'title':'Example','extract':'Example is a film.', 'originalimage':{'source':'https://upload.wikimedia.org/example.jpg'}}
                return {'entities':{'Q1':{'claims':{'P345':[claim('tt12345')],
                    'P577':[claim({'time':'+2000-01-01T00:00:00Z','precision':11}),claim({'time':'+2025-01-01T00:00:00Z','precision':11})],
                    'P364':[claim({'id':'Q13955'})],'P495':[claim({'id':'Q79'})]}}}}
        result=resolve(work(),Fake())
        self.assertEqual(result['release_year'],2000)
        self.assertEqual(result['language'],'ar');self.assertEqual(result['production_country'],'EG')

    def test_tv_sources_bind_their_own_series_id(self):
        url=CSM+'/tv-reviews/example'
        source=document(kind='TVSeries').replace(URL,url)
        self.assertEqual(parse_review(url,source,self.c)['kind'],'series')

    def test_rerun_keeps_stagnation_alert_until_recovered(self):
        state={'last_run':'2026-10-29','last_report':{'needs_attention':True}}
        report=replenish(self.c,[],state,[],'2026-10-29')
        self.assertTrue(report['needs_attention'])
