import copy
import io
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
from PIL import Image
from tiktok_daily.football import Football,football_content
from tiktok_daily.football_results import latest_results
from tiktok_daily.cards import render
from test_football import auto_config,fixture
from test_project import FakeHTTP,FakeOpenAI

NOW=datetime(2026,10,23,10,tzinfo=timezone.utc)


def final(id=1,code='PL',when='2026-10-22T18:00:00Z',home=2,away=0):
    m=fixture(id,when,'FINISHED',code);m['score']={'fullTime':{'home':home,'away':away}}
    return m


class FootballResultsTests(unittest.TestCase):
    def result(self,rows,previous=()):
        return latest_results(FakeHTTP([{'matches':rows}]),auto_config(),'dummy','2026-10-23',NOW,previous)
    def test_latest_day_per_league_only_and_exact_score(self):
        s=self.result([final(1,when='2026-10-20T18:00:00Z'),final(2),final(3,'PD')])
        self.assertEqual({m['id'] for m in s['matches']},{2,3})
        self.assertEqual(s['matches'][0]['home_score'],2)
        self.assertEqual(s['matches'][0]['away_score'],0)
        self.assertEqual(len(s['missing_leagues']),3)
    def test_only_five_leagues_and_completed_not_live_or_stale(self):
        live=final(2);live['status']='IN_PLAY'
        s=self.result([final(),live,final(3,'CL'),final(4,when='2026-10-01T18:00:00Z'),final(5,when='2026-10-24T18:00:00Z')])
        self.assertEqual([m['id'] for m in s['matches']],[1])
    def test_invalid_or_missing_final_score_is_never_zero(self):
        for value in [None,-1,'2',True]:
            with self.subTest(value=value),self.assertRaises(RuntimeError):self.result([final(home=value)])
        with self.assertRaises(RuntimeError):
            latest_results(FakeHTTP([{}]),auto_config(),'dummy','2026-10-23',NOW)
    def test_results_already_accepted_or_sent_cannot_repeat(self):
        first=self.result([final()]);previous=[{'status':'sent','fixture_schedule':first}]
        self.assertEqual(self.result([final()],previous)['matches'],[])
        previous[0]['status']='image_ready'
        self.assertEqual(len(self.result([final()],previous)['matches']),1)
    def test_fallback_only_after_successfully_empty_selected_fixtures(self):
        c=dict(auto_config(),football_results_fallback=True,football_standings_fallback=False)
        provider=Football(FakeHTTP([]),c,token='dummy',clock=lambda:NOW)
        with patch.object(provider,'tomorrow',return_value={'matches':[{'id':9}]}),patch('tiktok_daily.football_results.latest_results') as fallback:
            self.assertEqual(provider.publication('2026-10-23')['matches'],[{'id':9}]);fallback.assert_not_called()
        with patch.object(provider,'tomorrow',side_effect=RuntimeError('provider down')),patch('tiktok_daily.football_results.latest_results') as fallback:
            with self.assertRaises(RuntimeError):provider.publication('2026-10-23')
            fallback.assert_not_called()
        with patch.object(provider,'tomorrow',return_value={'matches':[]}),patch('tiktok_daily.football_results.latest_results',return_value={'matches':[{'id':1}]}) as fallback:
            self.assertEqual(provider.publication('2026-10-23')['matches'],[{'id':1}]);fallback.assert_called_once()
    def test_final_scores_render_with_results_heading_and_real_dates(self):
        s=self.result([final()]);c=auto_config();entry=football_content(s,c)
        self.assertEqual(entry['title'],'آخر نتائج الدوريات الخمس')
        self.assertIn('2026-10-22',entry['caption'])
        self.assertTrue(entry['caption'].endswith(c['caption_suffix']))
        with patch('tiktok_daily.cards.crest',return_value=None),patch('tiktok_daily.cards.text') as text:
            cards=render(FakeOpenAI().image('stadium'),entry,c)
        labels=[call.args[1] for call in text.call_args_list]
        self.assertIn('آخر النتائج',labels);self.assertIn('0 – 2',labels)
        self.assertNotIn('مباريات الغد',labels);self.assertNotIn('ألمانيا',labels)
        self.assertEqual(Image.open(io.BytesIO(cards[0])).size,(1080,1920))
    def test_no_empty_results_content(self):
        with self.assertRaises(RuntimeError):football_content(self.result([]),auto_config())
