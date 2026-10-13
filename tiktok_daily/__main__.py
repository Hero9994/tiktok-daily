import argparse
import json
import os
import sys
from pathlib import Path
from .buffer import Buffer
from .config import load_config, DISCLOSURE
from .content import OpenAI, prepare_image
from .http import HTTP
from .runner import Publisher
from .storage import GitStore


def secrets(*names):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing GitHub Actions Secrets: " + ", ".join(missing))
    return [os.environ[name] for name in names]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["doctor", "discover", "preview", "prepare", "verify", "publish-test"])
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    c = load_config(args.config)
    http = HTTP()
    if args.mode == "doctor":
        report = {"config_valid": True, "enabled": c["enabled"], "allow_paid_openai": c["allow_paid_openai"],
                  "content_mode": c.get("content_mode", "art"), "fixed_caption_ready": bool(c.get("fixed_caption")),
                  "secrets_present": {k: bool(os.environ.get(k)) for k in
                    ["OPENAI_API_KEY", "BUFFER_API_KEY", "BUFFER_ORGANIZATION_ID", "BUFFER_CHANNEL_ID"]}}
        print(json.dumps(report, indent=2))
        return
    if args.mode == "preview":
        # Entirely offline sample, never represented as an OpenAI-generated image.
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (1080, 1920), "#132e49")
        draw = ImageDraw.Draw(image)
        draw.ellipse((500, 210, 810, 520), fill="#e7b57a")
        for points, color in [([(0, 1100), (460, 500), (1080, 1300), (1080, 1920), (0, 1920)], "#397e87"),
                              ([(0, 1500), (850, 840), (1080, 1500), (1080, 1920), (0, 1920)], "#58a69b")]:
            draw.polygon(points, fill=color)
        import io
        raw = io.BytesIO(); image.save(raw, format="PNG")
        title = "The Shawshank Redemption" if c.get("content_mode") == "cinema" else None
        summary = "فيلم درامي عن الأمل والصداقة داخل السجن. نبذة تجريبية دون حرق الأحداث." if title else None
        data, digest, _ = prepare_image(raw.getvalue(), title, summary)
        args.output.mkdir(exist_ok=True, parents=True)
        (args.output / "sample.jpg").write_bytes(data)
        (args.output / "sample.json").write_text(json.dumps({"offline_demo": True, "dimensions": [1080, 1920],
            "caption": DISCLOSURE + "\n" + (c.get("fixed_caption") or "الوصف الثابت لم يحدَّد بعد. هذه معاينة محلية فقط.") + "\n" + " ".join(list(dict.fromkeys(c["fixed_hashtags"] + c["hashtag_pool"]))[:5]),
            "title": title, "summary": summary,
            "sha256": digest}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Offline demonstration saved; no API request or publication occurred")
        return
    if args.mode == "discover":
        token, = secrets("BUFFER_API_KEY")
        print(json.dumps(Buffer(http, token, "", "").discover(), ensure_ascii=False, indent=2))
        return
    if not c["enabled"]:
        print("Automation disabled in config.json; no remote request made")
        return
    buffer_key, org, channel = secrets("BUFFER_API_KEY", "BUFFER_ORGANIZATION_ID", "BUFFER_CHANNEL_ID")
    openai_key = None
    if args.mode != "verify":
        if not c["allow_paid_openai"]:
            raise RuntimeError("Paid OpenAI calls are disabled in config.json")
        openai_key, = secrets("OPENAI_API_KEY")
    if os.environ.get("GITHUB_REPOSITORY_VISIBILITY") != "public":
        raise RuntimeError("This media hosting mode requires a PUBLIC GitHub repository")
    store = GitStore(Path.cwd(), c["state_branch"], os.environ.get("GITHUB_REPOSITORY", ""))
    try:
        publisher = Publisher(c, store, OpenAI(http, openai_key, c), Buffer(http, buffer_key, org, channel), http)
        if args.mode == "verify":
            publisher.verify()
            print("Verification finished; only status=sent is considered confirmed publication")
            print(json.dumps([{"day": e["day"], "status": e["status"],
                               "external_link": e.get("external_link")}
                              for e in list(store.state["entries"].values())[-3:]], ensure_ascii=False, indent=2))
        else:
            print(publisher.prepare(publish_now=args.mode == "publish-test"))
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Unknown library errors can embed remote bodies or credentials. Only emit controlled errors.
        if isinstance(exc, (RuntimeError, ValueError)):
            message = str(exc)
            for name in ("OPENAI_API_KEY", "BUFFER_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
                value = os.environ.get(name)
                if value:
                    message = message.replace(value, "[REDACTED]")
            print(f"FAILED: {message}", file=sys.stderr)
        else:
            print(f"FAILED: {type(exc).__name__}; check configuration and API compatibility", file=sys.stderr)
        sys.exit(1)
