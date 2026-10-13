import io
import json
import unittest
from pathlib import Path
from PIL import Image
from tiktok_daily.config import load_config
from tiktok_daily.content import OpenAI, finalize_content, prepare_image
from test_project import config, raw_content, FakeHTTP, FakeOpenAI


class CinemaTests(unittest.TestCase):
    def cinema_config(self):
        c = config()
        c.update(content_mode="cinema", fixed_caption="تابعني لترشيح جديد كل يوم.",
                 fixed_hashtags=["#فن", "#تصميم", "#خيال", "#طبيعة", "#هدوء"])
        return c

    def test_same_caption_is_allowed_for_different_works(self):
        c = self.cinema_config()
        first = finalize_content(raw_content(), c, [])
        raw = raw_content(); raw["idea"] = "A lone blue spaceship circling a silent purple moon"
        raw["description"] = "نبذة مختلفة تمامًا"; raw["title"] = "ترشيح آخر"
        second = finalize_content(raw, c, [first])
        self.assertEqual(first["caption"], second["caption"])

    def test_source_is_required_and_canonical_id_is_saved(self):
        c = self.cinema_config()
        summary_raw = raw_content(); summary_raw["description"] = "فيلم درامي عن الصداقة والأمل."
        def response(raw):
            return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(raw)}]}]}
        source = {"type": "standard", "pageid": 30625, "title": "The Shawshank Redemption",
                  "extract": "The Shawshank Redemption is a 1994 American drama film.",
                  "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/The_Shawshank_Redemption"}}}
        http = FakeHTTP([response({"wikipedia_title": "The Shawshank Redemption"}), source, response(summary_raw)])
        client = OpenAI(http, "local-test", c)
        reserved = []; client.reserve_text_request = lambda: reserved.append(True)
        content = client.idea("2026-10-13", [], 1)
        self.assertEqual(content["subject_id"], "wikipedia-en:30625")
        self.assertEqual(content["summary"], summary_raw["description"])
        self.assertEqual(len(reserved), 1)
        http.responses = [response({"wikipedia_title": "The Shawshank Redemption"}), source]
        with self.assertRaises(ValueError): client.idea("2026-10-14", [content], 1)

    def test_arabic_text_card_has_correct_final_dimensions(self):
        data, _, _ = prepare_image(FakeOpenAI().image("art"), "ترشيح اليوم", "فيلم درامي عن الصداقة والأمل دون حرق الأحداث.")
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (1080, 1920))
        # The information panel is painted onto the actual output file.
        self.assertNotEqual(image.getpixel((20, 1800)), image.getpixel((20, 200)))

    def test_missing_fixed_caption_blocks_live_cinema_config(self):
        import tempfile
        c = self.cinema_config(); c["fixed_caption"] = ""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"; path.write_text(json.dumps(c))
            with self.assertRaises(ValueError): load_config(path)


if __name__ == "__main__": unittest.main()
