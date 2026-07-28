"""
JOB_TYPE=compile -- the weekly YouTube long-form cut.

Takes 4-6 pieces this pipeline already published, groups them under one idea,
and assembles a single landscape video with an intro, a spoken bridge into each
chapter, and an outro. Posted to YouTube ONLY, as youtubeData.type=VIDEO.

WHY A COMPILATION AND NOT A LONG ORIGINAL. A purpose-built 10-minute piece is
about 18,000 frames, which is ~8x the GPU of a short and a much larger blast
radius when a scene fails its gates. A compilation re-uses renders that are
already paid for and already known good: the marginal cost is one Claude call,
about 90 seconds of narration, and an ffmpeg re-encode. Roughly $0.40 against
$6-9. It also happens to be the better product, because a themed set of six
phenomena IS a broader story, which a single longer explainer is not.

WHY LANDSCAPE. The sources are 1080x1920. Stacking them vertically would make a
10-minute Short, which is not a thing. Each piece is centred in a 1920x1080
frame against a blurred, darkened copy of itself, which is the standard
treatment and is what makes this read as a real YouTube upload rather than six
Shorts glued together.

Chapters go in the description as timestamps, computed from the actual encoded
durations, so YouTube builds a real chapter list.
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import common
import slides as slidegen
import tts
from common import logger

W, H = 1920, 1080
FPS = 30
MIN_PIECES, MAX_PIECES = 4, 6
LOOKBACK_DAYS = int(os.environ.get('COMPILE_LOOKBACK_DAYS', '14'))
CLAUDE_MODEL = 'claude-opus-5'
PRICE = {'in': 5.0 / 1e6, 'out': 25.0 / 1e6}
MAX_TOKENS = 6000

PUBLIC_BUCKET = (os.environ.get('PUBLIC_BUCKET_NAME')
                 or 'iris-flow-videos-482625028438')
PUBLIC_PREFIX = 'motion/compilations/'

PROMPT = """You are assembling a single YouTube video out of {n} short science
explainers this channel has already published. Your job is to find the idea that
connects them and write the connective tissue.

THE AVAILABLE PIECES (index, title, and the full narration of each):

{catalogue}

Pick between {lo} and {hi} of them that genuinely share a theme. Do not force a
theme onto pieces that do not have one; a tight set of four beats a loose set of
six. Order them so the ideas build, which is usually simplest first.

You are writing for a viewer who will watch this for eight minutes, not eight
seconds. The intro earns that time, each bridge tells them why the next piece
follows from the last, and the outro closes the idea rather than asking for a
subscription.

HARD RULES:
- NO em dashes, NO en dashes, NO ellipses, NO emojis.
- NO "dive into", "fascinating", "let's explore", "unpack", "delve", "journey",
  "buckle up", "mind-blowing", "wild".
- NO "in this video", "in today's video", "coming up".
- NO asking for likes, subscribes or comments.
- Do not restate a piece's own narration. The viewer is about to hear it.
- Spoken text only in the narration sections: no headings, no stage directions,
  no speaker labels.

OUTPUT FORMAT. Each section opened by its marker alone on its own line. No JSON,
no markdown fences, no commentary.

===ORDER===
The indices you chose, comma separated, in the order they should play. Example:
3, 0, 5, 1
===TITLE===
The YouTube title. Under 90 characters. A concrete promise, keyword first.
===THEME===
Three to six words naming the theme, used as the on-screen opening card.
===INTRO===
25 to 40 words, spoken. Name the thread that runs through all of these and why
it is worth eight minutes.
===BRIDGES===
One line per chosen piece, IN THE SAME ORDER as ORDER, formatted as:
  Chapter title | spoken bridge of 12 to 25 words
