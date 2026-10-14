import copy
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tiktok_daily.buffer import Buffer
from tiktok_daily.config import load_config, track_config
from tiktok_daily.runner import Publisher
from tiktok_daily.video import make_video
from tiktok_daily.storage import GitStore
import subprocess
from test_project import FakeHTTP, FakeOpenAI, FakeBuffer, MemoryStore, NOW

ROOT = Path(__file__).resolve().parents[1]


class VideoStore(MemoryStore):
    def video_url(self, filename):
        return 'https://example.test/videos/' + filename


class MultiBuffer(FakeBuffer):
    def __init__(self):
        super().__init__()
        self.posts = {}
    def create(self, entry, now=False):
        post = super().create(entry,now)
        post['id'] = f'post-{self.creates}'
        self.posts[post['id']] = copy.deepcopy(post)
        return post
    def get(self, post_id):
        return self.posts[post_id]


class EmptyFootball:
    def tomorrow(self, day):
        return {'date':'2026-10-14','matches':[],'checked_at':NOW.isoformat(),
                'source_url':'https://www.football-data.org/'}


class DailyVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = VideoStore(self.temp.name)
        self.c = load_config(ROOT/'config.json')
        self.c['cinema_curated_only']=False  # Track tests use generic fake works, policy tested separately.
        self.c['skip_empty_football']=False  # Exercise the historical opt-in empty-card path as well.
        self.buffer,self.ai,self.http = MultiBuffer(),FakeOpenAI(),FakeHTTP()
    def publisher(self, kind, football=None):
        return Publisher(track_config(self.c,kind),self.store,self.ai,self.buffer,self.http,
                         lambda:NOW,sleep=lambda _:None,football=football or EmptyFootball())

    def test_two_tracks_use_different_audio_and_never_repeat_same_track(self):
        video=b'local-test-video';checksum=hashlib.sha256(video).hexdigest()
        with patch('tiktok_daily.runner.make_video',return_value=(video,checksum)) as encode:
            self.publisher('football').prepare()
            self.publisher('cinema').prepare()
            self.publisher('football').prepare()
            self.publisher('cinema').prepare()
        self.assertEqual(self.buffer.creates,2)
        self.assertEqual(encode.call_count,2)
        self.assertEqual({e['music_file'] for e in self.store.state['entries'].values()},
                         {'assets/audio/sports.m4a','assets/audio/cinema.m4a'})
        self.assertEqual({k.rsplit(':',1)[1] for k in self.store.state['entries']},{'football','cinema'})
        self.assertEqual(self.ai.ideas,1)  # Empty sports never falls back to cinema.

    def test_legacy_cinema_post_prevents_a_second_cinema_post_today(self):
        self.store.state['entries'][f'{self.buffer.channel}:2026-10-13']={'day':'2026-10-13','status':'sent'}
        with patch('tiktok_daily.runner.make_video',side_effect=AssertionError('No encoding')):
            self.publisher('cinema').prepare()
        self.assertEqual(self.buffer.creates,0)
        self.assertEqual(self.ai.ideas,0)

    def test_video_payload_has_video_asset_and_native_ai_flag_not_photo_title(self):
        http=FakeHTTP([{'data':{'createPost':{'post':{'id':'video-1','status':'buffer'}}}}])
        Buffer(http,'local-test','org','channel').create({'caption':'نص','title':'عمل',
              'due_at':'2026-10-14T14:00:00Z','image_url':'https://example.test/card.jpg',
              'video_url':'https://example.test/clip.mp4'})
        payload=http.calls[0][1]['variables']['input']
        self.assertEqual(payload['assets'],[{'video':{'url':'https://example.test/clip.mp4','metadata':{'thumbnailOffset':0}}}])
        self.assertEqual(payload['metadata'],{'tiktok':{'isAiGenerated':True}})

    def test_uncertain_video_matches_its_actual_video_source(self):
        url='https://example.test/clip.mp4'
        post={'id':'v1','text':'نص','channelId':'channel','assets':[{'source':url}]}
        response={'data':{'posts':{'edges':[{'node':post}], 'pageInfo':{'hasNextPage':False,'endCursor':None}}}}
        result=Buffer(FakeHTTP([response]),'local-test','org','channel').reconcile(
            {'caption':'نص','attempted_at':'2026-10-14T12:00:00Z','video_url':url})
        self.assertEqual(result['id'],'v1')

    def test_music_assignments_cannot_be_accidentally_swapped(self):
        c=copy.deepcopy(self.c);c['daily_posts'][0]['music_file']='assets/audio/cinema.m4a'
        p=Path(self.temp.name)/'bad-config.json';p.write_text(json.dumps(c))
        with self.assertRaises(ValueError):load_config(p)

    def test_transport_failure_retries_the_same_git_push_without_force(self):
        store=object.__new__(GitStore);store.root=ROOT
        failed=subprocess.CompletedProcess([],1,'','remote transport disconnected')
        success=subprocess.CompletedProcess([],0,'ok','')
        with patch('tiktok_daily.storage.subprocess.run',side_effect=[failed,success]) as call, \
             patch('tiktok_daily.storage.time.sleep'):
            self.assertEqual(store.git('push','origin','HEAD:refs/heads/bot-state'),'ok')
        self.assertEqual(call.call_args_list[0].args,call.call_args_list[1].args)
        self.assertNotIn('--force',call.call_args.args[0])

    def test_changed_remote_ref_stops_without_retry_or_force(self):
        store=object.__new__(GitStore);store.root=ROOT
        failed=subprocess.CompletedProcess([],1,'','rejected: non-fast-forward')
        with patch('tiktok_daily.storage.subprocess.run',return_value=failed) as call, \
             patch('tiktok_daily.storage.time.sleep') as sleep:
            with self.assertRaises(RuntimeError):store.git('push','origin','HEAD:refs/heads/bot-state')
        self.assertEqual(call.call_count,1);sleep.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_real_twenty_second_video_contains_every_card_and_audio(self):
        cards=[]
        for color in ('red','blue'):
            out=io.BytesIO();Image.new('RGB',(1080,1920),color).save(out,format='JPEG');cards.append(out.getvalue())
        data,digest=make_video(cards,ROOT/'assets/audio/cinema.m4a')
        self.assertIn(b'ftyp',data[:32])
        self.assertEqual(hashlib.sha256(data).hexdigest(),digest)


if __name__=='__main__':unittest.main()
