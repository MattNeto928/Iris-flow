"""
Shared plumbing for the iris-motion Batch jobs (prep / render / stitch).

Deliberately dependency-light: boto3 plus the stdlib. The renderer toolchain
(render.mjs, check.py) is driven as a subprocess and never imported, so this
module stays importable in a container that has no Chrome and no numpy.

S3 layout is CONTRACT.md's:  jobs/<video_id>/{plan.json,piece.html,data/,
narration.wav,beats.json,frames/f0000.png,out/video.mp4,out/gates.txt}
"""

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('iris-motion')

REGION = os.environ.get('AWS_REGION', 'us-east-1')
# Accept both spellings. The CDK stack injects MOTION_BUCKET_NAME, matching the
# sibling pipeline's VIDEO_BUCKET_NAME convention; MOTION_BUCKET is what the
# local test harness sets. Reading only one of them fails at the first S3 call
# with a confusing NoneType bucket rather than at startup.
BUCKET = os.environ.get('MOTION_BUCKET_NAME') or os.environ.get('MOTION_BUCKET')

# max_pool_connections must be >= the worker count below: botocore's default
# pool is 10, so a 16-way frame fetch spends its time retrying "Connection pool
# is full" instead of on the wire.
S3_THREADS = int(os.environ.get('MOTION_S3_THREADS', '16'))

# The bucket's expire-frames lifecycle rule filters on an OBJECT TAG, because an
# S3 prefix filter cannot express 'jobs/*/frames/' (no wildcards) and a plain
# 'jobs/' prefix would delete out/video.mp4 along with the frames. So frames
# must carry the tag or they are never cleaned up -- ~1.4 GB per video, forever.
# The stack passes it already URL-encoded, exactly as PutObject wants it.
FRAME_TAGGING = os.environ.get('FRAME_OBJECT_TAGGING', '')


def _extra_args(rel: str) -> dict:
    extra = {'ContentType': _content_type(rel)}
    if FRAME_TAGGING and '/frames/' in f'/{rel}':
        extra['Tagging'] = FRAME_TAGGING
    return extra
s3 = boto3.client(
    's3',
    region_name=REGION,
    config=Config(max_pool_connections=max(S3_THREADS, 10),
                  retries={'max_attempts': 5, 'mode': 'standard'}),
)

APP_DIR = Path(__file__).resolve().parent
# serve.mjs serves APP_DIR/.. and render.mjs resolves --page against that same
# root, so every workdir has to live UNDER it or the page 404s and the render
# dies with "HTTP 404" before the first frame.
SERVE_ROOT = APP_DIR.parent

_CONTENT_TYPES = {
    '.mp4': 'video/mp4',
    '.png': 'image/png',
    # Carousel slides and the still-image post. NOT optional: these objects are
    # fetched over plain HTTPS by Metricool and handed to Instagram's media
    # endpoint, and the default below ('application/octet-stream') is not an
    # image content type — the fetch is what would fail, several minutes later,
    # in someone else's service.
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.json': 'application/json',
    '.wav': 'audio/wav',
    '.html': 'text/html',
    '.txt': 'text/plain',
}

# A video_id becomes both an S3 key segment and a served URL path segment, so it
# is validated once here rather than trusted from the environment.
_SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')


# ============================================================
# ids, keys, workdirs
# ============================================================
def video_id() -> str:
    """VIDEO_ID from the environment, validated as a path/key segment."""
    vid = os.environ.get('VIDEO_ID', '').strip()
    if not vid:
        raise RuntimeError('VIDEO_ID environment variable not set')
    if not _SAFE_ID.fullmatch(vid):
        raise RuntimeError(f'VIDEO_ID {vid!r} is not a safe S3 key / URL segment')
    return vid


def key_prefix(vid: str) -> str:
    return f'jobs/{vid}'


def key(vid: str, rel: str) -> str:
    """S3 key for a path relative to the job prefix, e.g. 'frames/f0000.png'."""
    return f'{key_prefix(vid)}/{rel.lstrip("/")}'


def workdir(vid: str, clean: bool = False) -> Path:
    """
    Local scratch for one job, under the directory serve.mjs publishes.

    piece.html must be reachable over HTTP for render.mjs, and the piece fetches
    its data as `data/<name>.json` RELATIVE TO THE PAGE, so page and data have to
    be siblings inside this directory.
    """
    wd = SERVE_ROOT / 'work' / vid
    if clean and wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def page_url_path(local_page: Path) -> str:
    """The --page value for render.mjs: a path relative to the serve root."""
    return local_page.resolve().relative_to(SERVE_ROOT).as_posix()


# ============================================================
# S3
# ============================================================
def _bucket() -> str:
    if not BUCKET:
        raise RuntimeError('MOTION_BUCKET environment variable not set')
    return BUCKET


