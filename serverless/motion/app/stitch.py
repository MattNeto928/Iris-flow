"""
JOB_TYPE=stitch -- frames + narration -> out/video.mp4, with the gates recorded.

Order matters: verify the sequence is complete BEFORE spending two minutes on
gates and an encode, run the gates (informational, never fatal), encode, then
ffprobe the result against CONTRACT.md rule 7 so a file that concatenate_videos
would reject never leaves here unnoticed.

env: VIDEO_ID, MOTION_BUCKET
"""

import hashlib
import os
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import common
from common import logger

_FRAME_RE = re.compile(r'f(\d+)\.png')


# ============================================================
# frames
# ============================================================
def _verify_frames(frames_dir: Path, expected: int):
    """
    A missing shard must not silently produce a short video.

    Frame numbers come from the FILENAME, never list position (CONTRACT rule 3):
    a dead shard leaves a hole in the middle, and `-i f%04d.png` would stop dead
    at that hole and encode a video that looks fine and is half the length.
    """
    found = {}
    for p in frames_dir.glob('*.png'):
        m = _FRAME_RE.fullmatch(p.name)
        if m:
            found[int(m.group(1))] = p

    want = set(range(expected))
    missing = want - set(found)
    extra = set(found) - want
    empty = sorted(n for n, p in found.items() if p.stat().st_size == 0)

    if missing or extra or empty:
        parts = [f'{len(found)} frames on disk, plan.frames={expected}']
        if missing:
            parts.append(f'missing {len(missing)}: f[{common.compact_ranges(missing)}]')
        if extra:
            parts.append(f'unexpected {len(extra)}: f[{common.compact_ranges(extra)}]')
        if empty:
            parts.append(f'zero-byte {len(empty)}: f[{common.compact_ranges(empty)}]')
        raise RuntimeError('frame sequence is not complete -- ' + '; '.join(parts))

    logger.info(f'frame sequence complete: f0000-f{expected - 1:04d} ({expected} frames)')


# ============================================================
# gates
# ============================================================
def _beats_spec(beats: dict) -> str:
    """--beats "id:from-to,..." for check.py's per-beat report."""
    parts = []
    for b in (beats or {}).get('beats', []):
        bid = str(b.get('id', '')).strip()
        # check.py splits this spec on ',' and ':'; an id containing either would
        # sys.exit the whole gate run over a cosmetic report.
        if not bid or ',' in bid or ':' in bid:
            continue
        parts.append(f'{bid}:{int(b["from"])}-{int(b["to"])}')
    return ','.join(parts)


def _run_gates(vid: str, frames_dir: Path, out_dir: Path, fps: int,
               beats: dict, plan: dict) -> bool:
    """
    Full check.py pass (no --stride: a stride can step over the single bad frame
    the dead-frame gate exists to catch). Returns whether the gates passed.

    A FAILURE is recorded and uploaded but never aborts the job -- a gate result
    is information, and we still want to look at the video that produced it.
    A crash in check.py (missing numpy, unreadable PNG) lands here the same way:
    the traceback is in gates.txt and the encode goes ahead.
    """
    cmd = [sys.executable, common.APP_DIR / 'check.py',
           '--frames', frames_dir, '--fps', fps]
    spec = _beats_spec(beats)
    if spec:
        cmd += ['--beats', spec]
    # Optional: frame ranges the piece deliberately runs dark/bright (a fade,
    # a flash). prep may set it; absent by default.
    exempt = str(plan.get('exempt', '') or '')
    if exempt:
        cmd += ['--exempt', exempt]

    rc, text = common.run_logged(cmd, cwd=common.SERVE_ROOT, tag=f'[{vid} gates] ')
    passed = rc == 0

    gates_path = out_dir / 'gates.txt'
    gates_path.write_text(
        f'$ {" ".join(str(c) for c in cmd)}\n\n'
        f'{text}\n\n'
        f'exit {rc} -- gates {"PASSED" if passed else "FAILED"}\n'
    )
    common.upload_file(gates_path, vid, 'out/gates.txt')
    if not passed:
        logger.error(f'[{vid}] check.py exited {rc}: gates FAILED. '
                     f'Encoding anyway; see out/gates.txt.')
    return passed


# ============================================================
# encode + probe
# ============================================================
def _ffprobe(path, select: str, entries: str) -> dict:
    cmd = ['ffprobe', '-v', 'error', '-select_streams', select,
           '-show_entries', entries, '-of', 'json', str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f'ffprobe failed on {path}: {res.stderr.strip()}')
    data = json.loads(res.stdout or '{}')
    streams = data.get('streams') or [{}]
    out = dict(streams[0])
    out['_format'] = data.get('format', {})
    return out


