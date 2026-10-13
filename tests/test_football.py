import copy
import io
import unittest
from datetime import datetime, timezone
from PIL import Image
from tiktok_daily.football import Football, football_content
from tiktok_daily.cards import render
from tiktok_daily.content import finalize_content
from tiktok_daily.runner import Publisher
from test_project import config, raw_content, FakeHTTP, FakeOpenAI, FakeBuffer, MemoryStore, NOW


def fixture(id=1, when="2026-10-14T18:00:00Z", status="TIMED", code="CL"):
    return {"id": id, "utcDate": when, "status": status, "competition": {"code": code},
            "homeTeam": {"name": "FC Barcelona", "shortName": "Barcelona"},
            "awayTeam": {"name": "FC Bayern München", "shortName": "Bayern"}}


def auto_config():
    c = config()
    c.update(content_mode="auto", card_style="black_gold", timezone="Europe/Berlin", publish_time="18:00",
             prepare_lead_minutes=15, fixed_caption=None, fixed_hashtags=[],
             caption_suffix="شاهدها على سيرفراتنا بجودة عالية وبدون تقطيع ⚡🏆")
    return c


class FootballTests(unittest.TestCase):
    def test_tomorrow_uses_berlin_date_and_filters_utc_boundaries(self):
        http = FakeHTTP([{"matches": [fixture(1, "2026-10-13T22:15:00Z"), fixture(2, "2026-10-14T21:30:00Z"),
                                       fixture(3, "2026-10-14T22:15:00Z")]}])
        data = Football(http, auto_config(), token="dummy", clock=lambda: NOW).tomorrow("2026-10-13")
        self.assertEqual(data["date"], "2026-10-14")
        self.assertEqual([m["id"] for m in data["matches"]], [1, 2])
        self.assertEqual(data["matches"][1]["germany_time"], "23:30")
        self.assertEqual(data["matches"][1]["makkah_date"], "2026-10-15")
        self.assertEqual(http.calls[0][2]["extra_headers"]["X-Auth-Token"], "dummy")

    def test_dst_changes_offset_in_winter(self):
        http = FakeHTTP([{"matches": [fixture(1, "2026-12-14T18:00:00Z")]}])
        data = Football(http, auto_config(), token="dummy").tomorrow("2026-12-13")
        self.assertEqual(data["matches"][0]["germany_time"], "19:00")
        self.assertEqual(data["matches"][0]["makkah_time"], "21:00")

    def test_unknown_schedule_is_not_treated_as_no_matches(self):
        for data in [{}, {"matches": [] , "errorCode": 403}, {"matches": [fixture(status="SCHEDULED")]}]:
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                Football(FakeHTTP([data]), auto_config(), token="dummy").tomorrow("2026-10-13")

    def test_cancelled_and_uncovered_games_do_not_appear(self):
        data = Football(FakeHTTP([{"matches": [fixture(status="CANCELLED"), fixture(2, code="UNKNOWN")]}]), auto_config(), token="dummy").tomorrow("2026-10-13")
        self.assertEqual(data["matches"], [])

    def test_signature_last_and_dynamic_description(self):
        c = auto_config()
        first = finalize_content(raw_content(), c, [])
        raw = raw_content(); raw.update(idea="A different concept under a silent alien sky", description="نبذة أخرى جديدة", hashtags=["#خيال", "#فن", "#طبيعة", "#إبداع", "#تصميم"])
        second = finalize_content(raw, c, [first])
        self.assertNotEqual(first["caption"], second["caption"])
        self.assertTrue(second["caption"].endswith(c["caption_suffix"]))
        self.assertEqual(len(second["hashtags"]), 5)

    def test_more_than_six_games_render_all_pages(self):
        provider = Football(FakeHTTP([{"matches": [fixture(i) for i in range(1, 9)]}]), auto_config(), token="dummy", clock=lambda: NOW)
        entry = football_content(provider.tomorrow("2026-10-13"), auto_config())
        cards = render(FakeOpenAI().image("stadium"), entry, auto_config())
        self.assertEqual(len(cards), 2)
        self.assertEqual(Image.open(io.BytesIO(cards[0])).size, (1080, 1920))
        self.assertEqual(len(entry["fixture_schedule"]["matches"]), 8)
        self.assertTrue(entry["caption"].endswith(auto_config()["caption_suffix"]))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store, self.generator, self.buffer, self.http = MemoryStore(self.temp.name), FakeOpenAI(), FakeBuffer(), FakeHTTP()

    def publisher(self, football):
        return Publisher(auto_config(), self.store, self.generator, self.buffer, self.http, clock=lambda: NOW,
                         sleep=lambda _: None, football=football)

    def test_successful_empty_schedule_falls_back_to_cinema(self):
        class Empty:
            def tomorrow(self, day): return {"matches": []}
        self.publisher(Empty()).prepare()
        self.assertEqual(self.generator.ideas, 1)
        self.assertEqual(self.buffer.creates, 1)

    def test_failed_fixture_source_stops_before_paid_generation(self):
        class Failed:
            def tomorrow(self, day): raise RuntimeError("Source unavailable")
        with self.assertRaises(RuntimeError): self.publisher(Failed()).prepare()
        self.assertEqual(self.generator.images, 0)
        self.assertEqual(self.generator.ideas, 0)
        self.assertEqual(self.buffer.creates, 0)

    def test_fixture_change_before_submit_reuses_art_and_updates_schedule(self):
        first = Football(FakeHTTP([{"matches": [fixture()]}]), auto_config(), token="dummy", clock=lambda: NOW).tomorrow("2026-10-13")
        changed = Football(FakeHTTP([{"matches": [fixture(when="2026-10-14T19:00:00Z")]}]), auto_config(), token="dummy", clock=lambda: NOW).tomorrow("2026-10-13")
        class Changing:
            calls = 0
            def tomorrow(self, day):
                self.calls += 1
                return copy.deepcopy(first if self.calls < 3 else changed)
        self.publisher(Changing()).prepare()
        entry = next(iter(self.store.state["entries"].values()))
        self.assertEqual(entry["fixture_schedule"]["matches"][0]["germany_time"], "21:00")
        self.assertEqual(self.generator.images, 1)
        self.assertEqual(self.generator.ideas, 0)
        self.assertEqual(self.buffer.creates, 1)
        self.assertEqual(len(entry["image_urls"]), 1)


if __name__ == "__main__": unittest.main()
