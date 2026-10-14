"""Local 20-second H.264/AAC videos; no AI audio/video generation calls."""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def make_video(images, audio, seconds=20):
    if not images or not 1 <= len(images) <= 10 or seconds != 20:
        raise ValueError('Expected 1–10 cards and exactly 20 seconds')
    audio = Path(audio)
    if not audio.is_file():
        raise RuntimeError('Configured music file is missing')
    with tempfile.TemporaryDirectory(prefix='tk-video-') as folder:
        root = Path(folder)
        command = ['ffmpeg','-hide_banner','-loglevel','error','-y']
        for i, data in enumerate(images):
            card = root / f'{i}.jpg'
            card.write_bytes(data)
            command += ['-loop','1','-framerate','30','-t',str(seconds/len(images)),'-i',str(card)]
        command += ['-i',str(audio)]
        if len(images) == 1:
            command += ['-map','0:v:0']
        else:
            chain = ''.join(f'[{i}:v:0]' for i in range(len(images)))
            command += ['-filter_complex',f'{chain}concat=n={len(images)}:v=1:a=0[v]','-map','[v]']
        output = root / 'post.mp4'
        command += ['-map',f'{len(images)}:a:0','-t',str(seconds),'-c:v','libx264',
                    '-preset','veryfast','-tune','stillimage','-crf','22','-pix_fmt','yuv420p',
                    '-c:a','aac','-b:a','160k','-ar','44100','-map_metadata','-1',
                    '-movflags','+faststart','-shortest',str(output)]
        try:
            subprocess.run(command,capture_output=True,check=True,timeout=180)
            probe = subprocess.run(['ffprobe','-v','error','-show_entries',
                                    'stream=codec_type,codec_name,width,height,duration:format=duration',
                                    '-of','json',str(output)],capture_output=True,check=True,timeout=20)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError('Video encoding/verification failed; no post was submitted') from None
        info = json.loads(probe.stdout)
        video = next((s for s in info['streams'] if s['codec_type']=='video'), {})
        sound = next((s for s in info['streams'] if s['codec_type']=='audio'), {})
        if (video.get('codec_name')!='h264' or sound.get('codec_name')!='aac'
                or (video.get('width'),video.get('height'))!=(1080,1920)
                or abs(float(info['format']['duration'])-seconds)>.1
                or abs(float(sound.get('duration',0))-seconds)>.1):
            raise RuntimeError('Video must have 1080×1920 H.264 and 20 seconds of audio')
        data = output.read_bytes()
        if len(data)>20_000_000:
            raise RuntimeError('Video exceeds the public media verification size limit')
        return data, hashlib.sha256(data).hexdigest()
