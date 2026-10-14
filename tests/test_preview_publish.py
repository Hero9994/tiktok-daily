import hashlib
from datetime import timedelta
from test_project import NOW
import unittest
from unittest.mock import patch


class PreviewPublishTests(unittest.TestCase):
    def setUp(self):
        from test_daily_video import DailyVideoTests
        self.case=DailyVideoTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.c['approved_previews']={'show-now':{'day':'2026-10-13','track':'cinema'}}

    def test_one_extra_preview_preserves_daily_entries_and_cannot_repeat(self):
        c=self.case
        future={'day':'2026-10-14','status':'accepted','post_id':'future','due_at':(NOW+timedelta(days=1)).isoformat(),'idea':'future unrelated work'}
        c.store.state['entries']['future']=future
        c.buffer.posts['future']={'id':'future','status':'scheduled','schedulingType':'automatic'}
        c.store.state['entries'][f'{c.buffer.channel}:2026-10-13']={'day':'2026-10-13','status':'sent'}
        data=b'video';digest=hashlib.sha256(data).hexdigest()
        with patch('tiktok_daily.runner.make_video',return_value=(data,digest)):
            c.publisher('cinema').prepare(publish_now=True,preview_id='show-now')
            c.publisher('cinema').prepare(publish_now=True,preview_id='show-now')
            c.publisher('cinema').prepare(publish_now=True)
        self.assertEqual(c.buffer.creates,1)
        self.assertEqual(future['day'],'2026-10-14')
        self.assertEqual(c.c['daily_posts'][1]['time'],'18:00')
        preview=next(e for e in c.store.state['entries'].values() if e.get('preview_id'))
        self.assertEqual(preview['preview_id'],'show-now')

    def test_wrong_day_track_missing_approval_or_scheduled_preview_is_rejected(self):
        c=self.case
        for track,identifier,now in [('cinema','unknown',True),('football','show-now',True),('cinema','show-now',False)]:
            with self.subTest(track=track,identifier=identifier,now=now),self.assertRaises(RuntimeError):
                c.publisher(track).prepare(publish_now=now,preview_id=identifier)
        c.c['approved_previews']['show-now']['day']='2026-10-12'
        with self.assertRaises(RuntimeError):c.publisher('cinema').prepare(publish_now=True,preview_id='show-now')
        self.assertEqual(c.buffer.creates,0)
