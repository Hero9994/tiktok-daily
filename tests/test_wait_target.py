import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from datetime import datetime,timezone
from test_project import config


class WaitTargetTests(unittest.TestCase):
    def test_confirmed_post_finishes_wait_even_when_future_cards_are_prepared(self):
        from tiktok_daily.__main__ import main
        now=datetime(2026,10,14,19,tzinfo=timezone.utc)
        target={'day':'2026-10-14','status':'accepted','post_id':'v1','due_at':'2026-10-14T18:25:00Z'}
        future={'day':'2026-10-15','status':'image_ready','due_at':'2026-10-15T14:00:00Z'}
        store=SimpleNamespace(state={'entries':{'target':target,'future':future}},close=Mock())
        publisher=Mock()
        publisher.verify.side_effect=lambda:target.update(status='sent')
        frozen=Mock(wraps=datetime);frozen.now.return_value=now
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps(config()))
            with patch('sys.argv',['tiktok_daily','wait-first','--config',str(path)]), \
                 patch.dict(os.environ,{'BUFFER_API_KEY':'local-test','GITHUB_REPOSITORY_VISIBILITY':'public'}), \
                 patch('tiktok_daily.__main__.GitStore',return_value=store), \
                 patch('tiktok_daily.__main__.Publisher',return_value=publisher), \
                 patch('tiktok_daily.__main__.datetime',frozen), \
                 patch('tiktok_daily.__main__.time.sleep',side_effect=AssertionError('Already delivered; do not wait for a future card')), \
                 patch('builtins.print'):
                main()
        self.assertEqual(publisher.verify.call_count,2)
        self.assertEqual(future['status'],'image_ready')
        store.close.assert_called_once()

    def test_specific_post_does_not_wait_for_another_accepted_future_post(self):
        from tiktok_daily.__main__ import main
        now=datetime(2026,10,14,19,tzinfo=timezone.utc)
        target={'day':'2026-10-14','status':'accepted','post_id':'v1','due_at':'2026-10-14T18:25:00Z'}
        future={'day':'2026-10-15','status':'accepted','post_id':'v2','due_at':'2026-10-15T14:00:00Z'}
        store=SimpleNamespace(state={'entries':{'target':target,'future':future}},close=Mock())
        publisher=Mock()
        publisher.verify.side_effect=lambda:target.update(status='sent')
        frozen=Mock(wraps=datetime);frozen.now.return_value=now
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps(config()))
            with patch('sys.argv',['tiktok_daily','wait-first','--post-id','v1','--config',str(path)]), \
                 patch.dict(os.environ,{'BUFFER_API_KEY':'local-test','GITHUB_REPOSITORY_VISIBILITY':'public'}), \
                 patch('tiktok_daily.__main__.GitStore',return_value=store), \
                 patch('tiktok_daily.__main__.Publisher',return_value=publisher), \
                 patch('tiktok_daily.__main__.datetime',frozen), \
                 patch('tiktok_daily.__main__.time.sleep',side_effect=AssertionError('Already delivered; do not wait for a future card')), \
                 patch('builtins.print'):
                main()
        self.assertEqual(publisher.verify.call_count,2)
        self.assertEqual(future['status'],'accepted')
        store.close.assert_called_once()
