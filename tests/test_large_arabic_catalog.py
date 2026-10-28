import copy
import json
import unittest
from unittest.mock import patch
from tiktok_daily.cinema_catalog import catalog,choose,used,quality_eligible,identity,approve_entry
from test_project import config


class LargeArabicCatalogTests(unittest.TestCase):
    def setUp(self):self.c=dict(config(),cinema_curated_only=True,cinema_arabic_every=2)
    def test_missing_imdb_is_not_a_match_for_every_old_entry(self):
        work=next(w for w in catalog(self.c) if w['rating_source']=='ElCinema' and not w.get('imdb_id'))
        self.assertFalse(used(work,[{'subject_imdb':None,'title':'عمل آخر'}]))
        self.assertTrue(used(work,[{'subject_elcinema':work['elcinema_id']}]))
        self.assertTrue(used(work,[{'subject_wikidata':work['wikidata_id']}]))
        e={'subject_id':identity(work),'subject_wikidata':work['wikidata_id'],'subject_imdb':None}
        self.assertEqual(approve_entry(self.c,e,[]),work)
    def test_regional_rating_is_explicit_and_not_allowed_without_proof(self):
        work=next(w for w in catalog(self.c) if w['rating_source']=='ElCinema')
        self.assertTrue(quality_eligible(work,self.c))
        for bad in ({'critic_rating':6.9},{'rating_votes_lower_bound':1},{'review_url':'https://elcinema.com/work/99999999/'},{'sexual_focus':True}):
            self.assertFalse(quality_eligible(dict(work,**bad),self.c))
    def test_both_languages_get_films_and_series_instead_of_fixed_global_parity(self):
        previous=[];observed={'ar':set(),'foreign':set()}
        for day in range(1,17):
            work=choose(self.c,f'2026-11-{day:02d}',previous,1)
            language='ar' if work.get('language')=='ar' else 'foreign'
            observed[language].add(work['kind'])
            self.assertEqual(language,'ar' if day%2==0 else 'foreign')
            previous.append({'status':'sent','post_kind':'cinema','subject_wikidata':work['wikidata_id'],'subject_imdb':work.get('imdb_id'),
                             'subject_elcinema':work.get('elcinema_id'),'cinema_review':work})
        self.assertEqual(observed,{'ar':{'film','series'},'foreign':{'film','series'}})
    def test_regional_series_balance_does_not_count_egyptian_films_against_egyptian_series(self):
        works=catalog(self.c);egfilm=next(w for w in works if w.get('production_country')=='EG' and w['kind']=='film')
        egseries=next(w for w in works if w.get('production_country')=='EG' and w['kind']=='series')
        syseries=next(w for w in works if w.get('production_country')=='SY' and w['kind']=='series')
        # Same regional series count; extra Egyptian films do not force every series to be Syrian.
        history=[{'status':'sent','post_kind':'cinema','cinema_review':egfilm} for _ in range(3)]
        with patch('tiktok_daily.cinema_catalog.catalog',return_value=[egseries,syseries]):
            countries={choose(self.c,f'2026-11-{d:02d}',history,1)['production_country'] for d in range(1,20)}
        self.assertEqual(countries,{'EG','SY'})
