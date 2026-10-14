"""Refresh only an explicitly selected queued cinema post, never create a second post."""
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .buffer import Buffer, FIELDS
from .cards import render
from .config import load_config
from .http import HTTP
from .runner import CINEMA_TEMPLATE
from .storage import GitStore
from .video import make_video


def refresh(store, buffer, http, c, post_id, clock=lambda:datetime.now(timezone.utc)):
    entry=next((e for e in store.state['entries'].values() if e.get('post_id')==post_id),None)
    if not entry or entry.get('post_kind')!='cinema' or entry['status']!='accepted':
        raise RuntimeError('Only an existing accepted cinema post can be refreshed')
    post=buffer.get(post_id)
    if post['channelId']!=buffer.channel or post['status']!='scheduled':
        raise RuntimeError('Post is no longer queued on the configured channel')
    if datetime.fromisoformat(post['dueAt'].replace('Z','+00:00')) < clock()+timedelta(minutes=15):
        raise RuntimeError('Queued post is too close to delivery to edit safely')
    pending=entry.get('layout_refresh',{})
    if not pending:
        hero=(store.path/'images'/entry['hero_file']).read_bytes()
        cards=render(hero,entry,c)
        assets=[]
        for data in cards:
            digest=hashlib.sha256(data).hexdigest();name=f'{entry["day"]}-layout-{digest[:12]}.jpg'
            store.save_image(name,data);assets.append({'file':name,'sha256':digest})
        video,digest=make_video(cards,Path(__file__).resolve().parents[1]/'assets/audio/cinema.m4a')
        name=f'{entry["day"]}-layout-{digest[:12]}.mp4';store.save_video(name,video)
        entry['layout_refresh']={'status':'ready','video_file':name,'video_sha256':digest,'image_assets':assets}
        store.checkpoint();pending=entry['layout_refresh']
    if not pending.get('video_url'):
        pending['video_url']=store.video_url(pending['video_file']);store.checkpoint()
    url=pending['video_url']
    sources={a.get('source') for a in post.get('assets',[])}
    if url not in sources:
        if pending['status']!='ready':
            raise RuntimeError('Uncertain layout edit requires review; never repeat the mutation blindly')
        http.image(url,pending['video_sha256'])
        # Verify the old asset and caption before making this explicit, reversible edit.
        if entry['video_url'] not in sources or post['text']!=entry['caption']:
            raise RuntimeError('Queued post changed since preparation; refusing to overwrite')
        pending['status']='editing';store.checkpoint()
        result=buffer.query(f'mutation($input: EditPostInput!) {{ editPost(input: $input) {{ __typename ... on PostActionSuccess {{ post {{ {FIELDS} }} }} ... on MutationError {{ message }} }} }}',
                            {'input':{'id':post_id,'aiAssisted':True,'assets':[{'video':{'url':url,'metadata':{'thumbnailOffset':0}}}]}},mutation=True)['editPost']
        if not result.get('post'):raise RuntimeError('Buffer did not confirm layout edit; inspect before retrying')
        post=buffer.get(post_id)
        if url not in {a.get('source') for a in post.get('assets',[])} or post['text']!=entry['caption']:
            raise RuntimeError('Buffer layout readback did not match')
    assets=pending['image_assets']
    entry.update(image_assets=assets,image_file=assets[0]['file'],image_sha256=assets[0]['sha256'],
                 image_urls=[store.image_url(a['file']) for a in assets],image_url=store.image_url(assets[0]['file']),
                 video_file=pending['video_file'],video_sha256=pending['video_sha256'],video_url=url,
                 cinema_template=CINEMA_TEMPLATE)
    pending['status']='confirmed';store.checkpoint()
    print(json.dumps({'post_id':post_id,'status':post['status'],'due_at':post['dueAt'],'layout':CINEMA_TEMPLATE}))


if __name__=='__main__':
    c=load_config(Path('config.json'));http=HTTP()
    store=GitStore(Path.cwd(),c['state_branch'],os.environ['GITHUB_REPOSITORY'])
    try:
        refresh(store,Buffer(http,os.environ['BUFFER_API_KEY'],c['buffer_organization_id'],c['buffer_channel_id']),http,c,sys.argv[1])
    finally:store.close()
