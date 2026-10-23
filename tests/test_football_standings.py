import copy
import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from tiktok_daily.football_standings import standings,standings_content,CODES,EXPECTED
from tiktok_daily.football import Football
from tiktok_daily.cards import render
from test_project import FakeHTTP,FakeOpenAI
from test_football import auto_config

NOW=datetime(2026,10,23,10,tzinfo=timezone.utc)


def table(code):
    rows=[{'position':i,'team':{'id':i,'name':'FC Barcelona' if i==1 else f'Team {i}','shortName':'Barcelona' if i==1 else f'Team {i}'},
           'playedGames':5,'won':3,'draw':1,'lost':1,'points':10,'goalsFor':8,'goalsAgainst':4,'goalDifference':4}
          for i in range(1,EXPECTED[code]+1)]
    return {'competition':{'code':code},'season':{'id':2026,'startDate':'2026-08-01','endDate':'2027-06-30'},
            'standings':[{'type':'TOTAL','group':None,'table':rows}]}


class StandingsTests(unittest.TestCase):
    def fetch(self,responses=None,previous=()):
        return standings(FakeHTTP(responses or [table(code) for code in CODES]),auto_config(),'dummy','2026-10-23',NOW,previous)
    def test_all_five_complete_tables_preserve_provider_order_and_points(self):
        s=self.fetch();self.assertEqual([m['competition_code'] for m in s['matches']],list(CODES))
        self.assertEqual(sum(len(m['table']) for m in s['matches']),96)
        self.assertEqual(s['matches'][0]['table'][0]['name'],'برشلونة')
        self.assertEqual(s['matches'][0]['table'][0]['points'],10)
    def test_missing_league_or_partial_table_or_duplicate_position_stops(self):
        for change in ('missing','partial','rank','score','season'):
            data=[table(code) for code in CODES]
            if change=='missing':data[0]['standings']=[]
            if change=='partial':data[0]['standings'][0]['table'].pop()
            if change=='rank':data[0]['standings'][0]['table'][1]['position']=1
            if change=='score':data[0]['standings'][0]['table'][0]['playedGames']=99
            if change=='season':data[0]['season']['endDate']='2025-06-01'
            with self.subTest(change=change),self.assertRaises(RuntimeError):self.fetch(data)
    def test_identical_table_not_reposted_but_changed_points_are_allowed(self):
        first=self.fetch();previous=[{'status':'sent','fixture_schedule':first}]
        self.assertEqual(self.fetch(previous=previous)['matches'],[])
        data=[table(code) for code in CODES];data[0]['standings'][0]['table'][0]['points']=9
        self.assertEqual(len(self.fetch(data,previous)['matches']),5)
    def test_deducted_points_remain_exact(self):
        data=[table(code) for code in CODES];data[0]['standings'][0]['table'][-1]['points']=-2
        self.assertEqual(self.fetch(data)['matches'][0]['table'][-1]['points'],-2)
    def test_fallback_and_cache_do_not_repeat_five_requests_during_one_prepare(self):
        c=dict(auto_config(),football_standings_fallback=True,football_results_fallback=False)
        http=FakeHTTP([table(code) for code in CODES]);provider=Football(http,c,token='dummy',clock=lambda:NOW)
        with patch.object(provider,'tomorrow',return_value={'matches':[]}):
            first=provider.publication('2026-10-23');second=provider.publication('2026-10-23')
        self.assertEqual(first,second);self.assertEqual(len(http.calls),5)
    def test_fixtures_remain_first_choice_and_failed_source_never_falls_back(self):
        provider=Football(FakeHTTP([]),dict(auto_config(),football_standings_fallback=True),token='dummy')
        with patch.object(provider,'tomorrow',return_value={'matches':[{'id':9}]}):self.assertEqual(provider.publication('2026-10-23')['matches'],[{'id':9}])
        with patch.object(provider,'tomorrow',side_effect=RuntimeError('down')):
            with self.assertRaises(RuntimeError):provider.publication('2026-10-23')
    def test_five_pages_show_tables_not_scores_and_caption_suffix(self):
        s=self.fetch();c=auto_config();entry=standings_content(s,c)
        self.assertTrue(entry['caption'].endswith(c['caption_suffix']))
        with patch('tiktok_daily.cards.crest',return_value=None),patch('tiktok_daily.cards.text') as text:
            pages=render(FakeOpenAI().image('stadium'),entry,c)
        self.assertEqual(len(pages),5)
        labels=[call.args[1] for call in text.call_args_list]
        self.assertIn('ترتيب الدوريات',labels);self.assertIn('نقاط',labels)
        self.assertNotIn('آخر النتائج',labels)
        with self.assertRaises(RuntimeError):standings_content(dict(s,matches=[]),c)
