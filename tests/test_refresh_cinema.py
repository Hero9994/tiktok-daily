import copy
import hashlib
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch
from tiktok_daily.refresh_cinema import refresh
from tiktok_daily.http import APIError
from test_daily_video import VideoStore
from test_project import config, NOW, FakeHTTP, FakeOpenAI


class QueuedBuffer:
    channel='channel'
    def __init__(self):
        self.calls=0;self.uncertain=False
        self.post={'id':'queued','channelId':self.channel,'status':'buffer','dueAt':(NOW+timedelta(days=1)).isoformat(),
                   'text':'caption','assets':[{'source':'https://example.test/old.mp4'}]}
    def get(self, post_id):return copy.deepcopy(self.post)
    def query(self, doc, variables, mutation=False):
        self.calls+=1
        self.post['assets']=[{'source':variables['input']['assets'][0]['video']['url']}]
        if self.uncertain:raise APIError('Buffer',uncertain=True)
        return {'editPost':{'post':copy.deepcopy(self.post)}}


class RefreshCinemaTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=VideoStore(folder.name);self.b=QueuedBuffer();self.c=config()
        self.image=FakeOpenAI().image('art');self.store.save_image('hero.jpg',self.image)
        self.entry={'post_id':'queued','post_kind':'cinema','status':'accepted','day':'2026-10-14',
                    'hero_file':'hero.jpg','caption':'caption','video_url':'https://example.test/old.mp4'}
        self.store.state['entries']['key']=self.entry
    def call(self):
        video=b'encoded-video'
        with patch('tiktok_daily.refresh_cinema.render',return_value=[self.image]), \
             patch('tiktok_daily.refresh_cinema.make_video',return_value=(video,hashlib.sha256(video).hexdigest())):
            refresh(self.store,self.b,FakeHTTP(),self.c,'queued',lambda:NOW)
    def test_updates_existing_post_once_and_keeps_caption_and_due_date(self):
        old=copy.deepcopy(self.b.post)
        self.call();self.call()
        self.assertEqual(self.b.calls,1)
        self.assertEqual(self.b.post['text'],old['text'])
        self.assertEqual(self.b.post['dueAt'],old['dueAt'])
        self.assertEqual(self.entry['status'],'accepted')
        self.assertEqual(self.entry['layout_refresh']['status'],'confirmed')
    def test_uncertain_edit_reconciles_by_stable_media_url_without_second_mutation(self):
        self.b.uncertain=True
        with self.assertRaises(APIError):self.call()
        self.b.uncertain=False;self.call()
        self.assertEqual(self.b.calls,1)
        self.assertEqual(self.entry['layout_refresh']['status'],'confirmed')
    def test_sent_or_near_delivery_posts_are_never_edited(self):
        self.b.post['status']='sent'
        with self.assertRaises(RuntimeError):self.call()
        self.b.post.update(status='buffer',dueAt=(NOW+timedelta(minutes=5)).isoformat())
        with self.assertRaises(RuntimeError):self.call()
        self.assertEqual(self.b.calls,0)
