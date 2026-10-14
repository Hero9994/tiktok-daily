import copy
import io
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tiktok_daily.buffer import Buffer
from tiktok_daily.config import load_config, next_slot, DISCLOSURE
from tiktok_daily.content import OpenAI, finalize_content, prepare_image, idea_is_duplicate, image_is_duplicate
from tiktok_daily.http import HTTP, APIError
from tiktok_daily.runner import Publisher
from tiktok_daily.storage import LocalStore, GitStore

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


def config():
    c = load_config(ROOT / "config.json")
    c.update(enabled=True, allow_paid_openai=True, video_enabled=False, daily_posts=None, content_mode="art", card_style="simple", fixed_caption=None,
             publish_time="19:30", timezone="Asia/Riyadh", prepare_lead_minutes=60,
             hashtag_pool=["#فن", "#تصميم", "#خيال", "#طبيعة", "#هدوء", "#إبداع", "#مناظر"], fixed_hashtags=[])
    return c


def raw_content():
    return {"idea": "A turquoise paper lighthouse floating above a golden desert with lavender clouds",
            "title": "منارة فوق الغيوم", "description": "رحلة خيالية بين ألوان الهدوء، أي لون أحببت؟",
            "prompt": "A fictional paper lighthouse in lavender clouds and golden sand",
            "hashtags": ["#خيال", "#تصميم", "#فن", "#طبيعة", "#هدوء"], "safe_fictional_art": True}


class MemoryStore(LocalStore):
    def __init__(self, path):
        super().__init__(path)
        self.snapshots = []

    def checkpoint(self):
        super().checkpoint()
        self.snapshots.append(copy.deepcopy(self.state))

    def image_url(self, filename):
        return "https://example.test/images/" + filename


class FakeOpenAI:
    def __init__(self):
        self.ideas = self.images = 0
        self.reject = False

    def moderate(self, text, image=None):
        if self.reject and text.startswith("A fictional"):
            raise ValueError("Unsafe concept")

    def idea(self, day, previous, attempt):
        self.ideas += 1
        return finalize_content(raw_content(), config(), previous)

    def image(self, prompt):
        self.images += 1
        image = Image.new("RGB", (1024, 1536), "blue")
        stream = io.BytesIO(); image.save(stream, format="PNG")
        return stream.getvalue()


class FakeBuffer:
    channel = "test-channel"

    def __init__(self):
        self.creates = 0
        self.error = None
        self.post = None
        self.reconcile_result = None
        self.status = "scheduled"

    def preflight(self):
        pass

    def create(self, entry, now=False):
        self.creates += 1
        if self.error:
            raise self.error
        self.post = {"id": "post-1", "status": self.status, "schedulingType": "automatic", "sentAt": None,
                     "externalLink": None, "text": entry["caption"], "channelId": self.channel}
        return self.post

    def get(self, post_id):
        return self.post

    def reconcile(self, entry):
        return self.reconcile_result


class FakeHTTP:
    def __init__(self, responses=None):
        self.responses, self.calls = responses or [], []
        self.fail_image = False

    def image(self, url, digest):
        if self.fail_image:
            raise RuntimeError("Image inaccessible")

    def json(self, url, payload=None, token=None, **kwargs):
        self.calls.append((url, payload, kwargs))
        return self.responses.pop(0)