def _rate(value) -> float:
    """'30/1' -> 30.0"""
    if not value:
        return 0.0
    if '/' in str(value):
        num, den = str(value).split('/', 1)
        return float(num) / float(den) if float(den) else 0.0
    return float(value)


def _video_frame_count(path) -> int:
    st = _ffprobe(path, 'v:0', 'stream=nb_frames')
    if st.get('nb_frames') not in (None, '', 'N/A'):
        return int(st['nb_frames'])
    # Some muxer/ffmpeg combinations omit nb_frames. Counting packets is exact
    # for h264 in MP4 and costs a demux pass, not a decode.
    res = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets',
         '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', str(path)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f'ffprobe packet count failed: {res.stderr.strip()}')
    return int(res.stdout.strip())


MUSIC_BUCKET = os.environ.get('MUSIC_BUCKET_NAME', 'iris-flow-music-482625028438')
# 0.20 and a 15 s start offset are IrisFlowStack's settled values, copied rather
# than re-derived so a motion post sounds like the STEM posts it replaces:
# _add_background_music in serverless/src/video_pipeline.py. The offset skips the
# intro of a track that was chosen for its middle.
# 0.10, halved from 0.20 on the note that the bed was too loud against the
# narration. The voice is mixed at 1.0 and ElevenLabs delivers it fairly hot, so
# a bed at a fifth of that was competing with consonants rather than sitting
# under them. Env-overridable, so this can be nudged without a redeploy.
MUSIC_VOLUME = float(os.environ.get('MUSIC_VOLUME', '0.10'))
MUSIC_START_S = 15


def _pick_music(wd: Path, vid: str):
    """
    One track from the shared music bucket, chosen deterministically per video.

    Deterministic on video_id, not random: a re-run of the same job -- a Spot
    retry, a manual re-stitch -- produces the same audio, which is what makes
    the encode reproducible. Returns None if the bucket is empty or unreadable;
    music is a nice-to-have and must never fail a render that is otherwise fine.
    """
    try:
        objs = []
        for page in common.s3.get_paginator('list_objects_v2').paginate(
                Bucket=MUSIC_BUCKET):
            objs += [o['Key'] for o in page.get('Contents', [])
                     if o['Key'].lower().endswith(('.mp3', '.m4a', '.wav'))]
        if not objs:
            common.logger.warning('no music in s3://%s — encoding without', MUSIC_BUCKET)
            return None
        objs.sort()
        key = objs[int(hashlib.sha256(vid.encode()).hexdigest(), 16) % len(objs)]
        dest = wd / 'music' / Path(key).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        common.s3.download_file(MUSIC_BUCKET, key, str(dest))
        common.logger.info('background music: %s', key)
        return dest
    except Exception as e:                                  # noqa: BLE001
        common.logger.warning('could not fetch background music (%s) — '
                              'encoding without', e)
        return None


def _encode(wd: Path, video_path: Path, fps: int, narration, music=None):
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
           '-framerate', fps,
           # start_number is 0 by default, but say it: the sequence starts at
           # f0000 and an implicit default is not worth a silent 5-frame probe.
           '-start_number', '0',
           '-i', 'frames/f%04d.png']          # never a glob (CONTRACT rule 4)
    if narration:
        cmd += ['-i', str(narration)]
    if narration and music:
        # -stream_loop -1 so a track shorter than the piece repeats rather than
        # dropping out; -ss BEFORE -i seeks the music input only.
        cmd += ['-ss', str(MUSIC_START_S), '-stream_loop', '-1', '-i', str(music)]
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p']
    if narration and music:
        # duration=first pins the mix to the NARRATION, not the looped music,
        # which is otherwise infinite. normalize=0 stops amix halving both inputs
        # whenever one of them goes quiet — without it the voice ducks every time
        # the music swells, which is backwards.
        cmd += ['-filter_complex',
                f'[1:a]volume=1.0[v];[2:a]volume={MUSIC_VOLUME}[m];'
                f'[v][m]amix=inputs=2:duration=first:dropout_transition=0'
                f':normalize=0[a]',
                '-map', '0:v', '-map', '[a]',
                '-c:a', 'aac', '-b:a', '192k', '-shortest']
    elif narration:
        cmd += ['-c:a', 'aac', '-b:a', '128k', '-shortest']
    cmd += ['-movflags', '+faststart', str(video_path)]

    rc, _ = common.run_logged(cmd, cwd=wd, tag='[ffmpeg] ')
    if rc != 0:
        raise RuntimeError(f'ffmpeg exited {rc}')
    if not video_path.exists() or video_path.stat().st_size == 0:
        raise RuntimeError(f'ffmpeg exited 0 but {video_path} is missing or empty')


