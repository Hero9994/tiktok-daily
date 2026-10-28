import unittest
from unittest.mock import patch
from tiktok_daily.cinema_catalog import availability, age_eligible, catalog, choose, used, verify_source, approve_entry
from tiktok_daily.content import OpenAI
from tiktok_daily.runner import Publisher
from test_project import config, raw_content, FakeHTTP, FakeBuffer, FakeOpenAI, MemoryStore, NOW


class CinemaCatalogTests(unittest.TestCase):
    def setUp(self):
        self.c = config()
        self.c.update(cinema_curated_only=True, cinema_min_critic_rating=4, content_mode='cinema')
        self.work = catalog(self.c)[0]

    def entry(self):
        w=self.work
        return dict(subject_id=f"wikipedia-en:{w['wikipedia_pageid']}", subject_wikidata=w['wikidata_id'],
                    subject_imdb=w['imdb_id'],title='اسم عربي مختلف')

    def test_every_catalogue_work_is_high_rated_and_content_reviewed(self):
        for w in catalog(self.c):
            if w['rating_source']=='Common Sense Media':
                self.assertGreaterEqual(w['critic_rating'],4)
                self.assertEqual(w['rating_scale'],5)
                self.assertTrue(w['review_url'].startswith('https://www.commonsensemedia.org/'))
            else:
                self.assertIn(w['rating_source'],('IMDb','ElCinema'))
                self.assertGreaterEqual(w['critic_rating'],7)
                self.assertEqual(w['rating_scale'],10)
            self.assertIn(w['sex_nudity'],('none','brief_romance_only','occasional_mature'))
        self.assertTrue(any(w['kind']=='series' for w in catalog(self.c)))

    def test_old_work_needs_recent_top200_evidence(self):
        w=dict(self.work,release_year=1990)
        self.assertFalse(age_eligible(w,self.c,'2026-10-17'))
        w['top200']={'rank':200,'checked_at':'2026-10-16','source_url':'https://www.imdb.com/chart/top/','imdb_id':w['imdb_id']}
        self.assertTrue(age_eligible(w,self.c,'2026-10-17'))
        for changes in ({'rank':201},{'checked_at':'2026-01-01'},{'imdb_id':'tt999'},{'source_url':'https://example.com'}):
            bad=dict(w,top200=dict(w['top200'],**changes))
            self.assertFalse(age_eligible(bad,self.c,'2026-10-17'))

    def test_top200_does_not_override_explicit_content_exclusion(self):
        w=dict(self.work,sex_nudity='explicit')
        with patch('tiktok_daily.cinema_catalog.CATALOG') as source:
            import json
            source.read_text.return_value=json.dumps({'works':[w]})
            with self.assertRaises(RuntimeError):catalog(self.c,'2026-10-17')

    def test_arabic_alias_and_any_canonical_identity_cannot_repeat(self):
        for field in ('subject_id','subject_wikidata','subject_imdb'):
            previous=[{field:self.entry()[field], 'title':'اسم آخر'}]
            self.assertTrue(used(self.work,previous))
            with self.assertRaises(ValueError):approve_entry(self.c,self.entry(),previous)

    def test_old_wikipedia_only_journal_entry_is_also_excluded(self):
        self.assertTrue(used(self.work,[{'subject_id':self.entry()['subject_id']}]))

    def test_exhausted_pool_stops_instead_of_recycling_or_selecting_unreviewed_work(self):
        previous=[{'subject_wikidata':w['wikidata_id'],'subject_imdb':w.get('imdb_id')} for w in catalog(self.c)]
        with self.assertRaisesRegex(RuntimeError,'exhausted'):choose(self.c,'2026-10-15',previous,1)

    def test_exhaustion_stops_before_any_openai_call_or_budget_reservation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            ai=FakeOpenAI();ai.moderate=lambda *a,**k:self.fail('Exhausted catalogue must fail locally')
            buffer=FakeBuffer();store=MemoryStore(folder)
            store.state['entries']={f"old:{w['wikidata_id']}":{'status':'sent','subject_wikidata':w['wikidata_id'],'subject_imdb':w.get('imdb_id')} for w in catalog(self.c,'2026-10-14')}
            p=Publisher(self.c,store,ai,buffer,FakeHTTP(),lambda:NOW,sleep=lambda _:None)
            with self.assertRaisesRegex(RuntimeError,'exhausted'):p.prepare()
            self.assertEqual(store.state['text_requests'],{})
            self.assertEqual(buffer.creates,0)

    def test_availability_counts_aliases_as_used_before_the_pool_is_empty(self):
        previous=[{'subject_imdb':self.work['imdb_id']}]
        report=availability(self.c,'2026-10-28',previous)
        self.assertEqual(report['remaining'],report['eligible']-1)
        self.assertEqual(report['used'],1)

    def test_wrong_version_or_unreviewed_title_is_rejected(self):
        with self.assertRaises(ValueError):verify_source(self.work,{'pageid':1,'wikibase_item':self.work['wikidata_id']})
        bad=self.entry();bad['subject_imdb']='tt0000000'
        with self.assertRaises(ValueError):approve_entry(self.c,bad,[])

    def test_reviewed_selection_uses_one_summary_call_and_keeps_rating_source(self):
        w=self.work
        source={'type':'standard','pageid':w['wikipedia_pageid'],'wikibase_item':w['wikidata_id'],
                'title':w['wikipedia_title'],'extract':'An American science fiction film about visitors from space.'}
        http=FakeHTTP([source]);client=OpenAI(http,'local-test',self.c)
        client.reserve_text_request=lambda: self.fail('No extra paid selection call allowed')
        raw=raw_content();raw['description']='فيلم خيال علمي عن زوار من الفضاء.'
        with patch('tiktok_daily.content.choose',return_value=w), \
             patch.object(client,'structured',return_value=raw) as call, \
             patch('tiktok_daily.content.enrich',return_value={'cinema_details':{'facts':[], 'poster_url':'https://upload.wikimedia.org/poster.jpg'}}):
            entry=client.idea('2026-10-15',[],1)
        self.assertEqual(call.call_count,1)
        self.assertEqual(entry['subject_imdb'],w['imdb_id'])
        self.assertTrue(any(f['label']=='تقييم Common Sense' for f in entry['cinema_details']['facts']))

    def test_publisher_rejects_unreviewed_work_before_image_spend_or_post(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            ai=FakeOpenAI();b=FakeBuffer();store=MemoryStore(folder)
            p=Publisher(self.c,store,ai,b,FakeHTTP(),lambda:NOW,sleep=lambda _:None)
            with self.assertRaisesRegex(ValueError,'Unreviewed'):p.prepare()
            self.assertEqual(ai.images,0)
            self.assertEqual(b.creates,0)
            self.assertEqual(store.state['image_requests'],{})

    def test_reference_layout_keeps_long_facts_and_three_cast_names_readable(self):
        import io
        from PIL import Image
        from tiktok_daily.cards import render
        entry={'title':'الوصول','subject_title':'Arrival','summary':'نبذة عربية قصيرة دون حرق الأحداث.',
               'cinema_details':{'poster_url':'https://upload.wikimedia.org/poster.jpg',
                 'facts':[{'label':'سنة الإصدار','value':'2016'},
                          {'label':'بلد الإنتاج','value':'المملكة المتحدة والولايات المتحدة الأمريكية'},
                          {'label':'اللغة الأصلية','value':'الإنجليزية'}],
                 'genres':['دراما وخيال علمي','مغامرات واستكشاف'],
                 'cast':[{'name':name} for name in ['إيمي آدمز','جيرمي رينر','فورست ويتكر']]}}
        with patch('tiktok_daily.cards.artwork',return_value=Image.new('RGB',(600,900),'#273942')):
            cards=render(b'',entry,self.c)
        self.assertEqual(Image.open(io.BytesIO(cards[0])).size,(1080,1920))


if __name__=='__main__':unittest.main()
