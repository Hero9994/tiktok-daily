import unittest
from datetime import datetime,timezone
from pathlib import Path
from tiktok_daily.config import load_config
from tiktok_daily.maintenance import maintain


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.c=load_config(Path(__file__).resolve().parents[1]/'config.json')
        self.calls=[];self.entries={}
        owner=self
        class P:
            def __init__(self,settings):self.kind=settings['post_kind']
            def prepare(self,publish_now=False):owner.calls.append((self.kind,publish_now));return self.kind
        self.factory=P
    def run_at(self,hour,minute=0,month=10,day=16):
        return maintain(self.c,self.entries,'channel',self.factory,datetime(2026,month,day,hour,minute,tzinfo=timezone.utc))
    def test_noon_prepares_both_tracks(self):
        self.run_at(10)
        self.assertEqual(self.calls,[('football',False),('cinema',False)])
    def test_hourly_wake_up_repairs_missed_sports_without_reposting_booked_cinema(self):
        self.entries['channel:2026-10-16:cinema']={'status':'accepted'}
        self.run_at(14,40)
        self.assertEqual(self.calls,[('football',True)])
    def test_booked_and_sent_are_skipped_without_any_generation_or_preflight(self):
        self.entries.update({'channel:2026-10-16:football':{'status':'sent'},'channel:2026-10-16:cinema':{'status':'accepted'}})
        self.run_at(11)
        self.assertEqual(self.calls,[])
    def test_near_deadline_is_reported_instead_of_silently_choosing_tomorrow(self):
        with self.assertRaisesRegex(RuntimeError,'not silently moved'):self.run_at(11,55)
        self.assertEqual(self.calls,[('cinema',False)])
    def test_night_never_generates_or_creates_an_early_tomorrow_post(self):
        self.run_at(22)
        self.assertEqual(self.calls,[])
    def test_winter_keeps_berlin_wall_time(self):
        self.entries['channel:2026-12-16:cinema']={'status':'accepted'}
        self.run_at(15,40,month=12,day=16)
        self.assertEqual(self.calls,[('football',True)])
    def test_user_pause_is_respected(self):
        self.c['daily_enabled']=False;self.run_at(8)
        self.assertEqual(self.calls,[])

    def test_nothing_is_generated_before_noon(self):
        self.run_at(9,59)
        self.assertEqual(self.calls,[])

    def test_new_schedule_does_not_change_today_booked_posts(self):
        self.entries['channel:2026-10-15:cinema']={'status':'accepted','due_at':'2026-10-15T16:00:00Z'}
        self.run_at(13,day=15)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.entries['channel:2026-10-15:cinema']['due_at'],'2026-10-15T16:00:00Z')

    def test_noon_preparation_tracks_berlin_winter_time(self):
        self.run_at(10,59,month=12,day=16)
        self.assertEqual(self.calls,[])
        self.run_at(11,month=12,day=16)
        self.assertEqual(self.calls,[('football',False),('cinema',False)])

    def test_prepare_time_must_be_before_both_publish_times(self):
        import json,tempfile
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json'
            for invalid in ['14:00','16:00','12:60']:
                c=dict(self.c,daily_prepare_time=invalid);path.write_text(json.dumps(c))
                with self.subTest(value=invalid),self.assertRaises(ValueError):load_config(path)

    def test_effective_date_must_be_a_real_iso_date(self):
        import json,tempfile
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json'
            for invalid in ['2026-02-30','tomorrow']:
                path.write_text(json.dumps(dict(self.c,schedule_effective_date=invalid)))
                with self.subTest(value=invalid),self.assertRaises(ValueError):load_config(path)
