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
    def run_at(self,hour,minute=0,month=10,day=15):
        return maintain(self.c,self.entries,'channel',self.factory,datetime(2026,month,day,hour,minute,tzinfo=timezone.utc))
    def test_morning_backup_run_prepares_both_tracks(self):
        self.run_at(6)
        self.assertEqual(self.calls,[('football',False),('cinema',False)])
    def test_hourly_wake_up_repairs_missed_sports_without_reposting_booked_cinema(self):
        self.entries['channel:2026-10-15:cinema']={'status':'accepted'}
        self.run_at(14,40)
        self.assertEqual(self.calls,[('football',True)])
    def test_booked_and_sent_are_skipped_without_any_generation_or_preflight(self):
        self.entries.update({'channel:2026-10-15:football':{'status':'sent'},'channel:2026-10-15:cinema':{'status':'accepted'}})
        self.run_at(8)
        self.assertEqual(self.calls,[])
    def test_near_deadline_is_reported_instead_of_silently_choosing_tomorrow(self):
        with self.assertRaisesRegex(RuntimeError,'not silently moved'):self.run_at(13,55)
        self.assertEqual(self.calls,[('cinema',False)])
    def test_night_never_generates_or_creates_an_early_tomorrow_post(self):
        self.run_at(22)
        self.assertEqual(self.calls,[])
    def test_winter_keeps_berlin_wall_time(self):
        self.entries['channel:2026-12-15:cinema']={'status':'accepted'}
        self.run_at(15,40,month=12,day=15)
        self.assertEqual(self.calls,[('football',True)])
    def test_user_pause_is_respected(self):
        self.c['daily_enabled']=False;self.run_at(8)
        self.assertEqual(self.calls,[])
