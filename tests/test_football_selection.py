import copy
import unittest
from tiktok_daily.football_selection import select


def match(identifier,home,away,when='2026-10-17T18:00:00+00:00',code='PL'):
    return {'id':identifier,'home':home,'away':away,'competition_code':code,
            'kickoff_utc':when,'germany_time':'20:00','makkah_time':'21:00',
            'germany_date':'2026-10-17','makkah_date':'2026-10-17'}


class SelectionTests(unittest.TestCase):
    c={'football_featured_only':True,'football_min_team_priority':3}
    def test_big_clash_precedes_a_giant_against_unknown_and_small_clash_is_removed(self):
        source=[match(1,'Barcelona','Unlisted Club'),match(2,'Minor Home','Minor Away'),
                match(3,'Liverpool','Arsenal')]
        before=copy.deepcopy(source)
        selected,meta=select(source,self.c)
        self.assertEqual([m['id'] for m in selected],[3,1])
        self.assertEqual(meta['excluded_count'],1)
        self.assertEqual(source,before)
        self.assertEqual(selected[0]['home'],'ليفربول')
        self.assertEqual(selected[0]['germany_time'],source[2]['germany_time'])
        self.assertEqual(selected[0]['kickoff_utc'],source[2]['kickoff_utc'])
    def test_exact_aliases_allow_accents_and_arabic_but_not_reserve_sides(self):
        source=[match(1,'FC Bayern München','Other'),match(2,'Real Madrid B','Other'),match(3,'ريال مدريد','Other')]
        selected,_=select(source,self.c)
        self.assertEqual({m['id'] for m in selected},{1,3})
    def test_two_unlisted_teams_do_not_become_popular_just_because_competition_is_cl(self):
        selected,_=select([match(1,'Small A','Small B',code='CL')],self.c)
        self.assertEqual(selected,[])
    def test_priority_ties_are_chronological_and_unknown_teams_can_face_popular_opponents(self):
        source=[match(1,'Chelsea','Minor A','2026-10-17T20:00:00+00:00'),
                match(2,'Minor B','Chelsea','2026-10-17T16:00:00+00:00')]
        selected,_=select(source,self.c)
        self.assertEqual([m['id'] for m in selected],[2,1])
    def test_disabling_filter_preserves_original_order_and_all_fixtures(self):
        source=[match(1,'Small A','Small B')]
        selected,meta=select(source,{'football_featured_only':False})
        self.assertEqual(selected,source)
        self.assertEqual(meta,{})

    def test_barca_short_name_is_recognized_and_low_priority_translations_do_not_qualify(self):
        selected,_=select([match(1,'Barça','Real Betis'),match(2,'Everton','Ipswich Town')],self.c)
        self.assertEqual([m['id'] for m in selected],[1])
        self.assertEqual(selected[0]['home'],'برشلونة')

    def test_transient_badge_download_is_retried_and_success_is_cached(self):
        import io
        from types import SimpleNamespace
        from unittest.mock import patch,MagicMock
        from urllib.error import URLError
        from PIL import Image
        from tiktok_daily.cards import crest
        url='https://crests.football-data.org/999999.png'
        raw=io.BytesIO();Image.new('RGBA',(80,80),'gold').save(raw,format='PNG')
        context=MagicMock()
        context.__enter__.return_value=SimpleNamespace(url=url,read=lambda limit:raw.getvalue())
        crest.cache_clear()
        self.addCleanup(crest.cache_clear)
        with patch('tiktok_daily.cards.urllib.request.urlopen',side_effect=[URLError('temporary'),context]) as request, \
             patch('tiktok_daily.cards.time.sleep'):
            self.assertIsNotNone(crest(url))
            self.assertIsNotNone(crest(url))
        self.assertEqual(request.call_count,2)
