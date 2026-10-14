import unittest
from datetime import date
from tiktok_daily.uefa import fixtures
from tiktok_daily.football import Football
from test_project import FakeHTTP


def match(id='1',comp='14',time='2026-10-15T19:00:00Z',status='UPCOMING'):
    return {'id':id,'competition':{'id':comp},'seasonYear':'2027','status':status,
            'kickOffTime':{'dateTime':time},'homeTeam':{'internationalName':'Home','translations':{'displayName':{'AR':'الفريق المضيف'}}},
            'awayTeam':{'internationalName':'Away'}}


class UEFAFixtureTests(unittest.TestCase):
    def test_official_europa_and_conference_are_included_with_utc_conversion(self):
        h=FakeHTTP([[match()], [match('2','2019','2026-10-15T21:30:00Z')]])
        result=fixtures(h,date(2026,10,15),['EL','ECL'])
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['home'],'الفريق المضيف')
        self.assertEqual(result[0]['germany_time'],'21:00')
        self.assertEqual(result[1]['makkah_date'],'2026-10-16')
        self.assertIn('competitionId=2019',h.calls[1][0])

    def test_wrong_season_missing_kickoff_or_invalid_response_never_means_no_matches(self):
        wrong=match();wrong['seasonYear']='2026'
        missing=match();missing['kickOffTime']={}
        for data in ({'error':'bad'},[wrong],[missing]):
            with self.subTest(data=data),self.assertRaises(RuntimeError):
                fixtures(FakeHTTP([data]),date(2026,10,15),['EL'])

    def test_cl_uses_official_source_without_duplicate_provider_record(self):
        from test_football import auto_config,fixture
        c=auto_config();c['uefa_competitions']=['CL','EL']
        h=FakeHTTP([{'matches':[fixture()]},[match('3','1','2026-10-14T19:00:00Z')],[]])
        result=Football(h,c,token='test').tomorrow('2026-10-13')
        self.assertEqual([m['id'] for m in result['matches']],['uefa:3'])
        self.assertEqual(result['sources'],['football-data.org','UEFA.com'])

    def test_today_and_tomorrow_select_different_dates(self):
        from test_football import auto_config,fixture
        c=auto_config();c['fixture_day']='today'
        result=Football(FakeHTTP([{'matches':[fixture()]}]),c,token='test').tomorrow('2026-10-14')
        self.assertEqual(result['date'],'2026-10-14')
        self.assertEqual(result['date_mode'],'today')


class EmptyGuardTests(unittest.TestCase):
    def test_empty_day_does_not_create_a_post_or_spend_generation_budget(self):
        from test_daily_video import DailyVideoTests,EmptyFootball
        case=DailyVideoTests();case.setUp();self.addCleanup(case.doCleanups)
        case.c['skip_empty_football']=True
        result=case.publisher('football',EmptyFootball()).prepare()
        self.assertIn('skipped',result)
        self.assertEqual(case.buffer.creates,0)
        self.assertEqual(case.ai.ideas,0)
        self.assertEqual(case.ai.images,0)
        self.assertEqual(case.store.state['entries'],{})


if __name__=='__main__':unittest.main()