def _content_type(name: str) -> str:
    return _CONTENT_TYPES.get(Path(name).suffix.lower(), 'application/octet-stream')


def exists(vid: str, rel: str) -> bool:
    try:
        s3.head_object(Bucket=_bucket(), Key=key(vid, rel))
        return True
    except ClientError as e:
        if e.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
            return False
        raise


def upload_file(local, vid: str, rel: str) -> str:
    k = key(vid, rel)
    s3.upload_file(str(local), _bucket(), k,
                   ExtraArgs=_extra_args(rel))
    logger.info(f'Uploaded {local} -> s3://{_bucket()}/{k}')
    return k


def upload_bytes(data: bytes, vid: str, rel: str) -> str:
    """Upload an in-memory artifact (plan.json, beats.json) without a temp file."""
    k = key(vid, rel)
    s3.put_object(Bucket=_bucket(), Key=k, Body=data,
                  ContentType=_content_type(rel))
    logger.info(f'Uploaded {len(data)} bytes -> s3://{_bucket()}/{k}')
    return k


def upload_files(vid: str, pairs) -> int:
    """Upload [(local_path, rel_key), ...] in parallel. Raises on the first failure."""
    pairs = list(pairs)
    if not pairs:
        return 0

    def _one(pair):
        local, rel = pair
        k = key(vid, rel)
        s3.upload_file(str(local), _bucket(), k,
                       ExtraArgs=_extra_args(rel))
        return k

    with ThreadPoolExecutor(max_workers=S3_THREADS) as ex:
        # list() so an exception in any worker surfaces here instead of being
        # swallowed by a lazy map that nobody consumes.
        done = list(ex.map(_one, pairs))
    logger.info(f'Uploaded {len(done)} files -> s3://{_bucket()}/{key_prefix(vid)}/')
    return len(done)


def existing_frames(vid: str, lo: int, hi: int) -> set:
    """
    Frame numbers already uploaded within [lo, hi]. Used to make a Spot-reclaimed
    render shard resumable. Reads only the frames/ prefix, one paginated LIST.
    """
    out = set()
    prefix = key(vid, 'frames/')
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=_bucket(), Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj.get('Size', 0) <= 0:
                continue                      # a zero-byte object is not a frame
            m = re.search(r'f(\d+)\.png$', obj['Key'])
            if m and lo <= int(m.group(1)) <= hi:
                out.add(int(m.group(1)))
    return out


