import io
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from tiktok_daily.cinema_media import enrich, artwork
from tiktok_daily.runner import Publisher
from test_project import FakeHTTP, FakeBuffer, FakeOpenAI, MemoryStore, NOW, config


def claim(value):
    return {'mainsnak': {'datavalue': {'value': value}}}


class CinemaMediaTests(unittest.TestCase):
    def test_only_sourced_facts_and_actor_identity_are_used(self):
        source = {'wikibase_item': 'Q1', 'extract': 'A television series.',
                  'originalimage': {'source': 'https://upload.wikimedia.org/poster.jpg'}}
        work = {'claims': {'P577': [claim({'time': '+2010-01-01', 'precision': 9})],
                          'P2437': [claim({'amount': '+4'})],
                          'P2047': [claim({'amount': '+99', 'unit': 'wrong-unit'})],
                          'P161': [claim({'id': 'Q2'})]}}
        actor = {'labels': {'ar': {'value': 'ممثل موثق'}}, 'claims': {'P18': [claim('Actor photo.jpg')]}}
        http = FakeHTTP([{'entities': {'Q1': work}}, {'entities': {'Q2': actor}}])
        data = enrich(http, source)['cinema_details']
        self.assertEqual(data['cast'][0]['name'], 'ممثل موثق')
        self.assertIn({'label': 'المواسم', 'value': '4'}, data['facts'])
        self.assertNotIn('99', str(data['facts']))
        self.assertNotIn('rating', data)
        self.assertEqual(len(http.calls), 2)

    def test_documentary_series_is_not_mislabelled_as_a_film(self):
        source={'wikibase_item':'Q1','extract':'A British nature documentary series.',
                'originalimage':{'source':'https://upload.wikimedia.org/title.jpg'}}
        data=enrich(FakeHTTP([{'entities':{'Q1':{'claims':{}}}}]),source)['cinema_details']
        self.assertEqual(data['facts'][0],{'label':'نوع العمل','value':'مسلسل'})

    def test_missing_work_artwork_stops_before_publication(self):
        http = FakeHTTP([{'entities': {'Q1': {'claims': {}}}}])
        with self.assertRaises(ValueError):
            enrich(http, {'wikibase_item': 'Q1'})

    def test_tvmaze_poster_and_rating_require_the_same_sourced_imdb_id(self):
        source = {'wikibase_item': 'Q1', 'extract': 'A television series.',
                  'originalimage': {'source': 'https://upload.wikimedia.org/titlecard.jpg'}}
        work = {'claims': {'P345': [claim('tt1234')]}}
        for actual_id, expected in [('tt1234', True), ('tt9999', False)]:
            http = FakeHTTP([{'entities': {'Q1': work}}, {'externals': {'imdb': actual_id},
                            'image': {'original': 'https://static.tvmaze.com/poster.jpg'},
                            'rating': {'average': 8.6}, 'url': 'https://www.tvmaze.com/shows/1/test'}])
            data = enrich(http, source)['cinema_details']
            self.assertEqual(any(f['label'] == 'تقييم TVmaze' for f in data['facts']), expected)
            self.assertEqual(data['poster_url'].startswith('https://static.tvmaze.com'), expected)

    def test_external_image_hosts_are_rejected_without_request(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('Must not fetch')):
            with self.assertRaises(ValueError): artwork('https://example.org/poster.jpg')
            with self.assertRaises(ValueError): artwork('http://upload.wikimedia.org/poster.jpg')

    def test_reference_poster_does_not_spend_image_budget_or_duplicate_post(self):
        c = config(); c.update(content_mode='cinema', card_style='black_gold')
        ai = FakeOpenAI()
        original = ai.idea
        def idea(*args):
            entry = original(*args)
            entry['cinema_details'] = {'poster_url': 'https://upload.wikimedia.org/poster.jpg'}
            return entry
        ai.idea = idea
        b = FakeBuffer()
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(folder)
            publisher = Publisher(c, store, ai, b, FakeHTTP(), lambda: NOW, sleep=lambda _: None)
            with patch('tiktok_daily.runner.artwork', return_value=Image.new('RGB',(400,600),'red')), \
                 patch('tiktok_daily.cards.artwork', return_value=Image.new('RGB',(400,600),'red')):
                publisher.prepare(); publisher.prepare()
            self.assertEqual(ai.images, 0)
            self.assertEqual(store.state['image_requests'], {})
            self.assertEqual(b.creates, 1)
            card = next((store.path/'images').glob('*-1.jpg'))
            with Image.open(card) as image:
                self.assertEqual(image.size, (1080,1920))


if __name__ == '__main__':
    unittest.main()