The chapter title is under 50 characters and goes on screen. The bridge is
spoken over that card and leads INTO the piece that follows.
===OUTRO===
25 to 40 words, spoken. Land the shared idea. Do not summarise each piece.
===DESCRIPTION===
2 to 4 sentences for the YouTube description. Then a blank line, then exactly 3
hashtags.
===TAGS===
10 to 14 search keywords, comma separated, no "#"."""


# ============================================================
# source selection
# ============================================================
def _recent_pieces(days: int) -> list:
    """
    Published pieces from the last `days`, newest first.

    Requires post.status == 'scheduled' AND gates_passed: a compilation is a
    best-of, so it takes only pieces that both passed their gates and actually
    went out. A piece that failed its gates is exactly the one not to put in
    front of someone for eight minutes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    paginator = common.s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=common.BUCKET, Prefix='jobs/'):
        for obj in page.get('Contents', []):
            if not obj['Key'].endswith('/plan.json') or obj['LastModified'] < cutoff:
                continue
            try:
                plan = json.loads(common.s3.get_object(
                    Bucket=common.BUCKET, Key=obj['Key'])['Body'].read())
            except Exception as e:  # noqa: BLE001 - one bad plan is not fatal
                logger.warning('skipping unreadable %s: %s', obj['Key'], e)
                continue
            post = plan.get('post') or {}
            if post.get('status') != 'scheduled' or not post.get('gates_passed'):
                continue
            vid = plan.get('video_id') or obj['Key'].split('/')[1]
            narration = ' '.join(str(s.get('text', '')).strip()
                                 for s in (plan.get('narration') or [])
                                 if isinstance(s, dict))
            if not narration:
                continue
            out.append({'video_id': vid, 'ts': obj['LastModified'],
                        'title': post.get('title') or plan.get('topic') or vid,
                        'narration': narration})
    out.sort(key=lambda p: p['ts'], reverse=True)
    logger.info('compile: %d eligible pieces in the last %d days',
                len(out), days)
    return out


def _plan_compilation(pieces: list) -> tuple:
    """One Opus 5 call -> (plan dict, usd). Same block format as postcopy."""
    import anthropic
    from postcopy import parse_blocks

    catalogue = '\n\n'.join(
        f'[{i}] {p["title"]}\n{p["narration"][:700]}' for i, p in enumerate(pieces))
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
    msg = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=MAX_TOKENS,
        # Same measured reason as prep.py and postcopy.py: adaptive thinking on
        # Opus 5 has twice spent an entire budget in one thinking block on this
        # account and returned no text.
        thinking={'type': 'disabled'},
        messages=[{'role': 'user', 'content': PROMPT.format(
            n=len(pieces), catalogue=catalogue, lo=MIN_PIECES, hi=MAX_PIECES)}])

    raw = ''.join(b.text for b in msg.content
                  if getattr(b, 'type', None) == 'text').strip()
    usage = msg.usage.model_dump() if hasattr(msg.usage, 'model_dump') else dict(msg.usage)
    cost = (usage.get('input_tokens', 0) * PRICE['in']
            + usage.get('output_tokens', 0) * PRICE['out'])
    logger.info('compile plan: stop=%s out=%s $%.4f', msg.stop_reason,
                usage.get('output_tokens'), cost)

    b = parse_blocks(raw)
    need = {'ORDER', 'TITLE', 'INTRO', 'BRIDGES', 'OUTRO'}
    missing = need - set(b)
    if missing:
        raise RuntimeError(f'compile plan missing {sorted(missing)}; '
                           f'got {sorted(b)}')

    order = [int(x) for x in re.findall(r'\d+', b['ORDER'])
             if 0 <= int(x) < len(pieces)]
    # Dedupe while preserving order: a repeated index would put the same piece
    # in twice, which reads as a mistake rather than a callback.
    seen, clean_order = set(), []
    for i in order:
        if i not in seen:
            seen.add(i)
            clean_order.append(i)
    order = clean_order[:MAX_PIECES]
    if len(order) < MIN_PIECES:
        raise RuntimeError(f'compile plan chose only {len(order)} pieces '
                           f'(need {MIN_PIECES})')

    bridges = []
    for line in b['BRIDGES'].splitlines():
        line = re.sub(r'^(?:chapter\s*)?\d+\s*[.):]\s*', '', line.strip(), flags=re.I)
        line = re.sub(r'^[-*]\s*', '', line)
        if not line:
            continue
        title, _, spoken = line.partition('|')
        bridges.append({'title': title.strip()[:50],
                        'spoken': spoken.strip() or title.strip()})
    if len(bridges) < len(order):
        raise RuntimeError(f'compile plan has {len(bridges)} bridges for '
                           f'{len(order)} pieces')

    return {
        'order': order,
        'title': b['TITLE'].strip()[:97],
        'theme': (b.get('THEME') or b['TITLE']).strip()[:60],
        'intro': b['INTRO'].strip(),
        'bridges': bridges[:len(order)],
        'outro': b['OUTRO'].strip(),
        'description': (b.get('DESCRIPTION') or '').strip(),
        'tags': [t.strip().lstrip('#') for t in
                 re.split(r'[,\n]', b.get('TAGS', '')) if t.strip()][:14],
    }, cost