def download_file(vid: str, rel: str, dest, optional: bool = False):
    """Download one job file. Returns the local Path, or None if optional and absent."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    k = key(vid, rel)
    try:
        s3.download_file(_bucket(), k, str(dest))
    except ClientError as e:
        if optional and e.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
            logger.info(f'Optional s3://{_bucket()}/{k} not present')
            return None
        raise
    logger.info(f'Downloaded s3://{_bucket()}/{k} -> {dest}')
    return dest


def download_prefix(vid: str, rel: str, dest) -> list:
    """
    Download every object under jobs/<vid>/<rel>/ into dest, preserving the
    sub-path. Returns the local paths (may be empty; an absent prefix is not an
    error -- a piece with no data/ files is legitimate).
    """
    prefix = key(vid, rel)
    if not prefix.endswith('/'):
        prefix += '/'
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    keys = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=_bucket(), Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('/'):
                continue          # zero-byte "folder" marker, not a file
            keys.append(obj['Key'])

    def _one(k):
        local = dest / k[len(prefix):]
        local.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(_bucket(), k, str(local))
        return local

    with ThreadPoolExecutor(max_workers=S3_THREADS) as ex:
        out = list(ex.map(_one, keys))
    logger.info(f'Downloaded {len(out)} files from s3://{_bucket()}/{prefix} -> {dest}')
    return sorted(out)


# ============================================================
# plan.json
# ============================================================
def load_plan(vid: str) -> dict:
    body = s3.get_object(Bucket=_bucket(), Key=key(vid, 'plan.json'))['Body'].read()
    return json.loads(body)


def save_plan(vid: str, plan: dict) -> str:
    """
    Read-modify-write, so only ONE job may call this at a time. prep writes it
    before the fan-out and stitch writes it after; the render shards run
    concurrently and must stay read-only or they will clobber each other.
    """
    k = key(vid, 'plan.json')
    s3.put_object(Bucket=_bucket(), Key=k,
                  Body=json.dumps(plan, indent=2).encode(),
                  ContentType='application/json')
    logger.info(f'Wrote s3://{_bucket()}/{k}')
    return k


# ============================================================
# subprocesses
# ============================================================
def run_logged(cmd, cwd=None, env=None, tag='') -> tuple:
    """
    Run a command, stream its output into the log as it arrives, and return
    (returncode, combined_output).

    Splits on \\r as well as \\n: render.mjs and ffmpeg draw progress with a
    carriage return, and a plain line iterator would hold a whole 4-minute
    render in one buffer and then emit it as a single unreadable log event.
    os.read (not BufferedReader.read) because the latter blocks until the full
    request size is available, which defeats the streaming.
    """
    argv = [str(c) for c in cmd]
    logger.info(f'{tag}$ {" ".join(shlex.quote(a) for a in argv)}')
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    lines, buf = [], b''
    fd = proc.stdout.fileno()
    while True:
        chunk = os.read(fd, 8192)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb'[\r\n]', buf)
        buf = parts.pop()
        for p in parts:
            text = p.decode('utf-8', 'replace').rstrip()
            if text:
                lines.append(text)
                logger.info(f'{tag}{text}')
    if buf:
        text = buf.decode('utf-8', 'replace').rstrip()
        if text:
            lines.append(text)
            logger.info(f'{tag}{text}')
    proc.stdout.close()
    rc = proc.wait()
    return rc, '\n'.join(lines)


# ============================================================
# Chrome
# ============================================================
# CONTRACT.md rule 6. render.mjs hardcodes `--use-angle=metal` and omits
# `--no-sandbox`: correct on the Mac it was written on, fatal in a Fargate
# container (no GPU, no user namespaces, 64 MB /dev/shm). render.mjs is not ours
# to edit and puppeteer takes its launch args only from that file, so the flags
# are injected through the binary it actually execs -- CHROME_PATH points at
# this wrapper. The flags go AFTER "$@" because Chrome keeps the LAST value of a
# repeated switch, so ours must land after the --use-angle=metal render.mjs
# appends.
# Flags the wrapper appends after puppeteer's own argv. Chrome keeps the LAST
# occurrence of a repeated switch, which is what makes this work -- and is
# exactly why the GL flags are NOT in here.
#
# They used to be. On the GPU image that silently won: MOTION_GL_FLAGS asked for
# --use-angle=vulkan, the wrapper appended --use-angle=swiftshader after it, and
# the render came up on "SwiftShader Device (Subzero)" on a machine with a Tesla
# T4 sitting idle. Everything "worked", 107x slower. render.mjs now owns the GL
# backend (and honours MOTION_GL_FLAGS); the wrapper only supplies the two flags
# that are about running as root in a container and are true on every image.
LINUX_CHROME_FLAGS = (
    '--no-sandbox',
    '--disable-dev-shm-usage',
)

_CHROME_CANDIDATES = (
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/opt/chrome/chrome',
    '/opt/google/chrome/chrome',
)


def _probe_chrome() -> str:
    found = next((p for p in _CHROME_CANDIDATES if os.path.exists(p)), None)
    if not found:
        raise RuntimeError(
            'no Chrome/Chromium binary found in ' + ', '.join(_CHROME_CANDIDATES) +
            ' -- set CHROME_BINARY to the real executable'
        )
    return found


def chrome_launcher():
    """
    CHROME_PATH to hand render.mjs, or None to let it probe for itself.

    Returns None off Linux: on a dev Mac render.mjs's own candidate list and its
    Metal ANGLE backend are already right, and --no-sandbox is unnecessary.
    """
    if not sys.platform.startswith('linux'):
        return None

    wrapper = Path(tempfile.gettempdir()) / 'iris-motion-chrome.sh'
    real = os.environ.get('CHROME_BINARY') or os.environ.get('CHROME_PATH') or _probe_chrome()
    # If the image already exported CHROME_PATH pointing at this wrapper, wrapping
    # it again would exec itself forever.
    if os.path.abspath(real) == str(wrapper):
        real = os.environ.get('CHROME_BINARY') or _probe_chrome()
    if not os.path.exists(real):
        raise RuntimeError(f'Chrome binary {real!r} does not exist')

    wrapper.write_text(
        '#!/bin/sh\n'
        f'exec {shlex.quote(real)} "$@" {" ".join(LINUX_CHROME_FLAGS)}\n'
    )
    wrapper.chmod(0o755)
    logger.info(f'Chrome launcher {wrapper} -> {real} {" ".join(LINUX_CHROME_FLAGS)}')
    return str(wrapper)


def render_env():
    """os.environ plus the CHROME_PATH render.mjs should use, if we supply one."""
    env = os.environ.copy()
    launcher = chrome_launcher()
    if launcher:
        env['CHROME_PATH'] = launcher
    return env


# ============================================================
# misc
# ============================================================
def compact_ranges(nums) -> str:
    """[0,1,2,7,8] -> '0-2,7-8'. Keeps a 180-frame hole readable in one line."""
    nums = sorted(set(nums))
    if not nums:
        return ''
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(f'{start}-{prev}' if start != prev else f'{start}')
        start = prev = n
    out.append(f'{start}-{prev}' if start != prev else f'{start}')
    return ','.join(out)
