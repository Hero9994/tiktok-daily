import copy
import json
import tempfile
import unittest
from pathlib import Path
from tiktok_daily.__main__ import activate_verified_schedule
from test_project import config


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        self.c = config(); self.c.update(daily_enabled=False, activate_after_first_success=True)
        self.path.write_text(json.dumps(self.c))
        owner = self
        class Store:
            root = owner.root
            state = {"entries": {"first": {"status": "sent", "post_id": "confirmed-id"}}}
            def __init__(self): self.calls = []; self.on_merge = None
            def git(self, *args):
                self.calls.append(args)
                if args[0] == "merge" and self.on_merge: self.on_merge()
        self.store = Store()

    def test_accepted_is_not_enough_to_enable_daily_posts(self):
        self.store.state = {"entries": {"first": {"status": "accepted"}}}
        self.assertFalse(activate_verified_schedule(self.store, self.path))
        self.assertEqual(self.store.calls, [])
        self.assertFalse(json.loads(self.path.read_text())["daily_enabled"])

    def test_activation_preserves_newer_owner_settings(self):
        def owner_update():
            c = copy.deepcopy(self.c); c["publish_time"] = "19:00"
            self.path.write_text(json.dumps(c))
        self.store.on_merge = owner_update
        self.assertTrue(activate_verified_schedule(self.store, self.path))
        updated = json.loads(self.path.read_text())
        self.assertTrue(updated["daily_enabled"])
        self.assertFalse(updated["activate_after_first_success"])
        self.assertEqual(updated["publish_time"], "19:00")
        self.assertIn(("push", "origin", "HEAD:refs/heads/main"), self.store.calls)

    def test_owner_disabling_automation_during_wait_is_respected(self):
        def owner_update():
            c = copy.deepcopy(self.c); c["enabled"] = False
            self.path.write_text(json.dumps(c))
        self.store.on_merge = owner_update
        self.assertFalse(activate_verified_schedule(self.store, self.path))
        self.assertFalse(any(args[0] == "push" for args in self.store.calls))

    def test_later_manual_pause_is_not_undone(self):
        c = copy.deepcopy(self.c); c.update(daily_enabled=False, activate_after_first_success=False)
        self.path.write_text(json.dumps(c))
        self.assertFalse(activate_verified_schedule(self.store, self.path))
        self.assertEqual(self.store.calls, [])


if __name__ == "__main__": unittest.main()