# ============================================================
# assembly
# ============================================================
def _card(title: str, subtitle: str, dst: Path, backdrop: Path = None) -> Path:
    """A 1920x1080 chapter card, optionally over a blurred frame of the piece."""
    if backdrop and backdrop.exists():
        with Image.open(backdrop) as src:
            img = src.convert('RGB')
            scale = max(W / img.width, H / img.height)
            img = img.resize((round(img.width * scale), round(img.height * scale)),
                             Image.LANCZOS)
            img = img.crop(((img.width - W) // 2, (img.height - H) // 2,
                            (img.width - W) // 2 + W, (img.height - H) // 2 + H))
            img = img.filter(ImageFilter.GaussianBlur(28))
            img = Image.blend(img, Image.new('RGB', (W, H), (0, 0, 0)), 0.55)
    else:
        img = Image.new('RGB', (W, H), (8, 10, 16))

    draw = ImageDraw.Draw(img)
    f_title = slidegen._font('bold', 92)
    f_sub = slidegen._font('regular', 44)
    margin = 150
    t_lines = slidegen._wrap(draw, title, f_title, W - 2 * margin)
    s_lines = slidegen._wrap(draw, subtitle, f_sub, W - 2 * margin) if subtitle else []

    block = len(t_lines) * 108 + (30 if s_lines else 0) + len(s_lines) * 58
    y = (H - block) // 2
    for ln in t_lines:
        draw.text((margin, y), ln, font=f_title, fill=(255, 255, 255))
        y += 108
    if s_lines:
        y += 30
    for ln in s_lines:
        draw.text((margin, y), ln, font=f_sub, fill=(150, 190, 240))
        y += 58

    img.save(dst, 'JPEG', quality=92)
    return dst


def _encode_card(card: Path, audio: Path, dst: Path) -> float:
    """Still + voice track -> a video segment matching the concat parameters."""
    dur = slidegen._probe_duration(audio) + 0.6
    common.run_logged(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
         '-loop', '1', '-i', str(card), '-i', str(audio),
         '-t', f'{dur:.2f}',
         '-vf', f'scale={W}:{H},fps={FPS},format=yuv420p',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
         '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2',
         str(dst)],
        tag='compile.card')
    return dur


def _letterbox(src: Path, dst: Path) -> float:
    """
    1080x1920 -> 1920x1080, the piece centred over a blurred copy of itself.

    Audio is normalised to 44.1k stereo here as well: concat demuxer needs every
    input to agree on codec AND layout, and the cards above are stereo. A mono
    piece spliced between two stereo cards silently loses one channel.
    """
    common.run_logged(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(src),
         '-filter_complex',
         f'[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,'
         f'crop={W}:{H},gblur=sigma=28,eq=brightness=-0.22[bg];'
         f'[0:v]scale=-2:{H}[fg];[bg][fg]overlay=(W-w)/2:0,'
         f'fps={FPS},format=yuv420p[v]',
         '-map', '[v]', '-map', '0:a?',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
         '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2',
         str(dst)],
        tag='compile.letterbox')
    return slidegen._probe_duration(dst)


