import unittest
from unittest.mock import patch
from tiktok_daily.cinema_catalog import catalog, choose, used, verify_source, approve_entry
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
            self.assertGreaterEqual(w['critic_rating'],4)
            self.assertEqual(w['rating_scale'],5)
            self.assertIn(w['sex_nudity'],('none','brief_romance_only'))
            self.assertTrue(w['review_url'].startswith('https://www.commonsensemedia.org/'))
        self.assertTrue(any(w['kind']=='series' for w in catalog(self.c)))

    def test_arabic_alias_and_any_canonical_identity_cannot_repeat(self):
        for field in ('subject_id','subject_wikidata','subject_imdb'):
            previous=[{field:self.entry()[field], 'title':'اسم آخر'}]
            self.assertTrue(used(self.work,previous))
            with self.assertRaises(ValueError):approve_entry(self.c,self.entry(),previous)

    def test_old_wikipedia_only_journal_entry_is_also_excluded(self):
        self.assertTrue(used(self.work,[{'subject_id':self.entry()['subject_id']}]))

    def test_exhausted_pool_stops_instead_of_recycling_or_selecting_unreviewed_work(self):
        previous=[{'subject_imdb':w['imdb_id']} for w in catalog(self.c)]
        with self.assertRaisesRegex(RuntimeError,'exhausted'):choose(self.c,'2026-10-15',previous,1)

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
        self.assertEqual(entry['cinema_details']['facts'][0]['label'],'تقييم Common Sense')

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
