"""
JOB_TYPE=render -- render frames [FRAME_FROM, FRAME_TO] of one piece to S3.

Sharding exists because WebGL under SwiftShader is ~37x slower than a real GPU:
at ss=16 a frame costs ~2.14 s, so 1440 frames in one task is ~36 minutes. Eight
shards of 180 frames land at ~4.5 minutes each.

env: VIDEO_ID, FRAME_FROM, FRAME_TO (inclusive), MOTION_BUCKET
"""

import os
import re
import time

import common
from common import logger

# render.mjs clears its --out directory unless it was given --only (or --probe),
# so --only is the only flag that appends to an existing sequence. There is no
# range flag: an explicit CSV of every frame in the shard is the whole interface.
# 180 numbers is ~800 bytes of argv, four orders of magnitude under ARG_MAX.
_RENDERED_RE = re.compile(r'rendered (\d+) frames in ([\d.]+)s')


def _int_env(name: str) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == '':
        raise RuntimeError(f'{name} environment variable not set')
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f'{name}={raw!r} is not an integer')


def run():
    vid = common.video_id()
    frame_from = _int_env('FRAME_FROM')
    frame_to = _int_env('FRAME_TO')

    plan = common.load_plan(vid)
    frames = int(plan['frames'])
    subsamples = int(plan.get('subsamples', 16))
    tag = f'[{vid} f{frame_from}-{frame_to}] '

    if frame_from < 0 or frame_to < frame_from or frame_to >= frames:
        raise RuntimeError(
            f'shard range f{frame_from}-f{frame_to} is not inside the piece '
            f'(plan.frames={frames}, valid f0-f{frames - 1})'
        )
    wanted = list(range(frame_from, frame_to + 1))

    # RESUME. A Fargate Spot reclaim is routine at 24 concurrent shards (2 of 24
    # in one measured run), and Batch restarts the whole attempt. Frames already
    # in S3 for THIS shard's own range are re-usable: shards own disjoint ranges
    # and render.mjs is deterministic, so an f0123.png that exists was produced
    # by this same piece at this same subsample count. Skipping them turns a
    # reclaim near the end of a shard from 14 wasted minutes into seconds.
    # Only ever skip inside the shard's own range -- never trust a neighbour's.
    already = common.existing_frames(vid, frame_from, frame_to)
    if already:
        wanted = [f for f in wanted if f not in already]
        logger.info('%s%d/%d frames already in S3 — rendering %d',
                    tag, len(already), frame_to - frame_from + 1, len(wanted))
    if not wanted:
        logger.info('%sshard already complete, nothing to do', tag)
        return

    # --- inputs -------------------------------------------------------------
    wd = common.workdir(vid, clean=True)
    page = wd / 'piece.html'
    common.download_file(vid, 'piece.html', page)
    # data/ has to sit NEXT TO the page: the piece fetches 'data/<name>.json'
    # relative to its own URL, not to the serve root.
    common.download_prefix(vid, 'data', wd / 'data')

    out_dir = wd / 'out' / 'frames'
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- render -------------------------------------------------------------
    cmd = [
        'node', common.APP_DIR / 'render.mjs',
        '--page', common.page_url_path(page),
        '--out', out_dir,
        '--ss', subsamples,
        '--only', ','.join(str(f) for f in wanted),
    ]
    t0 = time.time()
    rc, out = common.run_logged(cmd, cwd=common.SERVE_ROOT, env=common.render_env(), tag=tag)
    wall = time.time() - t0
    if rc != 0:
        raise RuntimeError(f'render.mjs exited {rc} for f{frame_from}-f{frame_to}')
    # render.mjs reports page errors raised DURING the loop and then still exits
    # 0 (it only hard-fails on errors seen before the first frame). Those frames
    # are unusable, so the shard has to fail on its own.
    if 'page errors during render' in out:
        raise RuntimeError(
            f'the piece threw a JS error while rendering f{frame_from}-f{frame_to}; '
            f'frames are not trustworthy -- see the log above'
        )

    # --- verify then upload -------------------------------------------------
    produced, missing, empty = [], [], []
    for f in wanted:
        p = out_dir / f'f{f:04d}.png'
        if not p.exists():
            missing.append(f)
        elif p.stat().st_size == 0:
            empty.append(f)
        else:
            produced.append((p, f'frames/f{f:04d}.png'))
    if missing or empty:
        raise RuntimeError(
            f'render.mjs exited 0 but the shard is incomplete: '
            f'{len(missing)} missing [{common.compact_ranges(missing)}], '
            f'{len(empty)} zero-byte [{common.compact_ranges(empty)}]'
        )

    common.upload_files(vid, produced)

    # --- throughput ---------------------------------------------------------
    # In-page seconds come from render.mjs's own timer (the seek+encode loop);
    # wall adds Chrome startup, the piece's module graph and the S3 round trips.
    m = _RENDERED_RE.search(out)
    render_secs = float(m.group(2)) if m else wall
    n = len(wanted)
    logger.info(
        f'{tag}{n} frames at ss={subsamples}: '
        f'{render_secs:.1f}s in-page = {render_secs / n:.2f} s/frame '
        f'({n / render_secs:.2f} frames/s); {wall:.1f}s wall = {wall / n:.2f} s/frame '
        f'including Chrome startup and S3. CONTRACT estimate: 2.14 s/frame at ss=16.'
    )
