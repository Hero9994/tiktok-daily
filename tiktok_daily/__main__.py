import argparse
import json
import os
import sys
import time
from datetime import timedelta
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from .buffer import Buffer
from .config import load_config, DISCLOSURE, track_config
from .content import OpenAI, prepare_image
from .http import HTTP
from .runner import Publisher
from .storage import GitStore


def secrets(*names):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing GitHub Actions Secrets: " + ", ".join(missing))
    return [os.environ[name] for name in names]


def activate_verified_schedule(store, config_path):
    entries = list(store.state["entries"].values())
    if not entries or not all(e.get("status") == "sent" for e in entries):
        return False
    if config_path.resolve() != (store.root / "config.json").resolve():
        return False
    current = load_config(config_path)
    if not current.get("activate_after_first_success"):
        return False
    # Fetch and fast-forward before editing, so any newer user settings are preserved.
    store.git("fetch", "origin", "main")
    store.git("merge", "--ff-only", "origin/main")
    current = load_config(config_path)
    if not current["enabled"] or not current["allow_paid_openai"] or not current.get("activate_after_first_success"):
        return False
    current.update(daily_enabled=True, activate_after_first_success=False)
    config_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store.git("add", "config.json")
    store.git("-c", "user.name=Daily Image Bot", "-c", "user.email=daily-image-bot@users.noreply.github.com",
              "commit", "-m", "Enable daily posts after confirmed first TikTok publication")
    store.git("push", "origin", "HEAD:refs/heads/main")
    print("DAILY_SCHEDULE_ACTIVATED_AFTER_CONFIRMED_PUBLICATION")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["doctor", "discover", "inspect-buffer", "check-openai", "check-football", "preview", "prepare", "verify", "wait-first", "publish-test", "publish-correction"])
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument('--track',choices=['football','cinema'],default=os.environ.get('POST_KIND') or 'cinema')
    parser.add_argument('--correction-id',default='')
    args = parser.parse_args()
    c = load_config(args.config)
    http = HTTP()
    if args.mode == "doctor":
        report = {"config_valid": True, "enabled": c["enabled"], "allow_paid_openai": c["allow_paid_openai"],
                  "daily_enabled": c.get("daily_enabled", True),
                  "video_enabled": c.get('video_enabled',False), "daily_posts": c.get('daily_posts'),
                  "content_mode": c.get("content_mode", "art"), "caption_suffix_ready": bool(c.get("caption_suffix")),
                  "channel_configured": bool((os.environ.get("BUFFER_ORGANIZATION_ID") or c.get("buffer_organization_id")) and
                                             (os.environ.get("BUFFER_CHANNEL_ID") or c.get("buffer_channel_id"))),
                  "secrets_present": {k: bool(os.environ.get(k)) for k in
                    ["OPENAI_API_KEY", "BUFFER_API_KEY", "FOOTBALL_DATA_API_KEY", "BUFFER_ORGANIZATION_ID", "BUFFER_CHANNEL_ID"]}}
        print(json.dumps(report, indent=2))
        return
    if args.mode == "check-openai":
        token, = secrets("OPENAI_API_KEY")
        response = http.json("https://api.openai.com/v1/models", token=token, safe_retry=True)
        if not isinstance(response.get("data"), list):
            raise RuntimeError("OpenAI model list is invalid; authentication is not confirmed")
        available = {m.get("id") for m in response["data"] if isinstance(m, dict)}
        ready = {name: c[name] in available for name in ("text_model", "image_model")}
        print(json.dumps({"openai_auth_verified": True, "configured_models_available": ready,
                          "billing_credit_verified": False, "publishing_enabled": c["enabled"]}, indent=2))
        if not all(ready.values()):
            raise RuntimeError("Configured OpenAI models are unavailable; review account access before generation")
        return
    if args.mode == "preview":
        # Entirely offline sample, never represented as an OpenAI-generated image.
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (1080, 1920), "#080d13")
        draw = ImageDraw.Draw(image)
        draw.ellipse((500, 210, 810, 520), fill="#b58d44")
        for points, color in [([(0, 1100), (460, 500), (1080, 1300), (1080, 1920), (0, 1920)], "#27271d"),
                              ([(0, 1500), (850, 840), (1080, 1500), (1080, 1920), (0, 1920)], "#46412b")]:
            draw.polygon(points, fill=color)
        import io
        raw = io.BytesIO(); image.save(raw, format="PNG")
        title = "The Shawshank Redemption" if c.get("content_mode") in ("cinema", "auto") else None
        summary = "فيلم درامي عن الأمل والصداقة داخل السجن. نبذة تجريبية دون حرق الأحداث." if title else None
        data, digest, _ = prepare_image(raw.getvalue(), title, summary)
        args.output.mkdir(exist_ok=True, parents=True)
        if c.get("card_style") == "black_gold":
            from .cards import render
            from .content import finalize_content
            raw_content = {"idea": "Offline demo prison drama card", "title": title or "ترشيح اليوم", "description": summary or "معاينة محلية للتصميم.",
                           "prompt": "Offline illustration", "hashtags": ["#أفلام", "#سينما", "#ترشيحات", "#ماذا_تشاهد", "#TK_Servers"], "safe_fictional_art": True}
            entry = finalize_content(raw_content, c, [])
            entry.update(summary=raw_content["description"], demo=True)
            data = render(raw.getvalue(), entry, c)[0]
            import hashlib
            digest = hashlib.sha256(data).hexdigest()
            (args.output / "cinema-preview.jpg").write_bytes(data)
            from .football import football_content
            demo_matches = [{"id": i, "competition_code": "CL", "competition": "دوري أبطال أوروبا",
                "home": f"الفريق الأحمر {i}", "away": f"الفريق الأزرق {i}", "germany_time": time,
                "germany_date": "2026-10-14", "makkah_time": makkah, "makkah_date": "2026-10-14"}
                for i, (time, makkah) in enumerate([("18:00", "19:00"), ("20:00", "21:00"), ("21:00", "22:00")], 1)]
            schedule = {"date": "2026-10-14", "matches": demo_matches, "checked_at": "2026-10-13T15:07:00+00:00", "source_url": "https://www.football-data.org/"}
            football_entry = football_content(schedule, c); football_entry["demo"] = True
            (args.output / "football-preview.jpg").write_bytes(render(raw.getvalue(), football_entry, c)[0])
        (args.output / "sample.jpg").write_bytes(data)
        (args.output / "sample.json").write_text(json.dumps({"offline_demo": True, "dimensions": [1080, 1920],
            "caption": entry["caption"] if c.get("card_style") == "black_gold" else DISCLOSURE + "\nهذه معاينة محلية فقط.\n" + " ".join(list(dict.fromkeys(c["fixed_hashtags"] + c["hashtag_pool"]))[:5]),
            "title": title, "summary": summary,
            "sha256": digest}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Offline demonstration saved; no API request or publication occurred")
        return
    if args.mode == "discover":
        token, = secrets("BUFFER_API_KEY")
        print(json.dumps(Buffer(http, token, "", "").discover(), ensure_ascii=False, indent=2))
        return
    if args.mode == "check-football":
        from .football import Football
        football_key, = secrets("FOOTBALL_DATA_API_KEY")
        day = datetime.now(timezone.utc).astimezone(ZoneInfo(c["timezone"])).date().isoformat()
        schedule = Football(http, c, token=football_key).tomorrow(day)
        today=Football(http,dict(c,fixture_day='today'),token=football_key).tomorrow(day)
        tomorrow=Football(http,dict(c,fixture_day='tomorrow'),token=football_key).tomorrow(day)
        print(json.dumps({"football_api_verified": True, "tomorrow_date": schedule["date"],
            "confirmed_match_count": len(schedule["matches"]), "source": schedule["source_url"],
            "sources":schedule.get('sources'),"today":{"date":today['date'],'matches':len(today['matches'])},
            "tomorrow":{"date":tomorrow['date'],'matches':len(tomorrow['matches'])},
            "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
            "publishing_enabled": c["enabled"]}, ensure_ascii=False, indent=2))
        return
    if not c["enabled"]:
        print("Automation disabled in config.json; no remote request made")
        return
    if args.mode == "prepare" and os.environ.get("EVENT_SCHEDULE") and not c.get("daily_enabled", True):
        print("Daily generation disabled while the first publishing test is verified")
        return
    if args.mode in ('prepare','publish-test','publish-correction') and c.get('daily_posts'):
        c = track_config(c,args.track)
    buffer_key, = secrets("BUFFER_API_KEY")
    org = os.environ.get("BUFFER_ORGANIZATION_ID") or c.get("buffer_organization_id")
    channel = os.environ.get("BUFFER_CHANNEL_ID") or c.get("buffer_channel_id")
    if not org or not channel:
        raise RuntimeError("Run discover and configure Buffer organization/channel IDs in config.json")
    openai_key = None
    if args.mode not in ("verify", "inspect-buffer", "wait-first"):
        if not c["allow_paid_openai"]:
            raise RuntimeError("Paid OpenAI calls are disabled in config.json")
        openai_key, = secrets("OPENAI_API_KEY")
        if c.get("content_mode") in ("auto","football"):
            secrets("FOOTBALL_DATA_API_KEY")
    if os.environ.get("GITHUB_REPOSITORY_VISIBILITY") != "public":
        raise RuntimeError("This media hosting mode requires a PUBLIC GitHub repository")
    store = GitStore(Path.cwd(), c["state_branch"], os.environ.get("GITHUB_REPOSITORY", ""))
    try:
        publisher = Publisher(c, store, OpenAI(http, openai_key, c), Buffer(http, buffer_key, org, channel), http)
        if args.mode == "inspect-buffer":
            result = publisher.buffer.inspect(list(store.state["entries"].values()))
            message = json.dumps(result, ensure_ascii=False, indent=2)
            for name in ("BUFFER_API_KEY", "OPENAI_API_KEY", "FOOTBALL_DATA_API_KEY"):
                if os.environ.get(name):
                    message = message.replace(os.environ[name], "[REDACTED]")
            print(message)
        elif args.mode in ("verify", "wait-first"):
            if args.mode == "wait-first":
                candidates = [e for e in store.state["entries"].values() if e.get("status") == "accepted" and e.get("post_id")]
                if not candidates:
                    raise RuntimeError("No accepted first post to wait for; this mode never creates a post")
                due = max(datetime.fromisoformat(e["due_at"].replace("Z", "+00:00")) for e in candidates)
                deadline = max(due,datetime.now(timezone.utc)) + timedelta(minutes=10)
                if due - datetime.now(timezone.utc) > timedelta(minutes=35):
                    raise RuntimeError("Post is more than 35 minutes away; hourly verification will continue")
                print("Waiting for accepted post delivery; no generation or publishing calls will be made", flush=True)
                while datetime.now(timezone.utc) < due:
                    time.sleep(min(60, max(0, (due - datetime.now(timezone.utc)).total_seconds())))
                while True:
                    publisher.verify()
                    if all(e.get("status") == "sent" for e in store.state["entries"].values()):
                        break
                    if datetime.now(timezone.utc) >= deadline:
                        raise RuntimeError("Publication remains unconfirmed; verification never creates another post")
                    time.sleep(30)
            publisher.verify()
            print("Verification finished; only status=sent is considered confirmed publication")
            print(json.dumps([{"day": e["day"], "status": e["status"],
                               "external_link": e.get("external_link")}
                              for e in list(store.state["entries"].values())[-3:]], ensure_ascii=False, indent=2))
            activate_verified_schedule(store, args.config)
        else:
            publish_now = args.mode in ("publish-test","publish-correction")
            if args.mode=='publish-correction' and not args.correction_id:
                raise RuntimeError('An approved correction ID is required')
            if publish_now and args.mode!='publish-correction':
                local = datetime.now(timezone.utc).astimezone(ZoneInfo(c["timezone"]))
                if not 12 <= local.hour < 20:
                    # Respect the user's publication window even during a live test.
                    c["publish_time"] = "12:05"
                    publish_now = False
                    print("Live test will be scheduled at the next valid 12:05 local publishing slot")
            print(publisher.prepare(publish_now=publish_now,correction_id=args.correction_id if args.mode=='publish-correction' else None))
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Unknown library errors can embed remote bodies or credentials. Only emit controlled errors.
        if isinstance(exc, (RuntimeError, ValueError)):
            message = str(exc)
            for name in ("OPENAI_API_KEY", "BUFFER_API_KEY", "FOOTBALL_DATA_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
                value = os.environ.get(name)
                if value:
                    message = message.replace(value, "[REDACTED]")
            print(f"FAILED: {message}", file=sys.stderr)
        else:
            print(f"FAILED: {type(exc).__name__}; check configuration and API compatibility", file=sys.stderr)
        sys.exit(1)