def _concat(parts: list, dst: Path) -> Path:
    listing = dst.parent / 'concat.txt'
    listing.write_text(''.join(f"file '{p.resolve()}'\n" for p in parts))
    common.run_logged(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
         '-f', 'concat', '-safe', '0', '-i', str(listing),
         # Re-encode rather than -c copy. Every part was produced by the two
         # encoders above with identical parameters, so a stream copy would
         # usually work -- but "usually" here means a silently desynced audio
         # track on the one week a source piece has a different SAR.
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
         '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2',
         '-movflags', '+faststart', str(dst)],
        tag='compile.concat')
    if not dst.exists() or dst.stat().st_size == 0:
        raise RuntimeError('compilation encode produced nothing')
    return dst


def _timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


# ============================================================
# job
# ============================================================
async def run():
    t0 = time.time()
    vid = os.environ.get('VIDEO_ID') or f'compile{int(t0)}'
    wd = common.workdir(vid, clean=True)

    pieces = _recent_pieces(LOOKBACK_DAYS)
    if len(pieces) < MIN_PIECES:
        # Not an error. A young or paused channel simply has nothing to compile
        # this week, and failing here would send a FAILED email every Sunday.
        logger.warning('compile: only %d eligible pieces, need %d - skipping',
                       len(pieces), MIN_PIECES)
        return

    plan, plan_usd = _plan_compilation(pieces[:12])
    chosen = [pieces[i] for i in plan['order']]
    logger.info('compile: %r from %d pieces: %s', plan['title'], len(chosen),
                [p['video_id'] for p in chosen])

    # --- narration ----------------------------------------------------------
    voice_dir = wd / 'voice'
    voice_dir.mkdir(parents=True, exist_ok=True)
    intro_wav, _ = tts.generate_voiceover(plan['intro'], voice_dir / 'intro.wav')
    outro_wav, _ = tts.generate_voiceover(plan['outro'], voice_dir / 'outro.wav')
    bridge_wavs = [
        tts.generate_voiceover(b['spoken'], voice_dir / f'bridge{i}.wav')[0]
        for i, b in enumerate(plan['bridges'])]

    # --- parts --------------------------------------------------------------
    parts, chapters, elapsed = [], [], 0.0
    seg_dir = wd / 'segments'
    seg_dir.mkdir(parents=True, exist_ok=True)

    first_frame = None
    for i, piece in enumerate(chosen):
        src = common.download_file(piece['video_id'], 'out/video.mp4',
                                   wd / f'src{i}.mp4')
        if first_frame is None:
            grabs = slidegen.pick_frames(src, wd / f'scan{i}', 1)
            first_frame = grabs[0][1] if grabs else None

        if i == 0:
            card = _card(plan['theme'], plan['intro'][:150],
                         seg_dir / 'intro.jpg', first_frame)
            part = seg_dir / 'intro.mp4'
            elapsed += _encode_card(card, Path(intro_wav), part)
            parts.append(part)

        b = plan['bridges'][i]
        card = _card(b['title'], b['spoken'][:150], seg_dir / f'c{i}.jpg', first_frame)
        part = seg_dir / f'card{i}.mp4'
        dur = _encode_card(card, Path(bridge_wavs[i]), part)
        parts.append(part)
        # The chapter starts at the CARD, not at the piece: a viewer who jumps
        # to a chapter should hear why it is there.
        chapters.append((elapsed, b['title']))
        elapsed += dur

        part = seg_dir / f'body{i}.mp4'
        elapsed += _letterbox(src, part)
        parts.append(part)

    card = _card('The thread', plan['outro'][:150], seg_dir / 'outro.jpg', first_frame)
    part = seg_dir / 'outro.mp4'
    chapters.append((elapsed, 'The thread'))
    _encode_card(card, Path(outro_wav), part)
    parts.append(part)

    final = _concat(parts, wd / 'compilation.mp4')
    total = slidegen._probe_duration(final)
    logger.info('compile: %.1f min, %.1f MB', total / 60, final.stat().st_size / 1e6)

    # --- publish ------------------------------------------------------------
    key = f'{PUBLIC_PREFIX}{vid}.mp4'
    common.s3.upload_file(str(final), PUBLIC_BUCKET, key,
                          ExtraArgs={'ContentType': 'video/mp4'})
    url = f'https://{PUBLIC_BUCKET}.s3.amazonaws.com/{key}'
    logger.info('compile: published %s', url)

    description = plan['description'] + '\n\n' + '\n'.join(
        f'{_timestamp(t)} {name}' for t, name in [(0.0, 'Intro')] + chapters)

    # --- post ---------------------------------------------------------------
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    result = None
    # Computed OUTSIDE the branch: the plan.json below records it either way,
    # and defining it only in the else arm makes a DRY_RUN pass die with a
    # NameError at the very last statement, after all the work is done.
    # 120 minutes, tuned with the weekly rule's 17:00 UTC fire time so the
    # upload lands near 15:40 ET, inside YouTube's best window on this account
    # and clear of both daily Shorts.
    when = datetime.now(timezone.utc) + timedelta(
        minutes=int(os.environ.get('COMPILE_DELAY_MINUTES', '120')))
    if dry_run:
        logger.info('compile: DRY_RUN -- would post to YouTube:\n'
                    '  title %s\n  tags %s\n  description\n%s',
                    plan['title'], plan['tags'], description)
        status = 'dry_run'
    else:
        from metricool_client import MetricoolClient
        result = await MetricoolClient().schedule(
            kind='longform',                  # YouTube only, type=VIDEO
            media=[url],
            copy={'youtube': {'title': plan['title'], 'description': description,
                              'tags': plan['tags'], 'category': 'SCIENCE_TECHNOLOGY',
                              'type': 'VIDEO'},
                  'instagram': {}, 'tiktok': {}, 'facebook': {}},
            schedule_time=when,
            include_youtube=True, include_tiktok=False)
        status = 'scheduled' if result.get('success') else 'failed'

    # Written as plan.json, in the shape app/lambdas/notify.py already reads,
    # so the weekly run reports itself by email with no notifier changes. The
    # compilation-specific fields ride alongside.
    common.save_plan(vid, {
        'video_id': vid,
        'kind': 'compilation',
        'topic': plan['theme'],
        'title': plan['title'],
        'sources': [p['video_id'] for p in chosen],
        'chapters': [{'at': round(t, 1), 'title': n} for t, n in chapters],
        'duration_s': round(total, 1),
        'cost': {'plan_usd': round(plan_usd, 4)},
        'timings': {'compile_s': round(time.time() - t0, 1)},
        'output': {'gates_passed': True},   # every source already passed its own
        'post': {
            'status': status,
            'public_url': url,
            'title': plan['title'],
            'copy': {'youtube': {'title': plan['title'], 'tags': plan['tags']},
                     'instagram': {}, 'tiktok': {}, 'facebook': {}},
            'include_youtube': True,
            'include_tiktok': False,
            'dry_run': dry_run,
            'gates_passed': True,
            'schedule_time': None if dry_run else when.isoformat(),
            'metricool': {'longform': result} if result else {},
            'description': description,
            'recorded_at': datetime.now(timezone.utc).isoformat(),
        },
    })

    logger.info('compile: %s in %.1fs', status, time.time() - t0)
    if status == 'failed':
        raise RuntimeError(f'compilation post failed: {result.get("error")}')
