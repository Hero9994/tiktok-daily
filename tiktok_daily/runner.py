import hashlib
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .config import next_slot
from .content import prepare_image, image_is_duplicate
from .http import APIError


def utc_text(now):
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Publisher:
    def __init__(self, c, store, generator, buffer, http, clock=None, sleep=time.sleep):
        self.c, self.store, self.generator, self.buffer, self.http = c, store, generator, buffer, http
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.generator.reserve_text_request = self.reserve_text_request

    def reserve_text_request(self):
        self.consume("text_requests", self.active_day, self.c["max_text_requests_per_day"])

    def consume(self, bucket, key, limit):
        counts = self.store.state[bucket]
        if counts.get(key, 0) >= limit:
            raise RuntimeError(f"Request safety cap reached: {bucket}")
        counts[key] = counts.get(key, 0) + 1
        self.store.checkpoint()  # Budget is reserved BEFORE a potentially paid request.

    def observe(self, entry, post):
        entry["post_id"] = post["id"]
        entry["buffer_status"] = post["status"]
        entry["last_checked_at"] = utc_text(self.clock())
        if post.get("schedulingType") != "automatic":
            entry["status"] = "blocked"
            self.store.checkpoint()
            raise RuntimeError("Buffer returned notification publishing; manual posting would be required")
        if post["status"] in ("draft", "needs_approval", "error"):
            entry["status"] = "blocked"
            self.store.checkpoint()
            raise RuntimeError("Buffer post failed or requires approval; inspect the Buffer dashboard")
        if post["status"] == "sent":
            entry["sent_at"] = post.get("sentAt")
            entry["external_link"] = post.get("externalLink")
            entry["status"] = "sent"
        else:
            entry["status"] = "accepted"
        self.store.checkpoint()
        if entry["status"] == "accepted":
            due = datetime.fromisoformat(entry["due_at"].replace("Z", "+00:00"))
            if self.clock() > due + timedelta(minutes=self.c["verification_grace_minutes"]):
                raise RuntimeError("Buffer has not confirmed publication within the allowed time")

    def verify(self):
        failures = []
        # Also reconcile uncertain posts; never issue another createPost mutation here.
        for entry in self.store.state["entries"].values():
            if entry["status"] in ("sent", "planned", "content_ready", "image_ready", "rejected"):
                continue
            try:
                if entry.get("post_id"):
                    post = self.buffer.get(entry["post_id"])
                else:
                    post = self.buffer.reconcile(entry)
                    if not post:
                        raise RuntimeError("Uncertain submission unresolved; inspect Buffer before taking action")
                self.observe(entry, post)
            except (RuntimeError, ValueError) as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError("Publication verification failed: " + "; ".join(sorted(set(failures))))

    def prepare(self, publish_now=False):
        if not self.c["enabled"] or not self.c["allow_paid_openai"]:
            raise RuntimeError("Live publishing is disabled. Enable it only after reviewing OpenAI costs")
        self.verify()  # Stop new posting if prior delivery is uncertain or failed.
        self.buffer.preflight()
        now = self.clock()
        slot = now if publish_now else next_slot(self.c, now)
        day = slot.astimezone(ZoneInfo(self.c["timezone"])).date().isoformat()
        self.active_day = day
        key = f"{self.buffer.channel}:{day}"
        entries = self.store.state["entries"]
        if key in entries and entries[key]["status"] in ("accepted", "sent"):
            return "This day's post already exists; skipped"
        entry = entries.get(key)
        if entry and entry["status"] in ("submitting", "uncertain", "blocked", "rejected"):
            raise RuntimeError("This date is blocked; never resubmit it blindly")
        if not entry:
            entry = entries[key] = {"day": day, "channel": self.buffer.channel, "due_at": utc_text(slot),
                                    "status": "planned", "created_at": utc_text(now), "image_attempts": 0}
            self.store.checkpoint()
        else:
            # Retrying an unfinished generation after its original slot has passed is unsafe.
            due = datetime.fromisoformat(entry["due_at"].replace("Z", "+00:00"))
            if not publish_now and due <= now + timedelta(minutes=5):
                raise RuntimeError("Unfinished post's publishing time has passed; review it manually")
        previous = [e for k, e in entries.items() if k != key and e.get("idea")]
        if entry["status"] == "planned":
            self.generator.moderate(self.c["theme"])
            generated = None
            while self.store.state["text_requests"].get(day, 0) < self.c["max_text_requests_per_day"]:
                self.consume("text_requests", day, self.c["max_text_requests_per_day"])
                try:
                    candidate = self.generator.idea(day, previous, self.store.state["text_requests"][day])
                    self.generator.moderate(candidate["prompt"] + "\n" + candidate["caption"] + "\n" + candidate.get("summary", ""))
                    generated = candidate
                    break
                except (ValueError, APIError):
                    self.sleep(2 ** self.store.state["text_requests"][day])
                    continue
            if generated is None:
                raise RuntimeError("Could not produce a safe unique idea within the daily request cap")
            entry.update(generated, status="content_ready")
            self.store.checkpoint()
        if entry["status"] == "content_ready":
            while entry["image_attempts"] < 3:
                month = self.clock().strftime("%Y-%m")
                self.consume("image_requests", month, self.c["max_image_requests_per_month"])
                entry["image_attempts"] += 1
                self.store.checkpoint()
                try:
                    image = self.generator.image(entry["prompt"])
                except APIError:
                    self.sleep(2 ** entry["image_attempts"])
                    continue  # Each generation retry is separately budgeted and might incur cost.
                image, digest, perceptual = prepare_image(image, entry.get("title") if entry.get("summary") else None, entry.get("summary"))
                self.generator.moderate(entry["caption"], image)
                if image_is_duplicate(digest, perceptual, previous):
                    continue
                filename = f"{day}-{hashlib.sha256(key.encode()).hexdigest()[:10]}.jpg"
                self.store.save_image(filename, image)
                entry.update(status="image_ready", image_file=filename, image_sha256=digest, image_dhash=perceptual)
                self.store.checkpoint()
                break
            if entry["status"] != "image_ready":
                raise RuntimeError("Could not generate a unique image within the request cap")
        if entry["status"] == "image_ready":
            entry["image_url"] = self.store.image_url(entry["image_file"])
            self.store.checkpoint()
            self.http.image(entry["image_url"], entry["image_sha256"])
            if not publish_now and datetime.fromisoformat(entry["due_at"].replace("Z", "+00:00")) <= self.clock() + timedelta(minutes=5):
                raise RuntimeError("Image preparation took too long; publishing slot is no longer safely in the future")
            # Include two minutes before the local attempt to tolerate provider clock differences.
            entry.update(status="submitting", attempted_at=utc_text(self.clock() - timedelta(minutes=2)))
            self.store.checkpoint()
            try:
                post = self.buffer.create(entry, now=publish_now)
            except APIError as exc:
                entry["status"] = "uncertain" if exc.uncertain else "rejected"
                self.store.checkpoint()
                raise
            self.observe(entry, post)
        return "Buffer confirmed sent" if entry["status"] == "sent" else "Buffer accepted; delivery confirmation is still pending"