class ContentTests(unittest.TestCase):
    def test_scheduled_generation_can_be_paused_without_disabling_verification(self):
        from tiktok_daily.__main__ import main
        import os
        c = config(); c.update(enabled=True, daily_enabled=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"; path.write_text(json.dumps(c))
            with patch("sys.argv", ["tiktok_daily", "prepare", "--config", str(path)]), \
                    patch.dict(os.environ, {"EVENT_SCHEDULE": "7 17 * * *"}), \
                    patch("tiktok_daily.http.HTTP.json", side_effect=AssertionError("No remote request allowed")), \
                    patch("builtins.print"):
                main()

    def test_invalid_config(self):
        c = config(); c["publish_time"] = "25:00"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"; path.write_text(json.dumps(c))
            with self.assertRaises(ValueError): load_config(path)

    def test_exactly_five_tags_and_disclosure(self):
        c = config(); c["fixed_hashtags"] = ["#إبداع"]
        r = raw_content(); r["hashtags"] = ["#إبداع", "#إبداع", "#not_allowed"]
        result = finalize_content(r, c, [])
        self.assertEqual(len(set(result["hashtags"])), 5)
        self.assertEqual(result["hashtags"][0], "#إبداع")
        self.assertTrue(result["caption"].startswith(DISCLOSURE))

    def test_duplicate_idea_and_caption(self):
        first = finalize_content(raw_content(), config(), [])
        with self.assertRaises(ValueError): finalize_content(raw_content(), config(), [first])
        raw = raw_content(); raw["idea"] = "Different original mountain scene with a crystal river"
        with self.assertRaises(ValueError): finalize_content(raw, config(), [first])
        self.assertTrue(idea_is_duplicate("  Hello WORLD!! ", [{"idea": "hello world"}]))

    def test_arabic_and_limits(self):
        for key, value in [("description", "English only"), ("title", "🌙" * 46), ("description", "أ" * 2300), ("safe_fictional_art", False)]:
            r = raw_content(); r[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): finalize_content(r, config(), [])

    def test_resize_and_image_dedup(self):
        raw = FakeOpenAI().image("art")
        data, digest, perceptual = prepare_image(raw)
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (1080, 1920))
        self.assertEqual(image.format, "JPEG")
        self.assertTrue(image_is_duplicate(digest, perceptual, [{"image_dhash": perceptual}]))

    def test_timezone_and_lead(self):
        slot = next_slot(config(), NOW)
        self.assertEqual(slot.isoformat(), "2026-10-13T19:30:00+03:00")
        later = datetime(2026, 10, 13, 17, tzinfo=timezone.utc)
        self.assertEqual(next_slot(config(), later).date().isoformat(), "2026-10-14")

    def test_nonexistent_dst_slot_is_skipped(self):
        c = config(); c.update(timezone="America/New_York", publish_time="02:30")
        now = datetime(2026, 3, 8, 5, tzinfo=timezone.utc)
        self.assertEqual(next_slot(c, now).date().isoformat(), "2026-03-09")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MemoryStore(self.tmp.name)
        self.openai, self.buffer, self.http = FakeOpenAI(), FakeBuffer(), FakeHTTP()
        self.c = config()
        self.publisher = Publisher(self.c, self.store, self.openai, self.buffer, self.http, lambda: NOW, sleep=lambda _: None)

    def entry(self):
        return next(iter(self.store.state["entries"].values()))

    def test_complete_generation_scheduling_and_confirmation(self):
        result = self.publisher.prepare()
        self.assertIn("pending", result)
        self.assertEqual(self.entry()["status"], "accepted")
        self.assertEqual(self.openai.images, 1)
        self.assertTrue(any(next(iter(s["entries"].values()))["status"] == "submitting" for s in self.store.snapshots))
        self.buffer.post.update(status="sent", sentAt="2026-10-13T16:30:00Z", externalLink="https://www.tiktok.com/@test/photo/123")
        self.publisher.verify()
        self.assertEqual(self.entry()["status"], "sent")
        self.assertIn("/photo/", self.entry()["external_link"])

    def test_same_day_rerun_never_recreates(self):
        self.publisher.prepare(); self.publisher.prepare()
        self.assertEqual(self.buffer.creates, 1)
        self.assertEqual(self.openai.ideas, 1)
        self.assertEqual(self.openai.images, 1)

    def test_timeout_never_retries_create(self):
        self.buffer.error = APIError("Buffer", uncertain=True)
        with self.assertRaises(APIError): self.publisher.prepare()
        self.assertEqual(self.entry()["status"], "uncertain")
        with self.assertRaises(RuntimeError): self.publisher.prepare()
        self.assertEqual(self.buffer.creates, 1)
        self.assertEqual(self.openai.images, 1)

    def test_uncertain_request_reconciles_to_sent(self):
        self.buffer.error = APIError("Buffer", uncertain=True)
        with self.assertRaises(APIError): self.publisher.prepare()
        self.buffer.reconcile_result = {"id": "recovered", "status": "sent", "schedulingType": "automatic"}
        self.publisher.verify()
        self.assertEqual(self.entry()["status"], "sent")
        self.assertEqual(self.buffer.creates, 1)

    def test_crash_after_write_ahead_checkpoint_is_safe(self):
        self.publisher.prepare()
        entry = self.entry(); entry.pop("post_id"); entry["status"] = "submitting"
        with self.assertRaises(RuntimeError): self.publisher.prepare()
        self.assertEqual(self.buffer.creates, 1)

    def test_failure_to_push_prevents_mutation(self):
        original = self.store.checkpoint
        def fail():
            if self.entry()["status"] == "submitting": raise RuntimeError("Push failed")
            original()
        self.store.checkpoint = fail
        with self.assertRaises(RuntimeError): self.publisher.prepare()
        self.assertEqual(self.buffer.creates, 0)

    def test_public_url_failure_reuses_existing_image_on_retry(self):
        self.http.fail_image = True
        with self.assertRaises(RuntimeError): self.publisher.prepare()
        self.assertEqual(self.buffer.creates, 0)
        self.http.fail_image = False
        self.publisher.prepare()
        self.assertEqual(self.openai.images, 1)
        self.assertEqual(self.buffer.creates, 1)

    def test_request_cap_blocks_paid_generation(self):
        self.store.state["image_requests"]["2026-10"] = self.c["max_image_requests_per_month"]
        with self.assertRaises(RuntimeError): self.publisher.prepare()
        self.assertEqual(self.openai.images, 0)
        self.assertEqual(self.buffer.creates, 0)

    def test_generation_retries_are_budgeted(self):
        original = self.openai.image
        attempts = []
        def retry(prompt):
            attempts.append(prompt)
            if len(attempts) < 3: raise APIError("OpenAI", 503, uncertain=True)
            return original(prompt)
        self.openai.image = retry
        self.publisher.prepare()
        self.assertEqual(len(attempts), 3)
        self.assertEqual(self.store.state["image_requests"]["2026-10"], 3)
        self.assertEqual(self.buffer.creates, 1)

    def test_unsafe_text_is_never_used_when_retries_exhausted(self):
        self.openai.reject = True
        with self.assertRaises(RuntimeError): self.publisher.prepare()
        self.assertEqual(self.openai.ideas, 3)
        self.assertEqual(self.openai.images, 0)
        self.assertEqual(self.buffer.creates, 0)

    def test_notification_or_draft_not_success(self):
        for status, scheduling in [("draft", "automatic"), ("scheduled", "notification"), ("error", "automatic")]:
            with self.subTest(status=status, scheduling=scheduling):
                e = {"due_at": "2026-10-13T16:30:00Z"}
                with self.assertRaises(RuntimeError): self.publisher.observe(e, {"id": "p", "status": status, "schedulingType": scheduling})

    def test_overdue_accepted_post_alerts(self):
        self.publisher.prepare()
        self.publisher.clock = lambda: datetime(2026, 10, 14, tzinfo=timezone.utc)
        with self.assertRaises(RuntimeError): self.publisher.verify()
        self.assertEqual(self.entry()["status"], "accepted")

    def test_disabled_has_no_side_effects(self):
        self.c["enabled"] = False
        with self.assertRaises(RuntimeError): self.publisher.prepare()
        self.assertEqual(self.openai.ideas, 0)
        self.assertEqual(self.buffer.creates, 0)


