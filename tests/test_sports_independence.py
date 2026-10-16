import hashlib
import unittest
from unittest.mock import patch
from tiktok_daily.http import APIError
from tiktok_daily.maintenance import maintain
from tiktok_daily.runner import static_football


class SportsIndependenceTests(unittest.TestCase):
    def setUp(self):
        from test_daily_video import DailyVideoTests
        self.case=DailyVideoTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
    def test_static_sports_publishes_without_any_openai_call(self):
        c=self.case
        c.ai.moderate=lambda *a,**k:(_ for _ in ()).throw(APIError('OpenAI',401,code='invalid_api_key'))
        c.ai.image=lambda *a,**k:self.fail('Sports must use bundled stadium')
        c.ai.idea=lambda *a,**k:self.fail('Sports must use verified fixtures')
        video=b'test-video'
        with patch('tiktok_daily.runner.make_video',return_value=(video,hashlib.sha256(video).hexdigest())):
            c.publisher('football').prepare(publish_now=True)
        self.assertEqual(c.buffer.creates,1)
        self.assertEqual(c.store.state['text_requests'],{})
        self.assertEqual(c.store.state['image_requests'],{})
    def test_cinema_still_stops_on_invalid_key(self):
        c=self.case
        c.ai.moderate=lambda *a,**k:(_ for _ in ()).throw(APIError('OpenAI',401,code='invalid_api_key'))
        with self.assertRaises(APIError):c.publisher('cinema').prepare(publish_now=True)
        self.assertEqual(c.buffer.creates,0)
    def test_broken_cinema_does_not_undo_or_prevent_sports_preparation(self):
        from datetime import datetime,timezone
        c=self.case;c.c['schedule_effective_date']='2026-10-01'
        calls=[]
        class P:
            def __init__(self,settings):self.kind=settings['post_kind']
            def prepare(self,publish_now=False):
                calls.append(self.kind)
                if self.kind=='cinema':raise APIError('OpenAI',401,code='invalid_api_key')
                return 'sports booked'
        with self.assertRaisesRegex(RuntimeError,'invalid_api_key'):
            maintain(c.c,{},'channel',P,datetime(2026,10,16,10,tzinfo=timezone.utc))
        self.assertEqual(calls,['football','cinema'])
    def test_generated_or_unbundled_football_art_keeps_openai_checks(self):
        self.assertFalse(static_football({'content_mode':'football','card_style':'simple'}))
        self.assertFalse(static_football({'content_mode':'football','card_style':'black_gold','football_background':None}))
