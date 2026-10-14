import hashlib
import unittest
from unittest.mock import patch


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        from test_daily_video import DailyVideoTests
        self.case=DailyVideoTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.c['approved_corrections']={'test-fix':{'day':'2026-10-13','track':'football'}}

    def test_explicit_correction_is_allowed_once_and_normal_daily_post_does_not_repeat(self):
        case=self.case;data=b'video';digest=hashlib.sha256(data).hexdigest()
        with patch('tiktok_daily.runner.make_video',return_value=(data,digest)):
            case.publisher('football').prepare(publish_now=True)
            case.publisher('football').prepare(publish_now=True,correction_id='test-fix')
            case.publisher('football').prepare(publish_now=True,correction_id='test-fix')
            case.publisher('football').prepare(publish_now=True)
        self.assertEqual(case.buffer.creates,2)
        self.assertEqual(len(case.store.state['entries']),2)
        correction=next(e for e in case.store.state['entries'].values() if e.get('correction_id'))
        self.assertIn('تصحيح',correction['caption'])

    def test_unapproved_wrong_track_or_wrong_day_correction_is_rejected(self):
        case=self.case
        for kind,identifier in [('football','unknown'),('cinema','test-fix')]:
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):
                case.publisher(kind).prepare(publish_now=True,correction_id=identifier)
        case.c['approved_corrections']['test-fix']['day']='2026-10-12'
        with self.assertRaises(RuntimeError):case.publisher('football').prepare(publish_now=True,correction_id='test-fix')
        self.assertEqual(case.buffer.creates,0)


if __name__=='__main__':unittest.main()
