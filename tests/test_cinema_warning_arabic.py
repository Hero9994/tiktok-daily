import copy
import json
import unittest
from unittest.mock import patch
from tiktok_daily.cinema_catalog import catalog,content_eligible,quality_eligible,CINEMA_WARNING,warn_caption,used,choose,identity
from tiktok_daily.content import OpenAI
from tiktok_daily.cards import render
from test_project import config,FakeHTTP,raw_content,FakeOpenAI


class ArabicWarningTests(unittest.TestCase):
    def setUp(self):
        self.c=config();self.c.update(cinema_curated_only=True,cinema_allow_occasional_mature=True,content_mode='cinema')
    def test_mature_content_requires_explicit_review_and_never_admits_spartacus(self):
        w=next(w for w in catalog(self.c) if w['sex_nudity']=='occasional_mature')
        self.assertTrue(content_eligible(w,self.c))
        self.assertFalse(content_eligible(w,dict(self.c,cinema_allow_occasional_mature=False)))
        for changes in ({'sexual_focus':True},{'imdb_id':'tt1442449'},{'imdb_id':'tt1758429'},{'sexual_focus':None},{'sex_nudity':'predominant'}):
            self.assertFalse(content_eligible(dict(w,**changes),self.c))
    def test_imdb_ratings_never_become_fabricated_common_sense_scores(self):
        w=next(w for w in catalog(self.c) if w['rating_source']=='IMDb')
        self.assertTrue(quality_eligible(w,self.c))
        for changes in ({'rating_votes_lower_bound':50},{'critic_rating':6},{'rating_url':'https://example.com/'},{'sexual_focus':True}):
            self.assertFalse(quality_eligible(dict(w,**changes),self.c))
    def test_warning_is_once_at_start_signature_stays_last_and_is_red_on_card(self):
        caption='نبذة قصيرة\n'+self.c['caption_suffix']
        warned=warn_caption(caption)
        self.assertTrue(warned.startswith(CINEMA_WARNING));self.assertTrue(warned.endswith(self.c['caption_suffix']))
        self.assertEqual(warn_caption(warned),warned)
        entry={'post_kind':'cinema','title':'مثال عربي','summary':'نبذة قصيرة','cinema_details':{'facts':[]}}
        with patch('tiktok_daily.cards.text') as text:
            render(FakeOpenAI().image('poster'),entry,self.c)
        warning=next(call for call in text.call_args_list if call.args[1]==CINEMA_WARNING)
        self.assertEqual(warning.kwargs['color'],'#ff7070')
    def test_arabic_wikipedia_identity_is_bound_to_imdb_and_qid(self):
        w=next(w for w in catalog(self.c) if w.get('wiki_language')=='ar')
        self.assertTrue(identity(w).startswith('wikipedia-ar:'))
        self.assertTrue(used(w,[{'subject_imdb':w['imdb_id'],'title':'عنوان إنجليزي آخر'}]))
        source={'type':'standard','pageid':w['wikipedia_pageid'],'wikibase_item':w['wikidata_id'],
                'title':w['wikipedia_title'],'extract':'مسلسل مصري تدور أحداثه حول العلاقات الإنسانية.'}
        http=FakeHTTP([source]);client=OpenAI(http,'dummy',self.c);client.reserve_text_request=lambda:None
        raw=raw_content();raw['description']='نبذة عن مسلسل مصري.'
        with patch('tiktok_daily.content.choose',return_value=w),patch.object(client,'structured',return_value=raw),patch('tiktok_daily.content.enrich',return_value={}):
            entry=client.cinema_idea('2026-10-28',[],1)
        self.assertIn('ar.wikipedia.org',http.calls[0][0])
        self.assertEqual(entry['subject_id'],identity(w));self.assertTrue(entry['caption'].startswith(CINEMA_WARNING))
    def test_arabic_turn_and_film_series_alternation_preserve_dedup(self):
        history=[{'post_kind':'cinema','status':'sent','subject_id':'unrelated:'+str(i)} for i in range(2)]
        work=choose(self.c,'2026-10-29',history,1)
        self.assertEqual(work.get('language'),'ar')
        self.assertEqual(work['kind'],'film')
        selected=choose(self.c,'2026-10-29',history+[{'subject_imdb':work['imdb_id']}],1)
        self.assertNotEqual(selected['imdb_id'],work['imdb_id'])