# ============================================================
# job
# ============================================================
def run():
    vid = common.video_id()
    plan = common.load_plan(vid)
    frames = int(plan['frames'])
    fps = int(plan.get('fps', 30))

    wd = common.workdir(vid, clean=True)
    frames_dir = wd / 'frames'
    out_dir = wd / 'out'
    out_dir.mkdir(parents=True, exist_ok=True)

    common.download_prefix(vid, 'frames', frames_dir)
    _verify_frames(frames_dir, frames)

    narration = common.download_file(vid, 'narration.wav', wd / 'narration.wav', optional=True)
    beats_path = common.download_file(vid, 'beats.json', wd / 'beats.json', optional=True)
    beats = json.loads(beats_path.read_text()) if beats_path else {}

    gates_passed = _run_gates(vid, frames_dir, out_dir, fps, beats, plan)

    video_path = out_dir / 'video.mp4'
    music = _pick_music(wd, vid)
    _encode(wd, video_path, fps, narration, music)

    # --- verify the deliverable against CONTRACT rule 7 ---------------------
    v = _ffprobe(video_path, 'v:0',
                 'stream=codec_name,profile,pix_fmt,width,height,r_frame_rate,'
                 'avg_frame_rate,duration:format=duration')
    duration = float(v['_format'].get('duration') or v.get('duration') or 0.0)
    out_fps = _rate(v.get('r_frame_rate'))
    n_frames = _video_frame_count(video_path)

    audio = None
    if narration:
        a = _ffprobe(video_path, 'a:0', 'stream=codec_name,channels,sample_rate,bit_rate')
        audio = {
            'codec': a.get('codec_name'),
            'channels': a.get('channels'),
            'sample_rate': a.get('sample_rate'),
            'bit_rate': a.get('bit_rate'),
        }

    problems = []
    if v.get('codec_name') != 'h264':
        problems.append(f'codec {v.get("codec_name")!r}, expected h264')
    if v.get('profile') != 'High':
        problems.append(f'profile {v.get("profile")!r}, expected High')
    if v.get('pix_fmt') != 'yuv420p':
        problems.append(f'pix_fmt {v.get("pix_fmt")!r}, expected yuv420p')
    if (int(v.get('width', 0)), int(v.get('height', 0))) != (1080, 1920):
        problems.append(f'{v.get("width")}x{v.get("height")}, expected 1080x1920')
    if abs(out_fps - fps) > 0.01:
        problems.append(f'{out_fps} fps, expected {fps}')
    if narration and audio and audio['codec'] != 'aac':
        problems.append(f'audio codec {audio["codec"]!r}, expected aac')

    # -shortest ends the file with the SHORTER input, and narrate.py holds a tail
    # (0.8 s by default) of picture after the last word -- so the audio is
    # normally the shorter stream and those held frames are trimmed. Expected.
    # A count far below even the audio length is not: that is a half-written
    # encode, and it must fail.
    expected_frames = frames
    if narration:
        a_dur = float(_ffprobe(narration, 'a:0', 'format=duration')['_format'].get('duration') or 0.0)
        expected_frames = min(frames, int(round(a_dur * fps)))
        if expected_frames < frames:
            logger.info(
                f'[{vid}] -shortest trimmed {frames - expected_frames} held tail frames: '
                f'narration is {a_dur:.2f}s, picture is {frames / fps:.2f}s'
            )
    if n_frames < expected_frames - 2:
        problems.append(f'{n_frames} frames encoded, expected ~{expected_frames}')

    plan['output'] = {
        's3_key': common.key(vid, 'out/video.mp4'),
        'bytes': video_path.stat().st_size,
        'codec': v.get('codec_name'),
        'profile': v.get('profile'),
        'pix_fmt': v.get('pix_fmt'),
        'width': int(v.get('width', 0)),
        'height': int(v.get('height', 0)),
        'fps': round(out_fps, 3),
        'frames': n_frames,
        'duration': round(duration, 3),
        'audio': audio,
        'gates_passed': gates_passed,
        'gates_s3_key': common.key(vid, 'out/gates.txt'),
        'encoded_at': datetime.now(timezone.utc).isoformat(),
        'verified': not problems,
    }
    common.save_plan(vid, plan)
    common.upload_file(video_path, vid, 'out/video.mp4')

    logger.info(
        f'[{vid}] out/video.mp4: {v.get("codec_name")} {v.get("profile")} '
        f'{v.get("pix_fmt")} {v.get("width")}x{v.get("height")} @ {out_fps:g}fps, '
        f'{n_frames} frames, {duration:.2f}s, '
        f'{video_path.stat().st_size / 1e6:.1f} MB, gates '
        f'{"passed" if gates_passed else "FAILED"}'
    )

    # Uploaded first on purpose: a file that fails the container check is still
    # worth looking at. But the run must fail -- concatenate_videos in the
    # existing pipeline would silently re-encode or reject it.
    if problems:
        raise RuntimeError('encoded video does not meet CONTRACT rule 7: ' + '; '.join(problems))