class BufferTests(unittest.TestCase):
    def test_payload_is_official_graphql_photo_payload(self):
        http = FakeHTTP([{"data": {"createPost": {"post": {"id": "p"}}}}])
        buffer = Buffer(http, "secret", "org", "channel")
        e = {"title": "فن", "caption": DISCLOSURE, "image_url": "https://example.test/art.jpg", "due_at": "2026-10-14T12:00:00Z"}
        buffer.create(e)
        url, request, options = http.calls[0]
        self.assertEqual(url, "https://api.buffer.com")
        self.assertFalse(options["safe_retry"])
        value = request["variables"]["input"]
        self.assertEqual(value["mode"], "customScheduled")
        self.assertEqual(value["schedulingType"], "automatic")
        self.assertNotIn("isAiGenerated", value["metadata"]["tiktok"])
        self.assertIn("... on MutationError", request["query"])

    def test_http_200_graphql_error_is_not_success(self):
        http = FakeHTTP([{"errors": [{"message": "secret or unknown remote message"}]}])
        with self.assertRaises(APIError) as ctx:
            Buffer(http, "secret", "org", "ch").query("mutation {}", mutation=True)
        self.assertTrue(ctx.exception.uncertain)
        self.assertNotIn("remote message", str(ctx.exception))

    def test_typed_mutation_failure_is_definitive(self):
        http = FakeHTTP([{"data": {"createPost": {"message": "Invalid input"}}}])
        e = {"title": "فن", "caption": "أ", "image_url": "https://example.test/art.jpg", "due_at": "2026-10-14T12:00:00Z"}
        with self.assertRaises(APIError) as ctx: Buffer(http, "secret", "org", "ch").create(e)
        self.assertFalse(ctx.exception.uncertain)

    def test_reconciliation_paginates(self):
        post = {"id": "p", "text": "caption", "channelId": "ch", "assets": [{"source": "https://example.test/photo.jpg"}]}
        http = FakeHTTP([
            {"data": {"posts": {"edges": [], "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"}}}},
            {"data": {"posts": {"edges": [{"node": post}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}},
        ])
        self.assertEqual(Buffer(http, "key", "org", "ch").reconcile({"caption": "caption", "image_url": "https://example.test/photo.jpg", "attempted_at": "2026-10-13T08:58:00Z"}), post)
        self.assertEqual(http.calls[1][1]["variables"]["after"], "cursor-1")

    def test_disconnected_channel_is_blocked(self):
        http = FakeHTTP([{"data": {"channels": [{"id": "ch", "service": "tiktok", "isDisconnected": True}]}}])
        with self.assertRaises(RuntimeError): Buffer(http, "key", "org", "ch").preflight()


class RetryTests(unittest.TestCase):
    def test_reads_retry_but_writes_do_not(self):
        with patch("urllib.request.urlopen", side_effect=OSError("secret")) as request:
            http = HTTP(sleep=lambda _: None)
            with self.assertRaises(APIError): http.json("https://example.test", {}, safe_retry=True)
            self.assertEqual(request.call_count, 3)
            request.reset_mock()
            with self.assertRaises(APIError): http.json("https://example.test", {}, safe_retry=False)
            self.assertEqual(request.call_count, 1)


class APIFlowIntegrationTests(unittest.TestCase):
    def test_real_http_transport_with_local_simulated_provider(self):
        """Exercises actual HTTP, both API adapters, image hosting and restart verification."""
        import base64
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as directory:
            provider = {"create_calls": 0, "post": None}
            picture = base64.b64encode(FakeOpenAI().image("art")).decode()
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def respond(self, data):
                    payload = json.dumps(data).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.end_headers(); self.wfile.write(payload)
                def do_GET(self):
                    self.send_response(200); self.end_headers()
                    self.wfile.write((Path(directory) / "images" / self.path.rsplit("/", 1)[-1]).read_bytes())
                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if self.path.endswith("/moderations"):
                        self.respond({"results": [{"flagged": False}]})
                    elif self.path.endswith("/responses"):
                        self.respond({"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(raw_content())}]}]})
                    elif self.path.endswith("/images/generations"):
                        self.respond({"data": [{"b64_json": picture}]})
                    elif "createPost" in body["query"]:
                        provider["create_calls"] += 1
                        value = body["variables"]["input"]
                        provider["post"] = {"id": "local-post", "text": value["text"], "status": "scheduled", "channelId": "ch", "schedulingType": "automatic"}
                        self.respond({"data": {"createPost": {"post": provider["post"]}}})
                    elif "channels(" in body["query"]:
                        self.respond({"data": {"channels": [{"id": "ch", "service": "tiktok", "isDisconnected": False, "isQueuePaused": False, "isLocked": False}]}})
                    else:
                        self.respond({"data": {"post": provider["post"]}})
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            base = f"http://127.0.0.1:{server.server_port}"
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                class TestHTTP(HTTP):
                    def json(self, url, *args, **kwargs):
                        import urllib.parse
                        return super().json(base + urllib.parse.urlsplit(url).path, *args, **kwargs)
                class TestStore(MemoryStore):
                    def image_url(self, filename): return base + "/images/" + filename
                store, http, c = TestStore(directory), TestHTTP(), config()
                publisher = Publisher(c, store, OpenAI(http, "local-test-key", c), Buffer(http, "local-test-key", "org", "ch"), http, lambda: NOW)
                publisher.prepare()
                self.assertEqual(provider["create_calls"], 1)
                provider["post"].update(status="sent", sentAt="2026-10-13T16:30:00Z", externalLink="https://www.tiktok.com/@local/photo/1")
                # A fresh process-equivalent store loads persisted state and confirms sent.
                restarted = TestStore(directory)
                Publisher(c, restarted, OpenAI(http, "local-test-key", c), Buffer(http, "local-test-key", "org", "ch"), http, lambda: NOW).verify()
                self.assertEqual(next(iter(restarted.state["entries"].values()))["status"], "sent")
                self.assertEqual(provider["create_calls"], 1)
            finally:
                server.shutdown(); server.server_close(); thread.join()


class GitIntegrationTests(unittest.TestCase):
    def test_real_orphan_branch_push_reload_and_immutable_media(self):
        with tempfile.TemporaryDirectory() as temp:
            root, remote = Path(temp) / "project", Path(temp) / "remote.git"
            root.mkdir()
            def git(*args):
                return subprocess.run(["git", *map(str, args)], capture_output=True, check=True, text=True).stdout
            git("init", "--bare", remote)
            git("-C", root, "init", "-b", "main")
            (root / "code.txt").write_text("main code stays here")
            git("-C", root, "add", ".")
            git("-C", root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", "Initial")
            git("-C", root, "remote", "add", "origin", remote)
            git("-C", root, "push", "origin", "main")
            class TestStore(GitStore):
                def git(self, *args, directory=None):
                    if args == ("remote", "get-url", "origin"):
                        return "https://github.com/test/project.git\n"
                    return super().git(*args, directory=directory)
            store = TestStore(root, "bot-state", "test/project")
            store.state["text_requests"]["day"] = 1
            store.save_image("sample.jpg", b"test image")
            store.checkpoint()
            url = store.image_url("sample.jpg")
            sha = git("--git-dir", remote, "rev-parse", "bot-state").strip()
            self.assertIn(sha, url)
            store.close()
            store2 = TestStore(root, "bot-state", "test/project")
            self.assertEqual(store2.state["text_requests"]["day"], 1)
            self.assertEqual((store2.path / "images/sample.jpg").read_bytes(), b"test image")
            self.assertEqual((root / "code.txt").read_text(), "main code stays here")
            store2.close()


if __name__ == "__main__":
    unittest.main()
